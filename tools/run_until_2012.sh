#!/bin/bash
# Run tag_facts.py in a loop until all 2012 months are tagged.
# Commits + pushes after each year completes.

set -e
cd /home/user/facts

YEARS_PUSHED=""

year_complete() {
    python3 -c "
import json, sys
m = json.load(open('logs/manifest.json'))
months = {k: v for k, v in m['months'].items() if k.startswith('dyk_$1')}
all_done = bool(months) and all(v.get('tags', False) for v in months.values())
sys.exit(0 if all_done else 1)
"
}

commit_and_push() {
    local year=$1
    git add data/ logs/manifest.json
    git commit -m "Tag ${year} facts by month

https://claude.ai/code/session_016azyJv3ve2nq77LAKruXDU"
    git push -u origin claude/tag-facts-by-month-5C9To
    echo "=== Pushed year ${year} ==="
}

echo "Starting loop. Will stop after 2012 is complete."

while true; do
    python3 tools/tag_facts.py
    EXIT=$?
    if [ $EXIT -ne 0 ]; then
        echo "tag_facts.py exited with $EXIT — stopping."
        break
    fi

    # Check year completions and push
    for year in 2008 2009 2010 2011; do
        if [[ ! "$YEARS_PUSHED" == *"$year"* ]] && year_complete $year; then
            commit_and_push $year
            YEARS_PUSHED="$YEARS_PUSHED $year"
        fi
    done

    # Stop condition: 2012 complete
    if year_complete 2012; then
        echo "2012 is complete."
        commit_and_push 2012
        echo "All done."
        break
    fi
done
