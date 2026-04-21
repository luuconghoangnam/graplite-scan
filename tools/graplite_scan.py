#!/usr/bin/env python3
"""graplite-scan: local/offline project scanner that emits two Markdown files.

Design goals:
- No network calls for the baseline scan.
- Works without ripgrep.
- Produces stable, linkable references (path + line ranges when possible).
- Detailed enough for agents: entrypoints, module map, symbol index (heuristic),
  dependency graph (import graph), env map, route map, and change recipes.

Usage examples:
  python3 tools/graplite_scan.py --repo /path/to/repo --inplace
  python3 tools/graplite_scan.py --repo . --mode short
  python3 tools/graplite_scan.py --repo . --mode agent-claude
  python3 tools/graplite_scan.py --repo /path/to/repo --out /tmp/reportdir

Default outputs:
  - PROJECT_FAST_MAP.md
  - PROJECT_BLAST_RADIUS.md

Short mode outputs:
  - MAP.md
  - IMPACT.md

Agent/Claude mode outputs:
  - AGENT_MAP.md
  - CLAUDE_MAP.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

DEFAULT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".dart_tool",
    ".idea",
    ".vscode",
    ".cache",
    ".graplite",
    ".coonie",
    ".wrangler",
    ".venv",
    "venv",
    "vendor",
    "coverage",
    "target",
}

MANIFEST_NAMES = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pubspec.yaml",
    "pubspec.lock",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    ".env.example",
    ".env",
    "README.md",
    "codemagic.yaml",
    "*.csproj",
    "*.sln",
    "App.xaml",
}

TS_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?[^;]*?from\s+['\"](?P<spec>[^'\"]+)['\"];?\s*$",
    re.M,
)
TS_SIDE_EFFECT_IMPORT_RE = re.compile(
    r"^\s*import\s+['\"](?P<spec>[^'\"]+)['\"];?\s*$",
    re.M,
)
DART_IMPORT_RE = re.compile(
    r"^\s*(?:import|export)\s+['\"](?P<spec>[^'\"]+)['\"];?\s*$",
    re.M,
)
CS_USING_RE = re.compile(
    r'^\s*using\s+(?:static\s+)?(?P<spec>[A-Za-z_][A-Za-z0-9_\.]+)\s*;\s*$',
    re.M,
)
XAML_CODEBEHIND_RE = re.compile(
    r'x:Class\s*=\s*["\'](?P<klass>[^"\']+)["\']',
    re.I,
)

TS_DEF_RES = [
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("const", re.compile(r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("type", re.compile(r"^\s*(?:export\s+)?type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
]

DART_DEF_RES = [
    ("class", re.compile(r"^\s*(?:abstract\s+)?class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("function", re.compile(r"^\s*(?:Future<[^>]+>|Future|void|int|double|String|bool|dynamic|Widget|\w+)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)),
]

PY_DEF_RES = [
    ("class", re.compile(r"^\s*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("function", re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)),
]

CS_DEF_RES = [
    ("class", re.compile(r"^\s*(?:public\s+|internal\s+|private\s+|protected\s+|abstract\s+|sealed\s+|partial\s+|static\s+)*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("interface", re.compile(r"^\s*(?:public\s+|internal\s+|private\s+|protected\s+|partial\s+)*interface\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("record", re.compile(r"^\s*(?:public\s+|internal\s+|private\s+|protected\s+|partial\s+)*record\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("enum", re.compile(r"^\s*(?:public\s+|internal\s+|private\s+|protected\s+)*enum\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", re.M)),
    ("method", re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|static\s+|virtual\s+|override\s+|async\s+|sealed\s+|partial\s+)*(?:[A-Za-z_][A-Za-z0-9_<>\[\],?]*\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)),
]

ENV_USAGE_RE = re.compile(r"process\.env\.([A-Z0-9_]+)")
ENV_KEY_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=.*$", re.M)
FASTIFY_ROUTE_RE = re.compile(
    r"(?P<target>\bapp|\bserver|\brouter|\bfastify)\.(?P<method>get|post|put|delete|patch|options|head)\s*(?:<[^>]*>)?\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
    re.I | re.S,
)
REGISTER_ROUTE_RE = re.compile(r"\b(register[A-Za-z0-9_]*(?:Routes|Gateway))\s*\(")
WS_EVENT_RE = re.compile(r"['\"]([A-Za-z0-9:_\-]+)['\"]")
TRANSFER_HINT_RE = re.compile(r"transfer|gateway|websocket|socket|peer", re.I)
DIFF_SYMBOL_RES = [
    re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\binterface\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\benum\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\bfinal\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\bvar\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:async\s*)?\([^)]*\)\s*=>"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
    re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|override\s+|readonly\s+|abstract\s+|get\s+|set\s+)*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
]
DEFAULT_CONFIG_NAME = '.graplite.json'

DIR_RESP_HINTS = {
    'backend': 'server/backend logic',
    'server': 'server/backend logic',
    'src': 'primary source tree',
    'app': 'application / UI layer',
    'frontend': 'application / UI layer',
    'web': 'web app / frontend assets',
    'client': 'client-side code',
    'lib': 'shared/library source',
    'pages': 'route/page modules',
    'components': 'UI components',
    'widgets': 'UI components',
    'hooks': 'client hooks/state wiring',
    'stores': 'state/store modules',
    'state': 'state/store modules',
    'composables': 'vue composables',
    'layouts': 'layout / shell modules',
    'api': 'API handlers or service endpoints',
    'routes': 'router or endpoint definitions',
    'docs': 'architecture notes, plans, docs',
    'scripts': 'automation / helper scripts',
    'tools': 'developer tooling',
    'infra': 'CI/deploy/infrastructure',
    'packages': 'multi-package workspace',
    'services': 'service modules',
    'test': 'tests',
    'tests': 'tests',
    'core': 'shared core utilities/services',
    'features': 'feature-oriented modules',
    'modules': 'backend feature modules',
    'transfer': 'transfer/signaling/storage flow',
    'views': 'desktop UI views/windows/pages',
    'viewmodels': 'desktop viewmodel/state layer',
    'controls': 'desktop shared UI controls',
    'models': 'domain/data models',
    'converters': 'UI binding converters',
    'commands': 'UI command handlers',
}


@dataclass
class SymbolDef:
    lang: str
    kind: str
    name: str
    path: str
    line: int


@dataclass
class RouteDef:
    method: str
    path: str
    file: str
    line: int


@dataclass
class RegisterCall:
    name: str
    file: str
    line: int


@dataclass
class TransferFileHint:
    file: str
    line: int
    kind: str
    value: str


@dataclass
class RouteFlowHint:
    method: str
    path: str
    file: str
    line: int
    chain: List[str]


@dataclass
class ChangedLineRange:
    start: int
    end: int


@dataclass
class ScipReadiness:
    enabled: bool
    repo_kind: str
    indexer: str
    project_root: str
    index_path: str
    reasons: List[str]


@dataclass
class ScipIndexStatus:
    exists: bool
    path: str
    size_bytes: int
    summary: List[str]
    document_hints: List[str]
    symbol_hints: List[str]
    tool_name: str
    tool_version: str
    project_root: str
    document_count: int
    structured_document_hints: List[str]
    structured_symbol_hints: List[str]
    occurrence_count: int
    definition_count: int
    reference_count: int
    structured_occurrence_hints: List[str]
    structured_top_reference_hints: List[str]
    structured_occurrence_stats: Dict[str, Dict[str, int]]
    structured_symbols_by_file: Dict[str, List[str]]
    structured_occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, int]]]
    structured_occurrence_lines_by_file: Dict[str, Dict[str, List[int]]]


def normalize_rel_prefix(value: str) -> str:
    value = value.strip().replace('\\', '/').strip('/')
    return value


def should_ignore_rel(rel_posix: str, ignore_paths: Sequence[str]) -> bool:
    for prefix in ignore_paths:
        normalized = normalize_rel_prefix(prefix)
        if not normalized:
            continue
        if rel_posix == normalized or rel_posix.startswith(normalized + '/'):
            return True
    return False


def is_ignored(
    path: Path,
    ignore_dirs: Set[str],
    root: Optional[Path] = None,
    ignore_paths: Sequence[str] = (),
) -> bool:
    if any(part in ignore_dirs for part in path.parts):
        return True
    if root is not None:
        try:
            rel_posix = path.relative_to(root).as_posix()
        except Exception:
            rel_posix = ''
        if rel_posix and should_ignore_rel(rel_posix, ignore_paths):
            return True
    return False


def load_repo_config(repo: Path) -> Dict[str, Any]:
    config_path = repo / DEFAULT_CONFIG_NAME
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding='utf-8'))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def config_str(config: Dict[str, Any], key: str, default: str = '') -> str:
    value = config.get(key, default)
    return value if isinstance(value, str) else default


def config_bool(config: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    return value if isinstance(value, bool) else default


def config_str_list(config: Dict[str, Any], key: str) -> List[str]:
    value = config.get(key, [])
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                out.append(normalized)
    return out


def safe_read_text(path: Path, max_bytes: int = 500_000) -> str:
    try:
        b = path.read_bytes()
        if len(b) > max_bytes:
            b = b[:max_bytes]
        return b.decode("utf-8", errors="replace")
    except Exception:
        return ""


def relpath_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def list_tree(
    root: Path,
    max_depth: int = 3,
    ignore_dirs: Set[str] = DEFAULT_IGNORE_DIRS,
    ignore_paths: Sequence[str] = (),
) -> List[str]:
    lines: List[str] = []

    def rec(cur: Path, depth: int, prefix: str = ""):
        if depth < 0:
            return
        try:
            items = sorted(cur.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return
        for it in items:
            if is_ignored(it, ignore_dirs, root=root, ignore_paths=ignore_paths):
                continue
            if it.is_dir():
                lines.append(f"{prefix}{it.name}/")
                rec(it, depth - 1, prefix + "  ")
            else:
                lines.append(f"{prefix}{it.name}")

    rec(root, max_depth)
    return lines


def find_manifests(
    root: Path,
    max_depth: int = 4,
    ignore_dirs: Set[str] = DEFAULT_IGNORE_DIRS,
    ignore_paths: Sequence[str] = (),
) -> List[str]:
    out: List[str] = []
    for p in root.rglob("*"):
        if is_ignored(p, ignore_dirs, root=root, ignore_paths=ignore_paths):
            continue
        try:
            rel = p.relative_to(root)
        except Exception:
            continue
        if len(rel.parts) > max_depth:
            continue
        if not p.is_file():
            continue
        if p.name in MANIFEST_NAMES or p.suffix in {'.csproj', '.sln'}:
            out.append(rel.as_posix())
    return sorted(set(out))


def parse_package_scripts(pkg_json: Path) -> Dict[str, str]:
    try:
        obj = json.loads(pkg_json.read_text(encoding="utf-8"))
        scripts = obj.get("scripts", {})
        if isinstance(scripts, dict):
            return {str(k): str(v) for k, v in scripts.items()}
    except Exception:
        pass
    return {}


def detect_scan_subdirs(repo: Path) -> List[str]:
    candidates = [
        "src",
        "backend/src",
        "app/lib",
        "lib",
        "server",
        "frontend/src",
        "client/src",
        "web/src",
        "src/app",
        "src/pages",
        "src/components",
        "src/routes",
        "src/features",
        "src/hooks",
        "src/stores",
        "src/composables",
        "pages",
        "components",
        "routes",
        "apps",
        "packages",
        "services",
        "tools",
        "Views",
        "ViewModels",
        "Controls",
        "Models",
        "Converters",
        "Commands",
        "ExtentionChrome/extension",
    ]
    seen: Set[str] = set()
    out: List[str] = []
    for c in candidates:
        if c in seen:
            continue
        if (repo / c).exists():
            seen.add(c)
            out.append(c)
    return out


def resolve_ts_import(spec: str, from_file: Path) -> Optional[Path]:
    if not spec.startswith("."):
        return None
    base = (from_file.parent / spec).resolve()
    for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"):
        p = Path(str(base) + ext)
        if p.exists():
            return p
    if base.is_dir():
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"):
            p = base / ("index" + ext)
            if p.exists():
                return p
    if base.exists() and base.is_file():
        return base
    return None


def resolve_dart_import(spec: str, from_file: Path) -> Optional[Path]:
    if spec.startswith("package:") or spec.startswith("dart:"):
        return None
    if not (spec.startswith("./") or spec.startswith("../")):
        return None
    base = (from_file.parent / spec).resolve()
    if base.exists() and base.is_file():
        return base
    if not base.suffix:
        cand = Path(str(base) + ".dart")
        if cand.exists():
            return cand
    return None


def build_import_graph(
    repo: Path,
    subdirs: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    edges: Dict[str, Set[str]] = {}
    file_lang: Dict[str, str] = {}

    cs_class_index: Dict[str, str] = {}
    xaml_class_index: Dict[str, str] = {}
    candidate_files: List[Path] = []

    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs, root=repo, ignore_paths=ignore_paths) or not p.is_file():
                continue
            if p.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".dart", ".py", ".cs", ".xaml"}:
                continue
            candidate_files.append(p)
            rel = relpath_posix(p, repo)
            txt = safe_read_text(p)
            if p.suffix == '.cs':
                file_lang[rel] = 'cs'
                stem = p.stem.lower()
                cs_class_index[stem] = rel
                for _kind, rx in CS_DEF_RES[:4]:
                    for m in rx.finditer(txt):
                        cs_class_index[m.group('name').lower()] = rel
            elif p.suffix == '.xaml':
                file_lang[rel] = 'xaml'
                m = XAML_CODEBEHIND_RE.search(txt)
                if m:
                    xaml_class_index[m.group('klass').split('.')[-1].lower()] = rel

    for p in candidate_files:
        rel = relpath_posix(p, repo)
        txt = safe_read_text(p)
        if p.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"}:
            file_lang[rel] = "ts"
            specs = [m.group("spec") for m in TS_IMPORT_RE.finditer(txt)]
            specs.extend(m.group("spec") for m in TS_SIDE_EFFECT_IMPORT_RE.finditer(txt))
            for s in specs:
                rp = resolve_ts_import(s, p)
                if rp is None:
                    continue
                try:
                    edges.setdefault(rel, set()).add(relpath_posix(rp, repo))
                except Exception:
                    continue
        elif p.suffix == ".dart":
            file_lang[rel] = "dart"
            specs = [m.group("spec") for m in DART_IMPORT_RE.finditer(txt)]
            for s in specs:
                rp = resolve_dart_import(s, p)
                if rp is None:
                    continue
                try:
                    edges.setdefault(rel, set()).add(relpath_posix(rp, repo))
                except Exception:
                    continue
        elif p.suffix == ".py":
            file_lang[rel] = "py"
        elif p.suffix == '.cs':
            for m in CS_USING_RE.finditer(txt):
                target = m.group('spec').split('.')[-1].lower()
                target_rel = cs_class_index.get(target) or xaml_class_index.get(target)
                if target_rel and target_rel != rel:
                    edges.setdefault(rel, set()).add(target_rel)
            if p.name.endswith('.xaml.cs'):
                xaml_rel = rel[:-3]
                if (repo / xaml_rel).exists():
                    edges.setdefault(rel, set()).add(xaml_rel)
            stem_target = xaml_class_index.get(p.stem.lower())
            if stem_target and stem_target != rel:
                edges.setdefault(rel, set()).add(stem_target)
        elif p.suffix == '.xaml':
            codebehind = rel + '.cs'
            if (repo / codebehind).exists():
                edges.setdefault(rel, set()).add(codebehind)
            m = XAML_CODEBEHIND_RE.search(txt)
            if m:
                target = m.group('klass').split('.')[-1].lower()
                code_rel = cs_class_index.get(target)
                if code_rel and code_rel != rel:
                    edges.setdefault(rel, set()).add(code_rel)
    return edges, file_lang


def extract_symbols(
    repo: Path,
    files: Iterable[str],
    file_lang: Dict[str, str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> List[SymbolDef]:
    out: List[SymbolDef] = []
    for rel in files:
        p = repo / rel
        if not p.exists() or not p.is_file() or is_ignored(p, ignore_dirs, root=repo, ignore_paths=ignore_paths):
            continue
        txt = safe_read_text(p)
        lang = file_lang.get(rel)
        if lang == "ts":
            for kind, rx in TS_DEF_RES:
                for m in rx.finditer(txt):
                    out.append(SymbolDef(lang=lang, kind=kind, name=m.group("name"), path=rel, line=txt[: m.start()].count("\n") + 1))
        elif lang == "dart":
            for kind, rx in DART_DEF_RES:
                for m in rx.finditer(txt):
                    out.append(SymbolDef(lang=lang, kind=kind, name=m.group("name"), path=rel, line=txt[: m.start()].count("\n") + 1))
        elif lang == "py":
            for kind, rx in PY_DEF_RES:
                for m in rx.finditer(txt):
                    out.append(SymbolDef(lang=lang, kind=kind, name=m.group("name"), path=rel, line=txt[: m.start()].count("\n") + 1))
        elif lang == "cs":
            for kind, rx in CS_DEF_RES:
                for m in rx.finditer(txt):
                    out.append(SymbolDef(lang=lang, kind=kind, name=m.group("name"), path=rel, line=txt[: m.start()].count("\n") + 1))
        elif lang == "xaml":
            match = XAML_CODEBEHIND_RE.search(txt)
            if match:
                out.append(SymbolDef(lang=lang, kind='view', name=match.group('klass').split('.')[-1], path=rel, line=txt[: match.start()].count("\n") + 1))
    return out


def compute_degree_centrality(edges: Dict[str, Set[str]]) -> List[Tuple[str, int, int, int]]:
    indeg: Dict[str, int] = {}
    outdeg: Dict[str, int] = {}
    for src, dests in edges.items():
        outdeg[src] = outdeg.get(src, 0) + len(dests)
        for d in dests:
            indeg[d] = indeg.get(d, 0) + 1
    files = set(indeg) | set(outdeg)
    ranked = [(f, outdeg.get(f, 0), indeg.get(f, 0), outdeg.get(f, 0) + indeg.get(f, 0)) for f in files]
    ranked.sort(key=lambda t: (t[3], t[2], t[1]), reverse=True)
    return ranked


def extract_env_map(
    repo: Path,
    subdirs: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> Tuple[List[str], List[str], List[str], List[str]]:
    used: Set[str] = set()
    declared: Set[str] = set()

    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs) or not p.is_file():
                continue
            if p.suffix not in {".ts", ".js", ".dart"}:
                continue
            txt = safe_read_text(p)
            used.update(ENV_USAGE_RE.findall(txt))

    for env_name in (".env.example", ".env", "backend/.env.example", "backend/.env", "app/.env.example", "app/.env"):
        p = repo / env_name
        if p.exists():
            txt = safe_read_text(p)
            declared.update(ENV_KEY_LINE_RE.findall(txt))

    used_list = sorted(used)
    declared_list = sorted(declared)
    used_not_declared = sorted(used - declared)
    declared_not_used = sorted(declared - used)
    return used_list, declared_list, used_not_declared, declared_not_used


def extract_routes(
    repo: Path,
    subdirs: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> Tuple[List[RouteDef], List[RegisterCall]]:
    routes: List[RouteDef] = []
    regs: List[RegisterCall] = []
    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs) or not p.is_file() or p.suffix not in {".ts", ".js"}:
                continue
            txt = safe_read_text(p)
            rel = relpath_posix(p, repo)
            for m in FASTIFY_ROUTE_RE.finditer(txt):
                routes.append(RouteDef(method=m.group("method").upper(), path=m.group("path"), file=rel, line=txt[: m.start()].count("\n") + 1))
            for m in REGISTER_ROUTE_RE.finditer(txt):
                regs.append(RegisterCall(name=m.group(1), file=rel, line=txt[: m.start()].count("\n") + 1))
    routes.sort(key=lambda r: (r.file, r.line))
    regs.sort(key=lambda r: (r.file, r.line))
    return routes, regs


def extract_gateway_hints(
    repo: Path,
    subdirs: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs) or not p.is_file() or p.suffix not in {".ts", ".js", ".dart"}:
                continue
            rel = relpath_posix(p, repo)
            if not TRANSFER_HINT_RE.search(rel):
                continue
            txt = safe_read_text(p, max_bytes=180_000)
            if not TRANSFER_HINT_RE.search(txt):
                continue
            events = sorted({m.group(1) for m in WS_EVENT_RE.finditer(txt) if 3 <= len(m.group(1)) <= 48})
            trimmed = [e for e in events if any(ch in e for ch in (":", "-", "_"))][:20]
            if trimmed:
                out[rel] = trimmed
    return out


def extract_transfer_flow_hints(
    repo: Path,
    subdirs: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> List[TransferFileHint]:
    hints: List[TransferFileHint] = []
    interesting_words = {
        'createSession', 'attachReceiver', 'completeSession', 'markSessionCanceled',
        'registerTransferRoutes', 'registerTransferGateway', 'registerPeerGateway',
        'getChunkUploadUrl', 'getChunkDownloadUrl', 'deleteChunk', 'touchSession',
        'create_session', 'join_session', 'session_created', 'session_joined',
        'receiver_joined', 'sender_complete', 'receiver_complete', 'session_completed',
        'session_canceled', 'announce_presence', 'get_nearby_peers', 'signal', 'transfer_intent'
    }
    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob('*'):
            if is_ignored(p, ignore_dirs) or not p.is_file() or p.suffix not in {'.ts', '.js', '.dart'}:
                continue
            rel = relpath_posix(p, repo)
            if not TRANSFER_HINT_RE.search(rel):
                continue
            txt = safe_read_text(p, max_bytes=220_000)
            for word in sorted(interesting_words):
                for m in re.finditer(r'\b' + re.escape(word) + r'\b', txt):
                    line = txt[: m.start()].count('\n') + 1
                    kind = 'event' if any(ch in word for ch in ('_', '-')) and word.islower() else 'hook'
                    hints.append(TransferFileHint(file=rel, line=line, kind=kind, value=word))
                    break
    hints.sort(key=lambda h: (h.file, h.line, h.value))
    return hints[:120]


def extract_route_flow_hints(repo: Path) -> List[RouteFlowHint]:
    controller_rel = 'backend/src/modules/transfer/transfer.controller.ts'
    service_rel = 'backend/src/modules/transfer/transfer.service.ts'
    provider_candidates = [
        'backend/src/modules/transfer/chunk-url-provider.ts',
        'backend/src/modules/transfer/r2-url-provider.ts',
    ]
    controller = repo / controller_rel
    service = repo / service_rel
    if not controller.exists() or not service.exists():
        return []

    controller_txt = safe_read_text(controller, max_bytes=220_000)
    service_txt = safe_read_text(service, max_bytes=320_000)
    provider_hits: Dict[str, List[str]] = {}
    for rel in provider_candidates:
        p = repo / rel
        if not p.exists():
            continue
        txt = safe_read_text(p, max_bytes=180_000)
        hits = []
        for name in ('getUploadUrl', 'getDownloadUrl', 'deleteChunk', 'cleanupSession', 'chunkExists'):
            if re.search(r'\b' + re.escape(name) + r'\b', txt):
                hits.append(name)
        if hits:
            provider_hits[rel] = hits

    method_names = [
        'createSession', 'attachReceiver', 'touchSession', 'getChunkUploadUrl',
        'getChunkDownloadUrl', 'deleteChunk', 'getSession', 'getCompletionFlags',
        'completeSession', 'markSessionCanceled', 'isReceiverReady'
    ]

    def service_step_lines(name: str) -> List[str]:
        svc_match = re.search(r'\b' + re.escape(name) + r'\s*\(', service_txt)
        if not svc_match:
            return []
        svc_line = service_txt[: svc_match.start()].count('\n') + 1
        lines = [f'service `{name}()` at `{service_rel}:{svc_line}`']
        provider_links = []
        if name == 'getChunkUploadUrl':
            provider_links.append('getUploadUrl')
        elif name == 'getChunkDownloadUrl':
            provider_links.extend(['chunkExists', 'getDownloadUrl'])
        elif name == 'deleteChunk':
            provider_links.append('deleteChunk')
        elif name == 'completeSession':
            provider_links.append('cleanupSession')
        for provider_rel, hits in provider_hits.items():
            matched = [h for h in provider_links if h in hits]
            if matched:
                lines.append(f'provider `{provider_rel}` via `{", ".join(matched)}`')
        return lines

    def extract_balanced_block(text: str, start: int) -> str:
        open_paren = 0
        open_brace = 0
        in_single = False
        in_double = False
        in_template = False
        escaped = False
        seen_paren = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if in_single:
                if ch == "'":
                    in_single = False
                continue
            if in_double:
                if ch == '"':
                    in_double = False
                continue
            if in_template:
                if ch == '`':
                    in_template = False
                continue
            if ch == "'":
                in_single = True
                continue
            if ch == '"':
                in_double = True
                continue
            if ch == '`':
                in_template = True
                continue
            if ch == '(':
                open_paren += 1
                seen_paren = True
            elif ch == ')':
                open_paren = max(0, open_paren - 1)
            elif ch == '{':
                open_brace += 1
            elif ch == '}':
                open_brace = max(0, open_brace - 1)
            elif ch == ';' and seen_paren and open_paren == 0 and open_brace == 0:
                return text[start:idx + 1]
        return text[start:]

    helper_blocks: Dict[str, str] = {}
    for helper_name in ('createUploadHandler', 'createDownloadHandler'):
        helper_match = re.search(r'const\s+' + re.escape(helper_name) + r'\s*=\s*async\s*\(', controller_txt)
        if helper_match:
            helper_blocks[helper_name] = extract_balanced_block(controller_txt, helper_match.start())

    route_matches = list(FASTIFY_ROUTE_RE.finditer(controller_txt))
    flow_hints: List[RouteFlowHint] = []
    for m in route_matches:
        route_method = m.group('method').upper()
        route_path = m.group('path')
        route_line = controller_txt[: m.start()].count('\n') + 1
        block = extract_balanced_block(controller_txt, m.start())

        chain = [f'route `{route_method} {route_path}`', f'controller `{controller_rel}:{route_line}`']
        called: List[str] = []
        for name in method_names:
            if re.search(r'\bservice\.' + re.escape(name) + r'\b', block):
                called.append(name)

        for helper_name, helper_block in helper_blocks.items():
            if re.search(r'\b' + re.escape(helper_name) + r'\s*\(', block):
                chain.append(f'handler `{helper_name}()`')
                for name in method_names:
                    if re.search(r'\bservice\.' + re.escape(name) + r'\b', helper_block):
                        called.append(name)

        seen = set()
        for name in called:
            if name in seen:
                continue
            seen.add(name)
            for line in service_step_lines(name):
                chain.append(line)

        flow_hints.append(RouteFlowHint(method=route_method, path=route_path, file=controller_rel, line=route_line, chain=chain))

    return flow_hints[:40]


def file_dependency_details(edges: Dict[str, Set[str]], ranked: List[Tuple[str, int, int, int]]) -> Dict[str, List[str]]:
    top_files = [f for f, _, _, _ in ranked[:20]]
    details: Dict[str, List[str]] = {}
    reverse: Dict[str, List[str]] = defaultdict(list)
    for src, dests in edges.items():
        for d in dests:
            reverse[d].append(src)
    for f in top_files:
        deps = sorted(edges.get(f, set()))[:12]
        revs = sorted(reverse.get(f, []))[:12]
        lines: List[str] = []
        if deps:
            lines.append('depends on: ' + ', '.join(f'`{d}`' for d in deps))
        if revs:
            lines.append('used by: ' + ', '.join(f'`{r}`' for r in revs))
        if lines:
            details[f] = lines
    return details


def top_level_summary(repo: Path, ignore_dirs: Set[str], ignore_paths: Sequence[str] = ()) -> List[Tuple[str, str]]:
    summaries: List[Tuple[str, str]] = []
    for p in sorted(repo.iterdir(), key=lambda x: x.name.lower()):
        if is_ignored(p, ignore_dirs, root=repo, ignore_paths=ignore_paths):
            continue
        if p.is_dir():
            desc = DIR_RESP_HINTS.get(p.name.lower(), 'directory')
            summaries.append((p.name + '/', desc))
    return summaries


def nested_module_summary(
    repo: Path,
    roots: Sequence[str],
    ignore_dirs: Set[str],
    ignore_paths: Sequence[str] = (),
) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    preferred_groups = {
        'app', 'pages', 'routes', 'features', 'components', 'widgets', 'hooks',
        'stores', 'state', 'composables', 'layouts', 'core', 'lib', 'modules',
        'services', 'controllers', 'gateways', 'providers', 'api'
    }

    def add_group(rel: str, desc: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        out.append((rel, desc))

    for root in roots:
        base = repo / root
        if not base.exists() or not base.is_dir() or should_ignore_rel(root, ignore_paths):
            continue
        try:
            items = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except Exception:
            continue
        for p in items:
            if is_ignored(p, ignore_dirs, root=repo, ignore_paths=ignore_paths):
                continue
            if not p.is_dir():
                continue
            rel = relpath_posix(p, repo) + '/'
            desc = DIR_RESP_HINTS.get(p.name.lower(), 'module / feature group')
            add_group(rel, desc)

            lower_name = p.name.lower()
            if lower_name not in preferred_groups:
                continue
            try:
                child_items = sorted(p.iterdir(), key=lambda x: x.name.lower())
            except Exception:
                continue
            for child in child_items[:40]:
                if is_ignored(child, ignore_dirs, root=repo, ignore_paths=ignore_paths):
                    continue
                if not child.is_dir():
                    continue
                child_rel = relpath_posix(child, repo) + '/'
                child_desc = DIR_RESP_HINTS.get(child.name.lower(), 'module / feature slice')
                add_group(child_rel, child_desc)
    return out


def detect_backend_entry(repo: Path) -> Optional[str]:
    candidates = (
        "backend/src/main.ts", "backend/src/index.ts", "src/main.ts", "src/index.ts",
        "server/index.ts", "server/main.ts", "api/index.ts", "api/server.ts",
        "backend/src/main.js", "backend/src/index.js", "server/index.js", "server/main.js",
        "src/server.ts", "src/app.ts", "server/app.ts", "api/app.ts",
        "Program.cs",
    )
    for cand in candidates:
        if (repo / cand).exists():
            return cand
    return None


def detect_frontend_entry(repo: Path) -> Optional[str]:
    priority_candidates = (
        "app/lib/main.dart", "lib/main.dart",
        "src/main.tsx", "src/main.jsx", "src/main.ts", "src/main.js",
        "frontend/src/main.tsx", "frontend/src/main.jsx", "frontend/src/main.ts", "frontend/src/main.js",
        "client/src/main.tsx", "client/src/main.jsx", "client/src/main.ts", "client/src/main.js",
        "web/src/main.ts", "web/src/main.js", "web/src/main.tsx", "web/src/main.jsx",
        "pages/_app.tsx", "pages/_app.jsx", "pages/index.tsx", "pages/index.jsx",
        "app/page.tsx", "app/page.jsx", "src/app/page.tsx", "src/app/page.jsx",
        "src/App.tsx", "src/App.jsx", "frontend/src/App.tsx", "frontend/src/App.jsx",
        "client/src/App.tsx", "client/src/App.jsx", "web/src/App.tsx", "web/src/App.jsx",
        "App.xaml", "MainWindow.xaml",
    )
    for cand in priority_candidates:
        if (repo / cand).exists():
            return cand

    for rel in (
        "app", "src/app", "pages", "src/pages", "src/routes", "routes",
        "src", "frontend/src", "client/src", "web/src",
    ):
        base = repo / rel
        if not base.exists() or not base.is_dir():
            continue
        for name in (
            "page.tsx", "page.jsx", "layout.tsx", "layout.jsx",
            "index.tsx", "index.jsx", "main.tsx", "main.jsx", "main.ts", "main.js",
            "App.tsx", "App.jsx", "app.tsx", "app.jsx",
        ):
            matches = sorted(base.rglob(name))
            if matches:
                return relpath_posix(matches[0], repo)
    return None


def architecture_summary_lines(
    repo: Path,
    top_summary: List[Tuple[str, str]],
    module_summary: List[Tuple[str, str]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    route_flow_hints: List[RouteFlowHint],
    gateway_hints: Dict[str, List[str]],
) -> List[str]:
    lines: List[str] = []

    top_names = {name.rstrip('/') for name, _desc in top_summary}
    module_names = [name.rstrip('/') for name, _desc in module_summary]

    frontend_prefixes = (
        'app/lib/features/', 'app/lib/core/', 'src/app/', 'src/pages/', 'src/components/',
        'src/features/', 'src/routes/', 'src/hooks/', 'src/stores/', 'src/composables/',
        'src/state/', 'src/layouts/', 'frontend/src/', 'client/src/', 'web/src/',
        'pages/', 'components/', 'routes/'
    )
    desktop_prefixes = ('Views/', 'ViewModels/', 'Controls/', 'Models/', 'Converters/', 'Commands/', 'Services/')
    app_groups = [name for name in module_names if name.startswith(frontend_prefixes)]
    desktop_groups = [name for name in module_names if name.startswith(desktop_prefixes)]
    backend_groups = [name.split('/')[-1] for name in module_names if name.startswith(('backend/src/modules/', 'server/', 'services/', 'api/'))]

    def frontend_group_label(path: str) -> Optional[str]:
        normalized = path.rstrip('/')
        base = normalized.split('/')[-1].lower()
        if base in {'app', 'pages', 'routes'}:
            return 'route surface'
        if base in {'features'}:
            return 'feature screens'
        if base in {'components', 'widgets'}:
            return 'UI components'
        if base in {'hooks', 'stores', 'state', 'composables'}:
            return 'state / client logic'
        if base in {'core', 'lib', 'layouts'}:
            return 'shared app shell/core'
        parts = normalized.split('/')
        if any(part in {'pages', 'routes', 'app'} for part in parts):
            return 'route surface'
        if any(part in {'components', 'widgets'} for part in parts):
            return 'UI components'
        if any(part in {'hooks', 'stores', 'state', 'composables'} for part in parts):
            return 'state / client logic'
        return None

    frontend_labels: List[str] = []
    seen_frontend_labels: Set[str] = set()
    for name in app_groups:
        label = frontend_group_label(name)
        if label and label not in seen_frontend_labels:
            seen_frontend_labels.add(label)
            frontend_labels.append(label)

    if backend_entry or flutter_entry:
        runtime_parts: List[str] = []
        if backend_entry:
            if backend_entry.endswith('Program.cs'):
                runtime_parts.append(f"desktop runtime enters at `{backend_entry}`")
            else:
                runtime_parts.append(f"backend runtime enters at `{backend_entry}`")
        if flutter_entry:
            if flutter_entry.endswith('.xaml'):
                runtime_parts.append(f"desktop UI shell enters at `{flutter_entry}`")
            else:
                runtime_parts.append(f"app/frontend runtime enters at `{flutter_entry}`")
        lines.append(f"- Runtime entrypoints: {'; '.join(runtime_parts)}")

    subsystem_bits: List[str] = []
    frontend_roots = {'app', 'frontend', 'client', 'web'}
    if top_names & frontend_roots or flutter_entry:
        if frontend_labels:
            subsystem_bits.append(f"frontend shape: {', '.join(f'`{name}`' for name in frontend_labels[:5])}")
        elif app_groups:
            raw_groups = [name.split('/')[-1] for name in app_groups[:6]]
            subsystem_bits.append(f"frontend groups: {', '.join(f'`{name}`' for name in raw_groups)}")
        else:
            subsystem_bits.append("frontend/app layer present")
    if 'backend' in top_names or 'server' in top_names or backend_entry:
        if backend_groups:
            subsystem_bits.append(f"backend groups: {', '.join(f'`{name}`' for name in backend_groups[:8])}")
        elif not desktop_groups:
            subsystem_bits.append("backend/service layer present")
    if desktop_groups or backend_entry == 'Program.cs' or (flutter_entry and flutter_entry.endswith('.xaml')):
        desktop_labels: List[str] = []
        for path in desktop_groups:
            base = path.rstrip('/').split('/')[-1]
            if base not in desktop_labels:
                desktop_labels.append(base)
        if desktop_labels:
            subsystem_bits.append(f"desktop app shape: {', '.join(f'`{name}`' for name in desktop_labels[:6])}")
        else:
            subsystem_bits.append("desktop app layers present")
    if 'ExtentionChrome' in top_names:
        subsystem_bits.append("browser extension surface present")
    if subsystem_bits:
        lines.append(f"- Main subsystems: {'; '.join(subsystem_bits)}")

    meaningful_shared = [label for label in frontend_labels if label in {'UI components', 'state / client logic', 'shared app shell/core'}]
    if meaningful_shared:
        lines.append(f"- Shared frontend building blocks: {', '.join(f'`{name}`' for name in meaningful_shared[:3])}")
    elif desktop_groups:
        desktop_shared = [
            path.rstrip('/').split('/')[-1] for path in desktop_groups
            if any(path.startswith(prefix) for prefix in ('Controls/', 'Converters/', 'Commands/', 'ViewModels/'))
        ]
        if desktop_shared:
            deduped: List[str] = []
            for item in desktop_shared:
                if item not in deduped:
                    deduped.append(item)
            lines.append(f"- Shared desktop building blocks: {', '.join(f'`{name}`' for name in deduped[:4])}")

    if route_flow_hints:
        unique_routes: List[str] = []
        seen_routes: Set[str] = set()
        flow_files: List[str] = []
        seen_flow_files: Set[str] = set()
        for hint in route_flow_hints:
            route_label = f"{hint.method} {hint.path}"
            if route_label not in seen_routes:
                seen_routes.add(route_label)
                unique_routes.append(route_label)
            for step in hint.chain:
                for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
                    file_path = file_match.split(':', 1)[0]
                    if file_path not in seen_flow_files:
                        seen_flow_files.add(file_path)
                        flow_files.append(file_path)
        lines.append(f"- Detected route/flow coverage: {len(unique_routes)} route paths with chain hints across {len(flow_files)} source files")

    gateway_files = list(gateway_hints.keys())
    if gateway_files:
        lines.append(f"- Event/realtime surfaces: {', '.join(f'`{name}`' for name in gateway_files[:6])}")

    if not lines:
        lines.append("- (No high-confidence architecture summary detected yet.)")
    return lines



def mermaid_safe_id(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_]+', '_', value).strip('_')
    return cleaned or 'node'


def mermaid_safe_label(value: str) -> str:
    return value.replace('"', "'")


def render_architecture_mermaid(
    repo: Path,
    top_summary: List[Tuple[str, str]],
    module_summary: List[Tuple[str, str]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    route_flow_hints: List[RouteFlowHint],
    gateway_hints: Dict[str, List[str]],
) -> List[str]:
    lines: List[str] = []
    lines.append('flowchart LR')
    lines.append(f'    repo["{mermaid_safe_label(repo.name)}"]')

    added_nodes: Set[str] = set()
    added_edges: Set[Tuple[str, str, str]] = set()
    node_defs: List[str] = []
    app_defs: List[str] = []
    backend_defs: List[str] = []
    flow_defs: List[str] = []
    edge_lines: List[str] = []

    def shorten_label(value: str, max_len: int = 34) -> str:
        if len(value) <= max_len:
            return value
        return value[: max_len - 3] + '...'

    def bucket_for(node_id: str) -> List[str]:
        if node_id.startswith(('app_', 'mod_app_', 'gw_app_', 'hint_app_')):
            return app_defs
        if node_id.startswith(('backend_', 'mod_backend_', 'route_', 'gw_backend_', 'hint_backend_')):
            return backend_defs
        if node_id.startswith('flow_'):
            return flow_defs
        return node_defs

    def add_node(node_id: str, label: str) -> None:
        if node_id in added_nodes:
            return
        added_nodes.add(node_id)
        bucket_for(node_id).append(f'        {node_id}["{mermaid_safe_label(label)}"]')

    def add_edge(src: str, dst: str, label: str = '') -> None:
        key = (src, dst, label)
        if key in added_edges:
            return
        added_edges.add(key)
        if label:
            edge_lines.append(f'    {src} -->|{mermaid_safe_label(label)}| {dst}')
        else:
            edge_lines.append(f'    {src} --> {dst}')

    def classify_frontend_group(path: str) -> Tuple[int, str]:
        normalized = path.rstrip('/')
        base = normalized.split('/')[-1].lower()
        parts = normalized.split('/')
        mapping = {
            'app': (1, 'app router'),
            'pages': (1, 'route pages'),
            'routes': (1, 'route modules'),
            'features': (2, 'feature screens'),
            'components': (3, 'UI components'),
            'widgets': (3, 'UI components'),
            'hooks': (4, 'hooks / state'),
            'stores': (4, 'state store'),
            'state': (4, 'state store'),
            'composables': (4, 'vue composables'),
            'layouts': (5, 'app shell / layouts'),
            'core': (5, 'shared client core'),
            'lib': (5, 'shared client library'),
        }
        if base in mapping:
            return mapping[base]
        if any(part in {'pages', 'routes', 'app'} for part in parts):
            return (1, shorten_label(base or normalized.split('/')[-1], 24))
        if any(part in {'components', 'widgets'} for part in parts):
            return (3, shorten_label(base or normalized.split('/')[-1], 24))
        if any(part in {'hooks', 'stores', 'state', 'composables'} for part in parts):
            return (4, shorten_label(base or normalized.split('/')[-1], 24))
        if any(part in {'layouts', 'core', 'lib'} for part in parts):
            return (5, shorten_label(base or normalized.split('/')[-1], 24))
        return (6, shorten_label(base or normalized.split('/')[-1], 24))

    def classify_backend_group(path: str) -> Tuple[int, str]:
        normalized = path.rstrip('/')
        base = normalized.split('/')[-1].lower()
        mapping = {
            'modules': (1, 'backend modules'),
            'api': (1, 'API handlers'),
            'routes': (1, 'route handlers'),
            'controllers': (2, 'controllers'),
            'services': (3, 'services'),
            'gateways': (4, 'realtime gateways'),
            'providers': (5, 'providers / adapters'),
            'lib': (6, 'shared server lib'),
        }
        return mapping.get(base, (7, shorten_label(base or normalized.split('/')[-1], 24)))

    def runtime_label(file_path: str) -> str:
        base = file_path.split('/')[-1]
        mapping = {
            'transfer.controller.ts': 'transfer controller',
            'transfer.service.ts': 'transfer service',
            'transfer.gateway.ts': 'transfer gateway',
            'peer.gateway.ts': 'peer gateway',
            'chunk-url-provider.ts': 'chunk URL provider',
            'r2-url-provider.ts': 'R2 URL provider',
            'cloud_adapter_mobile.dart': 'mobile cloud adapter',
            'cloud_adapter_web.dart': 'web cloud adapter',
            'lan_discovery_mobile.dart': 'LAN discovery (mobile)',
            'lan_discovery_web.dart': 'LAN discovery (web)',
            'main.dart': 'app bootstrap',
            'main.tsx': 'frontend bootstrap',
            'main.jsx': 'frontend bootstrap',
            'app.tsx': 'app shell',
            'app.jsx': 'app shell',
            'page.tsx': 'route page',
            'page.jsx': 'route page',
        }
        return mapping.get(base.lower(), shorten_label(base, 24))

    top_names = {name.rstrip('/') for name, _desc in filter_top_summary_items(top_summary)}
    module_names = [name.rstrip('/') for name, _desc in module_summary]

    frontend_prefixes = (
        'app/lib/features/', 'app/lib/core/', 'src/app/', 'src/pages/', 'src/components/',
        'src/features/', 'src/routes/', 'src/hooks/', 'src/stores/', 'src/state/',
        'src/composables/', 'src/layouts/', 'frontend/src/', 'client/src/', 'web/src/',
        'pages/', 'components/', 'routes/'
    )
    backend_prefixes = ('backend/src/modules/', 'server/', 'services/', 'api/')

    frontend_groups = [name for name in module_names if name.startswith(frontend_prefixes)]
    backend_groups = [name for name in module_names if name.startswith(backend_prefixes)]
    has_frontend = bool(frontend_groups or flutter_entry or (top_names & {'app', 'frontend', 'client', 'web'}))
    has_backend = bool(backend_groups or backend_entry or 'backend' in top_names or 'server' in top_names)

    if has_frontend:
        add_node('app_surface', 'frontend / app shell')
        add_edge('repo', 'app_surface')
    if has_backend:
        backend_label = 'backend / API' if route_flow_hints else 'backend / services'
        add_node('backend_surface', backend_label)
        add_edge('repo', 'backend_surface')

    if flutter_entry and has_frontend:
        add_node('app_entry', runtime_label(flutter_entry))
        add_edge('app_surface', 'app_entry', 'entry')

    if backend_entry and has_backend:
        add_node('backend_entry', 'backend entry')
        add_edge('backend_surface', 'backend_entry', 'entry')

    selected_frontend: List[Tuple[int, str, str]] = []
    for name in frontend_groups:
        priority, label = classify_frontend_group(name)
        selected_frontend.append((priority, label, name))
    selected_frontend.sort(key=lambda item: (item[0], item[1], item[2]))

    selected_backend: List[Tuple[int, str, str]] = []
    for name in backend_groups:
        priority, label = classify_backend_group(name)
        selected_backend.append((priority, label, name))
    selected_backend.sort(key=lambda item: (item[0], item[1], item[2]))

    frontend_node_ids_by_label: Dict[str, str] = {}
    for priority, label, name in selected_frontend[:4]:
        node_id = 'mod_app_' + mermaid_safe_id(name)
        frontend_node_ids_by_label[label] = node_id
        add_node(node_id, label)
        add_edge('app_surface', node_id, 'group')

    for _priority, label, name in selected_backend[:3]:
        node_id = 'mod_backend_' + mermaid_safe_id(name)
        add_node(node_id, label)
        add_edge('backend_surface', node_id, 'group')

    ranked_route_hints = sorted(
        route_flow_hints,
        key=lambda hint: (
            'health' in hint.path,
            'status' in hint.path,
            len(hint.path),
        ),
    )

    seen_route_paths: Set[str] = set()
    runtime_file_order: List[str] = []
    seen_runtime_files: Set[str] = set()
    for hint in ranked_route_hints:
        route_key = f'{hint.method} {hint.path}'
        if route_key in seen_route_paths:
            continue
        seen_route_paths.add(route_key)
        route_id = 'route_' + mermaid_safe_id(hint.method + '_' + hint.path)
        add_node(route_id, shorten_label(route_key, 28))
        add_edge('backend_surface', route_id, 'route')

        route_runtime_files: List[str] = []
        seen_files: Set[str] = set()
        for step in hint.chain:
            for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
                file_path = file_match.split(':', 1)[0]
                if file_path in seen_files:
                    continue
                lower = file_path.lower()
                if not any(token in lower for token in ('controller', 'service', 'gateway', 'provider')):
                    continue
                seen_files.add(file_path)
                route_runtime_files.append(file_path)
                if file_path not in seen_runtime_files:
                    seen_runtime_files.add(file_path)
                    runtime_file_order.append(file_path)
        if route_runtime_files:
            first_file = route_runtime_files[0]
            first_id = 'flow_' + mermaid_safe_id(first_file)
            add_node(first_id, runtime_label(first_file))
            add_edge(route_id, first_id, 'uses')
        if len(seen_route_paths) >= 2:
            break

    spine_candidates: List[Tuple[int, str]] = []
    for file_path in runtime_file_order:
        lower = file_path.lower()
        priority = 99
        if 'controller' in lower:
            priority = 1
        elif 'service' in lower:
            priority = 2
        elif 'gateway' in lower:
            priority = 3
        elif 'provider' in lower:
            priority = 4
        spine_candidates.append((priority, file_path))
    spine_candidates.sort()
    spine_files = [file_path for _priority, file_path in spine_candidates[:4]]

    prev_spine = 'backend_entry' if backend_entry and has_backend else 'backend_surface'
    for file_path in spine_files:
        flow_id = 'flow_' + mermaid_safe_id(file_path)
        add_node(flow_id, runtime_label(file_path))
        add_edge(prev_spine, flow_id, 'spine')
        prev_spine = flow_id

    if has_frontend:
        frontend_story_order = [
            'app router', 'route pages', 'route modules', 'feature screens',
            'UI components', 'hooks / state', 'state store', 'vue composables',
            'app shell / layouts', 'shared client core', 'shared client library'
        ]
        prev_front = 'app_entry' if flutter_entry else 'app_surface'
        seen_front_story: Set[str] = set()
        linked_any = False
        for label in frontend_story_order:
            node_id = frontend_node_ids_by_label.get(label)
            if not node_id or node_id in seen_front_story:
                continue
            seen_front_story.add(node_id)
            add_edge(prev_front, node_id, 'spine')
            prev_front = node_id
            linked_any = True
        if not linked_any:
            fallback_labels = sorted(frontend_node_ids_by_label.items())[:3]
            for _label, node_id in fallback_labels:
                if node_id in seen_front_story:
                    continue
                add_edge(prev_front, node_id, 'spine')
                prev_front = node_id

    preferred_app_links = []
    preferred_backend_links = []
    for file_path, hints in sorted(gateway_hints.items()):
        lower = file_path.lower()
        if any(token in lower for token in ('cloud_adapter_mobile', 'cloud_adapter_web', 'lan_discovery_mobile', 'lan_discovery_web', 'client', 'adapter')):
            preferred_app_links.append((file_path, hints))
        elif any(token in lower for token in ('transfer.gateway', 'peer.gateway', 'socket', 'ws')):
            preferred_backend_links.append((file_path, hints))

    for file_path, hints in preferred_app_links[:2]:
        gw_id = 'gw_app_' + mermaid_safe_id(file_path)
        add_node(gw_id, runtime_label(file_path))
        anchor = 'app_surface'
        if 'hooks / state' in frontend_node_ids_by_label:
            anchor = frontend_node_ids_by_label['hooks / state']
        elif 'shared client core' in frontend_node_ids_by_label:
            anchor = frontend_node_ids_by_label['shared client core']
        add_edge(anchor, gw_id, 'network')
        meaningful = [h for h in hints if not h.startswith(('dart:', 'package:'))]
        meaningful = [h for h in meaningful if not any(t in h.lower() for t in ('content-type', 'content-disposition', 'x-drops-file-size'))]
        if meaningful:
            hint = meaningful[0]
            hint_id = 'hint_app_' + mermaid_safe_id(file_path + hint)
            add_node(hint_id, shorten_label(hint, 20))
            add_edge(gw_id, hint_id, 'event')

    for file_path, hints in preferred_backend_links[:2]:
        gw_id = 'gw_backend_' + mermaid_safe_id(file_path)
        add_node(gw_id, runtime_label(file_path))
        add_edge('backend_surface', gw_id, 'signal')
        meaningful = [h for h in hints if not h.startswith(('dart:', 'package:'))]
        if meaningful:
            hint = meaningful[0]
            hint_id = 'hint_backend_' + mermaid_safe_id(file_path + hint)
            add_node(hint_id, shorten_label(hint, 20))
            add_edge(gw_id, hint_id, 'event')

    lines.extend(node_defs)
    if app_defs:
        lines.append('    subgraph APP["Frontend / Client"]')
        lines.extend(app_defs)
        lines.append('    end')
    if backend_defs:
        lines.append('    subgraph BACKEND["Backend / Server"]')
        lines.extend(backend_defs)
        lines.append('    end')
    if flow_defs:
        flow_title = 'Runtime spine' if not route_flow_hints else 'Route / runtime spine'
        lines.append(f'    subgraph FLOW["{flow_title}"]')
        lines.extend(flow_defs)
        lines.append('    end')

    lines.extend(edge_lines)
    lines.append('    classDef root fill:#f8fafc,stroke:#475569,stroke-width:1.5px')
    lines.append('    classDef app fill:#ecfeff,stroke:#0891b2,stroke-width:1.2px')
    lines.append('    classDef backend fill:#fff7ed,stroke:#ea580c,stroke-width:1.2px')
    lines.append('    classDef flow fill:#f5f3ff,stroke:#7c3aed,stroke-width:1.2px')
    lines.append('    class repo root')
    if app_defs:
        app_nodes = ' '.join(sorted(node_id for node_id in added_nodes if node_id.startswith(('app_', 'mod_app_', 'gw_app_', 'hint_app_'))))
        if app_nodes:
            lines.append(f'    class {app_nodes} app')
    if backend_defs:
        backend_nodes = ' '.join(sorted(node_id for node_id in added_nodes if node_id.startswith(('backend_', 'mod_backend_', 'route_', 'gw_backend_', 'hint_backend_'))))
        if backend_nodes:
            lines.append(f'    class {backend_nodes} backend')
    if flow_defs:
        flow_nodes = ' '.join(sorted(node_id for node_id in added_nodes if node_id.startswith('flow_')))
        if flow_nodes:
            lines.append(f'    class {flow_nodes} flow')

    return lines


def filter_top_summary_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    hidden_roots = {'.agent/', '.claude/', '.gitnexus/', 'graplite-scan/'}
    return [item for item in items if item[0] not in hidden_roots]


def filter_tree_lines(lines: List[str]) -> List[str]:
    noisy_contains = (
        'ephemeral/',
        '.DS_Store',
        'index.scip',
        '.flutter-plugins-dependencies',
        'analyze_output',
        'build_log',
        'final_check.txt',
        'check.txt',
        'check2.txt',
    )
    hidden_roots = {'.agent/', '.claude/', '.gitnexus/', 'graplite-scan/'}
    filtered: List[str] = []
    skip_indent: Optional[int] = None
    for line in lines:
        indent = len(line) - len(line.lstrip(' '))
        stripped = line.strip()
        if skip_indent is not None:
            if indent > skip_indent:
                continue
            skip_indent = None
        if stripped in hidden_roots:
            skip_indent = indent
            continue
        if any(marker in stripped for marker in noisy_contains):
            continue
        filtered.append(line)
    return filtered


def approx_symbol_scores(symbols: List[SymbolDef], file_lang: Dict[str, str], repo: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    files = list(file_lang.keys())
    text_cache = {rel: safe_read_text(repo / rel) for rel in files}
    for sd in symbols:
        total = 0
        rx = re.compile(r"\b" + re.escape(sd.name) + r"\b")
        for rel, txt in text_cache.items():
            if rel == sd.path:
                continue
            total += len(rx.findall(txt))
        counts[f"{sd.lang}:{sd.kind}:{sd.name}:{sd.path}:{sd.line}"] = total
    return counts


def detect_scip_readiness(repo: Path) -> ScipReadiness:
    candidates = [
        (repo / 'backend', 'typescript-subproject'),
        (repo, 'typescript-root'),
    ]
    for root, kind in candidates:
        if not root.exists():
            continue
        has_tsconfig = any((root / name).exists() for name in ('tsconfig.json', 'tsconfig.base.json'))
        has_package = (root / 'package.json').exists()
        if not has_package:
            continue
        reasons: List[str] = []
        if has_tsconfig:
            reasons.append('tsconfig detected')
            return ScipReadiness(
                enabled=True,
                repo_kind=kind,
                indexer='scip-typescript index',
                project_root=relpath_posix(root, repo),
                index_path=relpath_posix(root / 'index.scip', repo),
                reasons=reasons,
            )
        reasons.append('package.json detected, tsconfig missing')
        return ScipReadiness(
            enabled=True,
            repo_kind='javascript-root',
            indexer='scip-typescript index --infer-tsconfig',
            project_root=relpath_posix(root, repo),
            index_path=relpath_posix(root / 'index.scip', repo),
            reasons=reasons,
        )
    return ScipReadiness(
        enabled=False,
        repo_kind='unsupported',
        indexer='scip-typescript index',
        project_root='.',
        index_path='index.scip',
        reasons=['no package.json/tsconfig combination detected for TS/JS indexing'],
    )


def detect_scip_index_status(repo: Path, scip_readiness: ScipReadiness) -> ScipIndexStatus:
    def extract_printable_strings(data: bytes, min_len: int = 6) -> List[str]:
        out: List[str] = []
        cur: List[str] = []
        for b in data:
            if 32 <= b < 127:
                cur.append(chr(b))
            else:
                if len(cur) >= min_len:
                    out.append(''.join(cur))
                cur = []
        if len(cur) >= min_len:
            out.append(''.join(cur))
        return out

    def normalize_symbol_hint(raw: str) -> Optional[str]:
        raw = raw.strip()
        raw = re.sub(r'^[^a-zA-Z]+', '', raw)
        match = re.search(r'(src/[A-Za-z0-9_./\-]+/`?[A-Za-z0-9_.\-]+\.ts`?)/([^\s]+)$', raw)
        if not match:
            return None
        path = match.group(1).replace('`', '')
        symbol = match.group(2)
        symbol = symbol.replace('`', '')
        symbol = re.sub(r'\([^)]*\)', '()', symbol)
        symbol = symbol.replace('.()', '()')
        while '()()' in symbol:
            symbol = symbol.replace('()()', '()')
        symbol = re.sub(r'\.+$', '', symbol)
        symbol = symbol.strip('/ ')
        if symbol.endswith('#'):
            return None
        if not symbol or symbol in {'local', 'export'}:
            return None
        return f'{path} :: {symbol}'

    def read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
        shift = 0
        value = 0
        while pos < len(buf):
            b = buf[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                return value, pos
            shift += 7
        raise ValueError('unexpected EOF while reading varint')

    def read_length_delimited(buf: bytes, pos: int) -> Tuple[bytes, int]:
        size, pos = read_varint(buf, pos)
        end = pos + size
        return buf[pos:end], end

    def iter_fields(buf: bytes) -> Iterable[Tuple[int, int, bytes]]:
        pos = 0
        while pos < len(buf):
            key, pos = read_varint(buf, pos)
            field_no = key >> 3
            wire_type = key & 0x7
            if wire_type == 0:
                value, pos = read_varint(buf, pos)
                yield field_no, wire_type, str(value).encode('utf-8')
            elif wire_type == 2:
                value, pos = read_length_delimited(buf, pos)
                yield field_no, wire_type, value
            elif wire_type == 5:
                value = buf[pos:pos + 4]
                pos += 4
                yield field_no, wire_type, value
            elif wire_type == 1:
                value = buf[pos:pos + 8]
                pos += 8
                yield field_no, wire_type, value
            else:
                raise ValueError(f'unsupported wire type {wire_type}')

    def decode_utf8(value: bytes) -> str:
        return value.decode('utf-8', errors='replace')

    def parse_metadata(buf: bytes) -> Tuple[str, str, str]:
        tool_name = ''
        tool_version = ''
        project_root = ''
        for field_no, wire_type, value in iter_fields(buf):
            if field_no == 2 and wire_type == 2:
                for nested_no, nested_wire, nested_val in iter_fields(value):
                    if nested_wire != 2:
                        continue
                    if nested_no == 1:
                        tool_name = decode_utf8(nested_val)
                    elif nested_no == 2:
                        tool_version = decode_utf8(nested_val)
            elif field_no == 3 and wire_type == 2:
                project_root = decode_utf8(value)
        return tool_name, tool_version, project_root

    def normalize_structured_symbol(symbol_text: str, display_name: str) -> Optional[str]:
        if display_name:
            cleaned_display = display_name.strip()
            if cleaned_display:
                return cleaned_display

        symbol_text = symbol_text.strip()
        if not symbol_text or symbol_text.startswith('local '):
            return None

        parts = symbol_text.split(' ')
        if len(parts) < 4:
            return None
        descriptor_blob = ' '.join(parts[3:])

        raw_segments = [seg for seg in descriptor_blob.split('/') if seg]
        if not raw_segments:
            return None

        cleaned_segments: List[str] = []
        for seg in raw_segments:
            seg = seg.replace('`', '')
            seg = re.sub(r'\([^)]*\)', '()', seg)
            seg = seg.replace('.()', '()')
            while '()()' in seg:
                seg = seg.replace('()()', '()')
            seg = re.sub(r'\.+$', '', seg)
            seg = seg.strip()
            if not seg:
                continue
            if seg.endswith('#'):
                cleaned_segments.append(seg)
            elif seg.endswith('.'):
                cleaned_segments.append(seg[:-1] + '()')
            else:
                cleaned_segments.append(seg)

        if not cleaned_segments:
            return None

        tail = cleaned_segments[-1]
        if tail.startswith('(') and len(cleaned_segments) >= 2:
            tail = cleaned_segments[-2] + tail
        if len(cleaned_segments) >= 2 and cleaned_segments[-2].endswith('#') and not tail.startswith(cleaned_segments[-2][:-1]):
            base = cleaned_segments[-2][:-1]
            if tail.startswith('('):
                tail = base + tail
            elif tail != base and not tail.startswith(base + '#'):
                tail = base + '#' + tail
        tail = tail.strip()
        if not tail or tail.endswith('#'):
            return None
        if tail.endswith('.ts') or '/' in tail:
            return None
        if tail.startswith('(') or '.(' in tail or tail.endswith('()()'):
            return None
        lower_tail = tail.lower()
        if any(token in lower_tail for token in ('typeliteral', 'objectliteral', 'tupleliteral', 'indexsignature')):
            return None
        if any(token in lower_tail for token in ('<constructor>', 'constructorsignature', 'callsignature')):
            return None
        if any(token in lower_tail for token in (':parameter', ':local', ':meta')):
            return None
        return tail

    def parse_occurrence_range_start_line(value: bytes, wire_type: int) -> Optional[int]:
        ints: List[int] = []
        if wire_type == 0:
            try:
                ints.append(int(decode_utf8(value)))
            except ValueError:
                return None
        elif wire_type == 2:
            pos = 0
            while pos < len(value):
                try:
                    item, pos = read_varint(value, pos)
                except ValueError:
                    break
                ints.append(int(item))
        if not ints:
            return None
        start_line = ints[0]
        if start_line < 0:
            return None
        return start_line + 1

    def parse_occurrence(buf: bytes) -> Tuple[Optional[str], bool, Optional[int]]:
        symbol_text = ''
        symbol_roles = 0
        start_line: Optional[int] = None
        for field_no, wire_type, value in iter_fields(buf):
            if field_no == 1 and wire_type in {0, 2} and start_line is None:
                start_line = parse_occurrence_range_start_line(value, wire_type)
            elif field_no == 2 and wire_type == 2:
                symbol_text = decode_utf8(value)
            elif field_no == 3 and wire_type == 0:
                try:
                    symbol_roles = int(decode_utf8(value))
                except ValueError:
                    symbol_roles = 0
        normalized = normalize_structured_symbol(symbol_text, '') if symbol_text else None
        is_definition = bool(symbol_roles & 0x1)
        return normalized, is_definition, start_line

    def is_generic_structured_symbol(symbol: str) -> bool:
        lower = symbol.lower().strip()
        if not lower:
            return True
        generic_exact = {
            'process', 'console', 'promise', 'string', 'number', 'boolean', 'object',
            'array', 'map', 'set', 'date', 'error', 'json', 'math', 'buffer'
        }
        if lower in generic_exact:
            return True
        generic_prefixes = (
            'node:', 'globalthis#', 'process#', 'console#', 'map#', 'set#', 'array#',
            'string#', 'number#', 'boolean#', 'object#', 'promise#', 'fastifyreply#',
            'fastifyrequest#', 'socket#', 'server#'
        )
        if lower.startswith(generic_prefixes):
            return True
        generic_contains = (
            'fastifyreply#', 'fastifyrequest#', 'incomingmessage#', 'serverresponse#',
            '__type', '<', 'typeof '
        )
        if any(token in lower for token in generic_contains):
            return True
        if symbol.startswith('"') and symbol.endswith('"'):
            return True
        if lower.endswith('()') and '#' not in lower and lower in {
            'parse()', 'stringify()', 'log()', 'warn()', 'error()', 'info()', 'send()'
        }:
            return True
        return False

    def parse_document(buf: bytes) -> Tuple[str, str, List[str], List[Tuple[str, bool, Optional[int]]]]:
        relative_path = ''
        language = ''
        symbols: List[str] = []
        occurrences: List[Tuple[str, bool, Optional[int]]] = []
        for field_no, wire_type, value in iter_fields(buf):
            if wire_type != 2:
                continue
            if field_no == 1:
                relative_path = decode_utf8(value)
            elif field_no == 4:
                language = decode_utf8(value)
            elif field_no == 2:
                normalized_occurrence, is_definition, start_line = parse_occurrence(value)
                if normalized_occurrence:
                    occurrences.append((normalized_occurrence, is_definition, start_line))
            elif field_no == 3:
                symbol_text = ''
                display_name = ''
                for nested_no, nested_wire, nested_val in iter_fields(value):
                    if nested_wire != 2:
                        continue
                    if nested_no == 1:
                        symbol_text = decode_utf8(nested_val)
                    elif nested_no == 6:
                        display_name = decode_utf8(nested_val)
                normalized = normalize_structured_symbol(symbol_text, display_name)
                if normalized:
                    symbols.append(normalized)
        return relative_path, language, symbols, occurrences

    index_path = repo / scip_readiness.index_path
    if not scip_readiness.enabled:
        return ScipIndexStatus(
            exists=False,
            path=scip_readiness.index_path,
            size_bytes=0,
            summary=['SCIP not enabled for this repo shape yet'],
            document_hints=[],
            symbol_hints=[],
            tool_name='',
            tool_version='',
            project_root='',
            document_count=0,
            structured_document_hints=[],
            structured_symbol_hints=[],
            occurrence_count=0,
            definition_count=0,
            reference_count=0,
            structured_occurrence_hints=[],
            structured_top_reference_hints=[],
            structured_occurrence_stats={},
            structured_symbols_by_file={},
            structured_occurrence_stats_by_file={},
            structured_occurrence_lines_by_file={},
        )
    if not index_path.exists() or not index_path.is_file():
        return ScipIndexStatus(
            exists=False,
            path=scip_readiness.index_path,
            size_bytes=0,
            summary=['index file not generated yet'],
            document_hints=[],
            symbol_hints=[],
            tool_name='',
            tool_version='',
            project_root='',
            document_count=0,
            structured_document_hints=[],
            structured_symbol_hints=[],
            occurrence_count=0,
            definition_count=0,
            reference_count=0,
            structured_occurrence_hints=[],
            structured_top_reference_hints=[],
            structured_occurrence_stats={},
            structured_symbols_by_file={},
            structured_occurrence_stats_by_file={},
            structured_occurrence_lines_by_file={},
        )
    try:
        file_stat = index_path.stat()
        data = index_path.read_bytes()
        strings = extract_printable_strings(data[: min(len(data), 1_000_000)])
        document_hints: List[str] = []
        symbol_hints: List[str] = []
        structured_document_hints: List[str] = []
        structured_symbol_hints: List[str] = []
        seen_docs: Set[str] = set()
        seen_symbols: Set[str] = set()
        tool_name = ''
        tool_version = ''
        project_root = ''
        document_count = 0
        occurrence_count = 0
        definition_count = 0
        reference_count = 0
        structured_occurrence_hints: List[str] = []
        structured_top_reference_hints: List[str] = []
        seen_occurrences: Set[str] = set()
        occurrence_stats: Dict[str, Dict[str, Any]] = {}
        symbols_by_file: Dict[str, List[str]] = defaultdict(list)
        occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        occurrence_lines_by_file: Dict[str, Dict[str, List[int]]] = defaultdict(dict)

        for field_no, wire_type, value in iter_fields(data):
            if field_no == 1 and wire_type == 2 and not tool_name:
                tool_name, tool_version, project_root = parse_metadata(value)
            elif field_no == 2 and wire_type == 2:
                document_count += 1
                relative_path, language, symbols, occurrences = parse_document(value)
                if relative_path:
                    doc_label = relative_path if not language else f'{relative_path} ({language})'
                    if doc_label not in seen_docs:
                        seen_docs.add(doc_label)
                        structured_document_hints.append(doc_label)
                for symbol in symbols:
                    if relative_path and symbol:
                        symbol_label = f'{relative_path} :: {symbol}'
                        if symbol_label not in seen_symbols:
                            seen_symbols.add(symbol_label)
                            structured_symbol_hints.append(symbol_label)
                        if symbol not in symbols_by_file[relative_path]:
                            symbols_by_file[relative_path].append(symbol)
                for symbol, is_definition, start_line in occurrences:
                    occurrence_count += 1
                    if is_definition:
                        definition_count += 1
                    else:
                        reference_count += 1
                    if relative_path and symbol:
                        symbol_stat = occurrence_stats.setdefault(symbol, {'defs': 0, 'refs': 0, 'docs': set()})
                        if is_definition:
                            symbol_stat['defs'] += 1
                        else:
                            symbol_stat['refs'] += 1
                        symbol_stat['docs'].add(relative_path)

                        per_file_symbol_stat = occurrence_stats_by_file[relative_path].setdefault(symbol, {'defs': 0, 'refs': 0})
                        if is_definition:
                            per_file_symbol_stat['defs'] += 1
                        else:
                            per_file_symbol_stat['refs'] += 1

                        if start_line is not None:
                            symbol_lines = occurrence_lines_by_file[relative_path].setdefault(symbol, [])
                            if start_line not in symbol_lines:
                                symbol_lines.append(start_line)

                        occ_kind = 'def' if is_definition else 'ref'
                        occ_label = f'{relative_path} :: {symbol} [{occ_kind}]'
                        if occ_label not in seen_occurrences:
                            seen_occurrences.add(occ_label)
                            structured_occurrence_hints.append(occ_label)

        seen_docs.clear()
        seen_symbols.clear()
        for s in strings:
            for m in re.finditer(r'src/[A-Za-z0-9_./\-]+\.ts', s):
                path = m.group(0)
                if path not in seen_docs:
                    seen_docs.add(path)
                    document_hints.append(path)
            if 'scip-typescript npm' in s and 'src/' in s:
                cleaned = normalize_symbol_hint(s)
                if cleaned and cleaned not in seen_symbols:
                    seen_symbols.add(cleaned)
                    symbol_hints.append(cleaned)
        ranked_occurrence_stats = sorted(
            occurrence_stats.items(),
            key=lambda kv: (kv[1]['refs'], kv[1]['defs'], len(kv[1]['docs']), kv[0]),
            reverse=True,
        )
        filtered_occurrence_stats = [
            (symbol, symbol_stat)
            for symbol, symbol_stat in ranked_occurrence_stats
            if not is_generic_structured_symbol(symbol)
        ]
        top_occurrence_stats = filtered_occurrence_stats[:10] or ranked_occurrence_stats[:10]
        for symbol, symbol_stat in top_occurrence_stats:
            structured_top_reference_hints.append(
                f"{symbol} [refs={symbol_stat['refs']}, defs={symbol_stat['defs']}, docs={len(symbol_stat['docs'])}]"
            )

        summary = [
            f'file exists at `{scip_readiness.index_path}`',
            f'size ≈ {file_stat.st_size} bytes',
            f'structured documents: {document_count}',
            f'structured symbols: {len(structured_symbol_hints)}',
            f'structured occurrences: {occurrence_count}',
            f'structured defs/refs: {definition_count}/{reference_count}',
            f'structured unique occurrence symbols: {len(occurrence_stats)}',
            f'printable document hints: {len(document_hints)}',
            f'printable symbol hints: {len(symbol_hints)}',
        ]
        return ScipIndexStatus(
            exists=True,
            path=scip_readiness.index_path,
            size_bytes=file_stat.st_size,
            summary=summary,
            document_hints=document_hints,
            symbol_hints=symbol_hints,
            tool_name=tool_name,
            tool_version=tool_version,
            project_root=project_root,
            document_count=document_count,
            structured_document_hints=structured_document_hints,
            structured_symbol_hints=structured_symbol_hints,
            occurrence_count=occurrence_count,
            definition_count=definition_count,
            reference_count=reference_count,
            structured_occurrence_hints=structured_occurrence_hints,
            structured_top_reference_hints=structured_top_reference_hints,
            structured_occurrence_stats={
                symbol: {
                    'refs': int(symbol_stat['refs']),
                    'defs': int(symbol_stat['defs']),
                    'docs': len(symbol_stat['docs']),
                }
                for symbol, symbol_stat in occurrence_stats.items()
            },
            structured_symbols_by_file={
                file_path: symbols[:]
                for file_path, symbols in symbols_by_file.items()
            },
            structured_occurrence_stats_by_file={
                file_path: {
                    symbol: {
                        'refs': int(stats.get('refs', 0)),
                        'defs': int(stats.get('defs', 0)),
                    }
                    for symbol, stats in file_stats.items()
                }
                for file_path, file_stats in occurrence_stats_by_file.items()
            },
            structured_occurrence_lines_by_file={
                file_path: {
                    symbol: sorted(lines)
                    for symbol, lines in file_lines.items()
                }
                for file_path, file_lines in occurrence_lines_by_file.items()
            },
        )
    except Exception as err:
        return ScipIndexStatus(
            exists=False,
            path=scip_readiness.index_path,
            size_bytes=0,
            summary=[f'failed to inspect index file: {err}'],
            document_hints=[],
            symbol_hints=[],
            tool_name='',
            tool_version='',
            project_root='',
            document_count=0,
            structured_document_hints=[],
            structured_symbol_hints=[],
            occurrence_count=0,
            definition_count=0,
            reference_count=0,
            structured_occurrence_hints=[],
            structured_top_reference_hints=[],
            structured_occurrence_stats={},
            structured_symbols_by_file={},
            structured_occurrence_stats_by_file={},
            structured_occurrence_lines_by_file={},
        )


def file_path_aliases(file_path: str) -> Set[str]:
    aliases = {file_path}
    if file_path.startswith('src/'):
        aliases.add('backend/' + file_path)
    elif file_path.startswith('backend/src/'):
        aliases.add(file_path[len('backend/'):])
    return aliases


def group_scip_symbols_by_file(symbol_hints: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for item in symbol_hints:
        if ' :: ' not in item:
            continue
        file_path, symbol = item.split(' :: ', 1)
        if not symbol:
            continue
        for alias in file_path_aliases(file_path):
            grouped[alias].append(symbol)

    cleaned: Dict[str, List[str]] = {}
    for file_path, symbols in grouped.items():
        seen: Set[str] = set()
        kept: List[str] = []
        for symbol in symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            kept.append(symbol)
        cleaned[file_path] = kept
    return cleaned


def group_structured_scip_symbols_by_file(structured_symbols_by_file: Dict[str, List[str]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for file_path, symbols in structured_symbols_by_file.items():
        for alias in file_path_aliases(file_path):
            grouped[alias].extend(symbols)

    cleaned: Dict[str, List[str]] = {}
    for file_path, symbols in grouped.items():
        seen: Set[str] = set()
        kept: List[str] = []
        for symbol in symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            kept.append(symbol)
        cleaned[file_path] = kept
    return cleaned


def group_structured_occurrence_stats_by_file(structured_occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    grouped: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(dict)
    for file_path, symbol_stats in structured_occurrence_stats_by_file.items():
        for alias in file_path_aliases(file_path):
            for symbol, stats in symbol_stats.items():
                current = grouped[alias].setdefault(symbol, {'refs': 0, 'defs': 0})
                current['refs'] += int(stats.get('refs', 0))
                current['defs'] += int(stats.get('defs', 0))
    return dict(grouped)


def group_structured_occurrence_lines_by_file(structured_occurrence_lines_by_file: Dict[str, Dict[str, List[int]]]) -> Dict[str, Dict[str, List[int]]]:
    grouped: Dict[str, Dict[str, List[int]]] = defaultdict(dict)
    for file_path, symbol_lines in structured_occurrence_lines_by_file.items():
        for alias in file_path_aliases(file_path):
            for symbol, lines in symbol_lines.items():
                current = grouped[alias].setdefault(symbol, [])
                for line in lines:
                    if line not in current:
                        current.append(int(line))
    for file_path, symbol_lines in grouped.items():
        for symbol, lines in symbol_lines.items():
            symbol_lines[symbol] = sorted(lines)
    return dict(grouped)


def group_symbol_defs_by_file(symbols: List[SymbolDef]) -> Dict[str, List[SymbolDef]]:
    grouped: Dict[str, List[SymbolDef]] = defaultdict(list)
    for symbol in symbols:
        for alias in file_path_aliases(symbol.path):
            grouped[alias].append(symbol)

    cleaned: Dict[str, List[SymbolDef]] = {}
    for file_path, items in grouped.items():
        cleaned[file_path] = sorted(items, key=lambda item: (item.line, item.name, item.kind))
    return cleaned


def nearest_symbol_defs_for_ranges(
    file_path: str,
    ranges: List[ChangedLineRange],
    symbol_defs_by_file: Dict[str, List[SymbolDef]],
) -> List[str]:
    defs = symbol_defs_by_file.get(file_path, [])
    if not defs or not ranges:
        return []

    ranked: List[Tuple[int, int, str]] = []
    seen: Set[str] = set()
    for item in ranges:
        best: Optional[Tuple[int, SymbolDef]] = None
        for symbol in defs:
            if symbol.line <= item.end:
                distance = max(0, item.start - symbol.line)
            else:
                distance = (symbol.line - item.end) + 100
            if best is None or distance < best[0] or (distance == best[0] and symbol.line > best[1].line):
                best = (distance, symbol)
        if best is None:
            continue
        distance, symbol = best
        label = f'{symbol.kind}:{symbol.name}@{symbol.line}'
        if label in seen:
            continue
        seen.add(label)
        ranked.append((distance, symbol.line, label))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [label for _distance, _line, label in ranked[:8]]


def extract_symbol_name_from_label(label: str) -> str:
    core = label.strip()
    if '::' in core:
        core = core.split('::', 1)[1].strip()
    if ':' in core:
        core = core.split(':', 1)[1]
    if '@' in core:
        core = core.split('@', 1)[0]
    return core.strip()


def extract_route_keywords_from_steps(steps: List[str]) -> List[str]:
    keywords: List[str] = []
    for step in steps:
        for m in re.finditer(r'`([A-Za-z_][A-Za-z0-9_]*)\(\)`', step):
            keywords.append(m.group(1))
        for m in re.finditer(r'via `([^`]+)`', step):
            parts = [p.strip() for p in m.group(1).split(',')]
            for part in parts:
                if part:
                    keywords.append(part)
    return keywords


def match_scip_symbols_for_names(file_path: str, names: List[str], scip_symbols_by_file: Dict[str, List[str]]) -> List[str]:
    if not names:
        return []
    matched: List[str] = []
    seen: Set[str] = set()
    lower_names = [name.lower() for name in names if name]
    for symbol in scip_symbols_by_file.get(file_path, []):
        lower_symbol = symbol.lower()
        if any(name in lower_symbol for name in lower_names):
            if symbol not in seen:
                seen.add(symbol)
                matched.append(symbol)
    return matched[:8]


def rank_changed_range_scip_candidates(
    file_path: str,
    names: List[str],
    scip_symbols_by_file: Dict[str, List[str]],
    scip_occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, int]]],
    scip_occurrence_lines_by_file: Dict[str, Dict[str, List[int]]],
    changed_ranges: Optional[List[ChangedLineRange]] = None,
) -> List[ScipRangeCandidate]:
    if not names:
        return []
    lower_names = [name.lower() for name in names if name]
    ranked: List[ScipRangeCandidate] = []
    seen: Set[str] = set()
    per_file_stats = scip_occurrence_stats_by_file.get(file_path, {})
    per_file_lines = scip_occurrence_lines_by_file.get(file_path, {})
    for symbol in scip_symbols_by_file.get(file_path, []):
        lower_symbol = symbol.lower()
        score = 0
        matched_names: List[str] = []
        for name in lower_names:
            if not name:
                continue
            if f'#{name}()' in lower_symbol or lower_symbol.endswith(f'{name}()'):
                score += 12
                if name not in matched_names:
                    matched_names.append(name)
            elif f'#{name}' in lower_symbol:
                score += 8
                if name not in matched_names:
                    matched_names.append(name)
            elif name in lower_symbol:
                score += 5
                if name not in matched_names:
                    matched_names.append(name)
        stats = per_file_stats.get(symbol, {})
        score += min(int(stats.get('refs', 0)), 10)
        score += min(int(stats.get('defs', 0)) * 3, 9)
        best_distance: Optional[int] = None
        if changed_ranges:
            occurrence_lines = per_file_lines.get(symbol, [])
            if occurrence_lines:
                for occurrence_line in occurrence_lines[:32]:
                    for changed_range in changed_ranges:
                        if changed_range.start <= occurrence_line <= changed_range.end:
                            distance = 0
                        elif occurrence_line < changed_range.start:
                            distance = changed_range.start - occurrence_line
                        else:
                            distance = occurrence_line - changed_range.end
                        if best_distance is None or distance < best_distance:
                            best_distance = distance
                if best_distance is not None:
                    if best_distance == 0:
                        score += 20
                    elif best_distance <= 2:
                        score += 12
                    elif best_distance <= 5:
                        score += 7
                    elif best_distance <= 12:
                        score += 3
        if score <= 0:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        ranked.append(ScipRangeCandidate(symbol=symbol, score=score, distance=best_distance, matched_names=matched_names[:]))
    ranked.sort(key=lambda item: (-item.score, item.distance if item.distance is not None else 10**9, item.symbol))
    return ranked[:8]


def build_changed_range_semantic_context(
    changed_files: List[str],
    changed_line_ranges: Dict[str, List[ChangedLineRange]],
    changed_symbol_names: Dict[str, List[str]],
    symbol_defs_by_file: Dict[str, List[SymbolDef]],
    scip_symbols_by_file: Dict[str, List[str]],
    scip_occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, int]]],
    scip_occurrence_lines_by_file: Dict[str, Dict[str, List[int]]],
) -> Tuple[Set[str], Dict[str, List[str]], Dict[str, List[str]], Dict[str, List[ScipRangeCandidate]]]:
    changed_aliases: Set[str] = set()
    changed_name_aliases: Dict[str, List[str]] = defaultdict(list)
    changed_range_name_aliases: Dict[str, List[str]] = defaultdict(list)
    changed_range_scip_aliases: Dict[str, List[ScipRangeCandidate]] = defaultdict(list)

    for file_path in changed_files:
        aliases = file_path_aliases(file_path)
        changed_aliases.update(aliases)
        raw_ranges = changed_line_ranges.get(file_path, [])
        raw_changed_names = changed_symbol_names.get(file_path, [])
        for alias in aliases:
            for name in raw_changed_names:
                if name not in changed_name_aliases[alias]:
                    changed_name_aliases[alias].append(name)
            nearest_labels = nearest_symbol_defs_for_ranges(alias, raw_ranges, symbol_defs_by_file)
            nearest_names_for_alias: List[str] = []
            for nearest_label in nearest_labels:
                nearest_name = extract_symbol_name_from_label(nearest_label)
                if nearest_name:
                    nearest_names_for_alias.append(nearest_name)
                    if nearest_name not in changed_range_name_aliases[alias]:
                        changed_range_name_aliases[alias].append(nearest_name)
            ranked_range_scip = rank_changed_range_scip_candidates(
                alias,
                nearest_names_for_alias,
                scip_symbols_by_file,
                scip_occurrence_stats_by_file,
                scip_occurrence_lines_by_file,
                raw_ranges,
            )
            existing_symbols = {item.symbol for item in changed_range_scip_aliases[alias]}
            for candidate in ranked_range_scip:
                if candidate.symbol not in existing_symbols:
                    changed_range_scip_aliases[alias].append(candidate)
                    existing_symbols.add(candidate.symbol)

    return changed_aliases, changed_name_aliases, changed_range_name_aliases, changed_range_scip_aliases


def format_scip_range_candidate(candidate: ScipRangeCandidate, full_label: str) -> str:
    matched_names_suffix = ''
    if candidate.matched_names:
        matched_names_suffix = f" [matched: {', '.join(candidate.matched_names[:3])}]"
    distance_suffix = '' if candidate.distance is None else f" [distance: {candidate.distance}]"
    return full_label + matched_names_suffix + distance_suffix


def collect_route_boost_reasons(
    hint: RouteFlowHint,
    changed_aliases: Set[str],
    changed_name_aliases: Dict[str, List[str]],
    changed_range_name_aliases: Dict[str, List[str]],
    changed_range_scip_aliases: Dict[str, List[ScipRangeCandidate]],
    scip_symbols_by_file: Dict[str, List[str]],
) -> List[str]:
    impacted_files: List[str] = []
    for step in hint.chain:
        for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
            file_path = file_match.split(':', 1)[0]
            if file_path not in impacted_files:
                impacted_files.append(file_path)

    route_keywords = {kw.lower() for kw in extract_route_keywords_from_steps(hint.chain)}
    reasons: List[str] = []
    seen: Set[str] = set()

    for impacted_file in impacted_files:
        range_names = changed_range_name_aliases.get(impacted_file, [])
        if range_names:
            matched_range = [name for name in range_names if name.lower() in route_keywords]
            if matched_range:
                text = f"changed range near `{matched_range[0]}()` in `{impacted_file}`"
                if text not in seen:
                    seen.add(text)
                    reasons.append(text)

        range_scip_candidates = changed_range_scip_aliases.get(impacted_file, [])
        if range_scip_candidates:
            matched_candidate = next(
                (candidate for candidate in range_scip_candidates if any(keyword in candidate.symbol.lower() for keyword in route_keywords)),
                range_scip_candidates[0],
            )
            candidate_text = format_scip_range_candidate(matched_candidate, f'{impacted_file} :: {matched_candidate.symbol}')
            text = f"changed range matched SCIP candidate `{candidate_text}`"
            if text not in seen:
                seen.add(text)
                reasons.append(text)

        if range_names and not range_scip_candidates:
            matched_scip = match_scip_symbols_for_names(impacted_file, range_names, scip_symbols_by_file)
            if matched_scip:
                text = f"range-aligned SCIP symbol `{impacted_file} :: {matched_scip[0]}`"
                if text not in seen:
                    seen.add(text)
                    reasons.append(text)

        candidate_names = changed_name_aliases.get(impacted_file, [])
        if candidate_names:
            matched_scip = match_scip_symbols_for_names(impacted_file, candidate_names, scip_symbols_by_file)
            if matched_scip:
                matched_name = next((name for name in candidate_names if name.lower() in matched_scip[0].lower()), candidate_names[0])
                text = f"heuristic diff symbol `{matched_name}` matched `{impacted_file} :: {matched_scip[0]}`"
                if text not in seen:
                    seen.add(text)
                    reasons.append(text)

    return reasons[:4]


def render_fast_map(
    repo: Path,
    tree: List[str],
    manifests: List[str],
    scripts_root: Dict[str, Dict[str, str]],
    edges_ranked: List[Tuple[str, int, int, int]],
    edge_details: Dict[str, List[str]],
    symbols: List[SymbolDef],
    symbol_scores: Dict[str, int],
    top_summary: List[Tuple[str, str]],
    module_summary: List[Tuple[str, str]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    env_used: List[str],
    env_declared: List[str],
    env_used_not_declared: List[str],
    env_declared_not_used: List[str],
    routes: List[RouteDef],
    regs: List[RegisterCall],
    gateway_hints: Dict[str, List[str]],
    transfer_flow_hints: List[TransferFileHint],
    route_flow_hints: List[RouteFlowHint],
    scip_readiness: ScipReadiness,
    scip_index_status: ScipIndexStatus,
    fast_name: str,
    blast_name: str,
    profile: str = 'default',
) -> List[str]:
    lines: List[str] = []
    lines.append(f"# {fast_name.rsplit('.', 1)[0]} — {repo.name}")
    lines.append("")
    lines.append("_Generated by `graplite-scan` (local/offline; heuristic project map)._")
    lines.append("")
    lines.append("## TL;DR")
    lines.append(f"- Repo root: `{repo}`")
    lines.append(f"- Main output pair: `{fast_name}` + `{blast_name}`")
    if backend_entry:
        lines.append(f"- Backend entrypoint: `{backend_entry}`")
    if flutter_entry:
        lines.append(f"- App entrypoint: `{flutter_entry}`")
    lines.append("")

    lines.append("## System architecture summary")
    for item in architecture_summary_lines(
        repo,
        top_summary,
        module_summary,
        backend_entry,
        flutter_entry,
        route_flow_hints,
        gateway_hints,
    ):
        lines.append(item)
    lines.append("")

    visible_top_summary = filter_top_summary_items(top_summary)
    lines.append("## Top-level structure & purpose")
    for name, desc in visible_top_summary[:30]:
        lines.append(f"- `{name}` — {desc}")
    lines.append("")

    lines.append("## Module / feature groups")
    if module_summary:
        for name, desc in module_summary[:80]:
            lines.append(f"- `{name}` — {desc}")
    else:
        lines.append("- (No nested module groups detected.)")
    lines.append("")

    filtered_tree = filter_tree_lines(tree)
    tree_limit = 280 if profile == 'ai-clean' else 500
    lines.append("## Repo layout (depth≈3, filtered)")
    lines.append("```")
    lines.extend(filtered_tree[:tree_limit])
    lines.append("```")
    if len(filtered_tree) < len(tree):
        lines.append(f"- Filtered out ~{len(tree) - len(filtered_tree)} noisy/generated tree entries for readability.")
    lines.append("")

    if profile != 'ai-clean':
        lines.append("## Key manifests (depth<=4)")
        lines.append("```")
        lines.extend(manifests)
        lines.append("```")
        lines.append("")

    lines.append("## Run / Build / Test (from package scripts)")
    if scripts_root:
        for where, scripts in scripts_root.items():
            lines.append(f"### {where}")
            for k, v in sorted(scripts.items()):
                lines.append(f"- `{k}`: `{v}`")
    else:
        lines.append("- (No package.json scripts parsed.)")
    lines.append("")

    lines.append("## Confirmed entrypoints")
    if backend_entry:
        lines.append(f"- Backend: `{backend_entry}`")
    if flutter_entry:
        lines.append(f"- App/frontend: `{flutter_entry}`")
    ext_bg = repo / "ExtentionChrome/extension/background.js"
    if ext_bg.exists():
        lines.append("- Chrome extension: `ExtentionChrome/extension/background.js` (+ content/offscreen)")
    lines.append("")

    lines.append("## Environment map")
    if env_used:
        lines.append("### Env vars used in code")
        for key in env_used[:80]:
            lines.append(f"- `{key}`")
    if env_declared:
        lines.append("### Env vars declared in .env/.env.example")
        for key in env_declared[:80]:
            suffix = " (used)" if key in env_used else ""
            lines.append(f"- `{key}`{suffix}")
    if env_used_not_declared:
        lines.append("### Used in code but not declared in env files")
        for key in env_used_not_declared[:80]:
            lines.append(f"- `{key}`")
    if env_declared_not_used:
        lines.append("### Declared in env files but not referenced in scanned code")
        for key in env_declared_not_used[:80]:
            lines.append(f"- `{key}`")
    if not env_used and not env_declared:
        lines.append("- (No env usage/declarations detected.)")
    lines.append("")

    lines.append("## Route / registration map")
    if routes:
        lines.append("| method | path | file |")
        lines.append("|---|---|---|")
        for r in routes[:120]:
            lines.append(f"| `{r.method}` | `{r.path}` | `{r.file}:{r.line}` |")
    if regs:
        lines.append("")
        lines.append("### Route/gateway registration calls")
        for r in regs[:80]:
            lines.append(f"- `{r.name}` at `{r.file}:{r.line}`")
    if not routes and not regs:
        lines.append("- (No route registrations detected with current heuristics.)")
    lines.append("")

    lines.append("## Transfer / gateway hints")
    if gateway_hints:
        for file, hints in list(gateway_hints.items())[:20]:
            lines.append(f"### `{file}`")
            lines.append(f"- string/event hints: {', '.join(f'`{h}`' for h in hints[:15])}")
    else:
        lines.append("- (No gateway/event hints detected.)")
    lines.append("")

    lines.append("## Transfer flow hooks / events")
    if transfer_flow_hints:
        for hint in transfer_flow_hints[:80]:
            lines.append(f"- `{hint.value}` ({hint.kind}) at `{hint.file}:{hint.line}`")
    else:
        lines.append("- (No transfer-flow hooks/events detected.)")
    lines.append("")

    lines.append("## Route → controller → service → provider chains")
    if route_flow_hints:
        for item in route_flow_hints[:40]:
            lines.append(f"### `{item.method} {item.path}`")
            for step in item.chain:
                lines.append(f"- {step}")
    else:
        lines.append("- (No route flow chains detected.)")
    lines.append("")

    lines.append("## SCIP / Tier-B readiness")
    lines.append(f"- Enabled: `{'yes' if scip_readiness.enabled else 'no'}`")
    lines.append(f"- Repo kind: `{scip_readiness.repo_kind}`")
    lines.append(f"- Suggested indexer command: `{scip_readiness.indexer}`")
    lines.append(f"- Suggested project root: `{scip_readiness.project_root}`")
    lines.append(f"- Expected index output: `{scip_readiness.index_path}`")
    lines.append(f"- Index present now: `{'yes' if scip_index_status.exists else 'no'}`")
    if scip_index_status.summary:
        lines.append("- Index status:")
        for item in scip_index_status.summary[:6]:
            lines.append(f"  - {item}")
    if scip_index_status.tool_name:
        lines.append(f"- Structured tool: `{scip_index_status.tool_name}` `{scip_index_status.tool_version}`")
    if scip_index_status.project_root:
        lines.append(f"- Structured project root: `{scip_index_status.project_root}`")
    if scip_index_status.document_count:
        lines.append(f"- Structured document count: `{scip_index_status.document_count}`")
    if scip_readiness.reasons:
        lines.append("- Detection notes:")
        for reason in scip_readiness.reasons[:6]:
            lines.append(f"  - {reason}")
    if scip_index_status.structured_document_hints:
        lines.append("- Structured document hints:")
        for item in scip_index_status.structured_document_hints[:10]:
            lines.append(f"  - `{item}`")
    if scip_index_status.structured_symbol_hints:
        lines.append("- Structured symbol hints:")
        for item in scip_index_status.structured_symbol_hints[:8]:
            lines.append(f"  - `{item}`")
    if scip_index_status.structured_occurrence_hints:
        lines.append("- Structured occurrence hints:")
        for item in scip_index_status.structured_occurrence_hints[:8]:
            lines.append(f"  - `{item}`")
    if scip_index_status.structured_top_reference_hints:
        lines.append("- Top referenced structured symbols:")
        for item in scip_index_status.structured_top_reference_hints[:8]:
            lines.append(f"  - `{item}`")
    if scip_index_status.document_hints:
        lines.append("- SCIP document hints:")
        for item in scip_index_status.document_hints[:10]:
            lines.append(f"  - `{item}`")
    if scip_index_status.symbol_hints:
        lines.append("- SCIP symbol hints:")
        for item in scip_index_status.symbol_hints[:8]:
            lines.append(f"  - `{item}`")
    lines.append("")

    lines.append("## File dependency hotspots (import graph)")
    if edges_ranked:
        lines.append("| file | out | in | total |")
        lines.append("|---|---:|---:|---:|")
        for f, o, i, t in edges_ranked[:40]:
            lines.append(f"| `{f}` | {o} | {i} | {t} |")
        lines.append("")
        lines.append("### Dependency detail for top files")
        for f in list(edge_details.keys())[:20]:
            lines.append(f"#### `{f}`")
            for detail in edge_details[f]:
                lines.append(f"- {detail}")
    else:
        lines.append("- (No import edges detected in scanned code.)")
    lines.append("")

    symbol_limit = 60 if profile == 'ai-clean' else 120
    lines.append("## Symbol index (definitions + approx mentions)")
    if symbols:
        ranked_syms = sorted(
            symbols,
            key=lambda sd: symbol_scores.get(f"{sd.lang}:{sd.kind}:{sd.name}:{sd.path}:{sd.line}", 0),
            reverse=True,
        )
        lines.append("| kind | name | defined at | approx mentions elsewhere |")
        lines.append("|---|---|---|---:|")
        for sd in ranked_syms[:symbol_limit]:
            score = symbol_scores.get(f"{sd.lang}:{sd.kind}:{sd.name}:{sd.path}:{sd.line}", 0)
            lines.append(f"| {sd.lang}:{sd.kind} | `{sd.name}` | `{sd.path}:{sd.line}` | {score} |")
    else:
        lines.append("- (No symbols extracted. Tầng B/SCIP sẽ làm cái này chính xác hơn.)")
    lines.append("")

    lines.append("## Notes")
    lines.append("- Output này tối ưu để AI đọc nhanh: entrypoints, env, route map, transfer hooks, hotspots, symbol index.")
    lines.append("- Với repo TypeScript lớn, bước tiếp theo là bật SCIP để có callers/callees chuẩn hơn.")
    return lines


def render_blast_map(
    repo: Path,
    edges: Dict[str, Set[str]],
    edges_ranked: List[Tuple[str, int, int, int]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    gateway_hints: Dict[str, List[str]],
    route_flow_hints: List[RouteFlowHint],
    scip_readiness: ScipReadiness,
    scip_index_status: ScipIndexStatus,
    scip_symbols_by_file: Dict[str, List[str]],
    scip_occurrence_stats_by_file: Dict[str, Dict[str, Dict[str, int]]],
    scip_occurrence_lines_by_file: Dict[str, Dict[str, List[int]]],
    symbol_defs_by_file: Dict[str, List[SymbolDef]],
    blast_name: str,
    diff_range: str = '',
    changed_files: Optional[List[str]] = None,
    changed_line_ranges: Optional[Dict[str, List[ChangedLineRange]]] = None,
    changed_symbol_names: Optional[Dict[str, List[str]]] = None,
    diff_error: str = '',
) -> List[str]:
    def is_generic_route_symbol(symbol: str) -> bool:
        lower = symbol.lower().strip()
        if not lower:
            return True
        if lower in {'process', 'console', 'promise', 'string', 'number', 'boolean', 'object', 'array', 'map', 'set', 'date', 'error'}:
            return True
        if lower.startswith(('node:', 'globalthis#', 'process#', 'console#', 'map#', 'set#', 'array#', 'promise#', 'fastifyreply#', 'fastifyrequest#', 'dateconstructor#')):
            return True
        if any(token in lower for token in ('fastifyreply#', 'fastifyrequest#', 'incomingmessage#', 'serverresponse#', '__type', '<', 'typeof ')):
            return True
        if symbol.startswith('"') and symbol.endswith('"'):
            return True
        return False

    reverse_edges: Dict[str, List[str]] = defaultdict(list)
    for src, dests in edges.items():
        for dest in dests:
            reverse_edges[dest].append(src)

    def build_app_feature_flow_map() -> List[Tuple[str, List[str], List[str], List[str]]]:
        explicit_feature_files = [
            'app/lib/features/send/send_page.dart',
            'app/lib/features/receive/receive_page.dart',
            'app/lib/features/lan/lan_tab_page.dart',
            'app/lib/features/internet/internet_tab_page.dart',
            'app/lib/features/settings/settings_page.dart',
        ]

        def classify_frontend_dep(dep: str) -> str:
            lower = dep.lower()
            if any(token in lower for token in ('/services/', '/api/', '/lib/api/', '/client/', '/gateway/', '/providers/', 'cloud_adapter', 'transfer_service', '/core/transfer/')):
                return 'service'
            if any(token in lower for token in ('/stores/', '/store/', '/state/', '/hooks/', '/composables/', '/context/', '/reducers/', '/models/')):
                return 'state'
            if any(token in lower for token in ('/components/', '/widgets/', '/ui/', '/theme/', '/styles/', '/layouts/', '/shell/')):
                return 'ui'
            if any(token in lower for token in ('/utils/', '/helpers/', '/core/', '/lib/', '/platform/', 'discovery')):
                return 'core'
            return 'other'

        def candidate_frontend_files() -> List[str]:
            candidates: List[str] = []
            seen: Set[str] = set()
            for file_path in explicit_feature_files:
                if file_path in edges and file_path not in seen:
                    seen.add(file_path)
                    candidates.append(file_path)
            preferred_roots = (
                'src/app/', 'src/pages/', 'src/routes/', 'src/features/', 'src/components/',
                'src/hooks/', 'src/stores/', 'src/state/', 'src/layouts/', 'frontend/src/',
                'client/src/', 'web/src/', 'pages/', 'components/', 'routes/'
            )
            preferred_suffixes = (
                '.tsx', '.jsx', '.ts', '.js', '.vue', '.dart'
            )
            priority_files: List[Tuple[int, str]] = []
            for file_path, deps in edges.items():
                if file_path in seen:
                    continue
                lower = file_path.lower()
                if not lower.endswith(preferred_suffixes):
                    continue
                if not lower.startswith(preferred_roots):
                    continue
                if any(token in lower for token in ('spec.', 'test.', '.d.ts', '__tests__/', '/node_modules/')):
                    continue
                score = 0
                if any(token in lower for token in ('/pages/', '/routes/', '/app/', '/features/')):
                    score += 4
                if any(token in lower for token in ('page.', 'layout.', 'screen.', 'view.', 'tab_')):
                    score += 4
                if '/components/' in lower or '/widgets/' in lower:
                    score += 2
                if deps:
                    score += min(len(deps), 4)
                priority_files.append((-score, file_path))
            priority_files.sort()
            for _neg_score, file_path in priority_files[:10]:
                if file_path in seen:
                    continue
                seen.add(file_path)
                candidates.append(file_path)
            return candidates[:10]

        flow_rows: List[Tuple[str, List[str], List[str], List[str]]] = []
        for file_path in candidate_frontend_files():
            deps = sorted(edges.get(file_path, set()))
            if not deps:
                continue
            service_links: List[str] = []
            ui_links: List[str] = []
            state_links: List[str] = []
            core_links: List[str] = []
            for dep in deps:
                bucket = classify_frontend_dep(dep)
                if bucket == 'service':
                    service_links.append(dep)
                elif bucket == 'ui':
                    ui_links.append(dep)
                elif bucket == 'state':
                    state_links.append(dep)
                elif bucket == 'core':
                    core_links.append(dep)
            prioritized_side_effects = service_links[:5] + state_links[:5]
            supporting_links = ui_links[:5] + core_links[:5]
            frontend_spine = []
            for dep in deps:
                lower = dep.lower()
                if any(token in lower for token in ('platform', 'discovery', 'cloud_adapter', 'transfer_service', '/api/', '/gateway/', '/stores/', '/state/', '/hooks/', '/layouts/')):
                    frontend_spine.append(dep)
            flow_rows.append((file_path, prioritized_side_effects[:8], supporting_links[:8], frontend_spine[:8]))
        return flow_rows

    def build_frontend_shared_surface_map() -> List[Tuple[int, str, List[str], List[str], List[str]]]:
        candidates: List[Tuple[int, str, List[str], List[str], List[str]]] = []
        seen: Set[str] = set()
        for file_path in set(edges.keys()) | set(reverse_edges.keys()):
            lower = file_path.lower()
            if file_path in seen:
                continue
            if not lower.endswith(('.tsx', '.jsx', '.ts', '.js', '.vue', '.dart')):
                continue
            if any(token in lower for token in ('spec.', 'test.', '.d.ts', '__tests__/')):
                continue
            is_shared_surface = any(token in lower for token in (
                '/components/', '/widgets/', '/layouts/', '/hooks/', '/stores/', '/state/',
                '/composables/', '/context/', '/reducers/', '/core/widgets/', '/core/theme/'
            ))
            if not is_shared_surface:
                continue
            consumers = sorted(reverse_edges.get(file_path, []))
            if not consumers:
                continue
            page_consumers = [c for c in consumers if any(token in c.lower() for token in ('/pages/', '/routes/', '/app/', '/features/', 'page.', 'layout.', 'screen.', 'view.'))]
            state_consumers = [c for c in consumers if any(token in c.lower() for token in ('/hooks/', '/stores/', '/state/', '/composables/', '/context/', '/reducers/'))]
            component_consumers = [c for c in consumers if any(token in c.lower() for token in ('/components/', '/widgets/'))]
            score = len(consumers) + (len(page_consumers) * 2) + len(state_consumers)
            if '/layouts/' in lower or 'layout.' in lower:
                score += 3
            if '/stores/' in lower or '/state/' in lower or '/hooks/' in lower:
                score += 2
            candidates.append((score, file_path, page_consumers[:6], state_consumers[:6], component_consumers[:6]))
            seen.add(file_path)
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[:10]

    def business_risk_profile(file_path: str, out_degree: int, in_degree: int) -> Tuple[int, List[str]]:
        score = out_degree + in_degree
        reasons: List[str] = []
        lower = file_path.lower()

        if in_degree >= 5:
            reasons.append('high fan-in')
        if out_degree >= 5:
            reasons.append('high fan-out')

        if '/transfer/' in lower or 'transfer.' in lower:
            score += 12
            reasons.append('transfer core')
        if lower.endswith('service.ts') or lower.endswith('transfer_service.dart'):
            score += 10
            reasons.append('service layer')
        if lower.endswith('controller.ts'):
            score += 9
            reasons.append('route/controller layer')
        if lower.endswith('gateway.ts'):
            score += 10
            reasons.append('realtime gateway')
        if lower.endswith('provider.ts') or 'cloud_adapter' in lower:
            score += 8
            reasons.append('storage/provider path')
        if 'platform_io' in lower or 'lan_discovery' in lower:
            score += 7
            reasons.append('platform/discovery path')
        if '/features/' in lower and any(token in lower for token in ('send_', 'receive_', 'lan_', 'internet_', 'settings_')):
            score += 5
            reasons.append('feature entry surface')
        if '/core/widgets/' in lower or '/core/theme/' in lower:
            score -= 4
            reasons.append('ui support layer')
        if '/core/utils/' in lower:
            score -= 2
            reasons.append('utility layer')

        deduped: List[str] = []
        seen_reasons: Set[str] = set()
        for reason in reasons:
            if reason not in seen_reasons:
                seen_reasons.add(reason)
                deduped.append(reason)
        return score, deduped[:4]

    def rank_route_symbols(impacted: List[str], chain: List[str]) -> List[str]:
        keywords = extract_route_keywords_from_steps(chain)
        keyword_set = {kw.lower() for kw in keywords}
        service_keywords = {kw.lower() for kw in keywords if kw and kw[0].islower()}
        strong_route_terms = {
            'uploadurl', 'downloadurl', 'deletechunk', 'cleanupsession', 'attachreceiver',
            'createsession', 'touchsession', 'completesession', 'getsession', 'getcompletionflags'
        }
        provider_allowed_terms: Set[str] = set()
        if 'getchunkuploadurl' in service_keywords:
            provider_allowed_terms.update({'getuploadurl'})
        if 'getchunkdownloadurl' in service_keywords:
            provider_allowed_terms.update({'getdownloadurl', 'chunkexists'})
        if 'deletechunk' in service_keywords:
            provider_allowed_terms.update({'deletechunk'})
        if 'completesession' in service_keywords:
            provider_allowed_terms.update({'cleanupsession'})
        has_explicit_route_method = bool(service_keywords)
        ranked: List[Tuple[int, str, int, int, bool, bool, bool, str]] = []
        seen: Set[str] = set()
        for file_path in impacted:
            for symbol in scip_symbols_by_file.get(file_path, []):
                label = f"{file_path} :: {symbol}"
                if label in seen:
                    continue
                seen.add(label)

                score = 0
                lower_symbol = symbol.lower()
                symbol_name = symbol.split('#', 1)[-1]
                symbol_name = symbol_name.replace('()', '')
                lower_name = symbol_name.lower()
                container_name = symbol.split('#', 1)[0].lower() if '#' in symbol else ''
                is_method = '#' in symbol or '()' in symbol
                is_field = '#' in symbol and '()' not in symbol
                is_constant = bool(re.fullmatch(r'[A-Z0-9_]+', symbol_name))
                is_typeish = any(token in symbol for token in ('TransferMetadata#', 'TransferFileDescriptor#', 'TransferSession#'))
                is_service_file = file_path.endswith('service.ts')
                is_provider_file = file_path.endswith('provider.ts')
                is_controller_file = file_path.endswith('controller.ts')

                if is_method:
                    score += 18
                elif is_field:
                    score += 1

                if is_provider_file:
                    score += 8
                elif is_service_file:
                    score += 6
                elif is_controller_file:
                    score += 2

                exact_matches = 0
                partial_matches = 0
                for kw in keyword_set:
                    if kw == lower_name:
                        exact_matches += 1
                    elif kw in lower_symbol:
                        partial_matches += 1
                score += exact_matches * 40
                score += partial_matches * 10

                if is_service_file and exact_matches:
                    score += 20
                if is_provider_file and exact_matches:
                    score += 16

                if any(term in lower_symbol for term in strong_route_terms):
                    score += 10
                if lower_name in strong_route_terms:
                    score += 16

                if is_constant:
                    score -= 16
                if is_typeish and not exact_matches:
                    score -= 16
                if is_field and not exact_matches:
                    score -= 14
                if has_explicit_route_method and is_field:
                    score -= 10
                if has_explicit_route_method and is_constant:
                    score -= 8

                if is_service_file:
                    if 'createsession' in service_keywords:
                        if 'createsession' in lower_symbol:
                            score += 34
                        if any(t in lower_symbol for t in ('createsessionresult', 'transfersession', 'pairingcode')):
                            score += 12
                        if 'transferfiledescriptor' in lower_symbol:
                            score -= 12
                        if 'transfermetadata' in lower_symbol:
                            score -= 6
                    if 'attachreceiver' in service_keywords:
                        if 'attachreceiver' in lower_symbol:
                            score += 34
                        if any(t in lower_symbol for t in ('receiver', 'transfersession', 'pairingcode')):
                            score += 10
                        if 'transferfiledescriptor' in lower_symbol:
                            score -= 14
                        if 'transfermetadata' in lower_symbol:
                            score -= 8
                    if 'completesession' in service_keywords:
                        if 'completesession' in lower_symbol:
                            score += 34
                        if any(t in lower_symbol for t in ('getcompletionflags', 'sendercompleted', 'receivercompleted', 'transfersession')):
                            score += 16
                        if 'transferfiledescriptor' in lower_symbol:
                            score -= 12
                    if 'getsession' in service_keywords and ('getsession' in lower_symbol or 'transfersession' in lower_symbol):
                        score += 18
                    if 'touchsession' in service_keywords and ('touchsession' in lower_symbol or 'lastactivity' in lower_symbol):
                        score += 18
                    if 'getchunkuploadurl' in service_keywords and ('getchunkuploadurl' in lower_symbol or 'getuploadurl' in lower_symbol):
                        score += 22
                    if 'getchunkdownloadurl' in service_keywords and ('getchunkdownloadurl' in lower_symbol or 'getdownloadurl' in lower_symbol):
                        score += 22
                    if 'deletechunk' in service_keywords and 'deletechunk' in lower_symbol:
                        score += 20
                    if container_name in {'transferservice', 'createsessionresult'}:
                        score += 6

                if is_provider_file:
                    if 'getchunkuploadurl' in service_keywords and 'getuploadurl' in lower_symbol:
                        score += 26
                    if 'getchunkdownloadurl' in service_keywords and 'getdownloadurl' in lower_symbol:
                        score += 26
                    if 'getchunkdownloadurl' in service_keywords and 'chunkexists' in lower_symbol:
                        score += 20
                    if 'deletechunk' in service_keywords and 'deletechunk' in lower_symbol:
                        score += 24
                    if 'completesession' in service_keywords and 'cleanupsession' in lower_symbol:
                        score += 24
                    if provider_allowed_terms and not any(term in lower_symbol for term in provider_allowed_terms):
                        score -= 28
                    if 'attachreceiver' in service_keywords and 'attachreceiver' not in lower_symbol:
                        score -= 6

                occurrence_stat = scip_index_status.structured_occurrence_stats.get(symbol, {})
                refs = int(occurrence_stat.get('refs', 0))
                defs = int(occurrence_stat.get('defs', 0))
                docs = int(occurrence_stat.get('docs', 0))
                if refs:
                    score += min(refs, 25)
                if defs:
                    score += min(defs * 3, 12)
                if docs > 1:
                    score += min((docs - 1) * 4, 16)
                if is_generic_route_symbol(symbol):
                    score -= 24

                if score <= 0 and not is_method:
                    continue
                ranked.append((score, label, exact_matches, partial_matches, is_method, is_provider_file, is_service_file, lower_name))

        ranked.sort(key=lambda x: (-x[0], x[1]))

        pruned: List[str] = []
        service_fallbacks: List[str] = []
        provider_fallbacks: List[str] = []
        exact_service_hits = 0
        exact_provider_hits = 0
        for score, label, exact_matches, partial_matches, is_method, is_provider_file, is_service_file, lower_name in ranked:
            keep = False
            if exact_matches > 0:
                keep = True
                if is_service_file and is_method:
                    exact_service_hits += 1
                if is_provider_file and is_method:
                    exact_provider_hits += 1
            elif partial_matches > 0 and is_method:
                keep = True
            elif is_provider_file and any(term in lower_name for term in ('getuploadurl', 'getdownloadurl', 'deletechunk', 'cleanupsession', 'chunkexists')):
                if not provider_allowed_terms:
                    keep = True
                else:
                    keep = any(term in lower_name for term in provider_allowed_terms)
            elif not has_explicit_route_method:
                keep = is_method

            if keep:
                pruned.append(label)
            elif is_service_file and is_method:
                service_fallbacks.append(label)
            elif is_provider_file and is_method:
                provider_fallbacks.append(label)

        allow_service_fallbacks = exact_service_hits == 0
        allow_provider_fallbacks = exact_provider_hits == 0

        merged: List[str] = []
        seen_labels: Set[str] = set()
        merge_sources: List[List[str]] = [pruned]
        if allow_provider_fallbacks:
            merge_sources.append(provider_fallbacks)
        if allow_service_fallbacks:
            merge_sources.append(service_fallbacks)
        for source in merge_sources:
            for label in source:
                if label in seen_labels:
                    continue
                seen_labels.add(label)
                merged.append(label)
                if len(merged) >= 8:
                    return merged
        return merged
    lines: List[str] = []
    lines.append(f"# {blast_name.rsplit('.', 1)[0]} — {repo.name}")
    lines.append("")
    lines.append("_Generated by `graplite-scan` (local/offline; heuristic blast radius)._")
    lines.append("")

    lines.append("## Module-level blast radius")
    if (repo / "backend").exists():
        lines.append("- `backend/`: impacts API/runtime, storage integration, route/gateway behavior")
    if (repo / "app").exists():
        lines.append("- `app/`: impacts UI, flows, transfer behaviors client-side")
    if any((repo / path).exists() for path in ("src", "frontend", "client", "web", "pages", "components")):
        lines.append("- frontend surface (`src/`, `pages/`, `components/`, `frontend/`, `client/`, `web/`): impacts routes/pages, shared UI, client state, browser-side API flows")
    if (repo / "ExtentionChrome/extension").exists():
        lines.append("- `ExtentionChrome/extension/`: impacts extension/browser integration")
    lines.append("")

    lines.append("## Highest-risk files (weighted by dependency centrality + business criticality)")
    if edges_ranked:
        weighted_files: List[Tuple[int, str, int, int, int, List[str]]] = []
        for f, o, i, t in edges_ranked:
            weighted_score, reasons = business_risk_profile(f, o, i)
            weighted_files.append((weighted_score, f, o, i, t, reasons))
        weighted_files.sort(key=lambda item: (-item[0], -item[4], item[1]))

        lines.append("| file | weighted risk | total degree | why |")
        lines.append("|---|---:|---:|---|")
        for weighted_score, f, _o, _i, t, reasons in weighted_files[:35]:
            why = reasons[:] if reasons else ['connected']
            lines.append(f"| `{f}` | {weighted_score} | {t} | {', '.join(why)} |")
    else:
        lines.append("- (No import graph available.)")
    lines.append("")

    route_to_steps: Dict[str, List[str]] = {}
    file_to_routes: Dict[str, List[str]] = defaultdict(list)
    file_to_steps: Dict[str, List[str]] = defaultdict(list)
    for hint in route_flow_hints:
        route_label = f"{hint.method} {hint.path}"
        route_to_steps[route_label] = hint.chain[:]
        seen_files: Set[str] = set()
        for step in hint.chain:
            for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
                file_path = file_match.split(':', 1)[0]
                if file_path not in seen_files:
                    file_to_routes[file_path].append(route_label)
                    seen_files.add(file_path)
                file_to_steps[file_path].append(step)

    lines.append("## Frontend / app-side feature impact")
    app_feature_flow_map = build_app_feature_flow_map()
    if app_feature_flow_map:
        for file_path, core_links, util_links, platform_links in app_feature_flow_map:
            lines.append(f"### If changing `{file_path}`")
            if core_links:
                lines.append(f"- Service/state links: {', '.join(f'`{item}`' for item in core_links[:8])}")
            if platform_links:
                lines.append(f"- Route/state/runtime-adjacent links: {', '.join(f'`{item}`' for item in platform_links[:8])}")
            if util_links:
                lines.append(f"- UI/core dependencies: {', '.join(f'`{item}`' for item in util_links[:8])}")
            lower = file_path.lower()
            if any(token in lower for token in ('/pages/', '/routes/', '/app/', 'page.', 'layout.')):
                lines.append("- Likely user-visible surface: route/page/app-shell behavior may shift")
            elif any(token in lower for token in ('/components/', '/widgets/')):
                lines.append("- Likely shared UI surface: reused component behavior/props may shift")
            elif any(token in lower for token in ('/hooks/', '/stores/', '/state/', '/composables/')):
                lines.append("- Likely client-state surface: derived state, effects, or data wiring may shift")
            app_symbols = scip_symbols_by_file.get(file_path, [])
            if app_symbols:
                lines.append(f"- Structured symbols in file: {', '.join(f'`{item}`' for item in app_symbols[:6])}")
    else:
        lines.append("- (No frontend/app-side feature flow map detected yet.)")
    lines.append("")

    lines.append("## Shared frontend component / state blast radius")
    shared_frontend_surface = build_frontend_shared_surface_map()
    if shared_frontend_surface:
        for score, file_path, page_consumers, state_consumers, component_consumers in shared_frontend_surface[:8]:
            lines.append(f"### If changing `{file_path}`")
            lines.append(f"- Shared-surface score: `{score}`")
            if page_consumers:
                lines.append(f"- User-visible consumers: {', '.join(f'`{item}`' for item in page_consumers[:6])}")
            if state_consumers:
                lines.append(f"- State/runtime consumers: {', '.join(f'`{item}`' for item in state_consumers[:6])}")
            if component_consumers:
                lines.append(f"- Component/UI consumers: {', '.join(f'`{item}`' for item in component_consumers[:6])}")
            lower = file_path.lower()
            if any(token in lower for token in ('/layouts/', 'layout.')):
                lines.append("- Likely app-shell impact: layout composition or route framing may shift")
            elif any(token in lower for token in ('/hooks/', '/stores/', '/state/', '/composables/', '/context/')):
                lines.append("- Likely cross-feature state impact: shared effects, selectors, or client data flow may shift")
            else:
                lines.append("- Likely shared UI impact: multiple routes/features may inherit rendering or prop behavior changes")
    else:
        lines.append("- (No shared frontend component/state surfaces detected yet.)")
    lines.append("")

    lines.append("## Flow-aware impact map")
    if route_flow_hints:
        important_files = [
            'backend/src/modules/transfer/transfer.controller.ts',
            'backend/src/modules/transfer/transfer.service.ts',
            'backend/src/modules/transfer/chunk-url-provider.ts',
            'backend/src/modules/transfer/r2-url-provider.ts',
            'backend/src/modules/transfer/transfer.gateway.ts',
            'backend/src/modules/transfer/peer.gateway.ts',
        ]
        rendered_any = False
        for file_path in important_files:
            routes = file_to_routes.get(file_path, [])
            steps = file_to_steps.get(file_path, [])
            if not routes and file_path not in gateway_hints:
                continue
            rendered_any = True
            lines.append(f"### If changing `{file_path}`")
            if routes:
                lines.append(f"- Likely affects routes: {', '.join(f'`{r}`' for r in routes[:10])}")
            uniq_steps = []
            seen_steps = set()
            for step in steps:
                if step not in seen_steps:
                    seen_steps.add(step)
                    uniq_steps.append(step)
            if uniq_steps:
                lines.append("- Touchpoints in known flow:")
                for step in uniq_steps[:6]:
                    lines.append(f"  - {step}")
            if file_path in gateway_hints:
                lines.append(f"- Event/message schema hints: {', '.join(f'`{h}`' for h in gateway_hints[file_path][:12])}")
            scip_symbols = scip_symbols_by_file.get(file_path, [])
            if scip_symbols:
                lines.append(f"- SCIP symbols in file: {', '.join(f'`{s}`' for s in scip_symbols[:8])}")
        if not rendered_any:
            lines.append("- (No flow-aware impact map detected yet.)")
    else:
        lines.append("- (No route flow hints available yet.)")
    lines.append("")

    lines.append("## Route-centric impact")
    prioritized_route_flow_hints = route_flow_hints[:]
    route_boost_reasons: Dict[str, List[str]] = {}
    if changed_files:
        changed_aliases, changed_name_aliases, changed_range_name_aliases, changed_range_scip_aliases = build_changed_range_semantic_context(
            changed_files,
            changed_line_ranges or {},
            changed_symbol_names or {},
            symbol_defs_by_file,
            scip_symbols_by_file,
            scip_occurrence_stats_by_file,
            scip_occurrence_lines_by_file,
        )

        def route_priority_key(hint: RouteFlowHint) -> Tuple[int, int, int, str, str]:
            route_label = f"{hint.method} {hint.path}"
            touched = 0
            symbol_hits = 0
            range_symbol_hits = 0
            impacted_files: List[str] = []
            route_keywords = {kw.lower() for kw in extract_route_keywords_from_steps(hint.chain)}
            for step in hint.chain:
                for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
                    file_path = file_match.split(':', 1)[0]
                    if file_path not in impacted_files:
                        impacted_files.append(file_path)
                    if file_path in changed_aliases:
                        touched += 1
            for impacted_file in impacted_files:
                candidate_names = changed_name_aliases.get(impacted_file, [])
                if candidate_names:
                    for symbol in scip_symbols_by_file.get(impacted_file, []):
                        lower_symbol = symbol.lower()
                        if any(name.lower() in lower_symbol for name in candidate_names):
                            symbol_hits += 1
                range_names = changed_range_name_aliases.get(impacted_file, [])
                if range_names:
                    for name in range_names:
                        lower_name = name.lower()
                        if lower_name in route_keywords:
                            range_symbol_hits += 3
                range_scip_candidates = changed_range_scip_aliases.get(impacted_file, [])
                for candidate in range_scip_candidates:
                    if any(keyword in candidate.symbol.lower() for keyword in route_keywords):
                        range_symbol_hits += 2
            return (-range_symbol_hits, -symbol_hits, -touched, hint.method, route_label)

        prioritized_route_flow_hints = sorted(route_flow_hints, key=route_priority_key)
        for hint in prioritized_route_flow_hints:
            route_label = f"{hint.method} {hint.path}"
            route_boost_reasons[route_label] = collect_route_boost_reasons(
                hint,
                changed_aliases,
                changed_name_aliases,
                changed_range_name_aliases,
                changed_range_scip_aliases,
                scip_symbols_by_file,
            )

    if route_flow_hints:
        for hint in prioritized_route_flow_hints[:12]:
            route_label = f"{hint.method} {hint.path}"
            lines.append(f"### `{route_label}`")
            boost_reasons = route_boost_reasons.get(route_label, [])
            if boost_reasons:
                lines.append(f"- Boost reasons: {'; '.join(boost_reasons[:4])}")
            impacted = []
            for step in hint.chain:
                for file_match in re.findall(r'`([^`]+\.(?:ts|js|dart)(?::\d+)?)`', step):
                    file_path = file_match.split(':', 1)[0]
                    if file_path not in impacted:
                        impacted.append(file_path)
            if impacted:
                lines.append(f"- Impacted files in this path: {', '.join(f'`{p}`' for p in impacted[:8])}")
                route_symbols = rank_route_symbols(impacted, hint.chain)
                if route_symbols:
                    lines.append(f"- Relevant SCIP symbols: {', '.join(f'`{s}`' for s in route_symbols[:8])}")
            for step in hint.chain[1:6]:
                lines.append(f"- {step}")
    else:
        lines.append("- (No route-centric impact available.)")
    lines.append("")

    lines.append("## Diff-aware impact")
    if diff_range:
        lines.append(f"- Diff range: `{diff_range}`")
        if diff_error:
            lines.append(f"- Diff error: `{diff_error}`")
        elif changed_files:
            lines.append(f"- Changed files: {', '.join(f'`{x}`' for x in changed_files[:20])}")
            if changed_line_ranges:
                rendered_ranges: List[str] = []
                for file_path in changed_files[:20]:
                    ranges = (changed_line_ranges or {}).get(file_path, [])
                    if not ranges:
                        continue
                    range_text = ', '.join(
                        f'{item.start}' if item.start == item.end else f'{item.start}-{item.end}'
                        for item in ranges[:6]
                    )
                    rendered_ranges.append(f'`{file_path}` → lines `{range_text}`')
                if rendered_ranges:
                    lines.append(f"- Changed line ranges: {'; '.join(rendered_ranges[:12])}")
            matched_routes: List[str] = []
            matched_route_scores: Dict[str, int] = defaultdict(int)
            changed_symbol_labels: List[str] = []
            range_symbol_labels: List[str] = []
            range_scip_candidate_labels: List[str] = []
            heuristic_changed_names: List[str] = []
            seen_symbol_labels: Set[str] = set()
            seen_range_symbol_labels: Set[str] = set()
            seen_range_scip_candidate_labels: Set[str] = set()
            seen_changed_names: Set[str] = set()
            normalized_changed_files: List[str] = []
            seen_changed_aliases: Set[str] = set()
            changed_aliases, changed_name_aliases, changed_range_name_aliases, changed_range_scip_aliases = build_changed_range_semantic_context(
                changed_files,
                changed_line_ranges or {},
                changed_symbol_names or {},
                symbol_defs_by_file,
                scip_symbols_by_file,
                scip_occurrence_stats_by_file,
                scip_occurrence_lines_by_file,
            )
            for file_path in changed_files:
                aliases = sorted(file_path_aliases(file_path))
                raw_changed_names = (changed_symbol_names or {}).get(file_path, [])
                for name in raw_changed_names:
                    if name not in seen_changed_names:
                        seen_changed_names.add(name)
                        heuristic_changed_names.append(name)
                for alias in aliases:
                    if alias not in seen_changed_aliases:
                        seen_changed_aliases.add(alias)
                        normalized_changed_files.append(alias)
                    nearest_labels = nearest_symbol_defs_for_ranges(alias, (changed_line_ranges or {}).get(file_path, []), symbol_defs_by_file)
                    nearest_names = [extract_symbol_name_from_label(label).lower() for label in nearest_labels]
                    matched_range_scip_candidates = changed_range_scip_aliases.get(alias, [])
                    for route in file_to_routes.get(alias, []):
                        matched_route_scores[route] += 1
                        route_keywords = {kw.lower() for kw in extract_route_keywords_from_steps(route_to_steps.get(route, []))}
                        for nearest_name in nearest_names:
                            if nearest_name and nearest_name in route_keywords:
                                matched_route_scores[route] += 3
                        for candidate in matched_range_scip_candidates:
                            if any(keyword in candidate.symbol.lower() for keyword in route_keywords):
                                matched_route_scores[route] += 2
                    for nearest_label in nearest_labels:
                        full_label = f'{alias} :: {nearest_label}'
                        if full_label not in seen_range_symbol_labels:
                            seen_range_symbol_labels.add(full_label)
                            range_symbol_labels.append(full_label)
                    for candidate in matched_range_scip_candidates:
                        full_label = f'{alias} :: {candidate.symbol}'
                        if full_label not in seen_range_symbol_labels:
                            seen_range_symbol_labels.add(full_label)
                            range_symbol_labels.append(full_label)
                        if full_label not in seen_range_scip_candidate_labels:
                            seen_range_scip_candidate_labels.add(full_label)
                            range_scip_candidate_labels.append(format_scip_range_candidate(candidate, full_label))
                    candidate_symbols = scip_symbols_by_file.get(alias, [])
                    prioritized_symbols = []
                    fallback_symbols = []
                    for symbol in candidate_symbols:
                        if raw_changed_names and any(name.lower() in symbol.lower() for name in raw_changed_names):
                            prioritized_symbols.append(symbol)
                        else:
                            fallback_symbols.append(symbol)
                    for symbol in prioritized_symbols + fallback_symbols:
                        label = f'{alias} :: {symbol}'
                        if label not in seen_symbol_labels:
                            seen_symbol_labels.add(label)
                            changed_symbol_labels.append(label)
            if range_symbol_labels:
                lines.append(f"- Changed-range nearest symbols: {', '.join(f'`{x}`' for x in range_symbol_labels[:10])}")
            if range_scip_candidate_labels:
                lines.append(f"- Changed-range SCIP candidates: {', '.join(f'`{x}`' for x in range_scip_candidate_labels[:10])}")
            if heuristic_changed_names:
                lines.append(f"- Heuristic changed symbols from diff: {', '.join(f'`{x}`' for x in heuristic_changed_names[:16])}")
            if normalized_changed_files and normalized_changed_files != changed_files:
                lines.append(f"- Normalized file aliases: {', '.join(f'`{x}`' for x in normalized_changed_files[:20])}")
            for route, _score in sorted(matched_route_scores.items(), key=lambda kv: (-kv[1], kv[0])):
                matched_routes.append(route)
            if matched_routes:
                lines.append(f"- Likely impacted routes: {', '.join(f'`{x}`' for x in matched_routes[:12])}")
            if changed_symbol_labels:
                lines.append(f"- Changed-file SCIP symbols: {', '.join(f'`{x}`' for x in changed_symbol_labels[:10])}")
            if not matched_routes and not changed_symbol_labels:
                lines.append("- No flow-aware route/symbol matches for changed files yet.")
        else:
            lines.append("- No changed files detected for this range.")
    else:
        lines.append("- (Run with `--diff-range <range>` to map changed files to impacted routes/symbols.)")
    lines.append("")

    lines.append("## Change recipes")
    if backend_entry:
        lines.append(f"- If changing `{backend_entry}`: verify server boots, health endpoints, route registration, WS on/off")
    if flutter_entry:
        lines.append(f"- If changing `{flutter_entry}`: verify app boot, service init, navigation, transfer flow startup")
    if gateway_hints:
        lines.append("- If changing gateway/transfer modules: run end-to-end transfer smoke test and watch message/event schema drift")
    if route_flow_hints:
        lines.append("- If changing transfer controller/service/provider files: verify session create/join, upload-url, download-url, complete, cancel, receiver-ready flows")
    lines.append("")

    lines.append("## Tier-B / SCIP status")
    lines.append(f"- Ready now: `{'yes' if scip_readiness.enabled else 'no'}`")
    lines.append(f"- Suggested indexer: `{scip_readiness.indexer}`")
    lines.append(f"- Suggested project root: `{scip_readiness.project_root}`")
    lines.append(f"- Expected index path: `{scip_readiness.index_path}`")
    lines.append(f"- Index present now: `{'yes' if scip_index_status.exists else 'no'}`")
    if scip_index_status.summary:
        for item in scip_index_status.summary[:6]:
            lines.append(f"- {item}")
    if scip_index_status.tool_name:
        lines.append(f"- Structured tool: `{scip_index_status.tool_name}` `{scip_index_status.tool_version}`")
    if scip_index_status.structured_document_hints:
        lines.append(f"- Structured docs: {', '.join(f'`{x}`' for x in scip_index_status.structured_document_hints[:5])}")
    if scip_index_status.structured_symbol_hints:
        lines.append(f"- Structured symbols: {', '.join(f'`{x}`' for x in scip_index_status.structured_symbol_hints[:4])}")
    if scip_index_status.structured_occurrence_hints:
        lines.append(f"- Structured occurrences: {', '.join(f'`{x}`' for x in scip_index_status.structured_occurrence_hints[:4])}")
    if scip_index_status.structured_top_reference_hints:
        lines.append(f"- Top referenced structured symbols: {', '.join(f'`{x}`' for x in scip_index_status.structured_top_reference_hints[:4])}")
    elif scip_index_status.document_hints:
        lines.append(f"- Example indexed docs: {', '.join(f'`{x}`' for x in scip_index_status.document_hints[:5])}")
    if scip_index_status.symbol_hints:
        lines.append(f"- Example indexed symbols: {', '.join(f'`{x}`' for x in scip_index_status.symbol_hints[:4])}")
    lines.append("")

    lines.append("## Next step")
    lines.append("1) Generate SCIP index for TS/JS subproject and parse refs/defs")
    lines.append("2) Add callers/callees + symbol-level impact from SCIP")
    lines.append("3) Add `--diff <range>` to map changed files/symbols → impacted graph")
    return lines


def git_changed_files(repo: Path, diff_range: str) -> Tuple[List[str], str]:
    if not diff_range:
        return [], ''
    try:
        proc = subprocess.run(
            ['git', 'diff', '--name-only', diff_range],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as err:
        return [], str(err)
    if proc.returncode != 0:
        return [], (proc.stderr or proc.stdout or f'git diff exited {proc.returncode}').strip()
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return files, ''


def parse_git_diff_ranges(repo: Path, diff_range: str) -> Tuple[Dict[str, List[ChangedLineRange]], str]:
    if not diff_range:
        return {}, ''
    try:
        proc = subprocess.run(
            ['git', 'diff', '--unified=0', '--no-color', diff_range],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as err:
        return {}, str(err)
    if proc.returncode != 0:
        return {}, (proc.stderr or proc.stdout or f'git diff exited {proc.returncode}').strip()

    current_file = ''
    grouped: Dict[str, List[ChangedLineRange]] = defaultdict(list)
    hunk_re = re.compile(r'^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@')

    for raw_line in proc.stdout.splitlines():
        if raw_line.startswith('+++ b/'):
            current_file = raw_line[6:].strip()
            continue
        if not current_file or not raw_line.startswith('@@'):
            continue
        match = hunk_re.match(raw_line)
        if not match:
            continue
        new_start = int(match.group('new_start'))
        new_len = int(match.group('new_len') or '1')
        if match.group('new_len') == '0':
            start = max(1, new_start)
            end = start
        else:
            start = max(1, new_start)
            end = max(start, new_start + max(new_len, 1) - 1)
        grouped[current_file].append(ChangedLineRange(start=start, end=end))

    cleaned: Dict[str, List[ChangedLineRange]] = {}
    for file_path, ranges in grouped.items():
        merged: List[ChangedLineRange] = []
        for item in sorted(ranges, key=lambda r: (r.start, r.end)):
            if not merged or item.start > merged[-1].end + 1:
                merged.append(ChangedLineRange(start=item.start, end=item.end))
            else:
                merged[-1].end = max(merged[-1].end, item.end)
        cleaned[file_path] = merged
    return cleaned, ''


def extract_diff_symbol_candidates(line: str) -> List[str]:
    lowered = line.strip().lower()
    if not lowered:
        return []
    if lowered in {'{', '}', '(', ')', '[', ']'}:
        return []
    blocked = {'if', 'for', 'while', 'switch', 'catch', 'return', 'throw', 'else', 'case'}
    found: List[str] = []
    seen: Set[str] = set()
    for rx in DIFF_SYMBOL_RES:
        for match in rx.finditer(line):
            name = match.group(1).strip()
            if not name or name.lower() in blocked:
                continue
            if len(name) <= 1:
                continue
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


def git_changed_symbol_names(repo: Path, diff_range: str) -> Tuple[Dict[str, List[str]], str]:
    if not diff_range:
        return {}, ''
    try:
        proc = subprocess.run(
            ['git', 'diff', '--unified=0', '--no-color', diff_range],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as err:
        return {}, str(err)
    if proc.returncode != 0:
        return {}, (proc.stderr or proc.stdout or f'git diff exited {proc.returncode}').strip()

    current_file = ''
    grouped: Dict[str, List[str]] = defaultdict(list)
    for raw_line in proc.stdout.splitlines():
        if raw_line.startswith('+++ b/'):
            current_file = raw_line[6:].strip()
            continue
        if raw_line.startswith('@@'):
            context = raw_line.split('@@', 2)[-1].strip()
            if current_file and context:
                grouped[current_file].extend(extract_diff_symbol_candidates(context))
            continue
        if not current_file:
            continue
        if raw_line.startswith('+++') or raw_line.startswith('---'):
            continue
        if raw_line.startswith('+') or raw_line.startswith('-'):
            grouped[current_file].extend(extract_diff_symbol_candidates(raw_line[1:]))

    cleaned: Dict[str, List[str]] = {}
    for file_path, names in grouped.items():
        seen: Set[str] = set()
        kept: List[str] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            kept.append(name)
        cleaned[file_path] = kept[:20]
    return cleaned, ''


def scan_repo(repo: Path, out_dir: Path, fast_name: str, blast_name: str, diff_range: str = '', profile: str = 'default') -> Tuple[Path, Path]:
    repo_config = load_repo_config(repo)
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_dirs.update(config_str_list(repo_config, 'ignoreDirs'))
    ignore_paths = config_str_list(repo_config, 'ignorePaths')
    scan_subdirs = [sub for sub in detect_scan_subdirs(repo) if not should_ignore_rel(sub, ignore_paths)]
    tree = list_tree(repo, max_depth=3, ignore_dirs=ignore_dirs, ignore_paths=ignore_paths)
    manifests = find_manifests(repo, max_depth=4, ignore_dirs=ignore_dirs, ignore_paths=ignore_paths)

    backend_entry = detect_backend_entry(repo)
    flutter_entry = detect_frontend_entry(repo)

    scripts_map: Dict[str, Dict[str, str]] = {}
    for rel in ("package.json", "backend/package.json", "app/package.json"):
        p = repo / rel
        if p.exists():
            scripts = parse_package_scripts(p)
            if scripts:
                scripts_map[rel] = scripts

    edges, file_lang = build_import_graph(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    ranked_files = compute_degree_centrality(edges)
    files_for_symbols = list(file_lang.keys())
    symbols = extract_symbols(repo, files_for_symbols, file_lang, ignore_dirs, ignore_paths=ignore_paths)
    symbol_scores = approx_symbol_scores(symbols, file_lang, repo) if symbols else {}
    env_used, env_declared, env_used_not_declared, env_declared_not_used = extract_env_map(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    routes, regs = extract_routes(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    gateway_hints = extract_gateway_hints(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    transfer_flow_hints = extract_transfer_flow_hints(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    route_flow_hints = extract_route_flow_hints(repo)
    scip_readiness = detect_scip_readiness(repo)
    scip_index_status = detect_scip_index_status(repo, scip_readiness)
    primary_scip_symbols = scip_index_status.structured_symbol_hints or scip_index_status.symbol_hints
    scip_symbols_by_file = group_structured_scip_symbols_by_file(scip_index_status.structured_symbols_by_file) if scip_index_status.structured_symbols_by_file else group_scip_symbols_by_file(primary_scip_symbols)
    scip_occurrence_stats_by_file = group_structured_occurrence_stats_by_file(scip_index_status.structured_occurrence_stats_by_file)
    scip_occurrence_lines_by_file = group_structured_occurrence_lines_by_file(scip_index_status.structured_occurrence_lines_by_file)
    symbol_defs_by_file = group_symbol_defs_by_file(symbols)
    top_summary = top_level_summary(repo, ignore_dirs, ignore_paths=ignore_paths)
    module_summary = nested_module_summary(repo, scan_subdirs, ignore_dirs, ignore_paths=ignore_paths)
    edge_details = file_dependency_details(edges, ranked_files)
    changed_files, diff_error = git_changed_files(repo, diff_range)
    changed_line_ranges, diff_ranges_error = parse_git_diff_ranges(repo, diff_range)
    changed_symbol_names, diff_symbol_error = git_changed_symbol_names(repo, diff_range)
    if diff_ranges_error and not diff_error:
        diff_error = diff_ranges_error
    if diff_symbol_error and not diff_error:
        diff_error = diff_symbol_error

    fast_lines = render_fast_map(
        repo=repo,
        tree=tree,
        manifests=manifests,
        scripts_root=scripts_map,
        edges_ranked=ranked_files,
        edge_details=edge_details,
        symbols=symbols,
        symbol_scores=symbol_scores,
        top_summary=top_summary,
        module_summary=module_summary,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        env_used=env_used,
        env_declared=env_declared,
        env_used_not_declared=env_used_not_declared,
        env_declared_not_used=env_declared_not_used,
        routes=routes,
        regs=regs,
        gateway_hints=gateway_hints,
        transfer_flow_hints=transfer_flow_hints,
        route_flow_hints=route_flow_hints,
        scip_readiness=scip_readiness,
        scip_index_status=scip_index_status,
        fast_name=fast_name,
        blast_name=blast_name,
        profile=profile,
    )
    blast_lines = render_blast_map(
        repo=repo,
        edges=edges,
        edges_ranked=ranked_files,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        gateway_hints=gateway_hints,
        route_flow_hints=route_flow_hints,
        scip_readiness=scip_readiness,
        scip_index_status=scip_index_status,
        scip_symbols_by_file=scip_symbols_by_file,
        scip_occurrence_stats_by_file=scip_occurrence_stats_by_file,
        scip_occurrence_lines_by_file=scip_occurrence_lines_by_file,
        symbol_defs_by_file=symbol_defs_by_file,
        blast_name=blast_name,
        diff_range=diff_range,
        changed_files=changed_files,
        changed_line_ranges=changed_line_ranges,
        changed_symbol_names=changed_symbol_names,
        diff_error=diff_error,
    )

    architecture_lines = render_architecture_mermaid(
        repo=repo,
        top_summary=top_summary,
        module_summary=module_summary,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        route_flow_hints=route_flow_hints,
        gateway_hints=gateway_hints,
    )

    fast_path = out_dir / fast_name
    blast_path = out_dir / blast_name
    architecture_path = out_dir / 'ARCHITECTURE.mmd'
    fast_path.write_text("\n".join(fast_lines), encoding="utf-8")
    blast_path.write_text("\n".join(blast_lines), encoding="utf-8")
    architecture_path.write_text("\n".join(architecture_lines) + "\n", encoding="utf-8")
    return fast_path, blast_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Path to repo (default: current directory)")
    ap.add_argument("--out", default="", help="Output directory (default: repo root)")
    ap.add_argument("--inplace", action="store_true", help="Write into repo root (default behavior if --out omitted)")
    ap.add_argument("--mode", choices=["project", "agent-claude", "short"], default="project")
    ap.add_argument("--fast-file", default="", help="Override first output filename")
    ap.add_argument("--blast-file", default="", help="Override second output filename")
    ap.add_argument("--diff-range", default="", help="Optional git diff range, e.g. HEAD~1..HEAD")
    ap.add_argument("--profile", choices=["default", "ai-clean"], default="", help="Output profile preset")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    repo_config = load_repo_config(repo)

    if args.out:
        out_dir = Path(args.out).expanduser().resolve()
    else:
        configured_out = config_str(repo_config, 'outDir', '')
        out_dir = (repo / configured_out).resolve() if configured_out else repo

    mode = args.mode or config_str(repo_config, 'mode', 'project')
    profile = args.profile or config_str(repo_config, 'profile', 'default')
    diff_range = args.diff_range or config_str(repo_config, 'diffRange', '')

    if mode == "agent-claude":
        fast_name = args.fast_file or "AGENT_MAP.md"
        blast_name = args.blast_file or "CLAUDE_MAP.md"
    elif mode == "short":
        fast_name = args.fast_file or "MAP.md"
        blast_name = args.blast_file or "IMPACT.md"
    else:
        fast_name = args.fast_file or "PROJECT_FAST_MAP.md"
        blast_name = args.blast_file or "PROJECT_BLAST_RADIUS.md"

    if not args.fast_file:
        fast_name = config_str(repo_config, 'fastFile', fast_name)
    if not args.blast_file:
        blast_name = config_str(repo_config, 'blastFile', blast_name)

    out_dir.mkdir(parents=True, exist_ok=True)
    fast, blast = scan_repo(repo, out_dir, fast_name=fast_name, blast_name=blast_name, diff_range=diff_range, profile=profile)
    print("OK")
    print("FAST:", fast)
    print("BLAST:", blast)


if __name__ == "__main__":
    main()
