#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from pathlib import Path


REPO = Path("/home/sarel/facts")
DATA_DIR = REPO / "data"
NOTES_DIR = REPO / "notes"
MANIFEST_PATH = DATA_DIR / "manifest.json"
DEFAULT_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _haiku_token() -> str:
    creds = json.loads((Path.home() / ".claude" / ".credentials.json").read_text())
    return creds["claudeAiOauth"]["accessToken"]


WRITE_RESOLVED_NOTES = False
FILLER = {
    # zero-information meta words
    "facts",
    "knowledge",
    "interesting",
    "trivia",
    "amazing",
    "information",
    "notable",
    "important",
    "significant",
    "unique",
    "unusual",
    "rare",
    "general",
    "various",
    "miscellaneous",
    "overview",
    "topic",
    "subject",
    "stuff",
    "things",
    "other",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def append_note(month: str, note: dict) -> None:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTES_DIR / f"{month}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")


def append_resolved(month: str, fact: dict, idx: int, area: str, created_by: str, reason: str) -> None:
    append_note(
        month,
        {
            "month": month,
            "fact_id": fact["id"],
            "fact_index": idx,
            "area": area,
            "status": "resolved",
            "action": "rerun-specialist",
            "created_by": created_by,
            "reason": reason,
        },
    )


def compact_text(text: str) -> str:
    return " ".join(text.split())


def validate_tags(tags: list[str]) -> bool:
    if len(tags) != 10:
        return False
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            return False
        tag = compact_text(tag.strip())
        if tag != tag.lower():
            return False
        if "," in tag or "/" in tag:
            return False
        words = tag.split()
        if not (1 <= len(words) <= 5):
            return False
        if tag in FILLER:
            return False
        if tag in seen:
            return False
        seen.add(tag)
    return True


def clean_tags(tags: list[str] | None) -> list[str]:
    if not isinstance(tags, list):
        return []
    cleaned = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        cleaned.append(compact_text(tag.strip().lower()))
    return cleaned


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


_GEMINI_QUOTA_PHRASES = ("quota exhausted", "quotaexceeded", "quota_exhausted", "terminalquotaerror", "exhausted your capacity")


