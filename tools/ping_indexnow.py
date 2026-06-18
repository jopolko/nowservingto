#!/usr/bin/env python3
"""
ping_indexnow.py - submit all live URLs to IndexNow on each daily cron.

IndexNow is an open protocol (Bing, Yandex, Naver, Seznam, Yep). One POST
and the participating engines re-crawl within minutes-to-hours. Google
does NOT participate, but ChatGPT Search and Perplexity both rely on
Bing's index, so this is the cheapest way to push freshness to AI-search.

Source of truth for the URL list is the host's sitemap.xml so this stays
in sync with whatever the daily ETL wrote on the same cron run.

This script is host-agnostic. With no flags it submits nowservingto.com
(the default, so the existing daily cron call is unchanged). Pass --host /
--key / --sitemap / --cache to drive any other IndexNow-verified site
(e.g. joshuaopolko.com) from the same code.

Usage:
    python3 tools/ping_indexnow.py [--dry-run]
    python3 tools/ping_indexnow.py --host joshuaopolko.com \
        --key d7a5a9b4c10cd380e4004523688b3ae0 \
        --sitemap /var/www/html/sitemap.xml \
        --cache /var/www/html/nowservingto/tools/cache/indexnow_last_seen_joshuaopolko.json

Exits 0 on success (200 or 202), non-zero on hard failure so cron MAILTO
catches it. IndexNow returns 200 when URLs were accepted for indexing,
202 when they were accepted but verification is still pending.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent

# Defaults reproduce the original nowservingto-only behaviour so the
# existing `python3 tools/ping_indexnow.py` cron call needs no change.
DEFAULT_HOST = 'nowservingto.com'
# Public key. Must match the filename + content of the file at
# https://<host>/<KEY>.txt - IndexNow fetches that to verify ownership
# before accepting submitted URLs. Each host has its OWN key file served
# on that host. Rotate by generating a new token, renaming the key file,
# and updating the value passed here.
DEFAULT_KEY = '23031e66a61c4cb883f85168446f7db0'

# api.indexnow.org distributes submissions to all participating engines.
# Per-engine endpoints (bing.com/indexnow, yandex.com/indexnow, etc.) are
# also available but redundant if you use the central API.
ENDPOINT = 'https://api.indexnow.org/IndexNow'


def default_cache_for(host):
    """Per-host last-seen snapshot path. nowservingto keeps its original
    filename so its diff history is preserved; every other host gets a
    host-slugged file so two sites never clobber each other's snapshot."""
    if host == DEFAULT_HOST:
        return ROOT / 'tools' / 'cache' / 'indexnow_last_seen.json'
    slug = host.replace('.', '_')
    return ROOT / 'tools' / 'cache' / f'indexnow_last_seen_{slug}.json'


def read_sitemap_urls(sitemap, host):
    xml = Path(sitemap).read_text()
    urls = re.findall(r'<loc>([^<]+)</loc>', xml)
    # Belt-and-suspenders: only submit URLs on our host. IndexNow rejects
    # the whole batch if any URL is off-host.
    return [u for u in urls if u.startswith(f'https://{host}/')]


def _is_frozen_archive(url, current_ym, host):
    """True if this is a /dispatch/<yyyy-mm> or /trends/<yyyy-mm> URL for
    a past month. Past-month archives are immutable and shouldn't be
    re-pinged daily. This pattern is nowservingto-specific; on hosts that
    have no such URLs (e.g. joshuaopolko) it simply never matches, so the
    full batch passes through untouched."""
    pattern = re.compile(
        rf'^https://{re.escape(host)}/(?:dispatch|trends)/(\d{{4}}-\d{{2}})$'
    )
    m = pattern.match(url)
    if not m:
        return False
    return m.group(1) < current_ym


def filter_mutable(urls, host):
    """Drop frozen archive URLs from the full-batch list. Keeps the
    rolling /dispatch/latest, /dispatch (bare), /trends (bare), and the
    current month's dated archives - all of which still drift."""
    today = date.today()
    current_ym = f'{today.year}-{today.month:02d}'
    return [u for u in urls if not _is_frozen_archive(u, current_ym, host)]


