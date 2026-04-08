# BokyLearn Facts Enricher

⛔ **No scripts.** A previous Python attempt assigned an Empire State Building photo to a fact about an actress. Scripts can't reason about relevance. Process each fact individually using your web search and file tools. Shell is for git only.

## Target file
`{{FILE}}` (repo: `/home/sarel/code/facts/`)

## Skip logic
A fact is done when: `tags` ≥ 10 AND image resolved (or deliberately blank) AND links clean AND `version == 2`. Skip it entirely. Only process incomplete steps.

## Step 1 — Tags
Assign **exactly 10 tags**. Rules:
- Lowercase, hyphens only (e.g. `world-war-ii`)
- 1–3 words each
- Mix broad (`history`, `science`) with specific (`1969 moon landing`, `emperor penguins`)
- Tag for audience interest profile — what else would a fan of this fact enjoy?
- Cover: subject, field, era/region, crossover topics

## Step 2 — Image
Use web search. Never guess URLs. Verify every URL resolves before writing.

**Default: find an image.** Most facts SHOULD get one. Blank is a genuine last resort, not a time-saver. If the fact mentions a named person, place, event, building, vehicle, species, plant, or artwork, there is almost certainly a Wikimedia Commons image — go find it. Do not blank unless you genuinely tried and failed.

**Fastest path to a good image:** the fact's `links` array already contains Wikipedia URLs for the fact's subject. Use those page titles directly with the REST API:
```
https://en.wikipedia.org/api/rest_v1/page/summary/<PAGE_TITLE>
```
→ take `originalimage.source` (or `thumbnail.source` if no original). This works in one call for the vast majority of facts. Only fall back to Commons search if the Wikipedia page has no image.

**When to leave `image.url` null (the ONLY valid cases):**
- Pure statistics/numbers with no visual subject (e.g. "X country has Y population")
- Linguistic/etymological facts about words
- Abstract legal or procedural facts
- Facts where every Wikipedia page for the subject genuinely has no image AND a targeted Commons search returns nothing

**Not valid reasons to blank:**
- "I couldn't think of what to search" — search the subject name from the fact text
- "The Wikipedia page exists but I didn't check for an image" — always check via REST API first
- "Multiple searches felt slow" — budget 2–3 lookups per fact, no more, no fewer

**Source priority:**
1. Wikipedia REST API for the subject's own page — `originalimage.source` preferred
2. Wikimedia Commons search — `https://commons.wikimedia.org/w/index.php?search=SUBJECT&ns6=1`
3. Unsplash — last resort, only for modern/abstract facts with no encyclopedic image
4. Blank — only when the four "ONLY valid cases" above apply

**Fields:**
```json
"image": { "url": "https://upload.wikimedia.org/...", "caption": "Subject, year or brief phrase" }
```
Caption ≤ 10 words.

## Step 3 — Links
**Prune** the existing Wikipedia links array using common sense. For each link ask: *"Would a reader curious about this fact actually want to follow this?"* If no, remove it.

**Remove date/year articles — unless the fact is specifically *about* that date/year/decade:**
- Year articles (`/wiki/1933`, `/wiki/1997`) — remove when the year is incidental context; keep if the fact is about the year itself (e.g. "1969 saw the first moon landing and Woodstock")
- Decade articles (`/wiki/1930s`) — same rule
- Month/day articles (`/wiki/August_16`, `/wiki/January_1`) — same rule

**Apply judgment — remove if the link adds nothing specific:**
- Generic units/concepts that anyone already knows: `Miles_per_hour`, `Kilometre`, `Color`, `Pond`, `Hill`
- Overly broad articles already covered by a more specific link in the same list (e.g. `Baseball` when `Christie_Pits_riot` is already there)
- Incidental geography where the place is background, not the subject
- Duplicates — keep the more specific one

**Always keep:**
- The primary subject of the fact
- Closely related concepts a curious reader would explore next
- Context that's non-obvious from the fact text itself

**Add 1–2 non-Wikipedia sources.** Search `britannica.com SUBJECT` first. Preferred: britannica.com → nationalgeographic.com → nasa.gov/noaa.gov → smithsonianmag.com → bbc.com → scientificamerican.com → history.com. Verify URLs exist. Skip if nothing good found after 2–3 searches.

Format:
```json
{ "url": "https://www.britannica.com/...", "title": "Subject — Britannica", "source": "Britannica" }
```

## Step 4 — Version
Set `"version": 2` on any fact you changed. Leave unchanged facts as-is.

## Step 5 — Write back
After each fact: write the **entire JSON file** back to disk (2-space indent). Preserve all fields exactly — only `tags`, `image`, `links`, `version` change.

## Step 6 — Manifest + push (after ALL facts done)
Update `/home/sarel/code/facts/data/manifest.json` for `{{MONTH_KEY}}`.

⚠️ **Structure warning:** The manifest has the shape `{"months": {"dyk_XXXX_YYY": {...}, ...}}`. The month entry lives **inside** the `months` object, NOT at the top level. Find the existing `{{MONTH_KEY}}` key already inside `months` and overwrite its value. Do NOT add a new key at the root of the JSON.

Target value:
```json
"{{MONTH_KEY}}": {
  "tags": true,
  "links": true,
  "tagged_facts": <count with ≥10 tags>,
  "linked_facts": <count with ≥1 non-wiki link>,
  "total_facts": <total>,
  "version": 2
}
```
`tags: true` only if ALL facts have ≥10 tags. `links: true` means pass is complete (some facts may still lack ext links if nothing found — that's fine).

**Verify after writing:** read the manifest back and confirm `months.{{MONTH_KEY}}.tags == true`. If it's still false, you wrote to the wrong location — fix it.

Then push:
```bash
cd /home/sarel/code/facts
git add data/{{MONTH_KEY}}.json data/manifest.json
git commit -m "enrich: {{MONTH_KEY}} — tags, images, links"
git pull --rebase origin main
git push origin main
```
If push fails, `git pull --rebase` and retry up to 3 times.

## Progress
Print after every 10 facts:
```
[10/76] tags: 10 | images: 8 found, 2 blank | ext links: 9
```
Final:
```
[done] {{MONTH_KEY}} — 76 facts | 76 tagged | 60 images, 16 blank | 70 ext links | pushed
```
