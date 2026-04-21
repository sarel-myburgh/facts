#!/usr/bin/env python3
"""Rebuild logs/manifest.json from data/*.json files on disk."""

import json
from pathlib import Path

DATA_DIR      = Path(__file__).parent.parent / 'data'
MANIFEST_PATH = Path(__file__).parent.parent / 'logs' / 'manifest.json'


def main():
    months = {p.stem: {'tags': False, 'links': False} for p in sorted(DATA_DIR.glob('*.json'))}
    MANIFEST_PATH.write_text(json.dumps({'months': months}, indent=2), encoding='utf-8')
    print(f'Written {len(months)} entries to {MANIFEST_PATH}')


if __name__ == '__main__':
    main()
