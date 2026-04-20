# graplite-scan (private)

Local/offline scanning logic to generate two **in-repo** Markdown files:
- `PROJECT_FAST_MAP.md`
- `PROJECT_BLAST_RADIUS.md`

## Usage

```bash
python3 tools/graplite_scan.py --repo /path/to/repo --inplace
```

## References (optional)
To pull reference repos (not committed):

```bash
./scripts/fetch-references.sh
```

`references/` and generated `output/` are gitignored.
