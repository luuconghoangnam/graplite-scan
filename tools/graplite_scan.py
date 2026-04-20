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
  python3 tools/graplite_scan.py --repo . --mode agent-claude
  python3 tools/graplite_scan.py --repo /path/to/repo --out /tmp/reportdir

Default outputs:
  - PROJECT_FAST_MAP.md
  - PROJECT_BLAST_RADIUS.md

Agent/Claude mode outputs:
  - AGENT_MAP.md
  - CLAUDE_MAP.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
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
    r"(?P<target>\bapp|\bserver|\brouter|\bfastify)\.(?P<method>get|post|put|delete|patch|options|head)\s*\(\s*['\"](?P<path>[^'\"]+)['\"]",
    re.I,
)
REGISTER_ROUTE_RE = re.compile(r"\b(register[A-Za-z0-9_]*(?:Routes|Gateway))\s*\(")
WS_EVENT_RE = re.compile(r"['\"]([A-Za-z0-9:_\-]+)['\"]")
TRANSFER_HINT_RE = re.compile(r"transfer|gateway|websocket|socket|peer", re.I)


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


def extract_env_map(repo: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Tuple[List[str], List[str]]:
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

    for env_name in (".env.example", ".env"):
        p = repo / env_name
        if p.exists():
            txt = safe_read_text(p)
            declared.update(ENV_KEY_LINE_RE.findall(txt))

    return sorted(used), sorted(declared)


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


def top_level_summary(repo: Path, ignore_dirs: Set[str]) -> List[Tuple[str, str]]:
    summaries: List[Tuple[str, str]] = []
    for p in sorted(repo.iterdir(), key=lambda x: x.name.lower()):
        if p.name in ignore_dirs:
            continue
        if p.is_dir():
            desc = "directory"
            name = p.name.lower()
            if name in {"src", "backend", "server", "api"}:
                desc = "server/backend logic"
            elif name in {"app", "frontend", "web", "client"}:
                desc = "application / UI layer"
            elif name in {"docs", "documentation"}:
                desc = "architecture notes, plans, docs"
            elif name in {"scripts", "bin", "tools"}:
                desc = "automation / helper scripts"
            elif name in {"infra", "deploy", ".github"}:
                desc = "CI/deploy/infrastructure"
            summaries.append((p.name + "/", desc))
    return summaries


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


def render_fast_map(
    repo: Path,
    tree: List[str],
    manifests: List[str],
    scripts_root: Dict[str, str],
    edges_ranked: List[Tuple[str, int, int, int]],
    symbols: List[SymbolDef],
    symbol_scores: Dict[str, int],
    top_summary: List[Tuple[str, str]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    env_used: List[str],
    env_declared: List[str],
    routes: List[RouteDef],
    regs: List[RegisterCall],
    gateway_hints: Dict[str, List[str]],
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

    lines.append("## File dependency hotspots (import graph)")
    if edges_ranked:
        lines.append("| file | out | in | total |")
        lines.append("|---|---:|---:|---:|")
        for f, o, i, t in edges_ranked[:40]:
            lines.append(f"| `{f}` | {o} | {i} | {t} |")
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
    lines.append("- Output này tối ưu để AI đọc nhanh: entrypoints, env, route map, hotspots, symbol index.")
    lines.append("- Với repo TypeScript lớn, bước tiếp theo là bật SCIP để có callers/callees chuẩn hơn.")
    return lines


def render_blast_map(
    repo: Path,
    edges_ranked: List[Tuple[str, int, int, int]],
    backend_entry: Optional[str],
    flutter_entry: Optional[str],
    gateway_hints: Dict[str, List[str]],
    blast_name: str,
) -> List[str]:
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

    lines.append("## Change recipes")
    if backend_entry:
        lines.append(f"- If changing `{backend_entry}`: verify server boots, health endpoints, route registration, WS on/off")
    if flutter_entry:
        lines.append(f"- If changing `{flutter_entry}`: verify app boot, service init, navigation, transfer flow startup")
    if gateway_hints:
        lines.append("- If changing gateway/transfer modules: run end-to-end transfer smoke test and watch message/event schema drift")
    lines.append("")

    lines.append("## Next step")
    lines.append("1) Add SCIP-based refs/defs for real callers/callees")
    lines.append("2) Add `--diff <range>` to map changed files/symbols → impacted files/symbols")
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
    env_used, env_declared = extract_env_map(repo, scan_subdirs, ignore_dirs)
    routes, regs = extract_routes(repo, scan_subdirs, ignore_dirs)
    gateway_hints = extract_gateway_hints(repo, scan_subdirs, ignore_dirs)
    top_summary = top_level_summary(repo, ignore_dirs)

    fast_lines = render_fast_map(
        repo=repo,
        tree=tree,
        manifests=manifests,
        scripts_root=scripts_map,
        edges_ranked=ranked_files,
        symbols=symbols,
        symbol_scores=symbol_scores,
        top_summary=top_summary,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        env_used=env_used,
        env_declared=env_declared,
        routes=routes,
        regs=regs,
        gateway_hints=gateway_hints,
        fast_name=fast_name,
        blast_name=blast_name,
    )
    blast_lines = render_blast_map(
        repo=repo,
        edges_ranked=ranked_files,
        backend_entry=backend_entry,
        flutter_entry=flutter_entry,
        gateway_hints=gateway_hints,
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
    ap.add_argument("--mode", choices=["project", "agent-claude"], default="project")
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
