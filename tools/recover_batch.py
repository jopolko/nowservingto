#!/usr/bin/env python3
"""
Download and merge results from a completed or partially-canceled Anthropic batch job.
Rebuilds the same candidate list that llm_verify_batch.py used when submitting,
maps custom_ids back to cache keys, and writes succeeded results to web_verify_cache.json.

Usage: python tools/recover_batch.py <batch_id> [--dry-run]
"""
import os, sys, csv, json, re
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
WEB_CACHE_PATH = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
PLACES_CACHE_PATH = ROOT / 'tools' / 'cache' / 'places_cache.json'
CSV_PATH = '/tmp/business_licences_alt.csv'

sys.path.insert(0, str(ROOT / 'tools'))
from places_key import cache_key
from chain_filter import is_known_chain
from cuisines import parse_cuisines_from_llm
from llm_verify_batch import (
    parse_d, needs_recheck, parse_result_msg, _WESTERN_SKIP_RE, MODEL
)

FOOD_CATS = {
    'EATING OR DRINKING ESTABLISHMENT', 'TAKE-OUT OR RETAIL FOOD ESTABLISHMENT',
    'EATING ESTABLISHMENT', 'RETAIL STORE (FOOD)',
}

SECRETS = Path('/var/secrets/nowservingto.env')


def load_env():
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())


def http(method, url, body=None):
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method, headers={
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    })
    try:
        with urlopen(req, timeout=120) as r:
            raw = r.read()
            ctype = r.headers.get('Content-Type', '')
            return json.loads(raw) if 'application/json' in ctype else raw
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:400]}")
        raise


def build_candidates(cache, places):
    today = date.today()
    cutoff = today - timedelta(days=365)
    candidates = []
    seen = set()
    with open(CSV_PATH, encoding='utf-8', errors='replace') as f:
        for row in csv.DictReader(f):
            if (row.get('Category') or '').strip() not in FOOD_CATS:
                continue
            if (row.get('Cancel Date') or '').strip():
                continue
            iss = parse_d(row.get('Issued'))
            if not iss or iss < cutoff:
                continue
            name = (row.get('Operating Name') or '').strip()
            if not name:
                continue
            addr = ((row.get('Licence Address Line 1') or '').strip() + ' ' +
                    (row.get('Licence Address Line 3') or '').strip()).strip()
            k = cache_key(name, addr)
            if k in seen:
                continue
            seen.add(k)
            if is_known_chain(name) or _WESTERN_SKIP_RE.search(name):
                continue
            p = places.get(k)
            if (p and p.get('status') == 'ok' and p.get('businessStatus') == 'OPERATIONAL'
                    and cache.get(k) and not needs_recheck(cache.get(k))):
                continue
            candidates.append((k, name, addr))
    return candidates


def main():
    load_env()

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <batch_id> [--dry-run]")
        sys.exit(1)

    batch_id = sys.argv[1]
    dry_run = '--dry-run' in sys.argv

    cache = json.loads(WEB_CACHE_PATH.read_text())
    places = json.loads(PLACES_CACHE_PATH.read_text())
    print(f"caches: web_verify={len(cache)}  places={len(places)}")

    candidates = build_candidates(cache, places)
    print(f"current candidates: {len(candidates)}")
    if not candidates:
        print("no candidates - cache may already be complete")
        sys.exit(0)

    # Check batch status
    info = http('GET', f'https://api.anthropic.com/v1/messages/batches/{batch_id}')
    rc = info.get('request_counts', {})
    print(f"\nbatch {batch_id}")
    print(f"  status:  {info['processing_status']}")
    print(f"  created: {info.get('created_at', '')}")
    print(f"  counts:  {rc}")

    results_url = info.get('results_url')
    if not results_url:
        print("No results_url yet - batch may still be processing")
        sys.exit(0)

    # Download JSONL
    print(f"\ndownloading results...")
    req = Request(results_url, headers={
        'x-api-key': os.environ.get('ANTHROPIC_API_KEY', ''),
        'anthropic-version': '2023-06-01',
    })
    with urlopen(req, timeout=120) as r:
        raw_text = r.read().decode('utf-8')

    lines = [l for l in raw_text.strip().split('\n') if l.strip()]
    print(f"downloaded {len(lines)} result lines")

    # Build id -> key map for current candidates
    id_to_key = {f'v{i:04d}': k for i, (k, n, a) in enumerate(candidates)}

    yes = no = unclear = err = skipped = written = 0
    tot_in = tot_out = tot_search = 0

    for obj in lines:
        obj = json.loads(obj)
        cid = obj.get('custom_id', '')
        result = obj.get('result', {})

        if result.get('type') != 'succeeded':
            err += 1
            continue

        key = id_to_key.get(cid)
        if not key:
            skipped += 1
            continue

        parsed = parse_result_msg(result['message'])
        tot_in += parsed.get('in_tok', 0)
        tot_out += parsed.get('out_tok', 0)
        tot_search += parsed.get('searches', 0)

        # Never overwrite a real result with a parse_failed one.
        if parsed.get('evidence') == 'parse_failed':
            skipped += 1
            unclear += 1
            continue

        op = parsed.get('operating')
        if op == 'yes': yes += 1
        elif op == 'no': no += 1
        else: unclear += 1

        if not dry_run:
            cache[key] = parsed
        written += 1

    if not dry_run:
        WEB_CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
        print(f"\nwrote {written} entries  skipped parse_failed: {skipped}  cache total: {len(cache)}")
    else:
        print(f"\n[dry-run] would write {written}  skip parse_failed: {skipped}")

    cost = (tot_in / 1e6 * 0.8 + tot_out / 1e6 * 4 + tot_search * 0.01) * 0.5
    print(f"results: yes={yes}  no={no}  unclear={unclear}  err={err}")
    print(f"tokens:  in={tot_in:,}  out={tot_out:,}  searches={tot_search}")
    print(f"est. cost: ${cost:.3f}")


if __name__ == '__main__':
    main()
