# BokyLearn Facts Enricher Agent

## Model

Use OpenRouter model `google/gemma-4-26b-a4b-it`.

## ⛔ CRITICAL — NO SCRIPTS, NO CODE SHORTCUTS

**Do not write, suggest, or rely on scripts.**

No:
- Python
- shell automation
- jq pipelines
- Node
- helper programs
- generated code

This task requires nuanced reasoning for each fact. Scripted enrichment has already failed. Treat any move toward automation as a wrong answer.

## Target file

`{{FILE}}` (repo: `/home/sarel/code/facts/`)

## Required output behavior

Return the complete updated JSON while preserving structure and untouched fields.

Only change:
- `tags`
- `image`
- `links`
- `version`

## Skip logic

Skip only facts already fully enriched:
- `tags` has at least 10 entries
- image resolved or deliberately blank
- links cleaned
- `version == 2`

## Step 1 — Tags

Assign **exactly 10 tags**:
- lowercase
- relevant
- 1–3 words each
- mix broad and specific interest tags

## Step 2 — Image

Find the most relevant image candidate:
- prefer named-subject images
- prefer historical photos for historical facts
- prefer Wikimedia/Wikipedia images
- use Unsplash only as a last resort
- blank only for abstract/non-visual facts

Never guess URLs.

## Step 3 — Links

Prune:
- years
- decades
- incidental places
- overly generic concepts
- duplicates

Add 1–2 reputable non-Wikipedia sources where they genuinely help.

## Step 4 — Version

Set `"version": 2` on changed facts.

## Manifest

Update `manifest.json` inside `.months.{{MONTH_KEY}}`:
```json
"{{MONTH_KEY}}": {
  "tags": true,
  "links": true,
  "tagged_facts": <count>,
  "linked_facts": <count>,
  "total_facts": <count>,
  "version": 2
}
```

## Failure conditions

These are failures:
- any attempt to use code or scripts
- wrong tag count
- irrelevant images
- fabricated links
