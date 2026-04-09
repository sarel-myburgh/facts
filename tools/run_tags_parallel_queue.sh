#!/usr/bin/env bash
set -euo pipefail

REPO="/home/sarel/facts"
QUEUE_BUILDER="$REPO/tools/build_tag_queue.py"
MONTH_PROCESSOR="$REPO/tools/process_tag_month.sh"
WORKERS="${WORKERS:-6}"
COUNT="${1:-0}"
QUEUE_FILE="${QUEUE_FILE:-$REPO/logs/tag-queue-$(date +%Y%m%d-%H%M%S).txt}"

mkdir -p "$REPO/logs"
if [[ "$COUNT" == "0" ]]; then
  python3 "$QUEUE_BUILDER" > "$QUEUE_FILE"
else
  python3 "$QUEUE_BUILDER" --count "$COUNT" > "$QUEUE_FILE"
fi

TOTAL="$(wc -l < "$QUEUE_FILE" | tr -d ' ')"
echo "[queue] file=$QUEUE_FILE months=$TOTAL workers=$WORKERS"

if [[ "$TOTAL" == "0" ]]; then
  exit 0
fi

xargs -P "$WORKERS" -L 1 "$MONTH_PROCESSOR" < "$QUEUE_FILE"
