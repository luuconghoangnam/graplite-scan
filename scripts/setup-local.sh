#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$ROOT/tools/graplite_install.py"
echo
printf '%s\n' 'Next steps:'
printf '  1) cd /path/to/your/repo\n'
printf '  2) graplite init\n'
printf '  3) graplite scan\n'
