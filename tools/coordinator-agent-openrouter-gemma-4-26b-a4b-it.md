# BokyLearn Facts Enrichment Coordinator

## Model

Use OpenRouter model `google/gemma-4-26b-a4b-it`.

Coordinate enrichment by assigning one month at a time to the model prompt in `/home/sarel/code/facts/tools/enricher-agent-openrouter-gemma-4-26b-a4b-it.md`.

Before running, substitute:
- `{{FILE}}` with `data/<month>.json`
- `{{MONTH_KEY}}` with `<month>`

Hard rule: the model must not create or propose scripts or automation. Any such output is disqualifying.
