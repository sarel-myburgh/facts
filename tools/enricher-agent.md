# Facts Enricher Agent

You are enriching a JSON file of educational facts for **BokyLearn** — a mobile app that replaces mindless social media scrolling with curiosity-driven learning. Users scroll a tweet-like feed of "Did You Know" facts, tap to expand into AI-generated deep-dives, and follow rabbit holes. **Tags are critical** — they drive the feed curation algorithm (user tag weights adjust based on likes/dislikes/exploration to surface more relevant content).

## Your file

`/home/sarel/code/facts/data/{{FILENAME}}`

## What to do

Read the full file. Process every fact in order, skipping any that are already fully enriched.

A fact is **fully enriched** when ALL three are true:
- `tags` has 10 or more entries
- `image.url` is not null
- `links` contains at least one entry whose URL does not contain `wikipedia.org`

**After completing each fact, immediately write the entire updated JSON back to the file** — so progress survives if you stop early.

---

## Operational notes from prior run

- Use webview/browser lookups directly for facts, images, and source pages.
- Do **not** use the OpenRouter/LLM script path for tags.
- Do **not** rely on guessed Wikimedia upload paths.
- For images, prefer a page summary `originalimage.source` or a Commons file page's direct "Original file" / upload URL.
- For additional links, a specific reputable article page is better than a homepage or generic topic page.
- Verify direct image and link URLs before writing them into the JSON.
- Keep the per-fact writeback behavior strict so partial progress is preserved.

---

## Step 1 — Tags

Generate exactly 10 tags for this fact. These are used by the app's feed ranking algorithm, so quality matters — bad tags mean bad recommendations.

Rules:
- Mix broad tags (`history`, `animals`, `science`, `music`) with specific ones (`emperor penguins`, `pokemon card game`, `2011 tōhoku earthquake`)
- All lowercase, no punctuation except hyphens
- 1–3 words each — concise and searchable
- Think about what a user who *liked* this fact would also enjoy seeing — tag for that audience
- Cover the main subject, the broader field, the era/region if relevant, and any crossover topics

Example for *"Solfrid Koanda qualified for her first weightlifting competition a few days after starting the sport"*:
`["weightlifting", "sports", "athletes", "women in sports", "olympics", "record breakers", "norway", "strength sports", "inspirational", "competition"]`

Set `fact.tags = [...]` with your 10 tags.

---

## Step 2 — Image

Find a real, publicly accessible image URL for this fact.

**Priority order:**

1. **Wikimedia Commons** — search the web for the subject + "wikimedia commons" or browse `https://commons.wikimedia.org/w/index.php?search=TOPIC&ns6=1`. Get a direct `https://upload.wikimedia.org/wikipedia/commons/...` URL. Verify it resolves.
2. **Wikipedia page thumbnail** — if the fact has a Wikipedia link, fetch `https://en.wikipedia.org/api/rest_v1/page/summary/PAGE_TITLE` and use `originalimage.source` or `thumbnail.source`.
3. **Unsplash** — last resort for facts where no encyclopedic image exists (very recent events, abstract concepts).

**Skip the image** (leave `image.url` null) only when the fact is genuinely unvisual — e.g. a pure linguistic curiosity, a legal ruling with no photographable subject. Most facts will have something. Use judgment.

Set `fact.image.url` to the direct image URL and `fact.image.caption` to a short descriptive label (subject name or brief phrase).

---

## Step 3 — Additional link

Add at least one link to a **reputable non-Wikipedia source** about this fact's subject. This appears on the fact card as "further reading."

**Preferred sources (roughly in order):**
- britannica.com
- nationalgeographic.com / natgeo.com
- nasa.gov / noaa.gov / esa.int
- smithsonianmag.com / si.edu
- bbc.com / bbc.co.uk
- nature.com / scientificamerican.com / science.org / newscientist.com
- pbs.org
- loc.gov (Library of Congress)
- nhm.ac.uk / metmuseum.org / amnh.org / britishmuseum.org
- iucnredlist.org
- history.com / historyextra.com / ancient.eu

**Strategy:** Search `britannica.com SUBJECT` or `site:britannica.com SUBJECT` to find a direct article. Verify the URL resolves before adding it. If Britannica has nothing, try the next source.

If you cannot find anything after 2–3 searches, leave `links` unchanged and move on.

Add to `fact.links`:
```json
{
  "url": "https://...",
  "title": "Descriptive title of the specific page",
  "source": "Britannica"
}
```

---

## JSON editing rules

- Read the full file once at the start
- After each fact, write the entire JSON back to the file (2-space indented, `ensure_ascii=False`)
- Preserve all existing fields exactly — only modify `tags`, `image`, and `links`
- Do not reorder facts or reformat unrelated fields

---

## Progress reporting

Print a one-line update after every 10 facts:
`[10/432] 8 images found, 9 extra links added`

Final summary when done:
`[done] 432 facts — 410 tag sets, 287 images, 398 extra links`
