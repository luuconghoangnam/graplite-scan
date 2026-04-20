# graplite-scan (private)

Local/offline scanning logic to generate two **in-repo** Markdown files.

## Smooth one-command usage

If you're already inside the target repo:

```bash
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite
```

Or:

```bash
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite .
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite /path/to/repo
```

Default outputs (full detailed mode with short names):
- `MAP.md`
- `IMPACT.md`

## Explicit modes

```bash
# same default output names
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite analyze .

# longer project-style names
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite project .

# legacy agent/claude naming
/home/gone/.openclaw/workspace/graplite-scan/bin/graplite agent .
```

## Optional shell alias

Source this file in your shell startup:

```bash
source /home/gone/.openclaw/workspace/graplite-scan/shell/graplite.sh
```

Then just run:

```bash
graplite
graplite .
graplite /path/to/repo
```

## References (optional)
To pull reference repos (not committed):

```bash
./scripts/fetch-references.sh
```

`references/` and generated `output/` are gitignored.
