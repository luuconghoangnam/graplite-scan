# graplite-scan (private)

Local/offline scanning logic to generate two **in-repo** Markdown files.

## Smooth one-command usage

From anywhere:

```bash
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite analyze /path/to/repo
```

Or if you're already inside the target repo:

```bash
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite analyze .
```

Default short outputs:
- `MAP.md`
- `IMPACT.md`

## Other modes

```bash
# longer project-style names
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite project .

# legacy agent/claude naming
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite agent .
```

## References (optional)
To pull reference repos (not committed):

```bash
./scripts/fetch-references.sh
```

`references/` and generated `output/` are gitignored.
