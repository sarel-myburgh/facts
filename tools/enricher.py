#!/usr/bin/env python3
"""
enricher.py — Enrich facts JSON with tags, images, and additional links.

For each fact (processed in chronological file order):
  1. Generate 10 relevant tags via the local Gemini CLI
  2. Find a relevant image URL (Wikipedia page thumbnail → Wikimedia Commons search)
  3. Find ≥1 additional non-Wikipedia link (via Wikipedia external-links API,
     filtered to reputable sources: Britannica, NatGeo, NASA, BBC, Smithsonian, etc.)

Progress is saved after every fact. Re-running skips already-enriched facts.

Usage:
  python tools/enricher.py                   # process all files
  python tools/enricher.py --file 2025_Jan   # process one file only
  python tools/enricher.py --limit 20        # process first N unenriched facts
  python tools/enricher.py --dry-run         # preview without writing

Requirements:
  pip install requests openai
  OPENROUTER_API_KEY must be set in environment (or hardcoded below as fallback)
"""

import argparse
import base64
import json
import html
from html import unescape
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
# ── Config ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"

# Seconds between Wikipedia API calls (be polite)
WIKI_DELAY = 0.4
# Seconds between Gemini CLI calls
OR_DELAY = 2.0
# Facts per OpenRouter batch (tag generation)
BATCH_SIZE = 12
GEMINI_MODEL = "gemini-2.5-flash"

HEADERS = {
    "User-Agent": (
        "FactsEnricher/1.0 "
        "(https://github.com/sarel-myburgh/facts; educational app enrichment bot)"
    )
}

# Ordered list of reputable non-Wikipedia domains to prefer for additional links.
# Checked in order — first match wins.
REPUTABLE_DOMAINS = [
    "britannica.com",
    "nationalgeographic.com",
    "natgeo.com",
    "nasa.gov",
    "noaa.gov",
    "smithsonianmag.com",
    "si.edu",          # Smithsonian Institution
    "bbc.com",
    "bbc.co.uk",
    "nature.com",
    "scientificamerican.com",
    "science.org",
    "pbs.org",
    "loc.gov",         # Library of Congress
    "archives.gov",    # US National Archives
    "metmuseum.org",
    "nhm.ac.uk",       # Natural History Museum London
    "amnh.org",        # American Museum of Natural History
    "iucn.org",
    "iucnredlist.org",
    "who.int",
    "un.org",
    "worldwildlife.org",
    "history.com",
    "historyextra.com",
    "theatlantic.com",
    "nytimes.com",
    "theguardian.com",
    "reuters.com",
]

SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "been", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has", "have",
    "he", "her", "his", "i", "if", "in", "into", "is", "it", "its", "just",
    "last", "more", "most", "my", "not", "of", "on", "one", "or", "our", "out",
    "over", "she", "some", "that", "the", "their", "them", "there", "these",
    "they", "this", "those", "to", "too", "use", "was", "were", "what", "when",
    "where", "which", "who", "will", "with", "would",
}

BAD_IMAGE_DOMAINS = {
    "alamy.com",
    "allpostersimages.com",
    "dreamstime.com",
    "ftcdn.net",
    "gettyimages.com",
    "licdn.com",
    "istockphoto.com",
    "media.istockphoto.com",
    "shutterstock.com",
    "depositphotos.com",
    "123rf.com",
    "pinimg.com",
    "made-in-china.com",
    "topdiplomaservice.com",
}

SEARCHABLE_REPUTABLE_DOMAINS = [
    "britannica.com",
    "nationalgeographic.com",
    "natgeo.com",
    "nasa.gov",
    "noaa.gov",
    "smithsonianmag.com",
    "si.edu",
    "bbc.com",
    "bbc.co.uk",
    "nature.com",
    "scientificamerican.com",
    "science.org",
    "pbs.org",
    "loc.gov",
    "archives.gov",
    "metmuseum.org",
    "nhm.ac.uk",
    "amnh.org",
    "iucn.org",
    "iucnredlist.org",
    "who.int",
    "un.org",
    "worldwildlife.org",
    "history.com",
    "historyextra.com",
    "theatlantic.com",
    "nytimes.com",
    "theguardian.com",
    "reuters.com",
    "cbc.ca",
]

