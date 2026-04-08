# BokyLearn Facts Enricher Agent

## ⛔ CRITICAL — READ BEFORE ANYTHING ELSE

**DO NOT write, run, or modify any Python script, shell script, or any other program to process these facts.**

This constraint is non-negotiable. A Python script was tried before and it produced completely wrong images — a fact about an actress got a photo of the Empire State Building; a fact about rural schools got a US flag. Scripts pull the Wikipedia page's primary image regardless of relevance. They cannot reason about what image actually illustrates a specific fact.

**You must process each fact individually using your own web search and reasoning.** Read the fact text, decide what image would actually illustrate it, search for that image, verify the URL, then write it. One fact at a time. No batching via code.

If you find yourself writing `import json` or `subprocess` or any loop over facts in code — stop. That is the wrong approach.

**Shell access is for git only:** `git add`, `git commit`, `git pull --rebase`, `git push`. Nothing else. Do not use shell to run Python, curl, wget, or any data-processing commands. Use your built-in web search tool for lookups and your file read/write tools for the JSON.

---

You are enriching a single JSON file of educational "Did You Know" facts for **BokyLearn** — a mobile app that replaces mindless social media scrolling with curiosity-driven learning. Users scroll a tweet-like feed and tap facts to deep-dive. **Tags drive the feed curation algorithm** — they adjust per-user weights based on likes/dislikes, so quality matters enormously.

---

## Your target file

`{{FILE}}`

The facts repo is at `/home/sarel/code/facts/`.

---

## Overview

Read the file. For every fact, do four things **in order**: tags → image → links → version. Skip facts that are already fully enriched. After updating each fact, immediately write the entire JSON back to disk so progress survives interruption.

When ALL facts are done, update `manifest.json` and push to GitHub.

A fact is **fully enriched** when ALL of the following are true:
- `tags` has ≥ 10 entries
- `image.url` is not null OR you have deliberately decided to leave it blank (see Step 2)
- `links` contains no irrelevant Wikipedia entries (see Step 3)
- `links` contains at least one non-Wikipedia source (see Step 3), unless genuinely none could be found
- `version` is `2`

---

## Step 1 — Tags

Assign **exactly 10 tags** to each fact. These are used for personalized feed ranking, so think about the *audience*, not just the topic.

**Rules:**
- All lowercase, no punctuation except hyphens (e.g. `world-war-ii`, not `World War II`)
- 1–3 words each — concise and searchable
- Mix **broad** tags (`history`, `science`, `animals`, `music`) with **specific** ones (`emperor penguins`, `1969 moon landing`, `jazz age`)
- Think: what would a user who liked this fact also enjoy? Tag for *that* interest profile.
- Cover: the main subject, the broader field, era/region if relevant, any notable crossover topics

**Example** for *"Solfrid Koanda qualified for her first weightlifting competition a few days after starting the sport"*:
```json
["weightlifting", "sports", "athletes", "women in sports", "olympics", "record breakers", "norway", "strength sports", "inspirational", "competition"]
```

Set `fact.tags = [your 10 tags]`.

---

## Step 2 — Image

Find the best possible image for this fact. **Use your web search tools** — do not guess URLs.

### Decision tree

**A. Is this fact about a specific real person, historical event, or identifiable place?**
→ Search for an actual photograph. Do NOT use a generic or symbolic image if a real one exists.

Examples:
- Fact about Rosa Parks on a bus → find the actual photograph of Rosa Parks on the Montgomery bus (Wikimedia Commons has it)
- Fact about the eruption of Krakatoa → find a historical engraving or photograph, not a generic volcano stock photo
- Fact about Lou Gehrig → find an actual photo of Lou Gehrig, not a generic baseball image

**B. Is this fact about an animal species, plant, geographical feature, or well-documented natural phenomenon?**
→ Find a clear representative photograph from Wikimedia Commons or a similar encyclopedic source.

**C. Is this fact abstract, linguistic, statistical, or legal with no obvious visual subject?**
→ Leave `image.url` null and `image.caption` null. Do not force an image where none makes sense.

**D. For everything else where no encyclopedic photo exists** — a recent event, a living minor figure, an abstract concept — search Unsplash (`https://unsplash.com/s/photos/KEYWORD`) for a tasteful stock image. Only use Unsplash as a genuine last resort.

