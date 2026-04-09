#!/usr/bin/env python3
"""
run_cleaner_gemini.py — Audit and remove irrelevant Wikipedia links/images from facts.

Usage:
  python3 tools/run_cleaner_gemini.py dyk_2026_Mar dyk_2026_Feb --provider gemini
  python3 tools/run_cleaner_gemini.py --all-uncleaned --provider gemini

Works newest-to-oldest by default when using --all-uncleaned (caller controls order otherwise).
Conservative: only removes clearly irrelevant links/images; keeps anything ambiguous.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path("/home/sarel/facts")
DATA_DIR = REPO / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
DEFAULT_GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# Helpers shared with run_tags_gemini.py
# ---------------------------------------------------------------------------

def _haiku_token() -> str:
    creds = json.loads((Path.home() / ".claude" / ".credentials.json").read_text())
    return creds["claudeAiOauth"]["accessToken"]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def parse_json_block(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    text = re.sub(r"^```json\s*|^```\s*|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


_GEMINI_QUOTA_PHRASES = (
    "quota exhausted", "quotaexceeded", "quota_exhausted",
    "terminalquotaerror", "exhausted your capacity",
)
_GEMINI_RATELIMIT_PHRASES = ("429", "rate_limit", "resource_exhausted", "rateLimitExceeded")

# Models that hit quota this run — skip them for all subsequent batches
_GEMINI_EXHAUSTED: set[str] = set()


def _parse_gemini_output(output: str, tmpdir: str) -> dict | None:
    """Try to parse JSON from stdout; fall back to any .json file the model created."""
    parsed = parse_json_block(output)
    if parsed is not None:
        return parsed
    # Gemini CLI sometimes saves JSON to a file instead of printing it
    for jf in Path(tmpdir).glob("*.json"):
        try:
            candidate = parse_json_block(jf.read_text())
            if candidate is not None:
                print(f"[gemini-file-recover] found result in {jf.name}", flush=True)
                return candidate
        except Exception:
            pass
    return None


def call_gemini(prompt: str, models: list[str], timeout: int) -> dict:
    last_error = None
    for model in models:
        if model in _GEMINI_EXHAUSTED:
            print(f"[gemini-skip] {model} (quota exhausted earlier this run)", flush=True)
            continue
        for attempt in range(3):
            print(f"[gemini] model={model} attempt={attempt + 1}", flush=True)
            # Fresh empty tmpdir each call — prevents CLI scanning accumulated files
            tmpdir_obj = tempfile.TemporaryDirectory()
            try:
                try:
                    proc = subprocess.run(
                        ["gemini", "-m", model, "--approval-mode", "yolo", "-p", prompt],
                        capture_output=True, text=True, check=False, timeout=timeout,
                        cwd=tmpdir_obj.name,
                    )
                except subprocess.TimeoutExpired:
                    last_error = f"{model}: timeout after {timeout}s"
                    print(f"[gemini-timeout] {model} attempt={attempt + 1}", flush=True)
                    # Don't retry the same model on timeout — move to next model immediately
                    break
                except Exception as exc:
                    last_error = f"{model}: {exc}"
                    time.sleep(2)
                    continue
                output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
                output_lower = output.lower()
                # Permanent quota exhaustion → mark and move to next model
                if any(p in output_lower for p in _GEMINI_QUOTA_PHRASES):
                    _GEMINI_EXHAUSTED.add(model)
                    print(f"[gemini-quota] {model} exhausted, skipping for rest of run", flush=True)
                    last_error = f"{model}: quota exhausted"
                    break  # Try next model instead of raising immediately
                if any(p in output_lower for p in _GEMINI_RATELIMIT_PHRASES):
                    wait = 15 * (attempt + 1)
                    print(f"[gemini-ratelimit] {model} attempt={attempt + 1}, sleeping {wait}s", flush=True)
                    last_error = f"{model}: rate limited (429)"
                    time.sleep(wait)
                    continue
                parsed = _parse_gemini_output(output, tmpdir_obj.name)
                if parsed is not None:
                    return parsed
                last_error = f"{model}: could not parse output"
                print(f"[gemini-parse-fail] first 200 chars: {output[:200]}", flush=True)
                time.sleep(3)
            finally:
                tmpdir_obj.cleanup()
    # If every model is exhausted, raise quota error so caller can fall back to haiku
    if all(m in _GEMINI_EXHAUSTED for m in models):
        raise RuntimeError(f"gemini quota exhausted on {', '.join(models)}")
    raise RuntimeError(last_error or "gemini call failed")


def call_haiku(prompt: str, model: str, timeout: int) -> dict:
    print(f"[haiku] model={model} attempt=1", flush=True)
    payload = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    })
    try:
        proc = subprocess.run(
            [
                "curl", "-s", ANTHROPIC_API_URL,
                "-H", f"x-api-key: {_haiku_token()}",
                "-H", "anthropic-version: 2023-06-01",
                "-H", "content-type: application/json",
                "-d", payload,
            ],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
        response = json.loads(proc.stdout)
        if "error" in response:
            raise RuntimeError(f"{model}: API error: {response['error']}")
        usage = response.get("usage", {})
        print(
            f"[haiku-usage] in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}",
            flush=True,
        )
        text = response["content"][0]["text"]
        parsed = parse_json_block(text)
        if parsed is not None:
            return parsed
        raise RuntimeError(f"{model}: could not parse output")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{model}: timeout")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"{model}: {exc}")


def call_model(
    provider: str,
    prompt: str,
    gemini_models: list[str],
    haiku_model: str,
    timeout: int,
) -> dict:
    if provider == "haiku":
        return call_haiku(prompt, haiku_model, timeout)
    try:
        return call_gemini(prompt, gemini_models, timeout)
    except RuntimeError as exc:
        is_quota = "quota" in str(exc).lower()
        if provider == "gemini" and not is_quota:
            raise
        print(f"[provider-fallback] gemini failed: {exc}", flush=True)
        return call_haiku(prompt, haiku_model, timeout)


# ---------------------------------------------------------------------------
# Cleaning logic
# ---------------------------------------------------------------------------

def needs_cleaning(fact: dict) -> bool:
    """True if the fact has any links or a non-null image URL to evaluate."""
    return bool(fact.get("links")) or bool((fact.get("image") or {}).get("url"))


def build_cleaner_prompt(month_key: str, batch: list[tuple[int, dict]]) -> str:
    payload = []
    for idx, fact in batch:
        links = fact.get("links") or []
        image = fact.get("image") or {}
        entry: dict = {
            "index": idx,
            "text": fact["text"],
            "links": [{"i": i, "title": lnk.get("title", "")} for i, lnk in enumerate(links)],
        }
        if image.get("url"):
            entry["image_caption"] = image.get("caption") or ""
        payload.append(entry)

    return (
        "Return only valid JSON. No markdown fences.\n"
        "You are auditing Wikipedia links and images attached to educational facts.\n"
        "Decide which links/images to KEEP. Be conservative — only remove clearly irrelevant items.\n\n"
        "REMOVE a link if:\n"
        "- Title is a bare year ('1933', '476') or month ('January') used only for dating context;\n"
        "  keep it only if the fact is SPECIFICALLY ABOUT that year or month itself\n"
        "- Title is a common generic word that appeared incidentally in the text (e.g. 'And', 'The',\n"
        "  'History', 'Construction') and is not the actual subject of the fact\n"
        "- The linked article is an extremely broad overarching category when the fact already has a\n"
        "  more specific link (e.g. 'Science' alongside 'Marine biology')\n\n"
        "KEEP a link if:\n"
        "- The article is about a specific named person, place, event, invention, work, or concept\n"
        "  that the fact is primarily or substantially about\n"
        "- When in doubt, KEEP it\n\n"
        "REMOVE the image if:\n"
        "- The caption describes something only tangential to the fact's main subject\n"
        "- It looks like a generic diagram, symbol, or icon for a word that appeared incidentally\n"
        "  (e.g. image of a cube because the word 'cube' appeared; flag of a country for a fact\n"
        "  that merely mentions that country in passing)\n\n"
        "KEEP the image if:\n"
        "- It depicts the actual primary subject of the fact (person, place, event, etc.)\n"
        "- When in doubt, KEEP it\n\n"
        "Output shape (omit keep_image entirely if the fact has no image field):\n"
        "{\n"
        '  "results": [\n'
        '    {"index": 0, "keep_links": [0, 2], "keep_image": true}\n'
        "  ]\n"
        "}\n\n"
        "keep_links: list of i-values (from the links array) to retain. Use [] to remove all.\n\n"
        f"Month: {month_key}\n"
        f"Facts: {json.dumps(payload, ensure_ascii=False)}\n"
    )


def apply_cleaner_results(
    facts: list[dict],
    batch: list[tuple[int, dict]],
    results: dict,
) -> int:
    """Apply cleaning decisions. Returns count of modified facts."""
    modified = 0
    for idx, fact in batch:
        res = results.get(idx)
        if res is None:
            continue
        changed = False

        links = fact.get("links") or []
        if links and "keep_links" in res:
            keep_set = set(res["keep_links"])
            new_links = [lnk for i, lnk in enumerate(links) if i in keep_set]
            if len(new_links) != len(links):
                facts[idx]["links"] = new_links
                removed = len(links) - len(new_links)
                titles = [lnk.get("title") for i, lnk in enumerate(links) if i not in keep_set]
                print(f"[clean] idx={idx} removed {removed} links: {titles}", flush=True)
                changed = True

        image = fact.get("image") or {}
        if image.get("url") and "keep_image" in res and not res["keep_image"]:
            facts[idx]["image"] = {"url": None, "caption": None}
            print(f"[clean] idx={idx} removed image: {image.get('caption', '')}", flush=True)
            changed = True

        if changed:
            modified += 1
    return modified


def process_batch_cleaner(
    month_key: str,
    facts: list[dict],
    batch: list[tuple[int, dict]],
    provider: str,
    gemini_models: list[str],
    haiku_model: str,
    timeout: int,
) -> int:
    prompt = build_cleaner_prompt(month_key, batch)
    try:
        parsed = call_model(provider, prompt, gemini_models, haiku_model, timeout)
    except Exception as exc:
        if len(batch) > 1:
            mid = len(batch) // 2
            return (
                process_batch_cleaner(
                    month_key, facts, batch[:mid], provider, gemini_models, haiku_model, timeout
                )
                + process_batch_cleaner(
                    month_key, facts, batch[mid:], provider, gemini_models, haiku_model, timeout
                )
            )
        print(f"[clean-error] idx={batch[0][0]} model failed: {exc}", flush=True)
        return 0

    results = {
        item["index"]: item
        for item in parsed.get("results", [])
        if "index" in item
    }
    return apply_cleaner_results(facts, batch, results)


def update_manifest_cleaned(month_key: str) -> None:
    with MANIFEST_PATH.open("r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        manifest = json.load(f)
        if month_key in manifest["months"]:
            manifest["months"][month_key]["cleaned"] = True
        f.seek(0)
        f.truncate()
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def process_month_cleaner(
    month_key: str,
    batch_size: int,
    provider: str,
    gemini_models: list[str],
    haiku_model: str,
    timeout: int,
    save_every: int,
) -> None:
    month_path = DATA_DIR / f"{month_key}.json"
    if not month_path.exists():
        print(f"[skip] {month_key}: file not found", flush=True)
        return

    # Skip if already cleaned
    manifest = load_json(MANIFEST_PATH)
    if manifest["months"].get(month_key, {}).get("cleaned"):
        print(f"[skip] {month_key}: already cleaned", flush=True)
        return

    data = load_json(month_path)
    facts = data["facts"]
    to_clean = [(i, fact) for i, fact in enumerate(facts) if needs_cleaning(fact)]
    print(f"[month] {month_key} cleanable={len(to_clean)}/{len(facts)}", flush=True)

    if not to_clean:
        update_manifest_cleaned(month_key)
        print(f"[done] {month_key} no links/images to clean", flush=True)
        return

    total_modified = 0
    dirty_batches = 0
    for start in range(0, len(to_clean), batch_size):
        batch = to_clean[start : start + batch_size]
        print(
            f"[batch] {month_key} start={start} size={len(batch)} "
            f"first_idx={batch[0][0]}",
            flush=True,
        )
        modified = process_batch_cleaner(
            month_key, facts, batch, provider, gemini_models, haiku_model, timeout
        )
        total_modified += modified
        dirty_batches += 1
        if dirty_batches >= save_every:
            save_json(month_path, data)
            dirty_batches = 0

    save_json(month_path, data)
    update_manifest_cleaned(month_key)
    print(f"[done] {month_key} modified={total_modified}/{len(to_clean)}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean irrelevant Wikipedia links/images from facts."
    )
    parser.add_argument("months", nargs="*", help="Month keys to process")
    parser.add_argument(
        "--all-uncleaned",
        action="store_true",
        help="Process all months without cleaned=true in manifest (newest first)",
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--provider", choices=["auto", "gemini", "haiku"], default="auto")
    parser.add_argument("--gemini-models", default=",".join(DEFAULT_GEMINI_MODELS))
    parser.add_argument("--haiku-model", default=DEFAULT_HAIKU_MODEL)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--save-every", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gemini_models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]
    haiku_model = args.haiku_model.strip()
    months = list(args.months)

    if args.all_uncleaned:
        manifest = load_json(MANIFEST_PATH)
        # Newest first: sort descending
        months.extend(
            key
            for key, value in sorted(manifest["months"].items(), reverse=True)
            if not value.get("cleaned")
        )

    if not months:
        print("No months specified.", file=sys.stderr)
        return 1

    for month_key in months:
        process_month_cleaner(
            month_key,
            args.batch_size,
            args.provider,
            gemini_models,
            haiku_model,
            args.timeout,
            args.save_every,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
