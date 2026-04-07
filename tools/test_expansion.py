#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_expansion.py -- Token usage diagnostic for fact expansion.

Sends the exact same request that BokyLearn's ai_client.dart sends for
expandFact(), logs the full request + response, and reports token counts.

One test only -- no loops.

Usage:
    python tools/test_expansion.py
"""

import json
import sys
import time
import requests

# Force UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---- Config -----------------------------------------------------------------

API_KEY  = "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"
MODEL    = "google/gemma-4-26b-a4b-it"   # Gemma 4 26B on OpenRouter
BASE_URL = "https://openrouter.ai/api/v1"

# Mirrors the system prompt in ai_client.dart _streamOpenRouter()
SYSTEM_PROMPT = (
    "You are a concise educational writer. Write only facts, mechanisms, history, and context. "
    "Never use filler, hype, or meta-commentary. "
    "Forbidden phrases include: \"it's worth noting\", \"this is remarkable\", \"surprisingly\", "
    "\"this isn't hyperbole\", \"it's fascinating\", \"one might wonder\", \"needless to say\", "
    "and any sentence that comments on how interesting the topic is rather than stating facts."
)

# A representative sample fact + tags (mirrors a real feed card)
SAMPLE_FACT = (
    "The mantis shrimp can punch with the force of a bullet, "
    "striking prey at 23 metres per second."
)
SAMPLE_TAGS = ["animals", "marine_biology", "physics", "deep_sea"]

# Mirrors expandFact() prompt construction in ai_client.dart
def build_user_prompt(fact_text, tags):
    tag_context = " (topics: {})".format(", ".join(tags)) if tags else ""
    return (
        'Expand on this fact{}: "{}"\n\n'
        "Write 2-3 short paragraphs. Each paragraph is 2-4 sentences. "
        "Only include facts, mechanisms, context, or history. "
        "Do not editorialize, hype, or comment on how interesting the topic is. "
        "Start the first paragraph immediately -- no intro sentence restating the fact.\n\n"
        "After the article, write exactly:\n"
        "QUESTIONS:\n"
        "1. [follow-up question]\n"
        "2. [follow-up question]\n"
        "3. [follow-up question]\n\n"
        "Questions should be specific and lead somewhere surprising."
    ).format(tag_context, fact_text)


def run_test(with_web_search):
    user_prompt = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS)

    body = {
        "model": MODEL,
        "stream": False,          # Non-streaming so usage is returned directly
        "max_tokens": 700,
        "provider": {
            "order": ["Together", "Fireworks", "DeepInfra"],
            "allow_fallbacks": True,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
    }

    if with_web_search:
        body["plugins"] = [{"id": "web"}]

    headers = {
        "Authorization": "Bearer {}".format(API_KEY),
        "Content-Type":  "application/json",
        "X-OpenRouter-Include-Usage": "true",
    }

    sep = "=" * 70
    print("\n{}".format(sep))
    print("TEST: web_search={}  model={}".format("ON" if with_web_search else "OFF", MODEL))
    print(sep)

    print("\n--- REQUEST BODY ---")
    print(json.dumps(body, indent=2, ensure_ascii=False))

    t0 = time.time()
    response = requests.post(
        "{}/chat/completions".format(BASE_URL),
        headers=headers,
        json=body,
        timeout=120,
    )
    elapsed = time.time() - t0

    print("\n--- HTTP STATUS: {}  ({:.1f}s) ---".format(response.status_code, elapsed))

    if response.status_code != 200:
        print("ERROR BODY:")
        print(response.text)
        return {"error": response.text}

    data = response.json()

    print("\n--- FULL RESPONSE JSON ---")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    # Extract token counts
    usage = data.get("usage", {})
    prompt_tokens     = usage.get("prompt_tokens", "?")
    completion_tokens = usage.get("completion_tokens", "?")
    total_tokens      = usage.get("total_tokens", "?")

    # Try to get cost from OpenRouter's usage extension
    cost_usd = usage.get("cost", None)

    print("\n--- TOKEN SUMMARY ---")
    print("  Prompt tokens:     {}".format(prompt_tokens))
    print("  Completion tokens: {}".format(completion_tokens))
    print("  Total tokens:      {}".format(total_tokens))
    if cost_usd is not None:
        print("  Cost (USD):        ${:.6f}  (~{:.4f}c)".format(cost_usd, cost_usd * 100))
    else:
        print("  Cost:              not reported by this endpoint")

    # Breakdown of where prompt tokens come from
    system_words = len(SYSTEM_PROMPT.split())
    user_words   = len(user_prompt.split())
    print("\n--- WHERE PROMPT TOKENS COME FROM (approx) ---")
    print("  System prompt words: {}  (~{} tokens)".format(system_words, int(system_words * 1.3)))
    print("  User prompt words:   {}  (~{} tokens)".format(user_words, int(user_words * 1.3)))
    if with_web_search and isinstance(prompt_tokens, int):
        base_estimate = int((system_words + user_words) * 1.3)
        overhead = prompt_tokens - base_estimate
        print("  Web search overhead: ~{} tokens (injected search results)".format(max(0, overhead)))

    # Extract and display the generated text
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        print("\n--- GENERATED TEXT ({} chars) ---".format(len(content)))
        print(content)

    print()

    return {
        "with_web_search":   with_web_search,
        "prompt_tokens":     prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens":      total_tokens,
        "cost_usd":          cost_usd,
        "elapsed_s":         round(elapsed, 1),
    }


def main():
    print("BokyLearn -- Fact Expansion Token Usage Test")
    print("One test: web search ON (current app behaviour)")

    result = run_test(with_web_search=True)

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(json.dumps(result, indent=2))
    print()
    print("Review the FULL RESPONSE JSON and TOKEN SUMMARY above.")
    print("The token_reduction_plan.md in this directory has the next steps.")


if __name__ == "__main__":
    main()
