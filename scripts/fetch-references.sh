#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
REF="${ROOT}/references"
mkdir -p "${REF}"

clone_or_update() {
  local url="$1"
  local name
  name=$(basename "${url}" .git)
  if [[ -d "${REF}/${name}/.git" ]]; then
    echo "Updating ${name}"
    git -C "${REF}/${name}" fetch --depth 1 origin
    git -C "${REF}/${name}" reset --hard origin/HEAD
  else
    echo "Cloning ${name}"
    git clone --depth 1 "${url}" "${REF}/${name}"
  fi
}

clone_or_update https://github.com/sourcegraph/scip.git
clone_or_update https://github.com/sourcegraph/scip-typescript.git
clone_or_update https://github.com/tree-sitter/tree-sitter.git

echo "OK"
