#!/usr/bin/env python3
"""Tag facts in dyk JSON files using OpenRouter. Manifest-driven, cron-safe."""

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
TAGS_FILE = ROOT / "data" / "tags.md"
LOG_FILE = LOGS_DIR / "tagged_facts.log"
MANIFEST_FILE = LOGS_DIR / "manifest.json"
CURRENT_FILE = LOGS_DIR / "current_file.txt"

PROMPT_TEMPLATE = """Given this fact:
"{text}"

Select 5-10 relevant tags from the following list only:

{tags_content}

Reply with only a JSON array of tag strings. No explanation."""


def load_tags() -> str:
    return TAGS_FILE.read_text()


def load_log() -> set[str]:
    if LOG_FILE.exists():
        return set(line for line in LOG_FILE.read_text().splitlines() if line.strip())
    return set()


def log_fact(fact_id: str) -> None:
    with LOG_FILE.open("a") as f:
        f.write(fact_id + "\n")


def load_manifest() -> dict:
    return json.loads(MANIFEST_FILE.read_text())


def save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def get_current_file() -> Path | None:
    if CURRENT_FILE.exists():
        p = Path(CURRENT_FILE.read_text().strip())
        if p.exists():
            return p
    return None


def set_current_file(filepath: Path) -> None:
    CURRENT_FILE.write_text(str(filepath))


def clear_state() -> None:
    LOG_FILE.write_text("")
    if CURRENT_FILE.exists():
        CURRENT_FILE.unlink()


def next_untagged(manifest: dict) -> Path | None:
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
    api_key = os.environ.get("OR_KEY")
    if not api_key:
        raise ValueError("OR_KEY environment variable not set")

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "google/gemma-4-26b-a4b-it",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def tag_file(filepath: Path) -> None:
    data = json.loads(filepath.read_text())
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
                filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                log_fact(fact_id)
                break
            except Exception as e:
                is_connection_error = any(
                    kw in str(e) for kw in ("Connection", "ConnectionReset", "RemoteDisconnected", "ChunkedEncodingError")
                )
                wait = 30 if is_connection_error else 2
                if attempt < 2:
                    print(f"    ERROR (attempt {attempt+1}, retrying in {wait}s): {e}")
                    time.sleep(wait)
                else:
                    print(f"    ERROR (giving up): {e}")

        time.sleep(1)


def main() -> None:
    manifest = load_manifest()
    done = load_log()

    if done:
        # Resume in-progress file
        filepath = get_current_file()
        if not filepath:
            print("ERROR: tagged_facts.log has entries but current_file.txt is missing.")
            sys.exit(1)
        print(f"Resuming: {filepath.name}")
    else:
        # Find next untagged month
        filepath = next_untagged(manifest)
        if not filepath:
            print("All months tagged. Nothing to do.")
            sys.exit(0)
        set_current_file(filepath)
        print(f"Starting: {filepath.name}")

    tag_file(filepath)

    # Mark complete in manifest
    key = filepath.stem  # e.g. "dyk_2026_Mar"
    mark_tagged(manifest, key)
    save_manifest(manifest)
    clear_state()
    print(f"\nCompleted: {filepath.name} — manifest updated.")


if __name__ == "__main__":
    main()
