#!/usr/bin/env python3
"""
Tag facts in dyk_*.json files using OpenRouter (Gemma free model).

HOW IT WORKS
------------
One run processes exactly one month file, then exits. This makes it safe to
run under cron or to call in a loop — every run is idempotent and restartable.

STATE FILES (all in logs/)
  manifest.json      — master list of all month files; tracks which are done
  current_file.txt   — absolute path of the file currently being worked on
  tagged_facts.log   — one fact ID per line for every fact tagged this run

RESUME LOGIC
  If tagged_facts.log is non-empty   → an interrupted run is in progress;
                                       resume the file named in current_file.txt.
  If tagged_facts.log is empty       → pick the first month in the manifest
                                       that still has tags=False.

After all facts in a file are tagged:
  1. manifest.json is updated (tags=True for that month).
  2. tagged_facts.log is cleared and current_file.txt is removed, so the next
     run starts fresh on the next untagged month.

TAGS
  data/tags.md lists all valid tag strings. The model is asked to select 5-10
  from that list only; raw JSON array is written back into the fact object.
"""

import io
import json
import os
import sys
import time
from pathlib import Path

# Ensure stdout handles non-ASCII characters on Windows terminals
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
TAGS_FILE = ROOT / "data" / "tags.md"
LOG_FILE = LOGS_DIR / "tagged_facts.log"       # IDs of facts tagged in this run
MANIFEST_FILE = LOGS_DIR / "manifest.json"     # per-month completion status
CURRENT_FILE = LOGS_DIR / "current_file.txt"   # path of the in-progress file

# Model to use: free-tier Gemma on OpenRouter. Cheap, fast enough for bulk tagging.
MODEL = "google/gemma-4-26b-a4b-it"

PROMPT_TEMPLATE = """Given this fact:
"{text}"

Select 5-10 relevant tags from the following list only:

{tags_content}

Reply with only a JSON array of tag strings. No explanation."""


def load_tags() -> str:
    return TAGS_FILE.read_text(encoding="utf-8")


def load_log() -> set[str]:
    """Return the set of fact IDs already tagged in the current run."""
    if LOG_FILE.exists():
        return set(line for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip())
    return set()


def log_fact(fact_id: str) -> None:
    """Append a fact ID to the log so it can be skipped on resume."""
    with LOG_FILE.open("a") as f:
        f.write(fact_id + "\n")


def load_manifest() -> dict:
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def get_current_file() -> Path | None:
    """Return the path stored in current_file.txt, or None if missing/invalid."""
    if CURRENT_FILE.exists():
        p = Path(CURRENT_FILE.read_text().strip())
        if p.exists():
            return p
    return None


def set_current_file(filepath: Path) -> None:
    CURRENT_FILE.write_text(str(filepath))


def clear_state() -> None:
    """Reset per-run state so the next invocation starts a fresh month."""
    LOG_FILE.write_text("")
    if CURRENT_FILE.exists():
        CURRENT_FILE.unlink()


def next_untagged(manifest: dict) -> Path | None:
    """Return the data file for the first month not yet tagged, or None if all done."""
    for key, meta in manifest["months"].items():
        if not meta.get("tags", False):
            candidate = DATA_DIR / f"{key}.json"
            if candidate.exists():
                return candidate
    return None


def mark_tagged(manifest: dict, key: str) -> None:
    if key in manifest["months"]:
        manifest["months"][key]["tags"] = True


def ask_openrouter(prompt: str) -> list[str]:
    """Call OpenRouter chat completions and parse the returned JSON tag array."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY environment variable not set")

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if the model wraps its output in them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def tag_file(filepath: Path) -> None:
    """
    Tag every untagged fact in `filepath`.

    For each fact: call OpenRouter, write tags back into the JSON file
    immediately (so progress survives a crash), and append the fact ID to
    tagged_facts.log. Facts already in the log are skipped.
    """
    data = json.loads(filepath.read_text(encoding="utf-8"))
    tags_content = load_tags()
    done = load_log()
    facts = data["facts"]

    skipped = sum(1 for f in facts if f["id"] in done)
    remaining = len(facts) - skipped
    print(f"File: {filepath.name} — {remaining} remaining ({skipped} already done)")

    for i, fact in enumerate(facts):
        fact_id = fact["id"]
        if fact_id in done:
            continue

        text = fact["text"]
        print(f"  [{i+1}/{len(facts)}] {text[:80]}...")

        prompt = PROMPT_TEMPLATE.format(text=text, tags_content=tags_content)
        for attempt in range(3):
            try:
                new_tags = ask_openrouter(prompt)
                print(f"    → {new_tags}")
                fact["tags"] = new_tags
                # Write after every fact so a crash doesn't lose progress
                filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                log_fact(fact_id)
                break
            except Exception as e:
                # Connection resets need a longer backoff; parse errors just retry fast
                is_connection_error = any(
                    kw in str(e) for kw in ("Connection", "ConnectionReset", "RemoteDisconnected", "ChunkedEncodingError")
                )
                wait = 30 if is_connection_error else 2
                if attempt < 2:
                    print(f"    ERROR (attempt {attempt+1}, retrying in {wait}s): {e}")
                    time.sleep(wait)
                else:
                    print(f"    ERROR (giving up): {e}")

        time.sleep(1)  # stay well under OpenRouter free-tier rate limits


def main() -> None:
    manifest = load_manifest()
    done = load_log()

    if done:
        # Non-empty log means we crashed or were interrupted mid-file — resume it
        filepath = get_current_file()
        if not filepath:
            print("ERROR: tagged_facts.log has entries but current_file.txt is missing.")
            sys.exit(1)
        print(f"Resuming: {filepath.name}")
    else:
        # Clean slate — find the next month the manifest says needs tagging
        filepath = next_untagged(manifest)
        if not filepath:
            print("All months tagged. Nothing to do.")
            sys.exit(0)
        set_current_file(filepath)
        print(f"Starting: {filepath.name}")

    tag_file(filepath)

    # Record completion: update manifest, wipe per-run state for the next invocation
    key = filepath.stem  # e.g. "dyk_2008_Oct"
    mark_tagged(manifest, key)
    save_manifest(manifest)
    clear_state()
    print(f"\nCompleted: {filepath.name} — manifest updated.")


if __name__ == "__main__":
    main()