# File order: Jan → Dec
MONTH_ORDER = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# ── Manifest helpers ──────────────────────────────────────────────────────────

def load_manifest() -> dict:
    base_months: dict = {}
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", "HEAD:data/manifest.json"],
            capture_output=True,
            text=True,
            check=True,
        )
        base = json.loads(result.stdout)
        months = base.get("months", {})
        if isinstance(months, dict):
            base_months = months
    except Exception:
        pass

    if not MANIFEST_PATH.exists():
        return {"months": base_months}

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    months = data.get("months", {})
    if not isinstance(months, dict):
        months = {}

    merged = dict(base_months)
    merged.update(months)
    return {"months": merged}


def save_manifest(manifest: dict) -> None:
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def manifest_entry_for_file(path: Path) -> dict:
    data = load_json(path)
    facts = data.get("facts", [])
    total_facts = len(facts)
    tagged_facts = sum(1 for f in facts if len(f.get("tags", [])) >= 10)
    linked_facts = sum(
        1
        for f in facts
        if any("wikipedia" not in l.get("url", "").lower() for l in f.get("links", []))
    )
    return {
        "tags": tagged_facts == total_facts,
        "links": linked_facts == total_facts,
        "tagged_facts": tagged_facts,
        "linked_facts": linked_facts,
        "total_facts": total_facts,
    }


def rebuild_manifest_from_files() -> dict:
    manifest = load_manifest()
    months = dict(manifest.get("months", {}))
    for path in sorted_data_files():
        existing = months.get(path.stem, {})
        entry = manifest_entry_for_file(path)
        # Preserve existing version — bump happens only in update_manifest_for_file.
        entry['version'] = existing.get('version', 1)
        months[path.stem] = entry
    manifest["months"] = months
    return manifest


def update_manifest_for_file(path: Path, facts: list[dict]) -> None:
    """
    Mark a month as tagged/linked in the manifest based on current file state.
    Bumps the month's version so the app knows to re-download enriched data.
    Images are intentionally not tracked here.
    """
    manifest = rebuild_manifest_from_files()
    key = path.stem
    if key in manifest["months"]:
        manifest["months"][key]['version'] = manifest["months"][key].get('version', 1) + 1
    save_manifest(manifest)

# ── Helpers ───────────────────────────────────────────────────────────────────

def sorted_data_files() -> list[Path]:
    """Return DYK and TIH data files sorted chronologically."""
    files = list(DATA_DIR.glob("dyk_*.json")) + list(DATA_DIR.glob("tih_*.json"))

    def sort_key(p: Path) -> tuple:
        # e.g. dyk_2025_Jan → (0, 2025, 0), tih_Jan → (1, 0, 0)
        parts = p.stem.split("_")  # ['dyk', '2025', 'Jan']
        if not parts:
            return (9, 9999, 99)
        prefix = parts[0]
        if prefix == "dyk":
            if len(parts) < 3:
                return (0, 9999, 99)
            year = int(parts[1]) if parts[1].isdigit() else 9999
            month_idx = MONTH_ORDER.index(parts[2]) if parts[2] in MONTH_ORDER else 99
            return (0, year, month_idx)
        if prefix == "tih":
            if len(parts) < 2:
                return (1, 9999, 99)
            month_idx = MONTH_ORDER.index(parts[1]) if parts[1] in MONTH_ORDER else 99
            return (1, 0, month_idx)
        return (9, 9999, 99)

    return sorted(files, key=sort_key)


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def is_enriched(fact: dict, include_image: bool = True) -> bool:
    """Return True if this fact is already fully enriched."""
    has_tags = len(fact.get("tags", [])) >= 10
    image = fact.get("image", {})
    has_image = bool(image.get("url")) and not is_likely_bad_thumbnail(
        image.get("url", ""),
        image.get("caption", ""),
    )
    links = fact.get("links", [])
    has_extra_link = any("wikipedia" not in l.get("url", "").lower() for l in links)
    return has_tags and has_extra_link and (has_image if include_image else True)


