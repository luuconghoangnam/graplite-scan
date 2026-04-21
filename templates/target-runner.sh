#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"
if command -v graplite >/dev/null 2>&1; then
  exec graplite scan .
fi
if [[ -x "$HOME/.local/bin/graplite" ]]; then
  exec "$HOME/.local/bin/graplite" scan .
fi
echo "graplite not found. Install graplite-scan first." >&2
exit 1
