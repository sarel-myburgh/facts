# Facts Tags Coordinator

Find all untagged months and process them in parallel using Haiku sub-agents.

## Step 1 — Find untagged months

```bash
cd /home/sarel/facts
jq -r '.months | to_entries[] | select(.value.tags == false) | .key' data/manifest.json | sort
```

## Step 2 — Split into 3 lists (interleave)

Divide the sorted list by index:
- **Agent A**: indices 0, 3, 6, …
- **Agent B**: indices 1, 4, 7, …
- **Agent C**: indices 2, 5, 8, …

Interleaving spreads the date range so no agent finishes far ahead of others.

## Step 3 — Spawn sub-agents

Read the enricher from `/home/sarel/facts/tools/enricher-agent-haiku.md`.

Spawn **Agent A**, **Agent B**, and **Agent C** simultaneously using the Agent tool with `model: "haiku"`.

Each agent gets this prompt (substitute its month list):

> Read `/home/sarel/facts/tools/enricher-agent-haiku.md`.
>
> Process these months **in order**, one at a time. For each month substitute `{{MONTH_KEY}}` with the month key and run all steps. Move to the next only after the current is committed and pushed.
>
> If a month's `tags` field is already `true` in the manifest, skip it.
>
> Your months:
> ```
> [LIST]
> ```

## Step 4 — Final report

After all agents complete:

```bash
cd /home/sarel/facts
jq '[.months | to_entries[] | select(.value.tags == false)] | length' data/manifest.json
```

Report: `Tagging complete. Remaining untagged: N`

If N > 0, list the remaining months by name.
