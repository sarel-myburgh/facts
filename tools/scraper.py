#!/usr/bin/env python3
"""
scraper.py — Wikipedia DYK + Today In History scraper
Populates data/facts.db with fact text, source links, and infobox images.
No AI, no tags — tags are the tagger agent's job.

Usage:
  python tools/scraper.py dyk          # Did You Know archive only
  python tools/scraper.py tih          # Today In History (Selected Anniversaries) only
  python tools/scraper.py all          # Both sources
  python tools/scraper.py all --no-images  # Skip infobox image fetching (faster)

Idempotent: SHA-256 hash dedup prevents duplicates on re-run.
"""

import re
import sys
import time
import hashlib
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH    = Path(__file__).parent.parent / 'data' / 'facts.db'
WIKI_BASE  = 'https://en.wikipedia.org'
DELAY      = 0.75   # seconds between page requests (polite to Wikipedia)
IMG_DELAY  = 0.5    # seconds between infobox image fetches
HEADERS    = {
    'User-Agent': (
        'BokyLearnScraper/1.0 '
        '(https://github.com/sarel-myburgh/facts; educational facts app)'
    )
}

# ── DB helpers ─────────────────────────────────────────────────────────────────

def open_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS facts (
            id         TEXT PRIMARY KEY,
            hash       TEXT UNIQUE NOT NULL,
            text       TEXT NOT NULL,
            image_url  TEXT,
            mature     INTEGER DEFAULT 0,
            source     TEXT,
            scraped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS fact_tags (
            fact_id TEXT NOT NULL REFERENCES facts(id),
            tag     TEXT NOT NULL,
            PRIMARY KEY (fact_id, tag)
        );
        CREATE TABLE IF NOT EXISTS fact_links (
            fact_id TEXT NOT NULL REFERENCES facts(id),
            url     TEXT NOT NULL,
            title   TEXT,
            source  TEXT,
            PRIMARY KEY (fact_id, url)
        );
    """)
    conn.commit()
    return conn


def make_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


def insert_fact(conn, text: str, links: list, image_url, source: str) -> bool:
    """Insert a fact. Returns True if new, False if duplicate (by hash)."""
    h = make_hash(text)
    c = conn.cursor()
    if c.execute('SELECT 1 FROM facts WHERE hash = ?', (h,)).fetchone():
        return False
    fid       = str(uuid.uuid4())
    scraped   = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    c.execute(
        'INSERT INTO facts (id, hash, text, image_url, mature, source, scraped_at)'
        ' VALUES (?,?,?,?,0,?,?)',
        (fid, h, text, image_url, source, scraped)
    )
    for (url, title, lsrc) in links:
        c.execute(
            'INSERT OR IGNORE INTO fact_links (fact_id, url, title, source)'
            ' VALUES (?,?,?,?)',
            (fid, url, title, lsrc)
        )
    return True

# ── HTTP helpers ──────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def get_soup(url: str, delay: float = DELAY, retries: int = 3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            time.sleep(delay)
            return BeautifulSoup(r.text, 'html.parser')
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None   # page doesn't exist — not an error
            print(f'    [warn] {url}: HTTP {e}', flush=True)
        except Exception as e:
            print(f'    [warn] {url}: {e}', flush=True)
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return None


def get_infobox_image(article_path: str) -> str | None:
    """Return the first infobox thumbnail URL from a Wikipedia article."""
    soup = get_soup(WIKI_BASE + article_path, delay=IMG_DELAY)
    if not soup:
        return None
    infobox = soup.find('table', class_=re.compile(r'\binfobox\b'))
    if not infobox:
        return None
    img = infobox.find('img')
    if not img or not img.get('src'):
        return None
    src = img['src']
    if src.startswith('//'):
        src = 'https:' + src
    # Upgrade thumbnail to full-size (//upload.wikimedia.org/…/thumb/…/200px-… → without /thumb/…px-)
    src = re.sub(r'/thumb(/[^/]+/[^/]+/[^/]+)/\d+px-[^/]+$', r'\1', src)
    return src


def extract_wiki_links(tag) -> list:
    """Extract Wikipedia article links from a BeautifulSoup tag."""
    links = []
    seen = set()
    for a in tag.find_all('a', href=True):
        href = a['href']
        # Only /wiki/ links, no special pages
        if not href.startswith('/wiki/'):
            continue
        # Skip Wikipedia meta-pages and file/category pages
        if re.match(r'/wiki/(Wikipedia|File|Category|Help|Template|Talk|Special):', href):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get('title') or a.get_text(strip=True)
        links.append((WIKI_BASE + href, title, 'Wikipedia'))
    return links

# ── Text cleaners ─────────────────────────────────────────────────────────────

_PICTURED_RE = re.compile(r'\([^)]*\bpictured\b[^)]*\)', re.IGNORECASE)
_SPACE_RE    = re.compile(r'  +')

def clean_hook(raw: str) -> str:
    """Strip '... that' prefix, (pictured) markers, trailing '?', extra spaces."""
    t = raw.strip()
    t = re.sub(r'^\.\.\.\s*that\s+', '', t, flags=re.IGNORECASE)
    t = _PICTURED_RE.sub('', t)
    t = _SPACE_RE.sub(' ', t).strip()
    t = t.rstrip('?').strip()
    if t:
        t = t[0].upper() + t[1:]
    return t


def clean_tih(raw: str) -> str:
    """Strip leading year + dash, (pictured), extra whitespace."""
    t = raw.strip()
    t = re.sub(r'^\d{1,4}\s*[–—\-]+\s*', '', t)
    t = _PICTURED_RE.sub('', t)
    t = _SPACE_RE.sub(' ', t).strip()
    return t

# ── DYK scraper ───────────────────────────────────────────────────────────────

MONTHS = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]


def dyk_urls() -> list:
    now = datetime.utcnow()
    urls = []
    for year in range(2004, now.year + 1):
        for i, month in enumerate(MONTHS, start=1):
            if year == 2004 and i < 10:   # archive starts ~Oct 2004
                continue
            if year == now.year and i > now.month:
                break
            urls.append(
                f'{WIKI_BASE}/wiki/Wikipedia:Did_you_know_archive/{year}/{month}'
            )
    return urls


def scrape_dyk_page(conn, url: str, fetch_images: bool) -> tuple[int, int]:
    soup = get_soup(url)
    if not soup:
        return 0, 0

    content = soup.find('div', id='mw-content-text')
    if not content:
        return 0, 0

    ins = skip = 0
    for li in content.find_all('li'):
        raw = li.get_text(' ', strip=True)
        if not raw.startswith('...'):
            continue

        has_pictured = bool(_PICTURED_RE.search(raw))
        text = clean_hook(raw)
        if len(text) < 25:
            continue

        image_url = None
        if fetch_images and has_pictured:
            bold_a = (li.find('b') or li).find('a', href=True)
            if bold_a and bold_a['href'].startswith('/wiki/'):
                image_url = get_infobox_image(bold_a['href'])

        links = extract_wiki_links(li)
        if insert_fact(conn, text, links, image_url, 'dyk'):
            ins += 1
        else:
            skip += 1

    return ins, skip


def scrape_dyk(conn, fetch_images: bool):
    urls = dyk_urls()
    total_ins = total_skip = 0
    print(f'DYK: {len(urls)} archive pages', flush=True)
    for i, url in enumerate(urls, 1):
        label = '/'.join(url.split('/')[-2:])
        ins, skip = scrape_dyk_page(conn, url, fetch_images)
        conn.commit()
        total_ins  += ins
        total_skip += skip
        print(f'  [{i:>3}/{len(urls)}] {label:<22}  +{ins:<4} new  {skip} dupes', flush=True)
    print(f'DYK done — {total_ins} inserted, {total_skip} dupes\n', flush=True)

# ── TIH scraper ───────────────────────────────────────────────────────────────

MONTH_DAYS = {
    'January': 31, 'February': 29, 'March': 31, 'April': 30,
    'May': 31, 'June': 30, 'July': 31, 'August': 31,
    'September': 30, 'October': 31, 'November': 30, 'December': 31,
}

_YEAR_PREFIX = re.compile(r'^\d{1,4}\s*[–—\-]')

# Section headings that signal we've left the historical events section
_SKIP_HEADINGS = re.compile(
    r'\b(born|died|death|birth|holiday|observance|ineligible)\b', re.IGNORECASE
)
_ELIGIBLE_RE = re.compile(r'\beligible\b', re.IGNORECASE)


def tih_urls() -> list:
    urls = []
    for month, days in MONTH_DAYS.items():
        for day in range(1, days + 1):
            urls.append(
                f'{WIKI_BASE}/wiki/Wikipedia:Selected_anniversaries/{month}_{day}'
            )
    return urls


def scrape_tih_page(conn, url: str, fetch_images: bool) -> tuple[int, int]:
    soup = get_soup(url)
    if not soup:
        return 0, 0

    content = soup.find('div', id='mw-content-text')
    if not content:
        return 0, 0

    ins = skip = 0
    in_events = True   # assume events section until a skip-heading is found

    for el in content.find_all(['h2', 'h3', 'h4', 'li']):
        if el.name in ('h2', 'h3', 'h4'):
            heading = el.get_text(' ', strip=True)
            if _SKIP_HEADINGS.search(heading):
                in_events = False
            elif _ELIGIBLE_RE.search(heading):
                in_events = True
            continue

        if not in_events:
            continue

        raw = el.get_text(' ', strip=True)
        if not _YEAR_PREFIX.match(raw):
            continue

        has_pictured = bool(_PICTURED_RE.search(raw))
        text = clean_tih(raw)
        if len(text) < 25:
            continue

        image_url = None
        if fetch_images and has_pictured:
            bold_a = (el.find('b') or el).find('a', href=True)
            if bold_a and bold_a['href'].startswith('/wiki/'):
                image_url = get_infobox_image(bold_a['href'])

        links = extract_wiki_links(el)
        if insert_fact(conn, text, links, image_url, 'tih'):
            ins += 1
        else:
            skip += 1

    return ins, skip


def scrape_tih(conn, fetch_images: bool):
    urls = tih_urls()
    total_ins = total_skip = 0
    print(f'TIH: {len(urls)} daily pages', flush=True)
    for i, url in enumerate(urls, 1):
        label = url.split('/')[-1]
        ins, skip = scrape_tih_page(conn, url, fetch_images)
        conn.commit()
        total_ins  += ins
        total_skip += skip
        print(f'  [{i:>3}/{len(urls)}] {label:<18}  +{ins:<4} new  {skip} dupes', flush=True)
    print(f'TIH done — {total_ins} inserted, {total_skip} dupes\n', flush=True)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = [a.lower() for a in sys.argv[1:]]
    mode = next((a for a in args if a in ('dyk', 'tih', 'all')), 'all')
    fetch_images = '--no-images' not in args

    if fetch_images:
        print('Images: ON  (add --no-images to skip infobox fetching)', flush=True)
    else:
        print('Images: OFF', flush=True)

    conn = open_db()

    t0 = time.time()
    if mode in ('dyk', 'all'):
        scrape_dyk(conn, fetch_images)
    if mode in ('tih', 'all'):
        scrape_tih(conn, fetch_images)

    total = conn.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
    elapsed = time.time() - t0
    print(f'Total facts in DB: {total}  |  elapsed: {elapsed:.0f}s')
    conn.close()


if __name__ == '__main__':
    main()
