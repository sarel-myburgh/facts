#!/bin/bash
# gemini-enrich.sh — Enrich one month's facts file using Gemini for per-fact reasoning.
# Gemini decides: tags, which image subject to look up, which links to keep, what external links to add.
# This script handles: calling Gemini, verifying image URLs via Wikipedia API, writing back to JSON, git push.
#
# Usage: gemini-enrich.sh <month_key>
# Example: gemini-enrich.sh dyk_2004_Nov

set -euo pipefail

MONTH_KEY="${1:?Usage: $0 <month_key>}"
REPO="/home/sarel/code/facts"
FILE="$REPO/data/$MONTH_KEY.json"
GEMINI="${HOME}/.nvm/versions/node/v24.14.0/bin/gemini"
RATE_DELAY=4   # seconds between Gemini calls — stay under RPM limit
WIKI_API="https://en.wikipedia.org/api/rest_v1/page/summary"

[[ -f "$FILE" ]] || { echo "ERROR: File not found: $FILE"; exit 1; }

TOTAL=$(jq '.facts | length' "$FILE")
echo "[start] $MONTH_KEY — $TOTAL facts"

PROCESSED=0; SKIPPED=0; FAILED=0; IMAGES=0; EXT_LINKS=0

for i in $(seq 0 $((TOTAL - 1))); do
    TAGS_LEN=$(jq ".facts[$i].tags | length" "$FILE")
    VERSION=$(jq ".facts[$i].version // 1" "$FILE")

    if [[ "$TAGS_LEN" -ge 10 && "$VERSION" -eq 2 ]]; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    TEXT=$(jq -r ".facts[$i].text" "$FILE")
    WIKI_TITLES=$(jq -r ".facts[$i].links[] | select(.source == \"Wikipedia\") | .title" "$FILE" | paste -sd ", " -)

    # --- IMAGE: use first Wikipedia link's article via REST API (no Gemini needed) ---
    IMAGE_URL="null"
    IMAGE_CAPTION_VAL="null"
    # Try each Wikipedia link in order until we get a real image
    WIKI_TITLES_ARR=$(jq -r '.links[] | select(.source == "Wikipedia") | .title' "$FILE" | head -3)
    while IFS= read -r WIKI_TITLE; do
        [[ -z "$WIKI_TITLE" ]] && continue
        ENCODED_TITLE=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1].replace(' ','_')))" "$WIKI_TITLE" 2>/dev/null)
        API_RESP=$(curl -s --max-time 8 "$WIKI_API/$ENCODED_TITLE" 2>/dev/null) || continue
        CANDIDATE=$(echo "$API_RESP" | jq -r '.originalimage.source // .thumbnail.source // empty' 2>/dev/null) || continue
        [[ -z "$CANDIDATE" ]] && continue
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$CANDIDATE" 2>/dev/null) || continue
        if [[ "$HTTP_CODE" == "200" ]]; then
            IMAGE_URL="\"$CANDIDATE\""
            IMAGE_CAPTION_VAL="\"$WIKI_TITLE\""
            IMAGES=$((IMAGES + 1))
            break
        fi
    done <<< "$WIKI_TITLES_ARR"

    # --- GEMINI: tags + link pruning + external links only ---
    PROMPT_FILE=$(mktemp /tmp/gemini-prompt-XXXXXX.txt)
    cat > "$PROMPT_FILE" <<PROMPT
Return ONLY a JSON object for this educational fact. No explanation, no markdown fences.

Fact: ${TEXT}
Wikipedia links to evaluate: ${WIKI_TITLES}

JSON structure (return this exactly):
{
  "interest_phrases": ["phrase 1", "phrase 2", "phrase 3", "phrase 4", "phrase 5", "phrase 6", "phrase 7", "phrase 8", "phrase 9", "phrase 10"],
  "keep_wiki_titles": ["titles to keep from the list above"],
  "new_links": [{"url": "...", "title": "...", "source": "..."}]
}

INTEREST_PHRASES — 10 readable English phrases describing what this fact is about and who would enjoy it. Each phrase is 1-3 words with SPACES between words. All lowercase. Examples of correct format: "lou gramm", "brain tumor", "west coast", "rock music", "cancer survivor". Examples of WRONG format: "lougramm", "braintumor", "westcoast". No punctuation except hyphens in hyphenated terms.

