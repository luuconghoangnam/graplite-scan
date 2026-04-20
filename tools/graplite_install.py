#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import shutil

ROOT = Path('/home/gone/.openclaw/workspace/graplite-scan')
SRC = ROOT / 'bin' / 'graplite'
DST_DIR = Path.home() / '.local' / 'bin'
DST = DST_DIR / 'graplite'


def main():
    if not SRC.exists():
        raise SystemExit(f'Missing source wrapper: {SRC}')

    DST_DIR.mkdir(parents=True, exist_ok=True)
    if DST.exists() or DST.is_symlink():
        DST.unlink()
    os.symlink(SRC, DST)

    print(f'Installed: {DST} -> {SRC}')
    print()
    path_entries = os.environ.get('PATH', '').split(':')
    if str(DST_DIR) in path_entries:
        print('~/.local/bin is already in PATH.')
        print('You can now run:')
        print('  graplite')
        print('  graplite .')
    else:
        print('~/.local/bin is not in PATH yet.')
        print('Add this to your shell rc (~/.bashrc or ~/.zshrc):')
        path_expr = str(Path.home() / '.local' / 'bin') + ':' + '{PATH_FROM_SHELL}'
        print('  export PATH="' + path_expr + '"')
        print('Replace {PATH_FROM_SHELL} with your existing PATH if needed, then open a new shell or source the rc file.')


if __name__ == '__main__':
    main()
