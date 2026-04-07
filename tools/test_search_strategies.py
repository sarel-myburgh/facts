#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_search_strategies.py -- Compare web-search token reduction strategies.

Tests 4 strategies (+ combinations) for injecting context into fact expansions,
measuring prompt tokens, total cost, and output quality (printed for review).

Strategies:
  A. No context              -- baseline, no web lookup at all
  B. OR web max_results=1    -- OpenRouter web plugin, 1 result
  C. OR web max_results=2    -- OpenRouter web plugin, 2 results (current default is unlimited)
  D. Wiki summary 700        -- Wikipedia REST API summary, truncated to 700 chars
  E. Wiki summary 500        -- Wikipedia REST API summary, truncated to 500 chars
  F. Wiki summary 300        -- Wikipedia REST API summary, truncated to 300 chars
  G. Simple Wiki 500         -- simple.wikipedia.org summary, truncated to 500 chars
  H. Simple Wiki 300         -- simple.wikipedia.org summary, truncated to 300 chars
  I. Combo: wiki 500 + OR web=1   -- manual context + limited search
  J. Combo: simple 300 + OR web=1 -- simple summary + limited search

Run: python tools/test_search_strategies.py
"""

import json
import sys
import time
import re
import io
import urllib.parse
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ---- Config -----------------------------------------------------------------

API_KEY  = "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"
MODEL    = "google/gemma-4-26b-a4b-it"
BASE_URL = "https://openrouter.ai/api/v1"

SYSTEM_PROMPT = (
    "You are a concise educational writer. Write only facts, mechanisms, history, and context. "
    "Never use filler, hype, or meta-commentary. "
    "Do not include any URLs or markdown formatting - plain prose only. "
    "Forbidden phrases: \"it's worth noting\", \"this is remarkable\", \"surprisingly\", "
    "\"it's fascinating\", \"one might wonder\", \"needless to say\", and any sentence "
    "that comments on how interesting the topic is."
)

# Test fact with its scraped Wikipedia links (real data from dyk_2025_Apr.json)
SAMPLE_FACT  = "A village in North Sulawesi traces its founding to exiles from the Java War"
SAMPLE_TAGS  = ["history", "indonesia", "java_war", "sulawesi"]
SAMPLE_LINKS = [
    "https://en.wikipedia.org/wiki/Kampung_Jawa,_Minahasa",
    "https://en.wikipedia.org/wiki/Java_War",
]

WIKI_HEADERS = {"User-Agent": "BokyLearnTest/1.0 (educational app research)"}

# ---- Helpers ----------------------------------------------------------------

def build_user_prompt(fact_text, tags, extra_context=""):
    tag_context = " (topics: {})".format(", ".join(tags)) if tags else ""
    context_block = ""
    if extra_context:
        context_block = (
            "\n\nBackground context for your reference:\n"
            "---\n{}\n---\n".format(extra_context.strip())
        )
    return (
        'Expand on this fact{}: "{}"{}\n\n'
        "Write 2-3 short paragraphs. Each paragraph is 2-4 sentences. "
        "Only include facts, mechanisms, context, or history. "
        "Do not editorialize or comment on how interesting the topic is. "
        "Start the first paragraph immediately.\n\n"
        "After the article, write exactly:\n"
        "QUESTIONS:\n"
        "1. [follow-up question]\n"
        "2. [follow-up question]\n"
        "3. [follow-up question]\n\n"
        "Questions should be specific and lead somewhere surprising."
    ).format(tag_context, fact_text, context_block)


def fetch_wiki_summary(wiki_url, use_simple=False):
    """Fetch the plain-text extract from Wikipedia REST summary API."""
    m = re.search(r"wikipedia\.org/wiki/(.+)$", wiki_url)
    if not m:
        return None
    title = urllib.parse.unquote(m.group(1))
    host  = "simple.wikipedia.org" if use_simple else "en.wikipedia.org"
    url   = "https://{}/api/rest_v1/page/summary/{}".format(
        host, urllib.parse.quote(title.replace(" ", "_"), safe=":/")
    )
    try:
        r = requests.get(url, headers=WIKI_HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json().get("extract", "")
        elif use_simple and r.status_code == 404:
            # Simple Wiki doesn't have this article -- fall back silently
            return None
    except Exception:
        pass
    return None


def build_wiki_context(links, max_chars, use_simple=False):
    """
    Fetch summaries for the given Wikipedia URLs and combine them,
    truncated to max_chars total. Returns the combined text.
    """
    parts = []
    for url in links[:3]:
        text = fetch_wiki_summary(url, use_simple=use_simple)
        time.sleep(0.3)
        if text:
            # Strip citations like [1], [2]
            text = re.sub(r'\[\d+\]', '', text).strip()
            parts.append(text)
        if not use_simple and parts:
            break  # one Wikipedia article is plenty for regular wiki

    combined = " ".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars].rsplit(" ", 1)[0] + "..."
    return combined


def call_openrouter(user_prompt, plugins=None, max_tokens=700):
    """Make a non-streaming OpenRouter call. Returns (data_dict, elapsed_s)."""
    body = {
        "model":      MODEL,
        "stream":     False,
        "max_tokens": max_tokens,
        "provider": {
            "order": ["Together", "Fireworks", "DeepInfra"],
            "allow_fallbacks": True,
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
    }
    if plugins:
        body["plugins"] = plugins

    headers = {
        "Authorization": "Bearer {}".format(API_KEY),
        "Content-Type":  "application/json",
        "X-OpenRouter-Include-Usage": "true",
    }

    t0 = time.time()
    r  = requests.post("{}/chat/completions".format(BASE_URL), headers=headers, json=body, timeout=120)
    elapsed = round(time.time() - t0, 1)

    if r.status_code != 200:
        return {"error": r.text, "status": r.status_code}, elapsed
    return r.json(), elapsed


def extract_metrics(data):
    usage = data.get("usage", {})
    content = ""
    choices = data.get("choices", [])
    if choices:
        content = choices[0].get("message", {}).get("content", "") or ""
    return {
        "prompt_tokens":     usage.get("prompt_tokens",     "?"),
        "completion_tokens": usage.get("completion_tokens", "?"),
        "total_tokens":      usage.get("total_tokens",      "?"),
        "cost_usd":          usage.get("cost",              None),
        "output":            content,
        "error":             data.get("error"),
    }

# ---- Strategy runners -------------------------------------------------------

def run_strategy(name, description, user_prompt, plugins=None):
    print("\n" + "=" * 70)
    print("STRATEGY {}: {}".format(name, description))
    print("=" * 70)
    data, elapsed = call_openrouter(user_prompt, plugins=plugins)
    m = extract_metrics(data)
    if m["error"]:
        print("ERROR:", m["error"])
        return {**m, "name": name, "description": description, "elapsed_s": elapsed}

    cost_str = "${:.5f} (~{:.3f}c)".format(m["cost_usd"], m["cost_usd"] * 100) if m["cost_usd"] else "?"
    print("Prompt tokens:  {}".format(m["prompt_tokens"]))
    print("Total tokens:   {}".format(m["total_tokens"]))
    print("Cost:           {}   ({:.1f}s)".format(cost_str, elapsed))
    print("\n--- OUTPUT ---")
    print(m["output"])
    return {**m, "name": name, "description": description, "elapsed_s": elapsed}


# ---- Main -------------------------------------------------------------------

def main():
    print("BokyLearn -- Web Search Token Strategy Comparison")
    print("Fact: \"{}\"".format(SAMPLE_FACT))
    print("Links available:", SAMPLE_LINKS)
    print()

    # Pre-fetch Wikipedia context variants (do once, reuse)
    print("Pre-fetching Wikipedia summaries...")
    wiki_en_full  = build_wiki_context(SAMPLE_LINKS, max_chars=9999, use_simple=False)
    wiki_en_700   = wiki_en_full[:700].rsplit(" ", 1)[0] + "..." if len(wiki_en_full) > 700  else wiki_en_full
    wiki_en_500   = wiki_en_full[:500].rsplit(" ", 1)[0] + "..." if len(wiki_en_full) > 500  else wiki_en_full
    wiki_en_300   = wiki_en_full[:300].rsplit(" ", 1)[0] + "..." if len(wiki_en_full) > 300  else wiki_en_full
    wiki_simple_full = build_wiki_context(SAMPLE_LINKS, max_chars=9999, use_simple=True) or wiki_en_full
    wiki_simple_500 = wiki_simple_full[:500].rsplit(" ", 1)[0] + "..." if len(wiki_simple_full) > 500 else wiki_simple_full
    wiki_simple_300 = wiki_simple_full[:300].rsplit(" ", 1)[0] + "..." if len(wiki_simple_full) > 300 else wiki_simple_full

    print("  EN Wikipedia extract length:     {} chars".format(len(wiki_en_full)))
    print("  Simple Wikipedia extract length: {} chars".format(len(wiki_simple_full)))
    print()

    results = []

    # A: Baseline — no context
    p = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS)
    results.append(run_strategy("A", "No context (baseline)", p))
    time.sleep(2)

    # B: OpenRouter web, max_results=1
    results.append(run_strategy("B", "OR web plugin, max_results=1", p,
        plugins=[{"id": "web", "max_results": 1}]))
    time.sleep(2)

    # C: OpenRouter web, max_results=2
    results.append(run_strategy("C", "OR web plugin, max_results=2", p,
        plugins=[{"id": "web", "max_results": 2}]))
    time.sleep(2)

    # D: Wikipedia EN summary, 700 chars
    p_d = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS, extra_context=wiki_en_700)
    results.append(run_strategy("D", "Wikipedia EN summary, 700 chars", p_d))
    time.sleep(2)

    # E: Wikipedia EN summary, 500 chars
    p_e = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS, extra_context=wiki_en_500)
    results.append(run_strategy("E", "Wikipedia EN summary, 500 chars", p_e))
    time.sleep(2)

    # F: Wikipedia EN summary, 300 chars
    p_f = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS, extra_context=wiki_en_300)
    results.append(run_strategy("F", "Wikipedia EN summary, 300 chars", p_f))
    time.sleep(2)

    # G: Simple Wikipedia, 500 chars
    p_g = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS, extra_context=wiki_simple_500)
    results.append(run_strategy("G", "Simple Wikipedia, 500 chars", p_g))
    time.sleep(2)

    # H: Simple Wikipedia, 300 chars
    p_h = build_user_prompt(SAMPLE_FACT, SAMPLE_TAGS, extra_context=wiki_simple_300)
    results.append(run_strategy("H", "Simple Wikipedia, 300 chars", p_h))
    time.sleep(2)

    # I: Combo: EN wiki 500 + OR web max_results=1
    results.append(run_strategy("I", "Combo: EN wiki 500 + OR web=1", p_e,
        plugins=[{"id": "web", "max_results": 1}]))
    time.sleep(2)

    # J: Combo: simple wiki 300 + OR web=1
    results.append(run_strategy("J", "Combo: simple wiki 300 + OR web=1", p_h,
        plugins=[{"id": "web", "max_results": 1}]))

    # ---- Summary table -------------------------------------------------------
    print("\n\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print("{:<4} {:<36} {:>7} {:>7} {:>7} {:>10}  {:>6}".format(
        "ID", "Strategy", "Prompt", "Comp.", "Total", "Cost(c)", "Time(s)"))
    print("-" * 70)
    for r in results:
        if r.get("error"):
            print("{:<4} {:<36} ERROR".format(r["name"], r["description"][:36]))
            continue
        cost_c = "{:.3f}".format(r["cost_usd"] * 100) if r["cost_usd"] else "?"
        print("{:<4} {:<36} {:>7} {:>7} {:>7} {:>10}  {:>6}".format(
            r["name"],
            r["description"][:36],
            r["prompt_tokens"],
            r["completion_tokens"],
            r["total_tokens"],
            cost_c,
            r["elapsed_s"],
        ))
    print()
    print("Current (unlimited web search) = ~3938 prompt tokens, ~2c")
    print("Target: prompt tokens < 1000 (good), < 700 (great), <= 500 (fantastic)")


if __name__ == "__main__":
    main()
