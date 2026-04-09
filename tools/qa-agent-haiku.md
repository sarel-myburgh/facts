# Facts Q&A Agent

Answer a question, explore a topic, or audit the facts database for data quality issues.

---

## Mode A — Answer a question

**Input:** `{{QUERY}}`

### Step 1 — Extract search terms

Identify 2–4 key concepts from the query (subject, field, era, place, person).

### Step 2 — Search facts

```bash
python3 - "TERM1" "TERM2" <<'PY'
import json, glob, sys

query_terms = [t.lower() for t in sys.argv[1:]]
results = []

for path in sorted(glob.glob("/home/sarel/facts/data/*.json")):
    try:
        data = json.load(open(path))
    except Exception:
        continue
    month = data.get("month", path)
    for fact in data.get("facts", []):
        tags = [t.lower() for t in fact.get("tags", [])]
        text = fact.get("text", "").lower()
        score = sum(
            1 for term in query_terms
            if any(term in tag for tag in tags) or term in text
        )
        if score > 0:
            results.append((score, month, fact["id"], fact["text"], tags))

results.sort(key=lambda x: -x[0])
for score, month, fid, text, tags in results[:15]:
    print(f"[{month}] {text}")
    print(f"  tags: {', '.join(tags)}")
    print()
PY
```

### Step 3 — Answer

Synthesise a clear, concise answer. Quote fact text directly where useful. If fewer than 3 results found, note the database may not cover this topic well.

> **Answer:** ...
>
> **Supporting facts:**
> - [month] fact text

---

## Mode B — Scan for garbage tags

Detects facts that have 10 tags but fail validation (e.g. single words, sentence fragments, filler words, tags that are too long). These are invisible to the normal tagger because it skips facts with `len(tags) >= 10`.

```bash
python3 - <<'PY'
import json, glob

FILLER = {
    "facts", "knowledge", "interesting", "trivia", "amazing", "information",
    "notable", "important", "significant", "unique", "unusual", "rare",
    "general", "various", "miscellaneous", "overview", "topic", "subject",
    "stuff", "things", "other",
}

def compact(s):
    return " ".join(s.split())

def valid(tags):
    if not isinstance(tags, list) or len(tags) != 10:
        return False
    seen = set()
    for tag in tags:
        if not isinstance(tag, str):
            return False
        tag = compact(tag.strip())
        if tag != tag.lower() or "," in tag or "/" in tag:
            return False
        words = tag.split()
        if not (1 <= len(words) <= 5):
            return False
        if tag in FILLER or tag in seen:
            return False
        seen.add(tag)
    return True

bad_months = []
total_bad = 0

for path in sorted(glob.glob("/home/sarel/facts/data/*.json")):
    try:
        data = json.load(open(path))
    except Exception:
        continue
    month_key = path.split("/")[-1].replace(".json", "")
    bad = [
        (i, f) for i, f in enumerate(data.get("facts", []))
        if f.get("tags") and not valid(f.get("tags", []))
    ]
    if bad:
        bad_months.append((month_key, bad))
        total_bad += len(bad)
        print(f"{month_key}: {len(bad)} invalid facts")
        for i, f in bad[:3]:
            print(f"  idx={i} tags={f['tags']}")

print(f"\nTotal: {total_bad} facts with garbage tags across {len(bad_months)} months")
print("Fix: clear their tags and rerun the tagger on those months.")
PY
```

To fix after scanning, clear the bad tags and rerun:

```bash
python3 - <<'PY'
import json
from pathlib import Path

# Populate from scan output above
bad = {
    # "month_key": [idx1, idx2, ...],
}

for month, idxs in bad.items():
    path = Path(f"/home/sarel/facts/data/{month}.json")
    data = json.loads(path.read_text())
    for i in idxs:
        data["facts"][i]["tags"] = []
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Cleared {len(idxs)} facts in {month}")
PY
```

Then rerun the tagger:
```bash
cd /home/sarel/facts
python3 tools/run_tags_gemini.py MONTH_KEY --provider haiku
```
