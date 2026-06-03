#!/usr/bin/env python3
"""
ping_indexnow.py - submit all live URLs to IndexNow on each daily cron.

IndexNow is an open protocol (Bing, Yandex, Naver, Seznam, Yep). One POST
and the participating engines re-crawl within minutes-to-hours. Google
does NOT participate, but ChatGPT Search and Perplexity both rely on
Bing's index, so this is the cheapest way to push freshness to AI-search.

Source of truth for the URL list is sitemap.xml so this stays in sync
with whatever inject_openings.py wrote on the same cron run.

Usage:
    python3 tools/ping_indexnow.py [--dry-run]

Exits 0 on success (200 or 202), non-zero on hard failure so cron MAILTO
catches it. IndexNow returns 200 when URLs were accepted for indexing,
202 when they were accepted but verification is still pending.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / 'sitemap.xml'
# Per-run URL snapshot. Diff against this on next run to identify NEW URLs
# (a new /r/<slug>.html created by tonight's inject because a fresh licence
# appeared in today's CSV pull). New URLs get a dedicated priority ping
# BEFORE the full-set batch ping, so Bing's crawler hits them within
# minutes of generation instead of waiting in the daily-batch queue.
LAST_SEEN = ROOT / 'tools' / 'cache' / 'indexnow_last_seen.json'

HOST = 'nowservingto.com'
# Public key. Must match the filename + content of the file at
# https://nowservingto.com/<KEY>.txt - IndexNow fetches that to verify
# ownership before accepting submitted URLs. Rotate by generating a new
# token, renaming the key file, and updating this constant.
KEY = '23031e66a61c4cb883f85168446f7db0'
KEY_LOCATION = f'https://{HOST}/{KEY}.txt'

# api.indexnow.org distributes submissions to all participating engines.
# Per-engine endpoints (bing.com/indexnow, yandex.com/indexnow, etc.) are
# also available but redundant if you use the central API.
ENDPOINT = 'https://api.indexnow.org/IndexNow'


def read_sitemap_urls():
    xml = SITEMAP.read_text()
    urls = re.findall(r'<loc>([^<]+)</loc>', xml)
    # Belt-and-suspenders: only submit URLs on our host. IndexNow rejects
    # the whole batch if any URL is off-host.
    return [u for u in urls if u.startswith(f'https://{HOST}/')]


# Per-month archive URLs are frozen content after their month ends.
# Re-pinging them daily wastes IndexNow quota AND signals "churn" to
# Bing/Yandex, which lowers crawl-priority confidence. The priority/new
# pass picks them up exactly once when first created; after that the
# full-batch pass should skip them. Current-month archives DO mutate
# daily (inject overwrites them within the active month) and stay in
# the batch.
_ARCHIVE_PATTERN = re.compile(
    rf'^https://{re.escape(HOST)}/(?:dispatch|trends)/(\d{{4}}-\d{{2}})$'
)

def _is_frozen_archive(url, current_ym):
    """True if this is a /dispatch/<yyyy-mm> or /trends/<yyyy-mm> URL
    for a past month. Past-month archives are immutable and shouldn't
    be re-pinged daily."""
    m = _ARCHIVE_PATTERN.match(url)
    if not m: return False
    return m.group(1) < current_ym

def filter_mutable(urls):
    """Drop frozen archive URLs from the full-batch list. Keeps the
    rolling /dispatch/latest, /dispatch (bare), /trends (bare), and
    the current month's dated archives — all of which still drift."""
    today = date.today()
    current_ym = f'{today.year}-{today.month:02d}'
    return [u for u in urls if not _is_frozen_archive(u, current_ym)]


