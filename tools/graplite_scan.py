#!/usr/bin/env python3
"""graplite-scan: local/offline project scanner that emits two Markdown files.

Design goals:
- No network calls.
- Works without ripgrep.
- Produces stable, linkable references (path + line ranges when possible).
- “Detailed enough” for agents: entrypoints, module map, symbol index (heuristic), dependency graph (import graph).

Usage:
  python3 graplite_scan.py --repo /path/to/repo --inplace
  python3 graplite_scan.py --repo /path/to/repo --out /path/to/outdir

Outputs:
  - PROJECT_FAST_MAP.md
  - PROJECT_BLAST_RADIUS.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
    "README.md",
    "codemagic.yaml",
}

TEXT_EXTS = {".ts", ".js", ".tsx", ".jsx", ".dart", ".md", ".yaml", ".yml", ".json"}


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def is_ignored(path: Path, ignore_dirs: Set[str]) -> bool:
    return any(part in ignore_dirs for part in path.parts)


def safe_read_text(path: Path, max_bytes: int = 400_000) -> str:
    try:
        b = path.read_bytes()
        if len(b) > max_bytes:
            b = b[:max_bytes]
        return b.decode("utf-8", errors="replace")
    except Exception:
        return ""


@dataclass
class SymbolDef:
    lang: str  # ts|dart
    kind: str  # function|class|const|type
    name: str
    path: str  # posix relative
    line: int


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
    # function / method defs are hard; we take top-level functions
    ("function", re.compile(r"^\s*(?:Future<[^>]+>|Future|void|int|double|String|bool|dynamic|Widget|\w+)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)),
]


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
        return {}
    except Exception:
        return {}


def resolve_ts_import(spec: str, from_file: Path, root: Path) -> Optional[Path]:
    # only resolve relative imports; skip node_modules.
    if not spec.startswith("."):
        return None

    base = (from_file.parent / spec).resolve()

    # Try exact file
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        p = Path(str(base) + ext)
        if p.exists():
            return p

    # Try index
    if base.is_dir():
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            p = base / ("index" + ext)
            if p.exists():
                return p

    # Try base itself
    if base.exists() and base.is_file():
        return base

    return None


def resolve_dart_import(spec: str, from_file: Path, root: Path) -> Optional[Path]:
    # local file imports: relative only
    if spec.startswith("package:") or spec.startswith("dart:"):
        return None
    if not (spec.startswith("./") or spec.startswith("../")):
        return None
    base = (from_file.parent / spec).resolve()
    if base.exists() and base.is_file():
        return base
    # dart imports might omit .dart
    if not base.suffix:
        cand = Path(str(base) + ".dart")
        if cand.exists():
            return cand
    return None


def build_import_graph(root: Path, subdirs: Sequence[str], ignore_dirs: Set[str]) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    """Returns (edges, file_lang) where edges[src]=set(dest)."""
    edges: Dict[str, Set[str]] = {}
    file_lang: Dict[str, str] = {}

    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if is_ignored(p, ignore_dirs):
                continue
            if not p.is_file():
                continue
            if p.suffix not in {".ts", ".js", ".dart"}:
                continue

            rel = relpath_posix(p, root)
            txt = safe_read_text(p)
            if p.suffix in {".ts", ".js"}:
                file_lang[rel] = "ts"
                specs = [m.group("spec") for m in TS_IMPORT_RE.finditer(txt)]
                for s in specs:
                    rp = resolve_ts_import(s, p, root)
                    if rp is None:
                        continue
                    try:
                        dest_rel = relpath_posix(rp, root)
                    except Exception:
                        continue
                    edges.setdefault(rel, set()).add(dest_rel)
            elif p.suffix == ".dart":
                file_lang[rel] = "dart"
                specs = [m.group("spec") for m in DART_IMPORT_RE.finditer(txt)]
                for s in specs:
                    rp = resolve_dart_import(s, p, root)
                    if rp is None:
                        continue
                    try:
                        dest_rel = relpath_posix(rp, root)
                    except Exception:
                        continue
                    edges.setdefault(rel, set()).add(dest_rel)

    return edges, file_lang


def extract_symbols(root: Path, files: Iterable[str], file_lang: Dict[str, str], ignore_dirs: Set[str]) -> List[SymbolDef]:
    out: List[SymbolDef] = []
    for rel in files:
        p = root / rel
        if not p.exists() or not p.is_file():
            continue
        if is_ignored(p, ignore_dirs):
            continue
        txt = safe_read_text(p)
        lang = file_lang.get(rel)
        if lang == "ts":
            for kind, rx in TS_DEF_RES:
                for m in rx.finditer(txt):
                    name = m.group("name")
                    line = txt[: m.start()].count("\n") + 1
                    out.append(SymbolDef(lang="ts", kind=kind, name=name, path=rel, line=line))
        elif lang == "dart":
            for kind, rx in DART_DEF_RES:
                for m in rx.finditer(txt):
                    name = m.group("name")
                    line = txt[: m.start()].count("\n") + 1
                    # Filter obvious false positives for dart: constructors (same as class), etc. Keep for now.
                    out.append(SymbolDef(lang="dart", kind=kind, name=name, path=rel, line=line))
    return out


def compute_degree_centrality(edges: Dict[str, Set[str]]) -> List[Tuple[str, int, int, int]]:
    """Return list of (file, out_degree, in_degree, total)."""
    indeg: Dict[str, int] = {}
    outdeg: Dict[str, int] = {}
    for src, dests in edges.items():
        outdeg[src] = outdeg.get(src, 0) + len(dests)
        for d in dests:
            indeg[d] = indeg.get(d, 0) + 1
    files = set(indeg) | set(outdeg)
    ranked = []
    for f in files:
        o = outdeg.get(f, 0)
        i = indeg.get(f, 0)
        ranked.append((f, o, i, o + i))
    ranked.sort(key=lambda t: (t[3], t[2], t[1]), reverse=True)
    return ranked


def section(title: str) -> str:
    return f"\n## {title}\n"


def md_code(lines: Sequence[str]) -> str:
    return "```\n" + "\n".join(lines) + "\n```\n"


def scan_repo(repo: Path, out_dir: Path, inplace: bool) -> Tuple[Path, Path]:
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)

    # Heuristic: choose subdirs to deeply scan
    scan_subdirs = []
    for cand in ("backend/src", "app/lib", "ExtentionChrome/extension"):
        if (repo / cand).exists():
            scan_subdirs.append(cand)

    tree = list_tree(repo, max_depth=3, ignore_dirs=ignore_dirs)
    manifests = find_manifests(repo, max_depth=4, ignore_dirs=ignore_dirs)

    # entrypoints
    backend_entry = "backend/src/main.ts" if (repo / "backend/src/main.ts").exists() else None
    flutter_entry = "app/lib/main.dart" if (repo / "app/lib/main.dart").exists() else None

    # scripts
    scripts_root = parse_package_scripts(repo / "package.json") if (repo / "package.json").exists() else {}
    scripts_backend = parse_package_scripts(repo / "backend/package.json") if (repo / "backend/package.json").exists() else {}

    edges, file_lang = build_import_graph(repo, scan_subdirs, ignore_dirs)
    ranked_files = compute_degree_centrality(edges)
    files_for_symbols = list(file_lang.keys())
    symbols = extract_symbols(repo, files_for_symbols, file_lang, ignore_dirs)

    # very lightweight symbol usage counts (name mentions across scanned files)
    symbol_counts: Dict[str, int] = {}
    if symbols:
        # limit to avoid quadratic blowup
        top_symbols = symbols[:]
        # build concatenated text per file once
        text_cache: Dict[str, str] = {rel: safe_read_text(repo / rel) for rel in files_for_symbols}
        for sd in top_symbols:
            # count in other files (exclude definition file)
            total = 0
            name_rx = re.compile(r"\b" + re.escape(sd.name) + r"\b")
            for rel, txt in text_cache.items():
                if rel == sd.path:
                    continue
                total += len(name_rx.findall(txt))
            symbol_counts[f"{sd.lang}:{sd.kind}:{sd.name}"] = total

    # FAST MAP
    fast_lines: List[str] = []
    fast_lines.append(f"# PROJECT_FAST_MAP — {repo.name}")
    fast_lines.append("")
    fast_lines.append("_Generated by `graplite-scan` (local/offline; heuristic link graph)._")
    fast_lines.append("")

    fast_lines.append("## TL;DR")
    fast_lines.append(f"- Repo root: `{repo}`")
    if backend_entry:
        fast_lines.append(f"- Backend entrypoint: `{backend_entry}`")
    if flutter_entry:
        fast_lines.append(f"- App entrypoint: `{flutter_entry}`")
    fast_lines.append("")

    fast_lines.append("## Repo layout (depth≈3)")
    fast_lines.append("```")
    fast_lines.extend(tree[:600])
    fast_lines.append("```")
    fast_lines.append("")

    fast_lines.append("## Key manifests (depth<=4)")
    fast_lines.append("```")
    fast_lines.extend(manifests)
    fast_lines.append("```")
    fast_lines.append("")

    fast_lines.append("## Run / Build / Test (from package scripts)")
    if scripts_root:
        fast_lines.append("### package.json")
        for k, v in sorted(scripts_root.items()):
            fast_lines.append(f"- `{k}`: `{v}`")
    if scripts_backend:
        fast_lines.append("### backend/package.json")
        for k, v in sorted(scripts_backend.items()):
            fast_lines.append(f"- `{k}`: `{v}`")
    if not scripts_root and not scripts_backend:
        fast_lines.append("- (no package.json scripts detected)")
    fast_lines.append("")

    fast_lines.append("## Confirmed entrypoints (if present)")
    if backend_entry and (repo / backend_entry).exists():
        fast_lines.append(f"- Backend: `{backend_entry}`")
    if flutter_entry and (repo / flutter_entry).exists():
        fast_lines.append(f"- Flutter: `{flutter_entry}`")
    if (repo / "ExtentionChrome/extension/background.js").exists():
        fast_lines.append("- Chrome extension: `ExtentionChrome/extension/background.js` (+ content/offscreen)")
    fast_lines.append("")

    fast_lines.append("## File dependency hotspots (import graph; heuristic)")
    if ranked_files:
        fast_lines.append("Top files by degree (in+out):")
        fast_lines.append("")
        fast_lines.append("| file | out | in | total |")
        fast_lines.append("|---|---:|---:|---:|")
        for f, o, i, t in ranked_files[:30]:
            fast_lines.append(f"| `{f}` | {o} | {i} | {t} |")
    else:
        fast_lines.append("- (No import edges detected in scanned subdirs.)")
    fast_lines.append("")

    fast_lines.append("## Symbol index (heuristic; definitions + mention counts)")
    if symbols:
        # rank by mention counts
        def score(sd: SymbolDef) -> int:
            return symbol_counts.get(f"{sd.lang}:{sd.kind}:{sd.name}", 0)

        syms_sorted = sorted(symbols, key=lambda sd: (score(sd), sd.kind), reverse=True)
        fast_lines.append("| kind | name | defined at | mentions elsewhere (approx) |")
        fast_lines.append("|---|---|---|---:|")
        for sd in syms_sorted[:80]:
            fast_lines.append(
                f"| {sd.lang}:{sd.kind} | `{sd.name}` | `{sd.path}:{sd.line}` | {score(sd)} |"
            )
    else:
        fast_lines.append("- (No symbols extracted; enable SCIP later for accurate symbol graph.)")
    fast_lines.append("")

    fast_lines.append("## Notes / limitations")
    fast_lines.append("- This scan is **offline** and currently uses: import graph + regex symbol extraction.")
    fast_lines.append("- For true callers/callees + precise blast radius, next step is **SCIP indexing** (backend TypeScript first).")

    fast_path = out_dir / "PROJECT_FAST_MAP.md"
    blast_path = out_dir / "PROJECT_BLAST_RADIUS.md"

    # BLAST RADIUS
    blast_lines: List[str] = []
    blast_lines.append(f"# PROJECT_BLAST_RADIUS — {repo.name}")
    blast_lines.append("")
    blast_lines.append("_Generated by `graplite-scan` (local/offline; heuristic impact)._")
    blast_lines.append("")

    blast_lines.append("## Module-level blast radius (heuristic)")
    if (repo / "backend").exists():
        blast_lines.append("- `backend/`: impacts API/runtime, storage integration, transfer signaling")
    if (repo / "app").exists():
        blast_lines.append("- `app/`: impacts UI + transfer behaviors client-side")
    if (repo / "ExtentionChrome/extension").exists():
        blast_lines.append("- `ExtentionChrome/extension/`: impacts browser integration/UX")
    blast_lines.append("")

    blast_lines.append("## High-risk files (by dependency centrality)")
    if ranked_files:
        blast_lines.append("| file | total degree | why |")
        blast_lines.append("|---|---:|---|")
        for f, o, i, t in ranked_files[:25]:
            why = []
            if i >= 5:
                why.append("high fan-in")
            if o >= 5:
                why.append("high fan-out")
            if not why:
                why.append("connected")
            blast_lines.append(f"| `{f}` | {t} | {', '.join(why)} |")
    else:
        blast_lines.append("- (No import graph available.)")
    blast_lines.append("")

    blast_lines.append("## Change recipes")
    if backend_entry:
        blast_lines.append(f"- If changing `{backend_entry}`: verify server boots + health endpoint + WS on/off")
    if flutter_entry:
        blast_lines.append(f"- If changing `{flutter_entry}`: verify app boots + TransferService init + main navigation")
    blast_lines.append("- If changing any `transfer` module: do an end-to-end multi-file transfer smoke test")
    blast_lines.append("")

    blast_lines.append("## Next step (recommended)")
    blast_lines.append("1) Install TS SCIP indexer (network required once) → build real symbol graph")
    blast_lines.append("2) Add `--diff <range>`: map git diff → changed files → impacted modules/symbols")

    fast_path.write_text("\n".join(fast_lines), encoding="utf-8")
    blast_path.write_text("\n".join(blast_lines), encoding="utf-8")

    return fast_path, blast_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="Path to repo")
    ap.add_argument("--out", default="", help="Output directory (if not inplace)")
    ap.add_argument("--inplace", action="store_true", help="Write into repo root")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        raise SystemExit(f"Repo not found: {repo}")

    if args.inplace:
        out_dir = repo
    else:
        if not args.out:
            raise SystemExit("Either --inplace or --out is required")
        out_dir = Path(args.out).expanduser().resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    fast, blast = scan_repo(repo, out_dir, inplace=args.inplace)
    print("OK")
    print("FAST:", fast)
    print("BLAST:", blast)


if __name__ == "__main__":
    main()
