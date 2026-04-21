#!/usr/bin/env python3
"""
scraper.py — Wikipedia DYK + Today In History scraper (JSON output)

Instead of writing to a SQLite database, this scraper writes per-month JSON
files to data/ and maintains a data/manifest.json index.

File naming:
  DYK  → data/dyk_2024_Feb.json   (one file per archive month)
  TIH  → data/tih_Jan.json        (one file per calendar month, scraped once)

manifest.json format:
  {
    "months": {
      "dyk_2004_Oct": {"tags": false, "links": false},
      "tih_Jan":      {"tags": false, "links": false},
      ...
    }
  }
  "tags" and "links" are set to true by the enrichment agents after they
  have processed that month.  Agents can quickly filter for unenriched months
  by checking which entries still have false values.

Usage:
  python tools/scraper.py dyk          # DYK only (new months)
  python tools/scraper.py tih          # TIH only (new calendar months)
  python tools/scraper.py all          # Both (default)
  python tools/scraper.py all --no-images
  python tools/scraper.py dyk --from-year 2010 --to-year 2026 --no-images

Behaviour:
  - Reads manifest.json to find already-scraped months.
  - For DYK: scrapes all months from Oct 2004 up to the previous calendar month.
  - For TIH: scrapes whichever of the 12 calendar months are not yet in manifest.
  - Writes each new month's JSON, then updates manifest.json atomically.

Idempotent: re-running will only scrape months not yet in the manifest.
"""

import json
import re
import sys
import time
import hashlib
import uuid
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR      = Path(__file__).parent.parent / 'data'
MANIFEST_PATH = Path(__file__).parent.parent / 'logs' / 'manifest.json'
WIKI_BASE     = 'https://en.wikipedia.org'
DELAY         = 0.75   # seconds between page requests
IMG_DELAY     = 0.5    # seconds between infobox image fetches
HEADERS       = {
    'User-Agent': (
        'BokyLearnScraper/1.0 '
        '(https://github.com/sarel-myburgh/facts; educational facts app)'
    )
}

MONTHS_FULL  = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]
MONTHS_SHORT = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

# ── Manifest helpers ──────────────────────────────────────────────────────────

def load_manifest() -> dict:
    """
    Return a dict mapping month_key → enrichment flags from manifest.json.
    Handles the old list format ({"months": [...]}) for backwards compatibility.
    """
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH, encoding='utf-8') as f:
        data = json.load(f)
    months = data.get('months', {})
    # Old format was a plain list — migrate on the fly.
    if isinstance(months, list):
        return {key: {'tags': False, 'links': False} for key in months}
    return months


