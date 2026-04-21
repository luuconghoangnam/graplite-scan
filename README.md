# graplite-scan (private)

Local/offline repo scanner that generates two **in-repo** Markdown files optimized for AI + human onboarding:
- `MAP.md`
- `IMPACT.md`

## Goals
- very short commands
- clean output for AI to read
- enough structure/detail for onboarding + impact analysis
- easy to clone onto another machine and set up quickly
- can be used in npm-style CLI flows

---

## Fastest usage

Inside any target repo:

```bash
graplite init --write-runner --write-gitignore
graplite scan
```

That will:
- create `.graplite.json`
- create `scripts/graplite-scan.sh`
- append a small graplite block into `.gitignore`
- generate `MAP.md` + `IMPACT.md`

You can also run:

```bash
graplite
graplite .
graplite /path/to/repo
```

---

## npm-style usage

### Local npx form (works now)
From inside the `graplite-scan` repo:

```bash
npx . /path/to/repo
```

### Local package-name form (works after link)

```bash
cd graplite-scan
npm link
cd /path/to/repo
npx graplite-scan .
```

### Future fully-global form
After publishing the package, the goal is:

```bash
cd /path/to/repo
npx graplite-scan
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

## 3-command setup on a new machine

```bash
git clone <graplite-scan-repo>
cd graplite-scan
./scripts/setup-local.sh
```

Then in any target repo:

```bash
cd /path/to/repo
graplite init --write-runner --write-gitignore
graplite scan
```

After that, future scans are usually just:

```bash
./scripts/graplite-scan.sh
```

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

# create local repo config only
graplite init

# create config + runner + gitignore helper
graplite init --write-runner --write-gitignore

# environment checks
graplite doctor
```

---

## Recommended files to keep in each target repo

Minimal portable setup:
- `.graplite.json`
- `scripts/graplite-scan.sh`

Helpful ignore block:
- small graplite section in `.gitignore`

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