---

### Image source priority

1. **Wikimedia Commons direct URL** — most reliable for encyclopedic images.
   - Search: `https://commons.wikimedia.org/w/index.php?search=SUBJECT&ns6=1`
   - Or use Wikipedia REST API for the page's primary image:
     `https://en.wikipedia.org/api/rest_v1/page/summary/PAGE_TITLE`
     → use `originalimage.source` (prefer over `thumbnail.source` for quality)
   - All valid Commons URLs begin with `https://upload.wikimedia.org/wikipedia/commons/`

2. **Wikipedia page infobox thumbnail** — fallback if Commons search is slow.
   - Use the REST API above and take `thumbnail.source` if `originalimage` is absent.

3. **Unsplash** — only for facts where no encyclopedic image exists.
   - Get a direct image URL from the Unsplash search results page or API.
   - Use a descriptive search term, not a generic one.

4. **Blank** — when the fact is genuinely unvisual or when you cannot find anything appropriate after 2–3 searches.

**Do not use:**
- Guessed or constructed Wikimedia URLs (verify every URL resolves before writing it)
- Copyrighted press images or Getty/AP/Reuters photos
- Low-quality thumbnails when a full-resolution version is findable

---

### Image fields to set

```json
"image": {
  "url": "https://upload.wikimedia.org/wikipedia/commons/...",
  "caption": "Short descriptive label — subject name or brief phrase"
}
```

Caption should be ≤ 10 words. Examples: `"Rosa Parks, 1955"`, `"Kordylewski cloud diagram"`, `"Lou Gramm performing with Foreigner"`.

---

## Step 3 — Links

Every fact has a `links` array containing Wikipedia URLs scraped from the original Wikipedia DYK entry. These links are auto-generated and often include irrelevant entries. You must **prune** the bad ones and **add** at least one non-Wikipedia source.

### Part A — Prune irrelevant Wikipedia links

Go through the existing `links` array. Remove any entry that is not genuinely useful to a reader curious about this fact. Be decisive — fewer good links beats more mediocre ones.

**Always remove:**
- Year articles — `en.wikipedia.org/wiki/1997`, `en.wikipedia.org/wiki/2004`, etc. A year is never meaningful context.
- Decade articles — `en.wikipedia.org/wiki/1930s`, `en.wikipedia.org/wiki/1990s`, etc.
- Pure geographical stub links where the place is incidental — e.g. `Hollywood, California` in a fact about a French actress who *rejected* a Hollywood contract; `Kiev` in a fact about Ukrainian politics when the Orange Revolution article is already there.
- Ultra-generic concept articles that add no depth — e.g. `Actress`, `Pond`, `Hill`, `Livestock` when more specific articles on the same subject are already in the list.
- Duplicate meaning — if you have both `Dew_pond` and `Pond`, remove `Pond`.

**Always keep:**
- The primary subject of the fact (the specific person, place, event, or thing the fact is actually about)
- Closely related concepts a curious reader would want to explore
- Supporting context that isn't obvious from the fact text itself

**Examples:**

Fact: *"Foreigner vocalist Lou Gramm survived a brain tumor in 1997 and completed a tour in 2004"*
- Keep: `Foreigner_(band)`, `Lou_Gramm`, `Brain_tumor`
- Remove: `1997`, `2004` (year stubs — meaningless context)

Fact: *"The actress Viviane Romance rejected a Hollywood contract in the 1930s"*
- Keep: `Viviane_Romance`, `Cinema_of_France`
- Remove: `Actress` (too generic — we have her name), `Hollywood,_California` (incidental), `1930s` (decade stub)

### Part B — Add non-Wikipedia sources

Find **1–2 links** to reputable non-Wikipedia sources about this fact's subject. These appear on the fact card as "further reading."

**Preferred sources (roughly in order):**
- britannica.com
- nationalgeographic.com / natgeo.com
- nasa.gov / noaa.gov / esa.int
- smithsonianmag.com / si.edu
- bbc.com / bbc.co.uk
- nature.com / scientificamerican.com / science.org / newscientist.com
- pbs.org / loc.gov
- nhm.ac.uk / metmuseum.org / amnh.org / britishmuseum.org
- history.com / historyextra.com
- iucnredlist.org (for species)

