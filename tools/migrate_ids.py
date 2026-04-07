#!/usr/bin/env python3
"""
migrate_ids.py — Rewrite fact IDs to prefixed format.

Old format: plain UUID  e.g. a1b2c3d4-e5f6-7890-abcd-123456789012
New format: {source}_{period}_{12 hex chars}  e.g. dyk_2025_Jan_a1b2c3d4e5f6

The 12 hex chars are the first 12 characters of the UUID with dashes removed,
making the migration fully deterministic and reversible.

Run once after upgrading scraper.py, before committing the data files.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'


def migrate_file(path: Path) -> int:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    source = data.get('source', '')
    period = data.get('period', '')
    facts  = data.get('facts', [])

    changed = 0
    for fact in facts:
        old_id = fact.get('id', '')
        # Skip if already in prefixed format.
        if old_id.startswith(f'{source}_'):
            continue
        hex_suffix = old_id.replace('-', '')[:12]
        fact['id'] = f'{source}_{period}_{hex_suffix}'
        changed += 1

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return changed


def main():
    files = sorted(DATA_DIR.glob('dyk_*.json')) + sorted(DATA_DIR.glob('tih_*.json'))
    total_files = 0
    total_facts = 0
    for path in files:
        n = migrate_file(path)
        if n:
            print(f'  {path.name}: {n} IDs rewritten')
            total_files += 1
            total_facts += n
    print(f'\nDone — {total_facts} IDs rewritten across {total_files} files.')


if __name__ == '__main__':
    main()