def call_gemini(prompt: str, models: list[str], timeout: int) -> dict:
    last_error = None
    for model in models:
        for attempt in range(2):
            print(f"[gemini] model={model} attempt={attempt + 1}", flush=True)
            try:
                proc = subprocess.run(
                    ["gemini", "-m", model, "--approval-mode", "yolo", "-p", prompt],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                )
            except Exception as exc:
                last_error = f"{model}: {exc}"
                time.sleep(2)
                continue
            output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            if any(p in output.lower() for p in _GEMINI_QUOTA_PHRASES):
                raise RuntimeError(f"gemini quota exhausted on {model}")
            parsed = parse_json_block(output)
            if parsed is not None:
                return parsed
            last_error = f"{model}: could not parse output"
            time.sleep(3)
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
                "curl", "-s",
                ANTHROPIC_API_URL,
                "-H", f"x-api-key: {_haiku_token()}",
                "-H", "anthropic-version: 2023-06-01",
                "-H", "content-type: application/json",
                "-d", payload,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        response = json.loads(proc.stdout)
        if "error" in response:
            raise RuntimeError(f"{model}: API error: {response['error']}")
        usage = response.get("usage", {})
        print(
            f"[haiku-usage] in={usage.get('input_tokens',0)} out={usage.get('output_tokens',0)}",
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


def call_model(provider: str, prompt: str, gemini_models: list[str], haiku_model: str, timeout: int) -> dict:
    if provider == "haiku":
        return call_haiku(prompt, haiku_model, timeout)

    # Both "gemini" and "auto" try gemini first, falling back to haiku on quota or auto-mode errors.
    try:
        return call_gemini(prompt, gemini_models, timeout)
    except RuntimeError as exc:
        is_quota = "quota" in str(exc).lower()
        if provider == "gemini" and not is_quota:
            raise  # explicit gemini mode: only fall back on quota, not parse errors
        print(f"[provider-fallback] gemini failed: {exc}", flush=True)
        return call_haiku(prompt, haiku_model, timeout)


def build_prompt(month_key: str, batch: list[tuple[int, dict]]) -> str:
    payload = []
    for idx, fact in batch:
        wiki_titles = [l["title"] for l in fact.get("links", []) if l.get("source") == "Wikipedia"][:5]
        payload.append(
            {
                "index": idx,
                "id": fact["id"],
                "text": fact["text"],
                "wiki_titles": wiki_titles,
            }
        )
    filler_list = ", ".join(sorted(FILLER))
    return (
        "Return only valid JSON.\n"
        "You are tagging educational facts for a user interest-matching app.\n"
        "Users declare interests like 'crime', 'biology', or 'space exploration' and see matching facts.\n"
        "\n"
        "Tag balance per fact (10 tags total):\n"
        "- 4-5 broad tags a user would actually list as interests "
        "(e.g. 'crime', 'biology', 'music', 'ancient history', 'space exploration')\n"
        "- 4-5 specific tags that narrow within those broad areas "
        "(e.g. 'church crime', 'marine biology', 'jazz music', 'roman empire', 'mars missions')\n"
        "- distinguish meaningfully where it matters "
        "(e.g. 'pokemon card game' not just 'pokemon'; 'silent films' not just 'film')\n"
        "- avoid tags so specific that only this one fact in a large database would carry them\n"
        "\n"
        "Rules:\n"
        "- exactly 10 tags per fact\n"
        "- lowercase only\n"
        "- no commas or slashes\n"
        "- hyphens allowed when natural\n"
        "- 1 to 5 words per tag\n"
        "- include subject, field, era, geography, and adjacent interests when useful\n"
        f"- never use zero-information words as tags: {filler_list}\n"
        "- do not repeat the same idea in near-duplicate form\n\n"
        "Output shape:\n"
        "{\n"
        '  "results": [\n'
        '    {"index": 0, "tags": ["...", "..."]}\n'
        "  ]\n"
        "}\n\n"
        f"Month: {month_key}\n"
        f"Facts: {json.dumps(payload, ensure_ascii=False)}\n"
    )


def update_manifest(month_key: str) -> None:
    month_path = DATA_DIR / f"{month_key}.json"
    data = load_json(month_path)
    facts = data["facts"]
    tagged = sum(1 for fact in facts if validate_tags(clean_tags(fact.get("tags"))))
    with MANIFEST_PATH.open("r+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        manifest = json.load(f)
        entry = manifest["months"][month_key]
        entry["tagged_facts"] = tagged
        entry["total_facts"] = len(facts)
        entry["tags"] = tagged == len(facts)
        f.seek(0)
        f.truncate()
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def mark_open_note(month_key: str, idx: int, fact: dict, reason: str, tags: list[str] | None = None) -> None:
    note = {
        "month": month_key,
        "fact_id": fact["id"],
        "fact_index": idx,
        "area": "tags",
        "status": "open",
        "action": "rerun-specialist",
        "created_by": "tags",
        "reason": reason,
    }
    if tags is not None:
        note["details"] = {"tags": tags}
    append_note(month_key, note)


def apply_results(month_key: str, facts: list[dict], batch: list[tuple[int, dict]], results: dict[int, list[str]]) -> tuple[int, list[tuple[int, dict]]]:
    applied = 0
    invalid: list[tuple[int, dict]] = []
    for idx, fact in batch:
        tags = clean_tags(results.get(idx))
        if validate_tags(tags):
            facts[idx]["tags"] = tags
            applied += 1
            if WRITE_RESOLVED_NOTES:
                append_resolved(
                    month_key,
                    fact,
                    idx,
                    "tags",
                    "tags",
                    "Valid tags were applied successfully.",
                )
        else:
            invalid.append((idx, fact))
    return applied, invalid


def process_batch(
    month_key: str,
    facts: list[dict],
    batch: list[tuple[int, dict]],
    provider: str,
    gemini_models: list[str],
    haiku_model: str,
    timeout: int,
) -> tuple[int, int]:
    prompt = build_prompt(month_key, batch)
    try:
        parsed = call_model(provider, prompt, gemini_models, haiku_model, timeout)
    except Exception as exc:
        if len(batch) > 1:
            midpoint = len(batch) // 2
            left = batch[:midpoint]
            right = batch[midpoint:]
            left_applied, left_total = process_batch(month_key, facts, left, provider, gemini_models, haiku_model, timeout)
            right_applied, right_total = process_batch(month_key, facts, right, provider, gemini_models, haiku_model, timeout)
            return left_applied + right_applied, left_total + right_total
        idx, fact = batch[0]
        mark_open_note(month_key, idx, fact, f"Tagging model failed: {exc}")
        return 0, 1

    results = {
        item["index"]: item["tags"]
        for item in parsed.get("results", [])
        if "index" in item and "tags" in item
    }
    applied, invalid = apply_results(month_key, facts, batch, results)
    if not invalid:
        return applied, len(batch)

    if len(batch) == 1:
        idx, fact = batch[0]
        mark_open_note(
            month_key,
            idx,
            fact,
            "Tagging model returned invalid or missing tags",
            clean_tags(results.get(idx)),
        )
        return applied, 1

    if len(invalid) == len(batch) and len(batch) > 1:
        midpoint = len(batch) // 2
        left = batch[:midpoint]
        right = batch[midpoint:]
        left_applied, left_total = process_batch(month_key, facts, left, provider, gemini_models, haiku_model, timeout)
        right_applied, right_total = process_batch(month_key, facts, right, provider, gemini_models, haiku_model, timeout)
        return left_applied + right_applied, left_total + right_total

    retried_applied = 0
    retried_total = 0
    for item in invalid:
        item_applied, item_total = process_batch(month_key, facts, [item], provider, gemini_models, haiku_model, timeout)
        retried_applied += item_applied
        retried_total += item_total
    return applied + retried_applied, (len(batch) - len(invalid)) + retried_total


def process_month(
    month_key: str,
    batch_size: int,
    provider: str,
    gemini_models: list[str],
    haiku_model: str,
    timeout: int,
    save_every: int,
) -> None:
    month_path = DATA_DIR / f"{month_key}.json"
    data = load_json(month_path)
    facts = data["facts"]
    remaining = [
        (i, fact) for i, fact in enumerate(facts)
        if not validate_tags(clean_tags(fact.get("tags")))
    ]
    print(f"[month] {month_key} remaining={len(remaining)} batch_size={batch_size}", flush=True)
    dirty_batches = 0
    for start in range(0, len(remaining), batch_size):
        batch = remaining[start : start + batch_size]
        print(
            f"[batch] {month_key} start={start} size={len(batch)} "
            f"indexes={[idx for idx, _ in batch]}",
            flush=True,
        )
        applied, attempted = process_batch(month_key, facts, batch, provider, gemini_models, haiku_model, timeout)
        dirty_batches += 1
        if dirty_batches >= save_every:
            save_json(month_path, data)
            dirty_batches = 0
        print(f"[batch-done] {month_key} applied={applied}/{attempted}", flush=True)
    save_json(month_path, data)
    update_manifest(month_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("months", nargs="*")
    parser.add_argument("--all-untagged", action="store_true")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--provider", choices=["auto", "gemini", "haiku"], default="auto")
    parser.add_argument("--gemini-models", default=",".join(DEFAULT_GEMINI_MODELS))
    parser.add_argument("--haiku-model", default=DEFAULT_HAIKU_MODEL)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--save-every", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gemini_models = [m.strip() for m in args.gemini_models.split(",") if m.strip()]
    haiku_model = args.haiku_model.strip()
    months = list(args.months)
    if args.all_untagged:
        manifest = load_json(MANIFEST_PATH)
        months.extend(
            key for key, value in manifest["months"].items() if not value.get("tags")
        )
    if not months:
        print("No months specified.", file=sys.stderr)
        return 1
    for month_key in months:
        process_month(
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