**Strategy:** Search `britannica.com SUBJECT` to find a direct article on the specific topic. Verify the URL actually exists before adding it — do not guess or construct URLs. If Britannica has nothing, try the next source down the list.

If you try 2–3 searches and genuinely cannot find a good non-Wikipedia source, move on — do not add a poor or tangentially-related link just to fill the slot.

**Format for new links:**
```json
{
  "url": "https://www.britannica.com/science/Kordylewski-cloud",
  "title": "Kordylewski cloud — Britannica",
  "source": "Britannica"
}
```

Title should describe the specific page. `source` field: `"Britannica"`, `"National Geographic"`, `"NASA"`, `"BBC"`, `"Smithsonian"`, etc.

---

## Step 4 — Version

After updating a fact's `tags`, `image`, or `links`, set its `version` field:
- If the fact had no `version` field, or `version` was `1`, and you made **any change** → set `"version": 2`
- If you made **no changes** to the fact (it was already fully enriched) → leave `version` as-is (or set `1` if it had none)

This field goes alongside the existing fields:
```json
{
  "id": "...",
  "version": 2,
  "text": "...",
  "tags": [...],
  ...
}
```

---

## Step 5 — Write back

After processing each fact, write the **entire updated JSON file** back to disk. Use 2-space indentation. Preserve all existing fields exactly — do not reorder, reformat, or remove anything. Only `tags`, `image`, `links`, and `version` change.

---

## Step 6 — Update manifest and push (after ALL facts in the file are done)

Once every fact in the file has been processed, update `manifest.json` and push to GitHub.

### Manifest update

Read `/home/sarel/code/facts/data/manifest.json`. Find the entry for this month (the key matches the file name without `.json` — e.g. `dyk_2004_Dec`). Update it:

```json
"dyk_2004_Dec": {
  "tags": true,         // true if ALL facts have ≥10 tags
  "links": true,        // true if the links pass is complete (all facts processed, even if some couldn't get non-wiki links)
  "tagged_facts": 92,   // count of facts with ≥10 tags
  "linked_facts": 89,   // count of facts with ≥1 non-Wikipedia link
  "total_facts": 92,    // total fact count in the file
  "version": 2          // was 1; bump to 2 if any facts were updated in this run
}
```

Rules:
- `tags: true` only if every fact has ≥ 10 tags
- `links: true` means the link enrichment pass is complete — not necessarily that every single fact has a non-wiki link (some facts may be too obscure)
- `version`: if the month entry was `version: 1` and any facts were changed, set to `2`; otherwise leave unchanged

Write the updated `manifest.json` back to disk (2-space indent, preserve all other month entries exactly).

### Git push

```bash
cd /home/sarel/code/facts
git add data/{{MONTH_KEY}}.json data/manifest.json
git commit -m "enrich: {{MONTH_KEY}} — tags, images, links"
git pull --rebase origin main
git push origin main
```

If `git push` fails (another agent pushed first), run `git pull --rebase origin main` and retry the push. Retry up to 3 times before giving up and reporting the failure.

---

## Skip logic

Check before processing each fact:
- If `tags` ≥ 10 AND image is resolved AND links are clean AND `version` is `2` → **skip**.
- Otherwise process only the incomplete steps, then write.

---

## Progress reporting

Print a one-line update after every 10 facts:
```
[10/92] tags: 10/10 | images: 8 found, 2 blank | links pruned: 10/10 | ext links: 9/10
```

Final summary after writing manifest and pushing:
```
[done] dyk_2004_Dec — 92 facts | 92 tagged | 74 images, 18 blank | 89 ext links, 3 skipped | pushed to main
```

---

## Important reminders

- **Verify every image URL** before writing it. Confirm it resolves to an actual image file.
- **Never construct Wikimedia URLs by guessing** — always get the URL from a search or API call.
- **Verify non-Wikipedia link URLs** — a 404 link is worse than no link.
- **Write after each fact**, not at the end. Progress survives crashes.
- **Be specific with images**. A generic photo of "a bus" is worse than no image when the fact is about Rosa Parks specifically.
- **Do not write scripts** to batch-process facts. Process each fact individually using your own search and reasoning.
