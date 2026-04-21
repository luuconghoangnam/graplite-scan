# Quick setup

## On a new machine

```bash
git clone <graplite-scan-repo>
cd graplite-scan
./scripts/setup-local.sh
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
