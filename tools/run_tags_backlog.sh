#!/usr/bin/env bash
set -euo pipefail

REPO="/home/sarel/facts"
RUNNER="$REPO/tools/run_tags_gemini.py"
PROVIDER="${PROVIDER:-haiku}"
BATCH_SIZE="${BATCH_SIZE:-8}"
TIMEOUT="${TIMEOUT:-180}"
PASSES_PER_MONTH="${PASSES_PER_MONTH:-3}"
SLEEP_BETWEEN_MONTHS="${SLEEP_BETWEEN_MONTHS:-1}"

next_month() {
  python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("/home/sarel/facts/data/manifest.json").read_text())
months = []
for key, value in manifest["months"].items():
    if value.get("tags"):
        continue
    remaining = value.get("total_facts", 0) - value.get("tagged_facts", 0)
    months.append((remaining, value.get("total_facts", 0), key))
months.sort()
print(months[0][2] if months else "")
PY
}

month_complete() {
  local month_key="$1"
  python3 - "$month_key" <<'PY'
import json
import sys
from pathlib import Path

month_key = sys.argv[1]
manifest = json.loads(Path("/home/sarel/facts/data/manifest.json").read_text())
print("1" if manifest["months"][month_key]["tags"] else "0")
PY
}

remaining_summary() {
  python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("/home/sarel/facts/data/manifest.json").read_text())
months = [v for v in manifest["months"].values() if not v.get("tags")]
remaining_months = len(months)
remaining_facts = sum(v.get("total_facts", 0) - v.get("tagged_facts", 0) for v in months)
print(f"remaining_months={remaining_months} remaining_facts={remaining_facts}")
PY
}

while true; do
  MONTH_KEY="$(next_month)"
  if [[ -z "$MONTH_KEY" ]]; then
    echo "[done] all months have tags"
    break
  fi

  echo "[month] $MONTH_KEY $(remaining_summary)"
  for ((pass=1; pass<=PASSES_PER_MONTH; pass++)); do
    echo "[pass] month=$MONTH_KEY pass=$pass provider=$PROVIDER batch_size=$BATCH_SIZE timeout=$TIMEOUT"
    python3 "$RUNNER" --provider "$PROVIDER" --batch-size "$BATCH_SIZE" --timeout "$TIMEOUT" "$MONTH_KEY"
    if [[ "$(month_complete "$MONTH_KEY")" == "1" ]]; then
      echo "[month-done] $MONTH_KEY"
      break
    fi
  done

  if [[ "$(month_complete "$MONTH_KEY")" != "1" ]]; then
    echo "[month-stalled] $MONTH_KEY still incomplete after $PASSES_PER_MONTH passes"
  fi

  sleep "$SLEEP_BETWEEN_MONTHS"
done
