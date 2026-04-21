# Quick setup

## On a new machine

```bash
git clone <graplite-scan-repo>
cd graplite-scan
./scripts/setup-local.sh
```

## npm-style local CLI (no publish yet)

Inside the `graplite-scan` repo:

```bash
npx . /path/to/repo
```

If you want to use the package name locally on your machine:

```bash
cd graplite-scan
npm link
cd /path/to/repo
npx graplite-scan .
```

## In a target repo

```bash
cd /path/to/repo
graplite init --write-runner --write-gitignore
graplite scan
```

## Shortest future workflow

```bash
cd /path/to/repo
./scripts/graplite-scan.sh
```
