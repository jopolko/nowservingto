#!/usr/bin/env python3
"""
Rewrite verifier evidence into editorial prose.

The validator's `validator_evidence` field is written by Haiku in a
verification-log register: "Website confirms X serves...", "Google
Places match shows...", "WEB VERIFY reports operational at...". That
voice leaks straight onto the LISTING-EXTRA "What we verified" panel
and the per-listing meta description.

This batch pass rewrites each evidence string into a 1-2 sentence
editorial blurb - what the restaurant is, what it serves, what's
distinctive - with no reference to websites, Places, verifications,
licences, or registries. Cached forever per _cacheKey in
tools/cache/evidence_rewrite_cache.json:
  {<cache_key>: {"blurb": "...", "raw": "...",
                 "in_tok": N, "out_tok": N,
                 "rewrote_at": ISO-8601, "via": "batch"}}

inject_openings.py prefers `validator_blurb` (from this cache) over
`validator_evidence` when rendering the listing-extra panel and the
meta description.

Cost: ~$0.13 for the full backlog (~430 entries), then ~$0.003/day
as new openings get verified.
"""
import os, sys, json, time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH      = ROOT / 'data' / 'corridors.json'
WV_CACHE_PATH  = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
CACHE_PATH     = ROOT / 'tools' / 'cache' / 'evidence_rewrite_cache.json'
SECRETS        = Path('/var/secrets/nowservingto.env')
MODEL          = 'claude-haiku-4-5-20251001'
POLL_INTERVAL_SEC = 30

SYSTEM_PROMPT = """You're rewriting verification notes about Toronto
restaurants into editorial prose that reads like a restaurant directory
entry, not like a verification log.

The input is a 1-3 sentence note written by a verification system. It
typically includes phrases like:
  - "Website confirms X is..."
  - "Google Places match shows..."
  - "WEB VERIFY reports operational at..."
  - "Licence and Places match on..."
  - "Places reviews praise..."
  - "Operational ___ restaurant at ___, with..."

You'll be given the restaurant's name, cuisine, and the raw note.
Write 1-2 natural-sounding sentences (45-110 words) about the
restaurant itself. Focus on:
  - what kind of food they serve (specific dishes when the note names them)
  - what's distinctive (family-run, takeout-only, signature item, etc.)
  - atmosphere or format if mentioned

Hard rules:
  - DO NOT mention "website", "Places", "Google", "verification",
    "verified", "registry", "licence", "licensed", "operational",
    "confirmed", "matched", "address" - any verification-system word.
  - DO NOT use the word "opened" (the site only knows the licence
    registration date, not when the kitchen actually opened) or any
    time-relative phrase like "X days ago", "recently opened", "this
    month", "this week" - the blurb is cached forever so anything
    relative goes stale. The page elsewhere shows the registration
    date dynamically.
  - DO NOT start with the restaurant name.
  - DO NOT fabricate details that aren't in the note. If the note
    mentions arancini, you can write about arancini. If it doesn't
    mention a specific dish, write about the cuisine in general terms.
  - Lead with the food or the kitchen, not corporate-y framing.
  - Sentence form, lowercase first letter is fine (it follows
    "What we know:" on the page).

Return JSON on one line:
  {"blurb": "<your rewrite>"}
"""


def load_api_key():
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit("ANTHROPIC_API_KEY not in secrets")


API_KEY = load_api_key()
HEADERS = {
    'x-api-key': API_KEY,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}


def http_request(method, url, data=None):
    body = json.dumps(data).encode('utf-8') if data else None
    req = Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urlopen(req, timeout=120) as r:
            raw = r.read()
            ctype = r.headers.get('Content-Type', '')
            if 'application/json' in ctype:
                return json.loads(raw)
            return raw
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        raise