def needs_tags(fact: dict) -> bool:
    return len(fact.get("tags", [])) < 10


def needs_image(fact: dict) -> bool:
    image = fact.get("image", {})
    if not image.get("url"):
        return True
    return is_likely_bad_thumbnail(image.get("url", ""), image.get("caption", ""))


def needs_extra_link(fact: dict) -> bool:
    links = fact.get("links", [])
    return not any("wikipedia" not in l.get("url", "").lower() for l in links)


# ── Wikipedia API ─────────────────────────────────────────────────────────────

def wiki_title_from_url(url: str) -> Optional[str]:
    """Extract Wikipedia page title from a Wikipedia URL."""
    m = re.search(r"wikipedia\.org/wiki/(.+)$", url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None


def score_wiki_title(title: str, fact_text: str) -> int:
    """Heuristic score for how well a wiki title matches a fact."""
    title_norm = re.sub(r"[_\s]+", " ", title).lower().strip()
    fact_norm = re.sub(r"[^a-z0-9\s]+", " ", fact_text.lower())
    title_tokens = [t for t in re.findall(r"[a-z0-9]+", title_norm) if len(t) > 2]
    fact_tokens = set(re.findall(r"[a-z0-9]+", fact_norm))

    score = 0
    for token in title_tokens:
        if token in fact_tokens:
            score += 2
    if title_norm and title_norm in fact_norm:
        score += 8
    if title_tokens and fact_tokens:
        score += min(len(set(title_tokens) & fact_tokens), 3)
    return score


def build_search_query(fact_text: str, title: str | None = None) -> str:
    """Build a compact keyword query from the fact text and optional wiki title."""
    parts: list[str] = []
    seen: set[str] = set()

    def add_tokens(source: str) -> None:
        for token in re.findall(r"[a-z0-9]+", source.lower()):
            if len(token) < 4 or token in SEARCH_STOPWORDS or token in seen:
                continue
            seen.add(token)
            parts.append(token)

    if title:
        add_tokens(title.replace("_", " "))
    add_tokens(fact_text)
    return " ".join(parts[:8]) or fact_text[:80]


def decode_bing_redirect(href: str) -> Optional[str]:
    """Decode a Bing redirect URL to the final destination."""
    href = html.unescape(href.replace("&amp;", "&"))
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    u = qs.get("u", [""])[0]
    if not u:
        return None
    if u.startswith("a1"):
        raw = u[2:]
        try:
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
            return decoded
        except Exception:
            return None
    return urllib.parse.unquote(u)


def rank_wiki_links(fact: dict) -> list[tuple[int, str, str]]:
    """Return Wikipedia links ranked by relevance to the fact text."""
    seen_urls = set()
    ranked: list[tuple[int, str, str]] = []
    fact_text = fact.get("text", "")
    for link in fact.get("links", []):
        url = link.get("url", "")
        if "wikipedia.org/wiki/" not in url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = wiki_title_from_url(url)
        if not title:
            continue
        ranked.append((score_wiki_title(title, fact_text), title, url))
    ranked.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return ranked


def fetch_wiki_thumbnail(title: str) -> Optional[tuple[str, str]]:
    """
    Fetch the main thumbnail image for a Wikipedia article.
    Returns (image_url, caption) or None.
    Uses the Wikipedia REST Summary API.
    """
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe=":/")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            thumb = data.get("thumbnail", {})
            src = thumb.get("source")
            if src:
                # Prefer original-resolution image
                original = data.get("originalimage", {}).get("source", src)
                caption = data.get("title", title)
                return original, caption
    except Exception:
        pass
    return None


