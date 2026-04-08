# BokyLearn Facts Enricher Agent

## Model

Use `gpt-5.4` via Codex. Do not switch to a mini model.

## ⛔ CRITICAL — NO SCRIPTS, NO SHORTCUT AUTOMATION

**Do not write, run, edit, or rely on any Python script, shell script, jq loop, Node script, Go program, or any other automation to process these facts.**

This is a hard requirement. Previous script-based attempts produced irrelevant images and weak links because scripts cannot reason about nuance at the fact level. This task must be done **fact by fact**, using judgment.

If you start thinking about `python`, `jq`, `for` loops over facts, `curl`, or batch-processing helpers, stop. That is failure, not optimization.

**Permitted tooling:**
- File read/write tools for the JSON files
- Built-in web search / browsing tools for image and source discovery
- Shell for git only: `git add`, `git commit`, `git pull --rebase`, `git push`

**Forbidden uses of shell:**
- No Python
- No `jq` transforms for enrichment
- No `curl` / `wget`
- No scraping helpers
- No generated helper scripts

Processing facts manually with reasoning is the task.

## Target file

`{{FILE}}` (repo: `/home/sarel/code/facts/`)

## Skip logic

A fact is done when all of the following are true:
- `tags` has at least 10 entries
- image is resolved, or deliberately blank for a valid reason
- `links` are pruned and contain at least one non-Wikipedia source when a good one exists
- `version == 2`

If all are true, skip that fact entirely.

## Step 1 — Tags

Assign **exactly 10 tags**.

Rules:
- lowercase only
- hyphens allowed; avoid other punctuation
- 1–3 words each
- mix broad and specific tags
- optimize for user-interest overlap, not just literal topic matching
- cover subject, field, era/region where relevant, and crossover interests

## Step 2 — Image

Use web search. Never guess URLs.

Default: find an image. Blank is a last resort.

Preferred flow:
1. Check the fact's subject Wikipedia page via REST summary API
2. Use `originalimage.source` if present
3. Fall back to Wikimedia Commons search
4. Use Unsplash only when no encyclopedic image exists
5. Leave blank only for genuinely abstract or non-visual facts

Good image behavior:
- named person: actual photo of that person
- named event: actual event image or historically relevant depiction
- place/building/species/artwork: direct image of the subject
- abstract/statistical/legal/etymological fact: blank when appropriate

Set:
```json
"image": { "url": "https://...", "caption": "short label" }
```

Caption must be 10 words or fewer.

## Step 3 — Links

Prune weak Wikipedia links aggressively.

Remove:
- year pages
- decade pages
- incidental geography
- generic concept pages when a more specific page already exists
- duplicates

Keep:
- primary subject
- directly useful related concepts
- context a curious reader would genuinely follow

Add 1–2 non-Wikipedia links where possible.

Preferred sources:
- Britannica
- National Geographic
- NASA / NOAA / ESA
- Smithsonian
- BBC
- Scientific American / Nature / Science.org
- PBS / LOC / museum sources
- History.com / History Extra

Verify URLs before writing them.

Format:
```json
{ "url": "https://...", "title": "Specific page title", "source": "Britannica" }
```

## Step 4 — Version

If you changed `tags`, `image`, or `links`, set `"version": 2`.

If no changes were needed, leave the version as-is.

## Step 5 — Write back

After each fact, write the **entire JSON file** back to disk with 2-space indentation.

Preserve everything except:
- `tags`
- `image`
- `links`
- `version`

## Step 6 — Manifest + push

After all facts are processed, update `/home/sarel/code/facts/data/manifest.json` for `{{MONTH_KEY}}` under `.months`.

Target shape:
```json
"{{MONTH_KEY}}": {
  "tags": true,
  "links": true,
  "tagged_facts": <count with at least 10 tags>,
  "linked_facts": <count with at least one non-Wikipedia link>,
  "total_facts": <total>,
  "version": 2
}
```

Then push:
```bash
cd /home/sarel/code/facts
git add data/{{MONTH_KEY}}.json data/manifest.json
git commit -m "enrich: {{MONTH_KEY}} — tags, images, links"
git pull --rebase origin main
git push origin main
```

Retry push up to 3 times if needed.

## Failure conditions

These count as failure:
- writing any script or helper program
- batch-processing facts through code
- guessed image URLs
- hallucinated external links
- generic or irrelevant images when a specific subject image exists
- fewer or more than 10 tags
