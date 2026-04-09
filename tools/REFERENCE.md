# Facts Pipeline Reference

## Paths
- Repo: `/home/sarel/facts`
- Data: `data/*.json` + `data/manifest.json`
- Tools: `tools/`

## Fact Format
Month files: `dyk_YYYY_Mon.json` (Wikipedia DYK archive) · `tih_Mon.json` (This Day in History)

```json
{
  "id": "dyk_2025_Jan_a1b2c3d4e5f6",
  "text": "...",
  "tags": ["tag1", "tag2", ..., "tag10"],
  "links": [{"url": "...", "title": "...", "source": "Wikipedia"}],
  "image": {"url": "...", "caption": "..."}
}
```

Manifest entry:
```json
"dyk_2025_Jan": {"tags": true, "links": false, "cleaned": false, "tagged_facts": 432, "total_facts": 432}
```
(`links` is a scraper counter field, not the same as `cleaned`)

## Tag Rules
Exactly 10 per fact · lowercase · 1–5 words · no commas/slashes · no filler words.

Filler (never use): `facts knowledge interesting trivia amazing information notable important significant unique unusual rare general various miscellaneous overview topic subject stuff things other`

Balance: ~4-5 broad interest tags (e.g. `crime`, `biology`) + ~4-5 specific sub-tags (e.g. `church crime`, `marine biology`).

## Key Scripts

| Script | Purpose |
|--------|---------|
| `tools/run_tags_gemini.py MONTH [--provider gemini\|haiku\|auto] [--batch-size N]` | Tag one month |
| `tools/process_tag_month.sh MONTH` | 3-pass haiku tagging (bulk→repair→straggler) |
| `tools/run_tags_parallel_queue.sh` | Queue-based parallel workers (6 default) |
| `tools/run_cleaner_gemini.py MONTH [--provider gemini\|haiku\|auto]` | Clean irrelevant links/images |
| `tools/build_tag_queue.py [--count N]` | Print untagged months (smallest first) |

## Agent Files

| File | Purpose |
|------|---------|
| `coordinator-agent-haiku.md` | Spawn 3 parallel tagging sub-agents (interleaved months) |
| `enricher-agent-haiku.md` | Tag one month (sub-agent instructions used by coordinator) |
| `qa-agent-haiku.md` | Mode A: search facts · Mode B: scan for garbage tags |
| `cleaner-agent.md` | Clean irrelevant links/images from facts (newest→oldest) |

## Tagging Workflow
1. Coordinator finds untagged months → splits interleaved across 3 Haiku sub-agents
2. Each sub-agent runs `run_tags_gemini.py MONTH --provider gemini` per month
3. Gemini falls back to Haiku on quota exhaustion
4. Commit + push after each month: `git add data/MONTH.json data/manifest.json && git commit -m "tags: MONTH" && git pull --rebase && git push`

## Cleaning Workflow
1. Run `run_cleaner_gemini.py MONTH --provider gemini` (newest months first, going backwards)
2. Script removes links/images the LLM judges irrelevant; sets `cleaned: true` in manifest
3. Commit + push: `git commit -m "clean: MONTH"`

## Gemini CLI
Called via: `gemini -m gemini-2.5-flash --approval-mode yolo -p "PROMPT"`
Models tried in order: `gemini-2.5-flash`, `gemini-2.5-pro`
Falls back to Haiku on quota exhaustion or parse errors (auto mode).

## QA Scan (garbage tags)
Mode B in `qa-agent-haiku.md` — run inline Python to scan all months for facts with invalid tag sets (10 tags but failing validation rules). Fix: clear `tags: []` on bad facts, then retag.

## Common Status Queries
```bash
# Untagged 2025/2026 months
python3 -c "import json; m=json.load(open('data/manifest.json')); [print(k,v['tagged_facts'],'/',v['total_facts']) for k,v in sorted(m['months'].items()) if ('2025' in k or '2026' in k) and not v.get('tags')]"

# Uncleaned months (2025/2026)
python3 -c "import json; m=json.load(open('data/manifest.json')); [print(k) for k,v in sorted(m['months'].items(), reverse=True) if ('2025' in k or '2026' in k) and not v.get('cleaned')]"
```

## Status Snapshot (2026-04-09)
- **2025**: All tagged. `dyk_2025_Apr.part2` had 2 untagged facts remaining.
- **2026**: `dyk_2026_Jan` 271/275 · `dyk_2026_Feb` 0/377 · `dyk_2026_Mar` 0/367
- Cleaning: not started on any 2025/2026 month
