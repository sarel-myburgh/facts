# BokyLearn Facts Enrichment Coordinator

Coordinate full enrichment of all unenriched files in `/home/sarel/code/facts/`.

## Step 1 — Build work list

```bash
cd /home/sarel/code/facts
jq -r '.months | to_entries[] | select(.value.tags == false or .value.links == false) | .key' data/manifest.json | sort
```

## Step 2 — Split between two agents

Divide the sorted list by interleaving:
- **Agent A**: indices 0, 2, 4, 6, … (even)
- **Agent B**: indices 1, 3, 5, 7, … (odd)

Interleaving spreads the date range evenly so neither agent finishes far earlier.

## Step 3 — Spawn two parallel Haiku sub-agents

Read the enricher prompt from `/home/sarel/code/facts/tools/enricher-agent-haiku.md`.

Spawn **Agent A** and **Agent B** simultaneously using the Agent tool with `model: "haiku"`. Each agent gets this prompt (substitute the file list):

> Read the full enricher instructions from `/home/sarel/code/facts/tools/enricher-agent-haiku.md`.
>
> Process these files **in order**, one at a time. For each file, substitute `{{FILE}}` with `data/<key>.json` and `{{MONTH_KEY}}` with `<key>`, then complete all enrichment steps. Update `manifest.json` and push after each file. Move to the next only when the current is fully done and pushed.
>
> If a file is already fully enriched (all facts version=2), skip it. If a git push fails 3 times, log and continue.
>
> Your file list:
> ```
> [LIST]
> ```

## Step 4 — Final validation

After both agents complete:
```bash
cd /home/sarel/code/facts
jq '[.months | to_entries[] | select(.value.tags == false or .value.links == false)] | length' data/manifest.json
```

Report:
```
Enrichment complete.
Months processed: X  |  Remaining: Y
```
If Y > 0, list which months remain and why.
