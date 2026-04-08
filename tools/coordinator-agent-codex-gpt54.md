# BokyLearn Facts Enrichment Coordinator

## Model

Use `gpt-5.4` via Codex for each spawned worker. Do not use mini.

Coordinate enrichment in `/home/sarel/code/facts/`.

## Step 1 — Build work list

```bash
cd /home/sarel/code/facts
jq -r '.months | to_entries[] | select(.value.tags == false or .value.links == false) | .key' data/manifest.json | sort
```

## Step 2 — Split between two agents

Interleave the sorted list:
- Agent A: even indices
- Agent B: odd indices

## Step 3 — Spawn two Codex sub-agents

Read `/home/sarel/code/facts/tools/enricher-agent-codex-gpt54.md`.

Each agent must:
- process files in order
- substitute `{{FILE}}` and `{{MONTH_KEY}}`
- finish one month before moving to the next
- update manifest and push after each file
- treat **any attempt to script the work** as disallowed

Prompt template:

> Read the full instructions from `/home/sarel/code/facts/tools/enricher-agent-codex-gpt54.md`.
>
> Process these files in order, one at a time. Complete all enrichment steps manually, fact by fact. Do not create scripts or helper automation. Update `manifest.json` and push after each file.
>
> File list:
> ```
> [LIST]
> ```

## Step 4 — Final validation

```bash
cd /home/sarel/code/facts
jq '[.months | to_entries[] | select(.value.tags == false or .value.links == false)] | length' data/manifest.json
```
