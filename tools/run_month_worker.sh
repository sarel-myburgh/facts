#!/usr/bin/env bash
# run_month_worker.sh <month_key> <tag|clean>
# Runs one month through the tagger or cleaner, then commits and pushes.
set -euo pipefail

REPO="/home/sarel/facts"
MONTH_KEY="${1:?usage: run_month_worker.sh <month_key> <tag|clean>}"
TYPE="${2:?usage: run_month_worker.sh <month_key> <tag|clean>}"

cd "$REPO"

echo "[worker-start] $MONTH_KEY type=$TYPE"

if [[ "$TYPE" == "tag" ]]; then
    python3 tools/run_tags_gemini.py "$MONTH_KEY" \
        --provider haiku \
        --batch-size 20 \
        --timeout 180 \
        --save-every 3
elif [[ "$TYPE" == "clean" ]]; then
    python3 tools/run_cleaner_gemini.py "$MONTH_KEY" \
        --provider haiku \
        --batch-size 20 \
        --timeout 180 \
        --save-every 3
else
    echo "Unknown type: $TYPE" >&2
    exit 1
fi

# Commit (no-op if nothing changed)
git add "data/${MONTH_KEY}.json" data/manifest.json
git diff --cached --quiet && { echo "[worker-skip-commit] $MONTH_KEY nothing changed"; exit 0; }
git commit -m "${TYPE}: ${MONTH_KEY}"

# Push with rebase retry
for i in 1 2 3 4 5; do
    if git pull --rebase origin main && git push origin main; then
        echo "[worker-done] $MONTH_KEY pushed"
        exit 0
    fi
    echo "[worker-retry-push] $MONTH_KEY attempt=$i"
    sleep $((i * 3))
done

echo "[worker-push-failed] $MONTH_KEY — committed but not pushed" >&2
exit 1
