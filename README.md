# graplite-scan (private)

Local/offline repo scanner that generates two **in-repo** Markdown files optimized for AI + human onboarding:
- `MAP.md`
- `IMPACT.md`

## Goals
- very short commands
- clean output for AI to read
- enough structure/detail for onboarding + impact analysis
- easy to clone onto another machine and set up quickly

---

## Fastest usage

Inside any target repo:

```bash
graplite init
graplite scan
```

That will:
- create `.graplite.json` once
- generate `MAP.md` + `IMPACT.md`

You can also run:

```bash
graplite
graplite .
graplite /path/to/repo
```

---

## Install on a machine

From this repo:

```bash
./scripts/setup-local.sh
```

Or manually:

```bash
python3 tools/graplite_install.py
```

Then ensure `~/.local/bin` is in your `PATH`.

---

## Repo-local config

Each scanned project can keep its own config file:

```json
{
  "mode": "short",
  "profile": "ai-clean",
  "fastFile": "MAP.md",
  "blastFile": "IMPACT.md",
  "outDir": "",
  "diffRange": ""
}
```

Default filename:
- `.graplite.json`

### Recommended preset
For AI-friendly output, use:

```json
{
  "mode": "short",
  "profile": "ai-clean"
}
```

`ai-clean` currently makes the output cleaner by:
- trimming noisy tree output
- skipping some low-value inventory sections
- shortening oversized symbol/tree sections

---

## Common commands

```bash
# scan current repo using local config if present
graplite scan

# scan another repo
graplite /path/to/repo

# generate short names explicitly
graplite analyze .

# longer project naming
graplite project .

# legacy agent naming
graplite agent .

# create local repo config
graplite init

# environment checks
graplite doctor
```

---

## Clone onto another machine

```bash
git clone <this-repo-url>
cd graplite-scan
./scripts/setup-local.sh

cd /path/to/target-repo
graplite init
graplite scan
```

If you want the target repo itself to be portable across machines, commit:
- `.graplite.json`
- optional wrapper script such as `scripts/graplite-scan.sh`
- generated `MAP.md` + `IMPACT.md` only when you intentionally want checked-in docs

---

## Recommended files to keep in each target repo

Minimal portable setup:
- `.graplite.json`
- `scripts/graplite-scan.sh`

Optional checked-in outputs:
- `MAP.md`
- `IMPACT.md`

---

## References (optional)

To pull reference repos (not committed):

```bash
./scripts/fetch-references.sh
```

`references/` and generated `output/` are gitignored.