def _submit(urls, label, host, key, key_location, dry_run=False):
    """POST a URL list to IndexNow. Returns True on success."""
    body = {
        'host': host,
        'key': key,
        'keyLocation': key_location,
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
            'User-Agent': f'{host} IndexNow client (https://{host})',
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
    ap = argparse.ArgumentParser(description='Submit a host\'s sitemap URLs to IndexNow.')
    ap.add_argument('--host', default=DEFAULT_HOST,
                    help=f'site host (default: {DEFAULT_HOST})')
    ap.add_argument('--key', default=None,
                    help='IndexNow key for this host (default: nowservingto key)')
    ap.add_argument('--key-location', default=None,
                    help='URL of the key file (default: https://<host>/<key>.txt)')
    ap.add_argument('--sitemap', default=None,
                    help='path to sitemap.xml (default: <repo>/sitemap.xml)')
    ap.add_argument('--cache', default=None,
                    help='path to the last-seen snapshot json (default: per-host)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    host = args.host
    key = args.key if args.key is not None else (DEFAULT_KEY if host == DEFAULT_HOST else None)
    # Guard: changing host without supplying its own key would submit with
    # the wrong key file and get the whole batch rejected (422). Fail loud.
    if key is None:
        sys.exit(f'--host {host} requires --key (each host has its own IndexNow key file)')
    if host != DEFAULT_HOST and key == DEFAULT_KEY:
        sys.exit(f'refusing to submit {host} with the {DEFAULT_HOST} key (422-bound). Pass --key for {host}.')

    key_location = args.key_location or f'https://{host}/{key}.txt'
    sitemap = Path(args.sitemap) if args.sitemap else (ROOT / 'sitemap.xml')
    last_seen = Path(args.cache) if args.cache else default_cache_for(host)
    dry_run = args.dry_run

    urls = read_sitemap_urls(sitemap, host)
    if not urls:
        sys.exit(f'no on-host URLs for {host} found in {sitemap}')
    url_set = set(urls)

    # Diff against last run's URL set to find NEW URLs created since the
    # previous run, so brand-new pages get a targeted ping first.
    fresh = []
    try:
        prev = set(json.loads(last_seen.read_text())) if last_seen.exists() else set()
    except Exception:
        prev = set()
    if prev:
        fresh = sorted(url_set - prev)

    # 1) Priority ping for NEW urls only. Sends a small targeted payload
    # FIRST so Bing's crawl queue prioritizes today's brand-new pages.
    # Cap at 100 because if the diff is larger than that something weird
    # happened (sitemap regen with a different base URL, etc.) and we'd
    # rather fall through to the full batch than spray noise.
    priority_ok = True
    if fresh and len(fresh) <= 100:
        priority_ok = _submit(fresh, 'priority/new', host, key, key_location, dry_run=dry_run)
    elif fresh and len(fresh) > 100:
        print(f'IndexNow [priority/new]: skipped - {len(fresh)} fresh URLs is too '
              f'many for a targeted ping (sitemap reset?), full batch below covers it')
    elif not prev:
        print('IndexNow [priority/new]: skipped - first run, no previous snapshot to diff against')
    else:
        print('IndexNow [priority/new]: no new URLs since last run')

    # 2) Full batch ping for everything that's still mutable. Frozen
    # archive snapshots are filtered out (nowservingto only; no-op
    # elsewhere) - they were already pinged once via priority/new when
    # first created, and re-pinging unchanged content burns quota AND
    # tells Bing/Yandex this content is volatile, which lowers crawl-
    # priority confidence on the things that actually do change.
    batch_urls = filter_mutable(urls, host)
    _n_frozen = len(urls) - len(batch_urls)
    if _n_frozen:
        print(f'IndexNow [full batch]: skipping {_n_frozen} frozen archive URL(s) '
              f'(past-month /dispatch and /trends snapshots)')
    batch_ok = _submit(batch_urls, 'full batch', host, key, key_location, dry_run=dry_run)

    # 3) Persist current URL set for next run's diff. Only writes when at
    # least one submission succeeded, so a network blip doesn't silently
    # mask the diff on the following cron.
    if not dry_run and (priority_ok or batch_ok):
        try:
            last_seen.parent.mkdir(parents=True, exist_ok=True)
            last_seen.write_text(json.dumps(sorted(url_set)))
        except Exception as e:
            print(f'  WARN: could not persist last-seen snapshot: {e}')

    if not (priority_ok or batch_ok):
        sys.exit(2)


if __name__ == '__main__':
    main()
