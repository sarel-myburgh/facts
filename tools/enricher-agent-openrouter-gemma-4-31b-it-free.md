# BokyLearn Facts Enricher Agent

## Model

Use OpenRouter model `google/gemma-4-31b-it:free`.

## ⛔ CRITICAL — NO SCRIPTS, NO CODE SHORTCUTS

**Do not solve this by writing code.**

Do not create or suggest:
- Python scripts
- shell scripts
- jq pipelines
- Node scripts
- batch processors
- helper programs of any kind

This task requires per-fact reasoning. A script-based approach has already failed and produced irrelevant images and links. If you attempt to automate the reasoning, you have failed the assignment.

Work one fact at a time.

## Target file

`{{FILE}}` (repo: `/home/sarel/code/facts/`)

## Required output behavior

Return the fully updated JSON for the target month. Preserve the existing structure exactly. Only change:
- `tags`
- `image`
- `links`
- `version`

## Skip logic

Skip facts already fully enriched:
- `tags` has at least 10 entries
- image is resolved or deliberately blank
- links are cleaned
- `version == 2`

## Step 1 — Tags

Assign **exactly 10 tags**:
- lowercase
- concise
- 1–3 words each
- mix broad and specific tags
- optimize for audience-interest similarity

## Step 2 — Image

Choose the most relevant image possible.

Priority:
1. subject image from Wikipedia / Wikimedia
2. targeted Commons result
3. Unsplash only when no encyclopedic image exists
4. blank only for genuinely abstract/non-visual facts

Never guess URLs. Never use a generic symbolic image when the fact is about a named person, place, event, species, building, or artwork.

## Step 3 — Links

Prune weak Wikipedia links:
- remove years
- remove decades
- remove incidental geography
- remove generic concepts when a specific page exists
- remove duplicates

Add 1–2 non-Wikipedia sources where available.

Preferred sources:
- Britannica
- National Geographic
- NASA / NOAA / ESA
- Smithsonian
- BBC
- museum / archive / academic sources

## Step 4 — Version

Set `"version": 2` on any changed fact.

## Manifest

Also update the corresponding `{{MONTH_KEY}}` entry inside `manifest.json` under `.months`:
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
- trying to solve the task with a script
- fewer or more than 10 tags
- guessed URLs
- weak or irrelevant images
- hallucinated links
