# Running the Enrichment Agents

Two agents live in this directory:

| File | Purpose |
|------|---------|
| `enricher-agent.md` | Enriches a **single** JSON file — tags + images |
| `coordinator-agent.md` | Reads the manifest and spawns parallel enricher agents for all unprocessed files |

No Python scripts. Each agent uses its own web search and file tools to do the work.

---

## Option A — Process one file (Claude Code)

```bash
# From /home/sarel/code/facts/
FILE=data/dyk_2025_Jan.json
claude --print -p "$(sed "s|{{FILE}}|$(pwd)/$FILE|" tools/enricher-agent.md)"
```

Or interactively — paste the enricher prompt into a Claude Code session with `{{FILE}}` replaced:

```bash
FILE=data/dyk_2025_Jan.json
sed "s|{{FILE}}|$(pwd)/$FILE|" tools/enricher-agent.md | pbcopy  # copy to clipboard
```

Then open a Claude Code session and paste.

---

## Option B — Process all files (Claude Code coordinator)

This spawns parallel sub-agents for every unprocessed month in the manifest.

```bash
# From /home/sarel/code/facts/
claude --print -p "$(cat tools/coordinator-agent.md)"
```

The coordinator reads the manifest, batches 5 files at a time, and updates the manifest when done.

---

## Option C — Gemini CLI (single file)

```bash
FILE=data/dyk_2025_Jan.json
PROMPT=$(sed "s|{{FILE}}|$(pwd)/$FILE|" tools/enricher-agent.md)
gemini -p "$PROMPT"
```

Gemini has a 1M token context window — good for large files. It also has live web search built in.

---

## Option D — Codex (single file)

```bash
FILE=data/dyk_2025_Jan.json
PROMPT=$(sed "s|{{FILE}}|$(pwd)/$FILE|" tools/enricher-agent.md)
codex "$PROMPT"
```

---

## Option E — OpenRouter via or-agent

Use for quick tagging passes on small files. Note: or-agent doesn't have web search or file tools, so image finding won't work. Tags only.

```bash
FILE=data/dyk_2025_Jan.json
cat "$FILE" | or-agent general "$(cat tools/enricher-agent.md | sed 's|{{FILE}}||') Read the JSON from stdin. Output only the updated JSON."
```

---

## Checking progress

```bash
# Count how many months still need tagging
jq '[.months | to_entries[] | select(.value.tags == false)] | length' data/manifest.json

# Count total untagged facts across all files
jq '[.months | to_entries[] | select(.value.tags == false) | .value.total_facts] | add' data/manifest.json

# Which files are done
jq '.months | to_entries[] | select(.value.tags == true) | .key' data/manifest.json
```

---

## File format reminder

Each fact in a monthly JSON has:

```json
{
  "id": "dyk_2025_Jan_abc123",
  "text": "...",
  "tags": [],                         ← fill with 10+ tags
  "image": { "url": null, "caption": null },   ← fill with direct image URL + caption
  "links": [...]
}
```

The enricher only modifies `tags` and `image`. All other fields are preserved exactly.