def save_manifest(scraped: dict) -> None:
    """Write the manifest sorted by key for stable diffs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'months': dict(sorted(scraped.items()))}, f, indent=2)


def write_month_file(month_key: str, source: str, period: str, facts: list) -> None:
    """Write a month's facts to data/<month_key>.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f'{month_key}.json'
    payload = {
        'source': source,
        'period': period,
        'facts':  facts,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def month_file_exists(month_key: str) -> bool:
    """Return True when the expected month JSON exists on disk."""
    return (DATA_DIR / f'{month_key}.json').exists()

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
                return None
            print(f'    [warn] {url}: HTTP {e}', flush=True)
        except Exception as e:
            print(f'    [warn] {url}: {e}', flush=True)
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return None


def get_infobox_image(article_path: str) -> tuple[str, str | None] | None:
    """
    Return (url, caption) for the first infobox image from a Wikipedia article,
    or None if no infobox image is found.
    """
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
    # Upgrade thumbnail to full-size
    src = re.sub(r'/thumb(/[^/]+/[^/]+/[^/]+)/\d+px-[^/]+$', r'\1', src)
    # Try to find a caption in the nearest <figcaption> or infobox caption cell.
    caption = None
    fig = img.find_parent('figure')
    if fig:
        fc = fig.find('figcaption')
        if fc:
            caption = fc.get_text(' ', strip=True) or None
    if caption is None:
        td = img.find_parent('td')
        if td:
            # The caption is often the next sibling <td> in the infobox image row.
            tr = td.find_parent('tr')
            if tr:
                next_tr = tr.find_next_sibling('tr')
                if next_tr:
                    caption = next_tr.get_text(' ', strip=True) or None
    return (src, caption)


def extract_wiki_links(tag) -> list:
    """Extract Wikipedia article links from a BeautifulSoup tag."""
    links = []
    seen = set()
    for a in tag.find_all('a', href=True):
        href = a['href']
        if not href.startswith('/wiki/'):
            continue
        if re.match(r'/wiki/(Wikipedia|File|Category|Help|Template|Talk|Special):', href):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get('title') or a.get_text(strip=True)
        links.append({'url': WIKI_BASE + href, 'title': title, 'source': 'Wikipedia'})
    return links

# ── Text cleaners ─────────────────────────────────────────────────────────────

_PICTURED_RE  = re.compile(r'\([^)]*\bpictured\b[^)]*\)', re.IGNORECASE)
_SPACE_RE     = re.compile(r'  +')
_PUNCT_SPACE  = re.compile(r' ([,;:!?.])')


def clean_hook(raw: str) -> str:
    t = raw.strip()
    t = re.sub(r'^\.\.\.\s*that\s+', '', t, flags=re.IGNORECASE)
    t = _PICTURED_RE.sub('', t)
    t = _SPACE_RE.sub(' ', t).strip()
    t = _PUNCT_SPACE.sub(r'\1', t)
    t = t.rstrip('?').strip()
    if t:
        t = t[0].upper() + t[1:]
    return t


def clean_tih(raw: str) -> str:
    t = raw.strip()
    t = re.sub(r'^\d{1,4}\s*[–—\-]+\s*', '', t)
    t = _PICTURED_RE.sub('', t)
    t = _SPACE_RE.sub(' ', t).strip()
    t = _PUNCT_SPACE.sub(r'\1', t)
    return t


def make_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


def make_fact(
    text: str,
    links: list,
    image: tuple[str, str | None] | None,
    source: str,
    period: str,
    tih_month: int | None = None,
    tih_day: int | None = None,
) -> dict:
    """
    image:     (url, caption) tuple returned by get_infobox_image(), or None.
    period:    the month period string used as an ID prefix (e.g. '2025_Jan', 'Apr').
    tih_month: calendar month number (1–12) for TIH facts; None for DYK.
    tih_day:   day of month (1–31) for TIH facts; None for DYK.
    tags:      empty list — filled in later by the AI tagger agent.

    ID format: {source}_{period}_{12 hex chars}  e.g. dyk_2025_Jan_a1b2c3d4e5f6
    """
    uid = uuid.uuid4().hex[:12]
    fact: dict = {
        'id':         f'{source}_{period}_{uid}',
        'hash':       make_hash(text),
        'text':       text,
        'tags':       [],
        'image':      {'url': image[0], 'caption': image[1]} if image else {'url': None, 'caption': None},
        'mature':     False,
        'source':     source,
        'scraped_at': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'links':      links,
    }
    if tih_month is not None:
        fact['tih_month'] = tih_month
        fact['tih_day']   = tih_day
    return fact

# ── DYK scraper ───────────────────────────────────────────────────────────────

def dyk_month_key(year: int, month_idx: int) -> str:
    """month_idx is 1-based (1=January). Returns e.g. 'dyk_2024_Feb'."""
    return f'dyk_{year}_{MONTHS_SHORT[month_idx - 1]}'


def dyk_months_to_scrape(
    scraped: set,
    only_year: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
) -> list:
    """
    Return a list of (year, month_idx, month_key) tuples for DYK months that
    have not yet been scraped, from Oct 2004 up to (but not including) the
    current calendar month.

    If only_year is given, restrict results to that year only.
    """
    today = date.today()
    # Previous month = the last complete archive month.
    # If today is April 2026, previous month is March 2026.
    prev_year  = today.year if today.month > 1 else today.year - 1
    prev_month = today.month - 1 if today.month > 1 else 12

    start_year = 2004 if from_year is None else max(2004, from_year)
    end_year = prev_year if to_year is None else min(prev_year, to_year)

    if only_year is not None:
        start_year = end_year = only_year

    if start_year > end_year:
        return []

    year_range = range(start_year, end_year + 1)

    result = []
    for year in year_range:
        start_m = 10 if year == 2004 else 1   # archive starts ~Oct 2004
        end_m   = prev_month if year == prev_year else 12
        for m in range(start_m, end_m + 1):
            key = dyk_month_key(year, m)
            if key not in scraped or not month_file_exists(key):
                result.append((year, m, key))
    return result


def scrape_dyk_page(url: str, fetch_images: bool, period: str = '') -> list:
    """Scrape one DYK archive page. Returns a list of fact dicts (no dedup)."""
    soup = get_soup(url)
    if not soup:
        return []

    content = soup.find('div', id='mw-content-text')
    if not content:
        return []

    facts = []
    seen_hashes = set()
    for li in content.find_all('li'):
        raw = li.get_text(' ', strip=True)
        if not raw.startswith('...'):
            continue

        has_pictured = bool(_PICTURED_RE.search(raw))
        text = clean_hook(raw)
        if len(text) < 25:
            continue

        h = make_hash(text)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        image = None
        if fetch_images and has_pictured:
            bold_a = (li.find('b') or li).find('a', href=True)
            if bold_a and bold_a['href'].startswith('/wiki/'):
                image = get_infobox_image(bold_a['href'])

        links = extract_wiki_links(li)
        facts.append(make_fact(text, links, image, 'dyk', period=period))

    return facts


def scrape_dyk(
    scraped: set,
    fetch_images: bool,
    only_year: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
) -> set:
    """Scrape missing DYK months. Returns updated scraped set."""
    months = dyk_months_to_scrape(
        scraped,
        only_year=only_year,
        from_year=from_year,
        to_year=to_year,
    )
    if not months:
        print('DYK: nothing new to scrape.', flush=True)
        return scraped

    print(f'DYK: {len(months)} new months to scrape', flush=True)
    for year, m, key in months:
        month_name = MONTHS_FULL[m - 1]
        url    = f'{WIKI_BASE}/wiki/Wikipedia:Did_you_know_archive/{year}/{month_name}'
        period = f'{year}_{MONTHS_SHORT[m - 1]}'
        facts  = scrape_dyk_page(url, fetch_images, period=period)
        write_month_file(key, 'dyk', f'{year}_{MONTHS_SHORT[m - 1]}', facts)
        scraped[key] = {'tags': False, 'links': False, 'version': 1}
        save_manifest(scraped)   # save after each month so progress is kept on crash
        print(f'  {key:<20}  {len(facts)} facts', flush=True)

    return scraped

# ── TIH scraper ───────────────────────────────────────────────────────────────

MONTH_DAYS = {
    'January': 31, 'February': 29, 'March': 31, 'April': 30,
    'May': 31, 'June': 30, 'July': 31, 'August': 31,
    'September': 30, 'October': 31, 'November': 30, 'December': 31,
}

_YEAR_PREFIX  = re.compile(r'^\d{1,4}\s*[–—\-]')
_SKIP_HEADINGS = re.compile(
    r'\b(born|died|death|birth|holiday|observance|ineligible)\b', re.IGNORECASE
)
_ELIGIBLE_RE  = re.compile(r'\beligible\b', re.IGNORECASE)


def tih_month_key(month_short: str) -> str:
    return f'tih_{month_short}'


def tih_months_to_scrape(scraped: set) -> list:
    """Return list of (month_full, month_short) for TIH months not yet scraped."""
    result = []
    for full, short in zip(MONTHS_FULL, MONTHS_SHORT):
        key = tih_month_key(short)
        if key not in scraped or not month_file_exists(key):
            result.append((full, short, key))
    return result


def scrape_tih_page(url: str, fetch_images: bool, tih_month: int, tih_day: int, period: str = '') -> list:
    """Scrape one TIH daily page. Returns a list of fact dicts."""
    soup = get_soup(url)
    if not soup:
        return []

    content = soup.find('div', id='mw-content-text')
    if not content:
        return []

    facts = []
    seen_hashes = set()
    in_events = True

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

        h = make_hash(text)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        image = None
        if fetch_images and has_pictured:
            bold_a = (el.find('b') or el).find('a', href=True)
            if bold_a and bold_a['href'].startswith('/wiki/'):
                image = get_infobox_image(bold_a['href'])

        links = extract_wiki_links(el)
        facts.append(make_fact(text, links, image, 'tih', period=period, tih_month=tih_month, tih_day=tih_day))

    return facts


def scrape_tih_month(month_full: str, month_short: str, fetch_images: bool) -> list:
    """Scrape all daily pages for one calendar month. Returns deduplicated facts."""
    days = MONTH_DAYS[month_full]
    month_num = MONTHS_FULL.index(month_full) + 1  # 1-based
    all_facts = []
    seen_hashes = set()
    print(f'  TIH {month_full}: {days} pages', flush=True)
    for day in range(1, days + 1):
        url   = f'{WIKI_BASE}/wiki/Wikipedia:Selected_anniversaries/{month_full}_{day}'
        daily = scrape_tih_page(url, fetch_images, tih_month=month_num, tih_day=day, period=month_short)
        for f in daily:
            if f['hash'] not in seen_hashes:
                seen_hashes.add(f['hash'])
                all_facts.append(f)
    return all_facts


def scrape_tih(scraped: set, fetch_images: bool, force: bool = False) -> set:
    """Scrape all missing TIH calendar months. Returns updated scraped set.

    If force=True, re-scrapes all 12 months regardless of manifest state,
    replacing existing files (picks up new facts added to Wikipedia).
    """
    if force:
        # Drop tih entries so tih_months_to_scrape returns all 12.
        scraped = {k: v for k, v in scraped.items() if not k.startswith('tih_')}
    months = tih_months_to_scrape(scraped)
    if not months:
        print('TIH: nothing new to scrape.', flush=True)
        return scraped

    print(f'TIH: {len(months)} new months to scrape', flush=True)
    for month_full, month_short, key in months:
        facts = scrape_tih_month(month_full, month_short, fetch_images)
        write_month_file(key, 'tih', month_short, facts)
        scraped[key] = {'tags': False, 'links': False, 'version': 1}
        save_manifest(scraped)
        print(f'  {key:<12}  {len(facts)} facts written', flush=True)

    return scraped

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args         = sys.argv[1:]
    args_lower   = [a.lower() for a in args]
    mode         = next((a for a in args_lower if a in ('dyk', 'tih', 'all')), 'all')
    fetch_images = '--no-images' not in args_lower

    # --year YYYY  restricts DYK to a single year and skips TIH.
    only_year: int | None = None
    for i, a in enumerate(args):
        if a.lower() == '--year' and i + 1 < len(args):
            only_year = int(args[i + 1])
            break

    from_year: int | None = None
    to_year: int | None = None
    for i, a in enumerate(args):
        if a.lower() == '--from-year' and i + 1 < len(args):
            from_year = int(args[i + 1])
        if a.lower() == '--to-year' and i + 1 < len(args):
            to_year = int(args[i + 1])

    force_tih = '--force-tih' in args_lower

    print(f'Images: {"ON" if fetch_images else "OFF"}', flush=True)
    print(f'Mode:   {mode}', flush=True)
    if force_tih:
        print('TIH:    force re-scrape', flush=True)
    if only_year:
        print(f'Year:   {only_year} only', flush=True)
    if from_year is not None or to_year is not None:
        print(
            f'Range:  {from_year if from_year is not None else "start"} '
            f'to {to_year if to_year is not None else "current"}',
            flush=True,
        )

    scraped = load_manifest()
    print(f'Manifest: {len(scraped)} months already scraped\n', flush=True)

    t0 = time.time()
    if mode in ('dyk', 'all'):
        scraped = scrape_dyk(
            scraped,
            fetch_images,
            only_year=only_year,
            from_year=from_year,
            to_year=to_year,
        )
    if mode in ('tih', 'all') and only_year is None:
        scraped = scrape_tih(scraped, fetch_images, force=force_tih)

    elapsed = time.time() - t0
    print(f'\nDone — {len(scraped)} total months in manifest  |  elapsed: {elapsed:.0f}s')


if __name__ == '__main__':
    main()
