#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path('/home/gone/.openclaw/workspace/graplite-scan')


def check_bin(name: str):
    return shutil.which(name) is not None


def main():
    print('graplite doctor')
    print()

    py = shutil.which('python3')
    print(f'- python3: {'OK' if py else 'MISSING'}' + (f' ({py})' if py else ''))
    git = shutil.which('git')
    print(f'- git: {'OK' if git else 'MISSING'}' + (f' ({git})' if git else ''))

    refs = ROOT / 'references'
    print(f'- references dir: {'OK' if refs.exists() else 'MISSING'} ({refs})')

    for name in ['scip', 'scip-typescript', 'tree-sitter']:
        p = refs / name
        print(f'- reference repo {name}: {'OK' if p.exists() else 'MISSING'} ({p})')

    print(f'- local wrapper: {'OK' if (ROOT / 'bin' / 'graplite').exists() else 'MISSING'} ({ROOT / 'bin' / 'graplite'})')

    local_bin = Path.home() / '.local' / 'bin' / 'graplite'
    print(f'- installed shortcut ~/.local/bin/graplite: {'OK' if local_bin.exists() else 'NOT INSTALLED'} ({local_bin})')

    path_entries = os.environ.get('PATH', '').split(':')
    print(f'- ~/.local/bin in PATH: {'YES' if str(Path.home() / '.local' / 'bin') in path_entries else 'NO'}')

    print()
    print('Recommended next steps:')
    if not local_bin.exists():
        print('- Run: graplite install')
    if not refs.exists() or not (refs / 'scip').exists():
        print('- Run: ./scripts/fetch-references.sh')


if __name__ == '__main__':
    main()
