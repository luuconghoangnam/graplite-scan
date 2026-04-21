#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'templates' / 'graplite.config.example.json'
DEFAULT_NAME = '.graplite.json'


def main() -> None:
    repo = Path('.').resolve()
    target = repo / DEFAULT_NAME
    if target.exists():
        print(f'Exists: {target}')
        return
    if not TEMPLATE.exists():
        raise SystemExit(f'Missing template: {TEMPLATE}')
    data = json.loads(TEMPLATE.read_text(encoding='utf-8'))
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Created: {target}')


if __name__ == '__main__':
    main()
