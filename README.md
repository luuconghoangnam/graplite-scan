# graplite-scan (private)

Local/offline scanning logic to generate two **in-repo** Markdown files.

## Smooth one-command usage

If you're already inside the target repo:

```bash
graplite
```

Or:

```bash
graplite .
graplite /path/to/repo
```

Default outputs (full detailed mode with short names):
- `MAP.md`
- `IMPACT.md`

## Install once

```bash
python3 tools/graplite_install.py
```

Or via wrapper command:

```bash
./bin/graplite install
```

## Doctor

```bash
graplite doctor
```

## Explicit modes

```bash
# same default output names
graplite analyze .

# longer project-style names
graplite project .

# legacy agent/claude naming
graplite agent .
```

## Optional shell alias

Source this file in your shell startup:

```bash
source /home/gone/.openclaw/workspace/graplite-scan/shell/graplite.sh
```

## References (optional)
To pull reference repos (not committed):

```bash
./scripts/fetch-references.sh
```

`references/` and generated `output/` are gitignored.