def _submit(urls, label, dry_run=False):
    """POST a URL list to IndexNow. Returns True on success."""
    body = {
        'host': HOST,
        'key': KEY,
        'keyLocation': KEY_LOCATION,
        'urlList': urls,
    }
    print(f'IndexNow [{label}]: submitting {len(urls)} URL(s)')
    if len(urls) <= 6:
        for u in urls: print(f'    {u}')
    else:
        print(f'    first 3: {urls[:3]}')
        print(f'    last  3: {urls[-3:]}')
    if dry_run:
        print('  (dry-run, not sending)')
        return True
    req = Request(
        ENDPOINT,
        data=json.dumps(body).encode('utf-8'),
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Host': 'api.indexnow.org',
            'User-Agent': 'NowServingTO IndexNow client (https://nowservingto.com)',
        },
        method='POST',
    )
    try:
        with urlopen(req, timeout=30) as r:
            print(f'  HTTP {r.status} {r.reason}')
            resp_body = r.read().decode('utf-8', errors='replace').strip()
            if resp_body:
                print(f'  body: {resp_body[:500]}')
            return True
    except HTTPError as e:
        # 422 = key file missing/mismatched on host. 429 = rate-limited.
        # 400 = malformed body or off-host URL slipped through.
        msg = e.read().decode('utf-8', errors='replace').strip()
        print(f'  ERROR HTTP {e.code} {e.reason}: {msg[:500]}')
        return False
    except URLError as e:
        print(f'  ERROR network: {e}')
        return False


def main():
    dry_run = '--dry-run' in sys.argv

    urls = read_sitemap_urls()
    if not urls:
        sys.exit('no on-host URLs found in sitemap.xml')
    url_set = set(urls)

    # Diff against last run's URL set to find NEW URLs created by this
    # cron (a /r/<slug> for a restaurant licensed today, a /cuisine/<key>
    # for a freshly-registered novel cuisine bucket).
    fresh = []
    try:
        prev = set(json.loads(LAST_SEEN.read_text())) if LAST_SEEN.exists() else set()
    except Exception:
        prev = set()
    if prev:
        fresh = sorted(url_set - prev)

    # 1) Priority ping for NEW urls only. Sends a small targeted payload
    # FIRST so Bing's crawl queue prioritizes today's brand-new pages.
    # Cap at 100 because if the diff is larger than that something
    # weird happened (sitemap regen with a different base URL, etc.)
    # and we'd rather fall through to the full batch than spray noise.
    priority_ok = True
    if fresh and len(fresh) <= 100:
        priority_ok = _submit(fresh, 'priority/new', dry_run=dry_run)
    elif fresh and len(fresh) > 100:
        print(f'IndexNow [priority/new]: skipped - {len(fresh)} fresh URLs is too '
              f'many for a targeted ping (sitemap reset?), full batch below covers it')
    elif not prev:
        print('IndexNow [priority/new]: skipped - first run, no previous snapshot to diff against')
    else:
        print('IndexNow [priority/new]: no new URLs since last run')

    # 2) Full batch ping for everything that's still mutable. Frozen
    # archive snapshots (/dispatch/<past-yyyy-mm>, /trends/<past-yyyy-mm>)
    # are filtered out — they were already pinged once via priority/new
    # when first created, and re-pinging unchanged content burns quota
    # AND tells Bing/Yandex this content is volatile, which lowers crawl-
    # priority confidence on the things that actually do change.
    batch_urls = filter_mutable(urls)
    _n_frozen = len(urls) - len(batch_urls)
    if _n_frozen:
        print(f'IndexNow [full batch]: skipping {_n_frozen} frozen archive URL(s) '
              f'(past-month /dispatch and /trends snapshots)')
    batch_ok = _submit(batch_urls, 'full batch', dry_run=dry_run)

    # 3) Persist current URL set for next run's diff. Only writes when
    # at least one submission succeeded, so a network blip doesn't
    # silently mask the diff on the following cron.
    if not dry_run and (priority_ok or batch_ok):
        try:
            LAST_SEEN.parent.mkdir(parents=True, exist_ok=True)
            LAST_SEEN.write_text(json.dumps(sorted(url_set)))
        except Exception as e:
            print(f'  WARN: could not persist last-seen snapshot: {e}')

    if not (priority_ok or batch_ok):
        sys.exit(2)


if __name__ == '__main__':
    main()