KEEP_WIKI_TITLES — from the list provided, keep titles that genuinely help a curious reader learn more. Drop: year articles (1997, 2004), decade articles (1990s), ultra-generic one-word articles when a more specific one is already listed (e.g. drop "Pond" if "Dew pond" is there, drop "Actress" if the person's name is there).

NEW_LINKS — 1-2 non-Wikipedia sources (Britannica, National Geographic, NASA, BBC, Smithsonian, etc). Specific article URLs only, not homepages. Verify they exist. Empty array if nothing good found.
PROMPT

    OUTPUT=$("$GEMINI" -p "$(cat $PROMPT_FILE)" 2>/dev/null) || true
    rm -f "$PROMPT_FILE"

    JSON=$(echo "$OUTPUT" | sed '/^```/d' | tr -d '\r' | python3 -c "
import sys, json, re
text = sys.stdin.read()
try:
    print(json.dumps(json.loads(text.strip())))
    sys.exit(0)
except: pass
m = re.search(r'\{.*\}', text, re.DOTALL)
if m:
    try:
        print(json.dumps(json.loads(m.group())))
        sys.exit(0)
    except: pass
sys.exit(1)
" 2>/dev/null) || true

    if [[ -z "$JSON" ]]; then
        echo "  [FAIL $((i+1))/$TOTAL] JSON parse error — ${TEXT:0:60}"
        FAILED=$((FAILED + 1))
        sleep "$RATE_DELAY"
        continue
    fi

    TAGS=$(echo "$JSON" | jq '.interest_phrases // []')
    KEEP_TITLES_RAW=$(echo "$JSON" | jq '[.keep_wiki_titles[]? | ascii_downcase]')
    NEW_LINKS=$(echo "$JSON" | jq '.new_links // []')
    NEW_LINKS_COUNT=$(echo "$NEW_LINKS" | jq 'length')
    [[ "$NEW_LINKS_COUNT" -gt 0 ]] && EXT_LINKS=$((EXT_LINKS + 1))

    UPDATED=$(jq \
        --argjson i "$i" \
        --argjson tags "$TAGS" \
        --argjson image_url "$IMAGE_URL" \
        --argjson image_caption "$IMAGE_CAPTION_VAL" \
        --argjson keep_titles "$KEEP_TITLES_RAW" \
        --argjson new_links "$NEW_LINKS" \
        '.facts[$i] |= . + {
            "version": 2,
            "tags": $tags,
            "image": {"url": $image_url, "caption": $image_caption},
            "links": (
                [.links[] | select(.source == "Wikipedia") |
                 select((.title | ascii_downcase) as $t | $keep_titles | map(. == $t) | any)] +
                $new_links
            )
        }' "$FILE") || { echo "  [FAIL $((i+1))/$TOTAL] jq error"; FAILED=$((FAILED+1)); sleep "$RATE_DELAY"; continue; }

    echo "$UPDATED" > "$FILE"
    PROCESSED=$((PROCESSED + 1))

    if (( PROCESSED % 10 == 0 )); then
        echo "  [$((i+1))/$TOTAL] done=$PROCESSED images=$IMAGES ext=$EXT_LINKS failed=$FAILED"
    fi

    sleep "$RATE_DELAY"
done

echo "[done] $MONTH_KEY — processed=$PROCESSED skipped=$SKIPPED failed=$FAILED images=$IMAGES ext_links=$EXT_LINKS"

# Update manifest
TAGGED=$(jq '[.facts[] | select(.tags | length >= 10)] | length' "$FILE")
LINKED=$(jq '[.facts[] | select(.links | map(select(.source != "Wikipedia")) | length > 0)] | length' "$FILE")
ALL_V2=$(jq '[.facts[] | select(.version == 2)] | length' "$FILE")
TAGS_DONE=$([[ "$TAGGED" -eq "$TOTAL" ]] && echo "true" || echo "false")
LINKS_DONE=$([[ "$ALL_V2" -eq "$TOTAL" ]] && echo "true" || echo "false")

jq --arg k "$MONTH_KEY" \
   --argjson tagged "$TAGGED" \
   --argjson linked "$LINKED" \
   --argjson total "$TOTAL" \
   --argjson tags_done "$TAGS_DONE" \
   --argjson links_done "$LINKS_DONE" \
   '.months[$k] |= . + {
       "tags": $tags_done,
       "links": $links_done,
       "tagged_facts": $tagged,
       "linked_facts": $linked,
       "total_facts": $total,
       "version": 2
   }' "$REPO/data/manifest.json" > /tmp/manifest-tmp.json \
   && mv /tmp/manifest-tmp.json "$REPO/data/manifest.json"

# Git commit and push with retry
cd "$REPO"
git add "data/$MONTH_KEY.json" data/manifest.json
git commit -m "enrich: $MONTH_KEY — $TAGGED/$TOTAL tagged, $IMAGES images, $EXT_LINKS ext links" || { echo "[skip commit] nothing changed"; exit 0; }
for attempt in 1 2 3; do
    git pull --rebase origin main && git push origin main && break
    echo "  Push attempt $attempt failed, retrying..."
    sleep 5
done

echo "[pushed] $MONTH_KEY"