def fetch_wiki_infobox_image(title: str) -> Optional[tuple[str, str]]:
    """
    Fetch the first image from a Wikipedia article infobox.
    Returns (image_url, caption) or None.
    """
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "redirects": "1",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        html = data.get("parse", {}).get("text", {}).get("*", "")
        if not html:
            return None
        m = re.search(r'<table[^>]*class="[^"]*infobox[^"]*"[^>]*>(.*?)</table>', html, re.I | re.S)
        if not m:
            return None
        block = m.group(1)
        img = re.search(r'<img[^>]+src="(?P<src>[^"]+)"[^>]*?(?:alt="(?P<alt>[^"]*)")?[^>]*>', block, re.I | re.S)
        if not img:
            return None
        src = img.group("src")
        if not src:
            return None
        if src.startswith("//"):
            src = "https:" + src
        src = src.split("?", 1)[0]
        caption = img.group("alt") or title
        return src, caption
    except Exception:
        return None


def is_likely_bad_thumbnail(url: str, caption: str) -> bool:
    """
    Reject thumbnails that are probably scans, newspaper pages, or book/page dumps.
    These often show up as technically valid thumbnails but are poor fact images.
    """
    haystack = f"{url} {caption}".lower()
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        host = ""
    if any(domain in host for domain in BAD_IMAGE_DOMAINS):
        return True
    return any(
        marker in haystack
        for marker in (
            ".pdf.jpg",
            "/page",
            "newspaper",
            "scan",
            "book scan",
            "ia_",
            "oojs_ui_icon",
            "edit-ltr",
            "placeholder",
        )
    )


