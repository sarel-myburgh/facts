# BokyLearn Facts Enrichment Coordinator

You are coordinating full enrichment of all unenriched facts files in the BokyLearn facts repository. You will spawn two parallel sub-agents that work through the file list simultaneously, each handling its own manifest updates and git pushes.

## Repository

`/home/sarel/code/facts/`

---

## Step 1 — Build the work list

Read `data/manifest.json`. Collect every month key where **either** `tags == false` **or** `links == false`:

```bash
cd /home/sarel/code/facts
jq -r '.months | to_entries[] | select(.value.tags == false or .value.links == false) | .key' data/manifest.json
```

Sort the result. This is your complete work list.

---

## Step 2 — Split between two agents

Divide the sorted work list into two halves:
- **Agent A** gets indices 0, 2, 4, 6, … (every even-indexed entry)
- **Agent B** gets indices 1, 3, 5, 7, … (every odd-indexed entry)

Interleaving (rather than splitting at the midpoint) ensures both agents work through the full date range rather than one doing all early years and one doing all late years. This avoids one agent finishing far earlier than the other.

---

## Step 3 — Spawn two parallel sub-agents

Spawn **Agent A** and **Agent B** simultaneously using the Agent tool. Each gets the enricher prompt below with its file list substituted.

### Sub-agent prompt template

> You are running the BokyLearn facts enricher. Read the full enricher instructions from `/home/sarel/code/facts/tools/enricher-agent.md`.
>
> Process the following files **in order**, one at a time. For each file:
> 1. Substitute `{{FILE}}` with the full path `data/<key>.json` and `{{MONTH_KEY}}` with `<key>`.
> 2. Complete all enrichment steps (tags → image → links → version → write back).
> 3. Update `manifest.json` and push to GitHub as described in Step 6 of the enricher instructions.
> 4. Only move to the next file after the current one is fully done and pushed.
>
> Your file list:
> ```
> [LIST OF MONTH KEYS FOR THIS AGENT]
> ```
>
> If a file is already fully enriched (all facts have version=2), skip it and move on.
> If a git push fails after 3 retries, log the failure and continue to the next file — do not stop.

---

## Step 4 — Monitor and report

After both agents complete, run a final validation:

```bash
cd /home/sarel/code/facts
jq '[.months | to_entries[] | select(.value.tags == false or .value.links == false)] | length' data/manifest.json
```

If the count is 0, all done. If not, list the remaining months and report why they were skipped.

Final report format:
```
Enrichment complete.
Months processed: 273
Remaining (skipped/failed): 0
Total facts tagged: ~
Total facts with ext links: ~
Manifest: up to date
GitHub: pushed
```

---

## Notes

- Both agents will occasionally push to the same `main` branch. Each is instructed to `git pull --rebase` before pushing, which handles concurrent pushes cleanly as long as they're touching different keys in `manifest.json`.
- If you see a git conflict that can't be auto-resolved, have the agent re-read the current `manifest.json`, re-apply its update for its month only, and push again.
- dyk_2004_Dec is already enriched — both agents should skip it automatically via the skip logic.
