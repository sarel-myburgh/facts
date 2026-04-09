# Facts Cleaner Agent

Remove irrelevant Wikipedia links and images from facts. Works newest-to-oldest.

## What gets removed
- **Links**: bare year articles (`1933`, `476`) used only for dating; month articles (`January`); 
  generic common words that appeared incidentally in the text; overly broad category links when 
  a more specific link for the same subject already exists
- **Images**: images of tangential subjects; generic icons/diagrams for a word that appeared 
  incidentally (e.g. image of a cube because the fact mentioned "cube")
- **NOT removed**: any link/image that is about the actual subject of the fact; 
  anything ambiguous (conservative by design)

## Step 1 — Run the cleaner

```bash
cd /home/sarel/facts
python3 tools/run_cleaner_gemini.py {{MONTH_KEY}} --provider gemini
```

The script handles batching, LLM calls, validation, and manifest update.
If Gemini quota is exhausted it falls back to Claude Haiku automatically.

To process multiple months in order:
```bash
cd /home/sarel/facts
python3 tools/run_cleaner_gemini.py dyk_2026_Mar dyk_2026_Feb dyk_2026_Jan \
  dyk_2025_Dec dyk_2025_Nov dyk_2025_Oct dyk_2025_Sep dyk_2025_Aug \
  dyk_2025_Jul dyk_2025_Jun dyk_2025_May dyk_2025_Apr dyk_2025_Mar \
  dyk_2025_Feb dyk_2025_Jan --provider gemini
```

## Step 2 — Verify

```bash
cd /home/sarel/facts
python3 -c "
import json
e = json.load(open('data/manifest.json'))['months'].get('{{MONTH_KEY}}', {})
print('cleaned:', e.get('cleaned'))
"
```

## Step 3 — Commit and push

```bash
cd /home/sarel/facts
git add data/{{MONTH_KEY}}.json data/manifest.json
git commit -m "clean: {{MONTH_KEY}}"
git pull --rebase origin main && git push origin main
```

On push failure: retry `git pull --rebase && git push` up to 3 times, then stop.

## Notes
- `cleaned: true` is set in manifest once a month is processed
- Skips months already marked `cleaned: true`
- Script is idempotent — safe to re-run
- Use `--provider haiku` if Gemini is unavailable
- Default batch size is 20 facts (links/images need more reasoning space than tags)