def fetch_page_og_image(page_url: str) -> Optional[tuple[str, str]]:
    """Fetch an Open Graph image from an arbitrary web page."""
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=10)
        if r.status_code != 200 or not r.text:
            return None
        text = r.text
        patterns = [
            r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:image(?:secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                src = unescape(m.group(1)).strip()
                if src.startswith("//"):
                    src = "https:" + src
                src = src.split("?", 1)[0]
                if src:
                    title_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', text, re.I | re.S)
                    caption = unescape(title_m.group(1)).strip() if title_m else page_url
                    return src, caption
    except Exception:
        return None
    return None


def search_web_for_image(query: str) -> Optional[tuple[str, str]]:
    """
    Use a real web search to find a likely-relevant image when Wikipedia fails.
    We search Bing Images and use the best-matching result card.
    """
    try:
        r = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if r.status_code != 200 or not r.text:
            return None
        query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        cards: list[tuple[int, str, str]] = []
        for m in re.finditer(r'<a[^>]+class="[^"]*iusc[^"]*"[^>]+m="([^"]+)"', r.text, re.I | re.S):
            raw = unescape(m.group(1))
            try:
                card = json.loads(raw)
            except Exception:
                continue
            murl = card.get("murl") or ""
            if not murl:
                continue
            purl = card.get("purl", "")
            title = card.get("t") or card.get("desc") or ""
            haystack = " ".join([query, purl, title, card.get("desc", "")]).lower()
            score = sum(1 for term in query_terms if term in haystack)
            cards.append((score, murl, title))

        cards.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
        min_score = max(2, min(4, len(query_terms) // 2 or 2))
        for score, img_url, caption in cards[:8]:
            if score < min_score:
                continue
            if not is_likely_bad_thumbnail(img_url, caption):
                return img_url, caption or query
    except Exception:
        return None
    return None


def search_web_for_link(query: str) -> Optional[dict]:
    """
    Use Bing web search to find a reputable non-Wikipedia source link.
    Returns {"url": ..., "source": ...} or None.
    """
    try:
        r = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if r.status_code != 200 or not r.text:
            return None

        query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        best: list[tuple[int, str, str]] = []

        for block in re.finditer(r'<li class="b_algo"[^>]*>(.*?)</li>', r.text, re.I | re.S):
            chunk = block.group(1)
            m = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.I | re.S)
            if not m:
                continue
            href = decode_bing_redirect(m.group(1))
            if not href:
                continue
            parsed = urllib.parse.urlparse(href)
            domain = parsed.netloc.lower()
            if not domain or "wikipedia.org" in domain or any(bad in domain for bad in BAD_IMAGE_DOMAINS):
                continue
            if not any(dom in domain for dom in SEARCHABLE_REPUTABLE_DOMAINS):
                continue

            title = re.sub(r"<.*?>", "", html.unescape(m.group(2))).strip()
            snippet_m = re.search(r'<div class="b_caption"><p[^>]*>(.*?)</p>', chunk, re.I | re.S)
            snippet = re.sub(r"<.*?>", "", html.unescape(snippet_m.group(1))).strip() if snippet_m else ""
            haystack = " ".join([query, title, snippet, href]).lower()
            score = sum(1 for term in query_terms if term in haystack)
            best.append((score, href, domain))

        best.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        if best:
            href = best[0][1]
            domain = best[0][2]
            return {"url": href, "source": domain_label(domain)}
    except Exception:
        return None
    return None


def fetch_wiki_extlinks(title: str) -> list[dict]:
    """
    Fetch external links from a Wikipedia article via the MediaWiki API.
    Returns a list of {url, title} dicts filtered to reputable domains.
    """
    api_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extlinks",
        "titles": title,
        "format": "json",
        "ellimit": "100",
        "redirects": "1",
    }
    try:
        r = requests.get(api_url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        all_links = []
        for page in pages.values():
            for el in page.get("extlinks", []):
                raw = el.get("*", "")
                if raw:
                    all_links.append(raw)

        # Filter and rank by REPUTABLE_DOMAINS order
        results = []
        for domain in REPUTABLE_DOMAINS:
            for link in all_links:
                if domain in link:
                    results.append({"url": link, "source": domain_label(domain)})
                    break  # one per domain
        return results
    except Exception:
        return []


def domain_label(domain: str) -> str:
    """Convert a domain string to a human-readable source label."""
    LABELS = {
        "britannica.com": "Britannica",
        "nationalgeographic.com": "National Geographic",
        "natgeo.com": "National Geographic",
        "nasa.gov": "NASA",
        "noaa.gov": "NOAA",
        "smithsonianmag.com": "Smithsonian Magazine",
        "si.edu": "Smithsonian Institution",
        "bbc.com": "BBC",
        "bbc.co.uk": "BBC",
        "nature.com": "Nature",
        "scientificamerican.com": "Scientific American",
        "science.org": "Science",
        "pbs.org": "PBS",
        "loc.gov": "Library of Congress",
        "archives.gov": "National Archives",
        "metmuseum.org": "The Met",
        "nhm.ac.uk": "Natural History Museum",
        "amnh.org": "AMNH",
        "iucn.org": "IUCN",
        "iucnredlist.org": "IUCN Red List",
        "who.int": "WHO",
        "un.org": "United Nations",
        "worldwildlife.org": "WWF",
        "history.com": "History",
        "historyextra.com": "History Extra",
        "theatlantic.com": "The Atlantic",
        "nytimes.com": "New York Times",
        "theguardian.com": "The Guardian",
        "reuters.com": "Reuters",
    }
    return LABELS.get(domain, domain)


def generate_tags_batch(facts: list[dict]) -> dict[str, list[str]]:
    """
    Send a batch of facts to Gemini CLI and get 10 tags for each.
    Returns a dict mapping str(1-based index) → list[str].
    """
    lines = []
    for i, fact in enumerate(facts, 1):
        lines.append(f"{i}. {fact['text']}")
    prompt = (
        "No tools. Respond only with a JSON object mapping each fact number "
        "to exactly 10 lowercase tags. Generate 10 tags for each of these facts:\n\n"
        + "\n".join(lines)
    )

    for attempt in range(3):
        try:
            resp = subprocess.run(
                [
                    "gemini",
                    "-m",
                    GEMINI_MODEL,
                    "-o",
                    "json",
                    "-p",
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            out = resp.stdout.strip()
            if not out:
                raise RuntimeError(resp.stderr.strip() or "gemini returned no output")
            payload = json.loads(out)
            raw = payload.get("response", "").strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            result = json.loads(raw)
            return result
        except json.JSONDecodeError as e:
            print(f"  [warn] JSON parse error on attempt {attempt+1}: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  [warn] Gemini error on attempt {attempt+1}: {e}")
            msg = str(e)
            wait_s = 15
            m = re.search(r"reset after (\d+)s", msg)
            if m:
                wait_s = max(wait_s, int(m.group(1)) + 2)
            time.sleep(wait_s)
    return {}


# ── Main enrichment logic ─────────────────────────────────────────────────────

def enrich_image(fact: dict, dry_run: bool) -> bool:
    """Try to find and set an image for the fact. Returns True if found."""
    ranked_links = rank_wiki_links(fact)
    if not ranked_links:
        return False

    for _, title, _ in ranked_links:
        result = fetch_wiki_infobox_image(title)
        time.sleep(WIKI_DELAY)
        if result:
            img_url, caption = result
            if is_likely_bad_thumbnail(img_url, caption):
                continue
            print(f"    [image] {img_url[:80]}...")
            if not dry_run:
                fact["image"]["url"] = img_url
                fact["image"]["caption"] = caption
            return True

        result = fetch_wiki_thumbnail(title)
        time.sleep(WIKI_DELAY)
        if result:
            img_url, caption = result
            if is_likely_bad_thumbnail(img_url, caption):
                continue
            print(f"    [image] {img_url[:80]}...")
            if not dry_run:
                fact["image"]["url"] = img_url
                fact["image"]["caption"] = caption
            return True

    search_query = build_search_query(fact.get("text", ""), ranked_links[0][1] if ranked_links else None)
    result = search_web_for_image(search_query)
    if result:
        img_url, caption = result
        if not is_likely_bad_thumbnail(img_url, caption):
            print(f"    [image] {img_url[:80]}...")
            if not dry_run:
                fact["image"]["url"] = img_url
                fact["image"]["caption"] = caption
            return True
    return False


def enrich_links(fact: dict, dry_run: bool) -> bool:
    """Try to find and add ≥1 reputable non-Wikipedia link. Returns True if found."""
    ranked_links = rank_wiki_links(fact)
    if not ranked_links:
        return False

    existing_urls = {l.get("url", "") for l in fact.get("links", [])}
    found_any = False

    for _, title, _ in ranked_links:
        candidates = fetch_wiki_extlinks(title)
        time.sleep(WIKI_DELAY)

        for candidate in candidates:
            url = candidate["url"]
            if url not in existing_urls:
                print(f"    [link] {candidate['source']}: {url[:70]}...")
                if not dry_run:
                    fact["links"].append({
                        "url": url,
                        "title": candidate["source"],
                        "source": candidate["source"],
                    })
                existing_urls.add(url)
                found_any = True
                break  # one new link per wiki article is enough

        if found_any:
            break

    if not found_any:
        search_query = build_search_query(fact.get("text", ""), ranked_links[0][1] if ranked_links else None)
        result = search_web_for_link(search_query)
        if result:
            url = result["url"]
            if url not in existing_urls:
                print(f"    [link] {result['source']}: {url[:70]}...")
                if not dry_run:
                    fact["links"].append({
                        "url": url,
                        "title": result["source"],
                        "source": result["source"],
                    })
                found_any = True

    return found_any


def process_file(
    path: Path,
    dry_run: bool = False,
    limit: Optional[int] = None,
    no_images: bool = False,
) -> int:
    """Process a single JSON file. Returns count of facts enriched."""
    data = load_json(path)
    facts = data.get("facts", [])
    enriched_count = 0

    # Identify facts that need work
    pending = [f for f in facts if not is_enriched(f, include_image=not no_images)]
    if limit:
        pending = pending[:limit]

    if not pending:
        print(f"  [skip] {path.name} — all {len(facts)} facts already enriched")
        if not dry_run:
            update_manifest_for_file(path, facts)
        return 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Processing {path.name}: "
          f"{len(pending)} facts need enrichment (out of {len(facts)} total)")

    # ── Phase 1: Tag generation (batched) ────────────────────────────────────
    needs_tag = [f for f in pending if needs_tags(f)]
    if needs_tag:
        print(f"  Generating tags for {len(needs_tag)} facts in batches of {BATCH_SIZE}...")
        for batch_start in range(0, len(needs_tag), BATCH_SIZE):
            batch = needs_tag[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(needs_tag) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"    Batch {batch_num}/{total_batches} ({len(batch)} facts)...", end=" ", flush=True)
            tag_map = generate_tags_batch(batch)
            time.sleep(OR_DELAY)
            applied = 0
            for i, fact in enumerate(batch, 1):
                tags = tag_map.get(str(i), [])
                if tags:
                    if not dry_run:
                        fact["tags"] = tags[:10]
                    applied += 1
            print(f"OK ({applied}/{len(batch)} tagged)")
        # Save after tagging phase
        if not dry_run:
            save_json(path, data)

    # ── Phase 2: Images + additional links (per-fact, interleaved) ───────────
    needs_img = [] if no_images else [f for f in pending if needs_image(f)]
    needs_lnk = [f for f in pending if needs_extra_link(f)]

    if needs_img or needs_lnk:
        all_targets = set(id(f) for f in needs_img) | set(id(f) for f in needs_lnk)
        target_facts = [f for f in pending if id(f) in all_targets]
        print(f"  Fetching images/links for {len(target_facts)} facts...")

        for idx, fact in enumerate(target_facts, 1):
            short_text = fact["text"][:60] + ("..." if len(fact["text"]) > 60 else "")
            print(f"  [{idx}/{len(target_facts)}] {short_text}")

            got_image = False
            got_link = False

            if not no_images and needs_image(fact):
                got_image = enrich_image(fact, dry_run)
                if not got_image:
                    print(f"    [image] not found")

            if needs_extra_link(fact):
                got_link = enrich_links(fact, dry_run)
                if not got_link:
                    print(f"    [link] not found")

            if (got_image or got_link) and not dry_run:
                save_json(path, data)

            enriched_count += 1

    if not dry_run:
        update_manifest_for_file(path, facts)

    return enriched_count


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich facts JSON files with tags, images, and links.")
    parser.add_argument("--file", help="Process only this file stem, e.g. 2025_Jan")
    parser.add_argument("--limit", type=int, help="Stop after enriching this many facts (across all files)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing any changes")
    parser.add_argument("--no-images", action="store_true", help="Skip image enrichment and only update tags/links")
    args = parser.parse_args()

    files = sorted_data_files()

    if args.file:
        files = [f for f in files if args.file in f.stem]
        if not files:
            print(f"No file matching '{args.file}' found in {DATA_DIR}")
            sys.exit(1)

    remaining_limit = args.limit
    total_enriched = 0

    for path in files:
        file_limit = remaining_limit
        count = process_file(path, dry_run=args.dry_run, limit=file_limit, no_images=args.no_images)
        total_enriched += count

        if remaining_limit is not None:
            remaining_limit -= count
            if remaining_limit <= 0:
                print(f"\nReached --limit of {args.limit}. Stopping.")
                break

    print(f"\nDone. Enriched {total_enriched} facts total.")


if __name__ == "__main__":
    main()
