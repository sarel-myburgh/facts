# Facts Tagger — Haiku Agent

Tag one month of facts using Gemini, then commit.

## Target
`{{MONTH_KEY}}` — file: `/home/sarel/facts/data/{{MONTH_KEY}}.json`

## Step 1 — Run the tagger

```bash
cd /home/sarel/facts
python3 tools/run_tags_gemini.py {{MONTH_KEY}} --provider gemini
```

The script handles batching, Gemini calls, validation, retries, and manifest update.
If Gemini quota is exhausted it falls back to Claude Haiku automatically.

## Step 2 — Verify

```bash
cd /home/sarel/facts
python3 -c "
import json
e = json.load(open('data/manifest.json'))['months'].get('{{MONTH_KEY}}', {})
print('tags:', e.get('tags'), '|', e.get('tagged_facts'), '/', e.get('total_facts'))
"
```

If `tags: False` still (some facts failed validation), re-run Step 1 once more.

## Step 3 — Commit and push

```bash
cd /home/sarel/facts
git add data/{{MONTH_KEY}}.json data/manifest.json
git commit -m "tags: {{MONTH_KEY}}"
git pull --rebase origin main && git push origin main
```

On push failure: retry `git pull --rebase && git push` up to 3 times, then log and stop.
