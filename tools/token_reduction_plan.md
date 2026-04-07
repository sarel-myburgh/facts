# Token Reduction Plan for Fact Expansion

## Test Results (2026-04-07)

Model: `google/gemma-3-27b-it` via OpenRouter  
Fact: "The mantis shrimp can punch with the force of a bullet…"  
Web search: ON (current app behaviour)

| Bucket              | Tokens | % of total |
|---------------------|--------|------------|
| System prompt       |     71 |       1.7% |
| User prompt         |    117 |       2.7% |
| Web search results  |  3,750 |      87.4% |
| Completion (output) |    355 |       8.3% |
| **Total**           |  4,293 |     100.0% |

**Cost: $0.0204 (~2c) per expansion.**

---

## Root Cause

The OpenRouter web plugin fetches live search results and injects them into
the prompt *before* the model generates its response.  At 3,750 tokens of
retrieved context per call, web search is responsible for ~95% of the prompt
cost and ~87% of the total cost.

---

## Proposed Changes (in priority order)

### 1. Remove the `web` plugin from `expandFact` and `answerQuestion`

**Impact: eliminate ~$0.018 (~1.8c) per call → ~$0.002 total.**

The BokyLearn facts are already curated, sourced Wikipedia DYK / Today In
History.  The model does not need to search the internet to write 2–3
paragraphs expanding on a well-attested fact.  Hallucination risk is low
because:
- Facts are short and concrete (not opinions or breaking news).
- The model was trained on this data anyway.
- The article is clearly labelled AI-generated in the UI.

**Files to change:**
- `bokylearn/lib/data/remote/ai_client.dart`
  - `expandFact()`: change `_stream(prompt, useWebSearch: true)` →
    `_stream(prompt)` (remove the named arg, which defaults to false)
  - `answerQuestion()`: same change

The `useWebSearch` parameter and the `if (useWebSearch)` plugin/tool
injection blocks can remain in `_stream` / `_streamAnthropic` so the
capability is there if ever needed, but it will no longer be called by
default.

---

### 2. Keep `explainSelection` as-is (no web search already)

`explainSelection` already uses the default `useWebSearch: false` and is
capped at 150 tokens.  No changes needed.

---

### 3. Optional: trim the system prompt slightly

Current system prompt: ~71 tokens.  Could be reduced to ~40 tokens by
removing the explicit list of forbidden phrases (the model is unlikely to
use them anyway once told "no filler, no meta-commentary").

**Savings: ~30 tokens × volume = small but cumulative.**

Suggested shorter version:
```
You are a concise educational writer. Write only facts, mechanisms, history,
and context. Never editorialize, hype, or comment on how interesting a topic
is. Use plain prose — no markdown, no URLs.
```

---

### 4. Optional: reduce max_tokens from 700 → 500

The current output averages ~355 tokens.  Capping at 500 would cut the
worst-case tail cost by ~30% with minimal quality impact (articles just
slightly shorter).

**Savings: ~0.01c per call on average (minor), but prevents runaway costs
on edge-case verbose responses.**

---

## After Change 1: Expected Cost Per Call

| Bucket          | Tokens | Note              |
|-----------------|--------|-------------------|
| System prompt   |     71 |                   |
| User prompt     |    117 |                   |
| Completion      |    355 | avg unchanged     |
| **Total**       |    543 |                   |

At gemma-3-27b-it pricing (~$0.000004/token input, ~$0.000004/token output):
**~$0.0022 per expansion (~0.2c) — a 10× reduction.**

---

## What NOT to change

- Do not remove web search from `explainSelection` (already off).
- Do not change `_streamAnthropic` web search — Anthropic users who want
  grounded articles can keep it; cost structure is different there.
- Do not add aggressive output caching beyond what already exists in
  `article_cache` — the cache is already in place and works well.
