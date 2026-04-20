# CLI ideas for graplite-scan

## Current smooth UX
- `graplite` → scan current repo, write `MAP.md` + `IMPACT.md`
- `graplite .` → same
- `graplite /path/to/repo` → scan target repo, write `MAP.md` + `IMPACT.md`

## Explicit modes
- `graplite analyze [repo]` → short names, full detailed content
- `graplite project [repo]` → `PROJECT_FAST_MAP.md` + `PROJECT_BLAST_RADIUS.md`
- `graplite agent [repo]` → `AGENT_MAP.md` + `CLAUDE_MAP.md`

## Next CLI upgrades
- `graplite diff [repo] --range HEAD~1..HEAD`
- `graplite init-shell` → print alias/export snippet
- `graplite doctor` → check python, refs, optional SCIP tools
- `graplite install` → install a symlink/wrapper into `~/.local/bin`
