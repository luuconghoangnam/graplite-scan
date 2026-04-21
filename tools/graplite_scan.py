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
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

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
}

TS_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:type\s+)?[^;]*?from\s+['\"](?P<spec>[^'\"]+)['\"];?\s*$",
    re.M,
)
DART_IMPORT_RE = re.compile(
    r"^\s*(?:import|export)\s+['\"](?P<spec>[^'\"]+)['\"];?\s*$",
    re.M,
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

ENV_USAGE_RE = re.compile(r"process\.env\.([A-Z0-9_]+)")
ENV_KEY_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=.*$", re.M)
FASTIFY_ROUTE_RE = re.compile(
    r"(?P<target>\bapp|\bserver|\brouter|\bfastify)\.(?P<method>get|post|put|delete|patch|options|head)\s*(?:<[^>]*>)?\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
    re.I | re.S,
)
REGISTER_ROUTE_RE = re.compile(r"\b(register[A-Za-z0-9_]*(?:Routes|Gateway))\s*\(")
WS_EVENT_RE = re.compile(r"['\"]([A-Za-z0-9:_\-]+)['\"]")
TRANSFER_HINT_RE = re.compile(r"transfer|gateway|websocket|socket|peer", re.I)
DIR_RESP_HINTS = {
    'backend': 'server/backend logic',
    'server': 'server/backend logic',
    'src': 'primary source tree',
    'app': 'application / UI layer',
    'frontend': 'application / UI layer',
    'web': 'web app / frontend assets',
    'client': 'client-side code',
    'lib': 'shared/library source',
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


def is_ignored(path: Path, ignore_dirs: Set[str]) -> bool:
    return any(part in ignore_dirs for part in path.parts)


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


def list_tree(root: Path, max_depth: int = 3, ignore_dirs: Set[str] = DEFAULT_IGNORE_DIRS) -> List[str]:
    lines: List[str] = []

    def rec(cur: Path, depth: int, prefix: str = ""):
        if depth < 0:
            return
        try:
            items = sorted(cur.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return
        for it in items:
            if it.name in ignore_dirs:
                continue
            if it.is_dir():
                lines.append(f"{prefix}{it.name}/")
                rec(it, depth - 1, prefix + "  ")
            else:
                lines.append(f"{prefix}{it.name}")

    rec(root, max_depth)
    return lines


def find_manifests(root: Path, max_depth: int = 4, ignore_dirs: Set[str] = DEFAULT_IGNORE_DIRS) -> List[str]:
    out: List[str] = []
    for p in root.rglob("*"):
        if is_ignored(p, ignore_dirs):
            continue
        try:
            rel = p.relative_to(root)
        except Exception:
            continue
        if len(rel.parts) > max_depth:
            continue
        if p.is_file() and p.name in MANIFEST_NAMES:
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
        "packages",
        "apps",
        "services",
        "ExtentionChrome/extension",
    ]
    return [c for c in candidates if (repo / c).exists()]


def resolve_ts_import(spec: str, from_file: Path) -> Optional[Path]:
    if not spec.startswith("."):
        return None
    base = (from_file.parent / spec).resolve()
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        p = Path(str(base) + ext)
        if p.exists():
            return p
    if base.is_dir():
        for ext in (".ts", ".tsx", ".js", ".jsx"):
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


def build_import_graph(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    edges: Dict[str, Set[str]] = {}
    file_lang: Dict[str, str] = {}

    for sub in subdirs:
        base = repo / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs) or not p.is_file():
                continue
            if p.suffix not in {".ts", ".js", ".dart"}:
                continue

            rel = relpath_posix(p, repo)
            txt = safe_read_text(p)
            if p.suffix in {".ts", ".js"}:
                file_lang[rel] = "ts"
                specs = [m.group("spec") for m in TS_IMPORT_RE.finditer(txt)]
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
    return edges, file_lang


def extract_symbols(repo: Path, files: Iterable[str], file_lang: Dict[str, str], ignore_dirs: Set[str]) -> List[SymbolDef]:
    out: List[SymbolDef] = []
    for rel in files:
        p = repo / rel
        if not p.exists() or not p.is_file() or is_ignored(p, ignore_dirs):
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


def extract_env_map(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Tuple[List[str], List[str], List[str], List[str]]:
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


def extract_routes(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Tuple[List[RouteDef], List[RegisterCall]]:
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


def extract_gateway_hints(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Dict[str, List[str]]:
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


def extract_transfer_flow_hints(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> List[TransferFileHint]:
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


def top_level_summary(repo: Path, ignore_dirs: Set[str]) -> List[Tuple[str, str]]:
    summaries: List[Tuple[str, str]] = []
    for p in sorted(repo.iterdir(), key=lambda x: x.name.lower()):
        if p.name in ignore_dirs:
            continue
        if p.is_dir():
            desc = DIR_RESP_HINTS.get(p.name.lower(), 'directory')
            summaries.append((p.name + '/', desc))
    return summaries


def nested_module_summary(repo: Path, roots: Sequence[str], ignore_dirs: Set[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for root in roots:
        base = repo / root
        if not base.exists() or not base.is_dir():
            continue
        try:
            items = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except Exception:
            continue
        for p in items:
            if p.name in ignore_dirs:
                continue
            if not p.is_dir():
                continue
            rel = relpath_posix(p, repo) + '/'
            desc = DIR_RESP_HINTS.get(p.name.lower(), 'module / feature group')
            out.append((rel, desc))
    return out


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

    def parse_occurrence(buf: bytes) -> Tuple[Optional[str], bool]:
        symbol_text = ''
        symbol_roles = 0
        for field_no, wire_type, value in iter_fields(buf):
            if field_no == 2 and wire_type == 2:
                symbol_text = decode_utf8(value)
            elif field_no == 3 and wire_type == 0:
                try:
                    symbol_roles = int(decode_utf8(value))
                except ValueError:
                    symbol_roles = 0
        normalized = normalize_structured_symbol(symbol_text, '') if symbol_text else None
        is_definition = bool(symbol_roles & 0x1)
        return normalized, is_definition

    def parse_document(buf: bytes) -> Tuple[str, str, List[str], List[Tuple[str, bool]]]:
        relative_path = ''
        language = ''
        symbols: List[str] = []
        occurrences: List[Tuple[str, bool]] = []
        for field_no, wire_type, value in iter_fields(buf):
            if wire_type != 2:
                continue
            if field_no == 1:
                relative_path = decode_utf8(value)
            elif field_no == 4:
                language = decode_utf8(value)
            elif field_no == 2:
                normalized_occurrence, is_definition = parse_occurrence(value)
                if normalized_occurrence:
                    occurrences.append((normalized_occurrence, is_definition))
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
                for symbol, is_definition in occurrences:
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
        for symbol, symbol_stat in ranked_occurrence_stats[:10]:
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
        )


def group_scip_symbols_by_file(symbol_hints: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for item in symbol_hints:
        if ' :: ' not in item:
            continue
        file_path, symbol = item.split(' :: ', 1)
        if not symbol:
            continue
        aliases = {file_path}
        if file_path.startswith('src/'):
            aliases.add('backend/' + file_path)
        elif file_path.startswith('backend/src/'):
            aliases.add(file_path[len('backend/'):])
        for alias in aliases:
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

    lines.append("## Top-level structure & purpose")
    for name, desc in top_summary[:30]:
        lines.append(f"- `{name}` — {desc}")
    lines.append("")

    lines.append("## Module / feature groups")
    if module_summary:
        for name, desc in module_summary[:80]:
            lines.append(f"- `{name}` — {desc}")
    else:
        lines.append("- (No nested module groups detected.)")
    lines.append("")

    lines.append("## Repo layout (depth≈3)")
    lines.append("```")
    lines.extend(tree[:700])
    lines.append("```")
    lines.append("")

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
        lines.append(f"- Flutter: `{flutter_entry}`")
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

    lines.append("## Symbol index (definitions + approx mentions)")
    if symbols:
        ranked_syms = sorted(
            symbols,
            key=lambda sd: symbol_scores.get(f"{sd.lang}:{sd.kind}:{sd.name}:{sd.path}:{sd.line}", 0),
            reverse=True,
        )
        lines.append("| kind | name | defined at | approx mentions elsewhere |")
        lines.append("|---|---|---|---:|")
        for sd in ranked_syms[:120]:
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
    edges_ranked: List[Tuple[str, int, int, int]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    gateway_hints: Dict[str, List[str]],
    route_flow_hints: List[RouteFlowHint],
    scip_readiness: ScipReadiness,
    scip_index_status: ScipIndexStatus,
    scip_symbols_by_file: Dict[str, List[str]],
    blast_name: str,
) -> List[str]:
    def extract_route_keywords(chain: List[str]) -> List[str]:
        keywords: List[str] = []
        for step in chain:
            for m in re.finditer(r'`([A-Za-z_][A-Za-z0-9_]*)\(\)`', step):
                keywords.append(m.group(1))
            for m in re.finditer(r'via `([^`]+)`', step):
                parts = [p.strip() for p in m.group(1).split(',')]
                for part in parts:
                    if part:
                        keywords.append(part)
        return keywords

    def rank_route_symbols(impacted: List[str], chain: List[str]) -> List[str]:
        keywords = extract_route_keywords(chain)
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
    if (repo / "ExtentionChrome/extension").exists():
        lines.append("- `ExtentionChrome/extension/`: impacts extension/browser integration")
    lines.append("")

    lines.append("## Highest-risk files (by dependency centrality)")
    if edges_ranked:
        lines.append("| file | total degree | why |")
        lines.append("|---|---:|---|")
        for f, o, i, t in edges_ranked[:35]:
            why = []
            if i >= 5:
                why.append("high fan-in")
            if o >= 5:
                why.append("high fan-out")
            if not why:
                why.append("connected")
            lines.append(f"| `{f}` | {t} | {', '.join(why)} |")
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
    if route_flow_hints:
        for hint in route_flow_hints[:12]:
            lines.append(f"### `{hint.method} {hint.path}`")
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


def scan_repo(repo: Path, out_dir: Path, fast_name: str, blast_name: str) -> Tuple[Path, Path]:
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    scan_subdirs = detect_scan_subdirs(repo)
    tree = list_tree(repo, max_depth=3, ignore_dirs=ignore_dirs)
    manifests = find_manifests(repo, max_depth=4, ignore_dirs=ignore_dirs)

    backend_entry = None
    for cand in ("backend/src/main.ts", "src/main.ts", "src/index.ts", "server/index.ts"):
        if (repo / cand).exists():
            backend_entry = cand
            break
    flutter_entry = None
    for cand in ("app/lib/main.dart", "lib/main.dart"):
        if (repo / cand).exists():
            flutter_entry = cand
            break

    scripts_map: Dict[str, Dict[str, str]] = {}
    for rel in ("package.json", "backend/package.json", "app/package.json"):
        p = repo / rel
        if p.exists():
            scripts = parse_package_scripts(p)
            if scripts:
                scripts_map[rel] = scripts

    edges, file_lang = build_import_graph(repo, scan_subdirs, ignore_dirs)
    ranked_files = compute_degree_centrality(edges)
    files_for_symbols = list(file_lang.keys())
    symbols = extract_symbols(repo, files_for_symbols, file_lang, ignore_dirs)
    symbol_scores = approx_symbol_scores(symbols, file_lang, repo) if symbols else {}
    env_used, env_declared, env_used_not_declared, env_declared_not_used = extract_env_map(repo, scan_subdirs, ignore_dirs)
    routes, regs = extract_routes(repo, scan_subdirs, ignore_dirs)
    gateway_hints = extract_gateway_hints(repo, scan_subdirs, ignore_dirs)
    transfer_flow_hints = extract_transfer_flow_hints(repo, scan_subdirs, ignore_dirs)
    route_flow_hints = extract_route_flow_hints(repo)
    scip_readiness = detect_scip_readiness(repo)
    scip_index_status = detect_scip_index_status(repo, scip_readiness)
    primary_scip_symbols = scip_index_status.structured_symbol_hints or scip_index_status.symbol_hints
    scip_symbols_by_file = group_scip_symbols_by_file(primary_scip_symbols)
    top_summary = top_level_summary(repo, ignore_dirs)
    module_summary = nested_module_summary(repo, scan_subdirs, ignore_dirs)
    edge_details = file_dependency_details(edges, ranked_files)

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
    )
    blast_lines = render_blast_map(
        repo=repo,
        edges_ranked=ranked_files,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        gateway_hints=gateway_hints,
        route_flow_hints=route_flow_hints,
        scip_readiness=scip_readiness,
        scip_index_status=scip_index_status,
        scip_symbols_by_file=scip_symbols_by_file,
        blast_name=blast_name,
    )

    fast_path = out_dir / fast_name
    blast_path = out_dir / blast_name
    fast_path.write_text("\n".join(fast_lines), encoding="utf-8")
    blast_path.write_text("\n".join(blast_lines), encoding="utf-8")
    return fast_path, blast_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Path to repo (default: current directory)")
    ap.add_argument("--out", default="", help="Output directory (default: repo root)")
    ap.add_argument("--inplace", action="store_true", help="Write into repo root (default behavior if --out omitted)")
    ap.add_argument("--mode", choices=["project", "agent-claude", "short"], default="project")
    ap.add_argument("--fast-file", default="", help="Override first output filename")
    ap.add_argument("--blast-file", default="", help="Override second output filename")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    if args.out:
        out_dir = Path(args.out).expanduser().resolve()
    else:
        out_dir = repo

    if args.mode == "agent-claude":
        fast_name = args.fast_file or "AGENT_MAP.md"
        blast_name = args.blast_file or "CLAUDE_MAP.md"
    elif args.mode == "short":
        fast_name = args.fast_file or "MAP.md"
        blast_name = args.blast_file or "IMPACT.md"
    else:
        fast_name = args.fast_file or "PROJECT_FAST_MAP.md"
        blast_name = args.blast_file or "PROJECT_BLAST_RADIUS.md"

    out_dir.mkdir(parents=True, exist_ok=True)
    fast, blast = scan_repo(repo, out_dir, fast_name=fast_name, blast_name=blast_name)
    print("OK")
    print("FAST:", fast)
    print("BLAST:", blast)


if __name__ == "__main__":
    main()
