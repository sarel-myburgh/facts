# BokyLearn Facts Collection Prompt

Use this prompt with Claude Code or Gemini CLI to refresh `data/facts.json`.

---

## Instructions

You are building a database of short, engaging facts for an educational app called BokyLearn.

### Step 1 — Browse the sites

Visit each of the following sites and explore them fully. Do not limit yourself to specific pages — navigate through all categories, sections, and article types you find (e.g. category pages, "Today in History", "Daily Facts", listicles, individual fact articles, etc.). Follow internal links to discover as much content as possible.

**Sites to browse:**
- https://www.thefactsite.com
- https://www.factretriever.com
- https://www.rd.com (Reader's Digest — focus on facts, trivia, and "did you know" content)

For each site, start from the homepage or sitemap to discover all available sections before diving in.

### Step 2 — Collect facts

From every page you visit, extract individual facts. A valid fact is:
- A single standalone piece of information (not an instruction, opinion, or list heading)
- Between 1–3 sentences
- Interesting, surprising, or curiosity-sparking
- Factually verifiable (not vague or speculative)

Rewrite each fact into a clean, consistent **tweet-like style**: punchy, direct, present tense where natural, no filler phrases like "Did you know that..." or "It is interesting to note that...". Keep it to 1–2 sentences maximum.

### Step 3 — Tag each fact

Assign one or more tags to each fact based on its content. Use your own judgment — there is no fixed taxonomy. Guidelines:
- Tags should be lowercase with underscores (e.g. `deep_sea`, `ancient_rome`, `human_body`)
- Be specific enough to be useful for filtering (e.g. prefer `ancient_egypt` over just `history`)
- A fact can have multiple tags (e.g. `["animals", "deep_sea", "bioluminescence"]`)
- Be consistent — reuse existing tags where appropriate rather than inventing new ones for every fact

### Step 4 — Semantic deduplication

Read the existing `data/facts.json` file before adding anything.

Do not add a fact if:
- The same fact already exists (exact or near-exact wording)
- A fact covering the same specific piece of information already exists, even if worded differently (e.g. "Octopuses have 3 hearts" and "An octopus has three hearts" are the same fact)

### Step 5 — Find a reliable "read more" link

For each fact, find a reliable external URL where the user can read further about the specific topic of that fact. This is not the site you scraped the fact from — it should be a trustworthy, in-depth source such as Wikipedia, Britannica, National Geographic, Science Daily, NASA, Smithsonian, or similar. The link should be as specific as possible (e.g. the Wikipedia article for "Octopus", not the Wikipedia homepage).

Preferred sources in order:
1. Wikipedia (most facts will have a relevant article)
2. Britannica
3. National Geographic
4. NASA (for space/science facts)
5. Smithsonian Magazine
6. Science Daily
7. Any other credible, well-known publication

### Step 6 — Find an image

For each fact, try to find one appropriate, factually relevant image. Rules:

- **Prefer specific over generic.** A fact about the first webcam should link to an actual photo of that webcam, not a generic "technology" stock photo. A fact about the Eiffel Tower should link to a real photo of it.
- **Preferred image sources** (in order):
  1. Wikimedia Commons — use the direct file URL (e.g. `https://upload.wikimedia.org/wikipedia/commons/...`)
  2. Wikipedia article images (same CDN)
  3. NASA Image Gallery (for space facts)
  4. Smithsonian Open Access
  5. The MET Museum Open Collection
  6. Unsplash — only for generic facts where no specific image exists (e.g. a general fact about sleep)
- **If no appropriate image exists, omit the field entirely.** Do not force a generic stock photo onto a specific fact.
- **Images must be appropriate for all ages** — no graphic, violent, or sexual imagery.
- Include the image credit/caption (photographer or source name) so it can be displayed in the app.

### Step 7 — Flag mature content

Mark any fact as `"mature": true` if it involves:
- Sexual content, anatomy in a sexual context, or adult themes
- Graphic violence or gore
- Drug use presented non-clinically

All other facts should be `"mature": false`.

### Step 8 — Output

Append only new, non-duplicate facts to `data/facts.json`. Each entry must follow this schema exactly:

```json
{
  "id": "<uuid-v4>",
  "text": "The rewritten tweet-like fact.",
  "tags": ["tag_one", "tag_two"],
  "read_more_url": "https://en.wikipedia.org/wiki/Octopus",
  "read_more_source": "Wikipedia",
  "credit": "The Fact Site",
  "image": {
    "url": "https://upload.wikimedia.org/wikipedia/commons/...",
    "source": "Wikimedia Commons",
    "caption": "A common octopus (Octopus vulgaris)"
  },
  "mature": false,
  "scraped_at": "<YYYY-MM-DD of today>"
}
```

- `read_more_url` / `read_more_source` — reliable further reading link and its display name
- `credit` — site the fact was scraped from; shown as small attribution tooltip in the app only
- `image` — omit this field entirely if no appropriate image was found (do not set to null)
- `image.url` — direct link to the image file
- `image.source` — display name of the image source (e.g. `"Wikimedia Commons"`, `"NASA"`, `"Unsplash"`)
- `image.caption` — short descriptive caption shown under the image in the app
- `mature` — `true` if the fact involves sexual, graphic, or adult content; `false` otherwise

---

## Running this prompt

### Claude Code
```
claude "$(cat prompt.md)"
```
Or open Claude Code, paste the contents of this file, and run it.

### Gemini CLI
```
gemini -p "$(cat prompt.md)"
```

---

## Notes
- Run this whenever you want to refresh the facts database (weekly, monthly, or on demand)
- The more sites you add to the list above, the richer the database becomes
- You can add new sites to the list at any time — just paste in the URL and re-run
