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
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / 'sitemap.xml'

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


def main():
    dry_run = '--dry-run' in sys.argv

    urls = read_sitemap_urls()
    if not urls:
        sys.exit('no on-host URLs found in sitemap.xml')

    body = {
        'host': HOST,
        'key': KEY,
        'keyLocation': KEY_LOCATION,
        'urlList': urls,
    }
    print(f'IndexNow: submitting {len(urls)} URLs to {ENDPOINT}')
    print(f'  first 3: {urls[:3]}')
    print(f'  last  3: {urls[-3:]}')

    if dry_run:
        print('(dry-run, not sending)')
        return

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
    except HTTPError as e:
        # 422 = key file missing/mismatched on host. 429 = rate-limited.
        # 400 = malformed body or off-host URL slipped through.
        msg = e.read().decode('utf-8', errors='replace').strip()
        print(f'  ERROR HTTP {e.code} {e.reason}: {msg[:500]}')
        sys.exit(2)
    except URLError as e:
        print(f'  ERROR network: {e}')
        sys.exit(3)


if __name__ == '__main__':
    main()
