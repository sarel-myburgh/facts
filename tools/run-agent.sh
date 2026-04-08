#!/bin/bash
# Invocation loop — calls Codex enricher agent for each file in the given list.
# Usage: run-agent.sh <list-file> <log-file>
# The list file contains one month key per line (or space-separated on one line).
# All data processing is done by the Codex agent, not this script.

LIST_FILE="$1"
LOG_FILE="${2:-/tmp/enricher-run.log}"
REPO="/home/sarel/code/facts"
ENRICHER="$REPO/tools/enricher-agent.md"

if [[ -z "$LIST_FILE" ]]; then
  echo "Usage: $0 <list-file> [log-file]"
  exit 1
fi

# Read keys (handle both newline and space separated)
KEYS=$(cat "$LIST_FILE" | tr ' ' '\n' | grep -v '^$')
TOTAL=$(echo "$KEYS" | wc -l)
COUNT=0

echo "[start] $(date) — $TOTAL files to process" | tee -a "$LOG_FILE"

for KEY in $KEYS; do
  COUNT=$((COUNT + 1))
  FILE="$REPO/data/$KEY.json"

  if [[ ! -f "$FILE" ]]; then
    echo "[$COUNT/$TOTAL] SKIP $KEY — file not found" | tee -a "$LOG_FILE"
    continue
  fi

  # Check if already done (all facts version=2, tags=true, links=true in manifest)
  DONE=$(jq --arg k "$KEY" '.months[$k] | (.tags == true and .links == true)' "$REPO/data/manifest.json" 2>/dev/null)
  if [[ "$DONE" == "true" ]]; then
    echo "[$COUNT/$TOTAL] SKIP $KEY — already complete" | tee -a "$LOG_FILE"
    continue
  fi

  echo "[$COUNT/$TOTAL] START $KEY — $(date)" | tee -a "$LOG_FILE"

  PROMPT=$(sed "s|{{FILE}}|$FILE|g; s|{{MONTH_KEY}}|$KEY|g" "$ENRICHER")

  echo "$PROMPT" | codex exec \
    -s danger-full-access \
    --dangerously-bypass-approvals-and-sandbox \
    - >> "$LOG_FILE" 2>&1

  EXIT=$?
  echo "[$COUNT/$TOTAL] DONE $KEY — exit $EXIT — $(date)" | tee -a "$LOG_FILE"
done

echo "[finished] $(date) — processed $COUNT/$TOTAL files" | tee -a "$LOG_FILE"