def main():
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache state: total={len(cache)}")

    if not DATA_PATH.exists():
        sys.exit(f"{DATA_PATH} missing")
    if not WV_CACHE_PATH.exists():
        sys.exit(f"{WV_CACHE_PATH} missing")

    data = json.loads(DATA_PATH.read_text())
    wv = json.loads(WV_CACHE_PATH.read_text())
    recent = data.get('newOpenings', {}).get('recent', [])

    # Cuisine label lookup (raw keys → display labels)
    labels = {}
    for c in data.get('newOpenings', {}).get('cuisines', []):
        if c.get('key'): labels[c['key']] = c.get('label', c['key'])

    targets = []   # list of (cache_key, name, cuisine_label, evidence)
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck or ck in cache: continue
        wv_e = wv.get(ck) or {}
        ev = (wv_e.get('validator_evidence') or wv_e.get('evidence') or '').strip()
        if not ev: continue
        keys = r.get('cuisines') or ([r['cuisine']] if r.get('cuisine') else [])
        cuisine_label = labels.get(keys[0], keys[0].title()) if keys else 'restaurant'
        targets.append((ck, r.get('operatingName', ''), cuisine_label, ev))

    print(f"  candidates: {len(targets)} uncached entries")

    if not targets:
        print("nothing to rewrite.")
        return

    requests = []
    target_keys = []
    for ck, name, cuisine, ev in targets:
        custom_id = 'e' + str(abs(hash(ck)) & 0x7fffffff)
        prompt = (
            f"Restaurant: {name}\n"
            f"Cuisine: {cuisine}\n"
            f"Verification note: {ev}\n\n"
            f"Rewrite as editorial blurb."
        )
        requests.append({
            'custom_id': custom_id,
            'params': {
                'model': MODEL,
                'max_tokens': 200,
                'system': SYSTEM_PROMPT,
                'messages': [{'role': 'user', 'content': prompt}],
            },
        })
        target_keys.append(ck)

    id_to_key = {r['custom_id']: k for r, k in zip(requests, target_keys)}
    print(f"submitting batch of {len(requests)} requests…")
    submit_resp = http_request('POST',
                               'https://api.anthropic.com/v1/messages/batches',
                               {'requests': requests})
    batch_id = submit_resp['id']
    print(f"  batch_id: {batch_id}")
    print(f"  status: {submit_resp['processing_status']}")

    print("polling…")
    t0 = time.time()
    while True:
        time.sleep(POLL_INTERVAL_SEC)
        info = http_request('GET',
                            f'https://api.anthropic.com/v1/messages/batches/{batch_id}')
        st = info['processing_status']
        counts = info.get('request_counts', {})
        el = time.time() - t0
        print(f"  [{el:.0f}s]  status={st}  counts={counts}")
        if st == 'ended': break
        if st in ('cancelling', 'canceled', 'expired'):
            sys.exit(f"batch ended unexpectedly: {st}")

    results_url = info.get('results_url')
    if not results_url:
        sys.exit("no results_url on completed batch")
    print(f"downloading results from {results_url}")
    raw = http_request('GET', results_url)
    raw_text = json.dumps(raw) if isinstance(raw, dict) else raw.decode('utf-8')

    n_ok = n_err = 0
    total_in = total_out = 0
    rewrote_at = datetime.utcnow().isoformat() + 'Z'
    for line in raw_text.strip().split('\n'):
        if not line.strip(): continue
        obj = json.loads(line)
        cid = obj.get('custom_id')
        ck = id_to_key.get(cid)
        if not ck: continue
        result = obj.get('result', {})
        rtype = result.get('type')
        if rtype != 'succeeded':
            n_err += 1
            cache[ck] = {'status': 'error', 'error': f'batch {rtype}',
                         'rewrote_at': rewrote_at}
            continue
        msg = result.get('message', {})
        usage = msg.get('usage', {})
        total_in += usage.get('input_tokens', 0)
        total_out += usage.get('output_tokens', 0)
        text_out = ''.join(b.get('text', '') for b in msg.get('content', [])
                           if b.get('type') == 'text').strip()
        # Parse JSON; if Haiku didn't wrap it in JSON, treat the raw text
        # as the blurb directly (defensive fallback).
        blurb = ''
        parsed = None
        for ln in text_out.split('\n'):
            s = ln.strip().lstrip('`').strip()
            if s.startswith('{') and s.endswith('}'):
                try: parsed = json.loads(s); break
                except Exception: continue
        if parsed and isinstance(parsed.get('blurb'), str):
            blurb = parsed['blurb'].strip()
        else:
            # Fallback: use the raw text minus any leading "blurb:" prefix
            blurb = text_out.strip().strip('"\'')
            if blurb.lower().startswith('blurb:'):
                blurb = blurb[6:].strip().strip('"\'')
        if not blurb:
            n_err += 1
            cache[ck] = {'status': 'error', 'error': 'empty-blurb',
                         'raw': text_out[:200], 'rewrote_at': rewrote_at}
            continue
        cache[ck] = {
            'status': 'ok',
            'blurb': blurb,
            'raw': text_out[:280],
            'in_tok': usage.get('input_tokens', 0),
            'out_tok': usage.get('output_tokens', 0),
            'via': 'batch',
            'rewrote_at': rewrote_at,
        }
        n_ok += 1

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    cost = (total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0) * 0.5
    print(f"\nbatch merged: ok={n_ok} err={n_err}  "
          f"tokens in={total_in:,} out={total_out:,}  "
          f"est ${cost:.3f} (50%-off batch)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from usage_log import log_usage
        log_usage('anthropic.haiku.batch.in',  units=total_in,
                  meta={'script': 'evidence_rewrite_batch', 'batch_id': batch_id})
        log_usage('anthropic.haiku.batch.out', units=total_out,
                  meta={'script': 'evidence_rewrite_batch', 'batch_id': batch_id})
    except Exception:
        pass


if __name__ == '__main__':
    main()
