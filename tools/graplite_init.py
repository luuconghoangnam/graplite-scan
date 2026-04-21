#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_TEMPLATE = ROOT / 'templates' / 'graplite.config.example.json'
RUNNER_TEMPLATE = ROOT / 'templates' / 'target-runner.sh'
GITIGNORE_SNIPPET = ROOT / 'templates' / 'gitignore.snippet.txt'
DEFAULT_CONFIG_NAME = '.graplite.json'


def ensure_config(repo: Path) -> None:
    target = repo / DEFAULT_CONFIG_NAME
    if target.exists():
        print(f'Exists: {target}')
        return
    if not CONFIG_TEMPLATE.exists():
        raise SystemExit(f'Missing template: {CONFIG_TEMPLATE}')
    data = json.loads(CONFIG_TEMPLATE.read_text(encoding='utf-8'))
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Created: {target}')


def ensure_runner(repo: Path) -> None:
    target = repo / 'scripts' / 'graplite-scan.sh'
    if target.exists():
        print(f'Exists: {target}')
        return
    if not RUNNER_TEMPLATE.exists():
        raise SystemExit(f'Missing template: {RUNNER_TEMPLATE}')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(RUNNER_TEMPLATE.read_text(encoding='utf-8'), encoding='utf-8')
    target.chmod(0o755)
    print(f'Created: {target}')


def ensure_gitignore(repo: Path) -> None:
    target = repo / '.gitignore'
    snippet = GITIGNORE_SNIPPET.read_text(encoding='utf-8').strip()
    if not target.exists():
        target.write_text(snippet + '\n', encoding='utf-8')
        print(f'Created: {target}')
        return
    existing = target.read_text(encoding='utf-8')
    if snippet in existing:
        print(f'Exists: {target} (graplite block present)')
        return
    new_text = existing.rstrip() + '\n\n' + snippet + '\n'
    target.write_text(new_text, encoding='utf-8')
    print(f'Updated: {target}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--write-runner', action='store_true', help='Also create scripts/graplite-scan.sh in target repo')
    ap.add_argument('--write-gitignore', action='store_true', help='Also append a small graplite block to .gitignore')
    args = ap.parse_args()

    repo = Path('.').resolve()
    ensure_config(repo)
    if args.write_runner:
        ensure_runner(repo)
    if args.write_gitignore:
        ensure_gitignore(repo)


if __name__ == '__main__':
    main()
