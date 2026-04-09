#!/usr/bin/env bash
set -euo pipefail

REPO="/home/sarel/facts"
RUNNER="$REPO/tools/run_tags_gemini.py"
MONTH_KEY="${1:?usage: process_tag_month.sh <month_key>}"

remaining_for_month() {
  python3 - "$MONTH_KEY" <<'PY'
import json
import sys
from pathlib import Path

month_key = sys.argv[1]
data = json.loads(Path(f"/home/sarel/facts/data/{month_key}.json").read_text())

def valid(tags):
    if not isinstance(tags, list) or len(tags) != 10:
        return False
    seen = set()
    filler = {
        "facts", "knowledge", "interesting", "trivia", "amazing", "information",
        "notable", "important", "significant", "unique", "unusual", "rare",
        "general", "various", "miscellaneous", "overview", "topic", "subject",
        "stuff", "things", "other",
    }
    for tag in tags:
        if not isinstance(tag, str):
            return False
        tag = " ".join(tag.strip().lower().split())
        if tag != tag.lower() or "," in tag or "/" in tag:
            return False
        words = tag.split()
        if not (1 <= len(words) <= 5):
            return False
        if tag in filler or tag in seen:
            return False
        seen.add(tag)
    return True

print(sum(1 for fact in data["facts"] if not valid(fact.get("tags", []))))
PY
}

echo "[process-month] $MONTH_KEY remaining=$(remaining_for_month)"

python3 "$RUNNER" \
  --provider haiku \
  --batch-size "${BULK_BATCH_SIZE:-40}" \
  --timeout "${BULK_TIMEOUT:-240}" \
  --save-every "${SAVE_EVERY:-6}" \
  --haiku-model "${BULK_MODEL:-claude-haiku-4-5-20251001}" \
  "$MONTH_KEY"

remaining="$(remaining_for_month)"
echo "[after-bulk] $MONTH_KEY remaining=$remaining"
if [[ "$remaining" == "0" ]]; then
  exit 0
fi

python3 "$RUNNER" \
  --provider haiku \
  --batch-size "${REPAIR_BATCH_SIZE:-8}" \
  --timeout "${REPAIR_TIMEOUT:-240}" \
  --save-every 2 \
  --haiku-model "${REPAIR_MODEL:-claude-haiku-4-5-20251001}" \
  "$MONTH_KEY"

remaining="$(remaining_for_month)"
echo "[after-repair] $MONTH_KEY remaining=$remaining"
if [[ "$remaining" == "0" ]]; then
  exit 0
fi

if [[ "$remaining" -le 5 ]]; then
  python3 "$RUNNER" \
    --provider haiku \
    --batch-size 1 \
    --timeout "${FINAL_TIMEOUT:-300}" \
    --save-every 1 \
    --haiku-model "${FINAL_MODEL:-claude-haiku-4-5-20251001}" \
    "$MONTH_KEY"
fi

echo "[done-month] $MONTH_KEY remaining=$(remaining_for_month)"
