#!/usr/bin/env python3
"""
Haiku-vision batch classifier: for every cached restaurant photo at
og/thumb/<slug>.webp, decide whether the image actually depicts a
restaurant (storefront, interior, food, signage) or something
completely unrelated (hair salon, gas station, paint section, etc.)
that Google Places attached to the restaurant's CID by mistake.

Output: tools/cache/photo_classification.json
  {<slug>: {"is_restaurant_or_food": bool, "description": str,
            "raw": str, "in_tok": int, "out_tok": int,
            "classified_at": ISO-8601, "via": "batch"}}

inject_openings.py honors this verdict alongside the manual denylist:
slugs where the classifier returns is_restaurant_or_food=false get
their cached image deleted and the photo/thumb fields cleared, so
the row renders text-only.

Safe to call from cron - already-classified slugs are skipped. Uses
the 196x196 webp thumbnails (~5 KB each) for cost-efficiency: Haiku
needs only enough resolution to distinguish "restaurant" from "not
restaurant" categorically, not to read fine detail.

Reads ANTHROPIC_API_KEY from /var/secrets/nowservingto.env.
"""
import os, sys, json, time, base64
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
THUMB_DIR  = ROOT / 'og' / 'thumb'
CACHE_PATH = ROOT / 'tools' / 'cache' / 'photo_classification.json'
SECRETS    = Path('/var/secrets/nowservingto.env')
MODEL      = 'claude-haiku-4-5-20251001'
POLL_INTERVAL_SEC = 30

SYSTEM_PROMPT = """You are classifying images returned by Google Places API
for a directory of newly licensed Toronto restaurants. Some images Places
returns for a restaurant are actually photos of NEIGHBORING businesses
(a hair salon next door, a gas station across the street, a paint section
of a hardware store, parking lot, billboard) that ended up attached to
the restaurant's CID. Your job is to filter those out.

For each supplied image, decide whether it depicts a restaurant in ANY
form:
  - storefront / exterior / signage
  - interior / dining room / counter / kitchen
  - food dish / drink / takeout container
  - menu board / chalkboard menu
  - food prep / branded packaging
  - food-truck or kiosk

vs. something that is clearly NOT restaurant-related:
  - hair salon, nail salon, barbershop
  - gas station, parking lot, car wash
  - retail shelves of unrelated goods (paint, hardware, electronics)
  - unrelated office or lobby
  - generic sky / landscape / road
  - billboard / advertisement for non-food product
  - residential building exterior

Be LIBERAL in the restaurant direction: dim interiors, blurry phone
photos of food, awkward storefront shots, generic-looking diner
exteriors with hand-painted signs, hole-in-the-wall takeout counters
all qualify if there's any food-service signal. A photo where you
genuinely cannot tell what the business is should default to
is_restaurant_or_food=true (don't penalize ambiguity).

Be STRICT only when the photo is clearly something else - hair salon
chairs visible, gas pumps visible, retail shelves of clearly non-food
items visible, etc.

Return JSON on one line, nothing else:
  {"is_restaurant_or_food": true, "description": "<one short line>"}
or:
  {"is_restaurant_or_food": false, "description": "<one short line>"}
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

    if not THUMB_DIR.exists():
        sys.exit(f"{THUMB_DIR} missing - run inject_openings.py first")

    # Walk thumbs, skip already-cached slugs
    targets = []  # (slug, path)
    for p in sorted(THUMB_DIR.glob('*.webp')):
        slug = p.stem
        if slug in cache: continue
        targets.append((slug, p))

    print(f"  candidates: {len(targets)} unclassified thumbs "
          f"({len(list(THUMB_DIR.glob('*.webp')))} total on disk)")

    if not targets:
        print("nothing to classify.")
        return

    requests = []
    target_keys = []
    skipped_too_big = 0
    for slug, p in targets:
        try:
            img_bytes = p.read_bytes()
        except OSError:
            continue
        # Sanity cap: Anthropic limit is 5 MB per image. Thumbs are ~5 KB
        # so this is just defence against a corrupt file.
        if len(img_bytes) > 4_500_000:
            skipped_too_big += 1
            continue
        b64 = base64.standard_b64encode(img_bytes).decode('ascii')
        custom_id = 'p' + str(abs(hash(slug)) & 0x7fffffff)
        requests.append({
            'custom_id': custom_id,
            'params': {
                'model': MODEL,
                'max_tokens': 100,
                'system': SYSTEM_PROMPT,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': 'image/webp',
                                'data': b64,
                            },
                        },
                        {
                            'type': 'text',
                            'text': "Classify this restaurant-directory image.",
                        },
                    ],
                }],
            },
        })
        target_keys.append(slug)

    if skipped_too_big:
        print(f"  skipped {skipped_too_big} oversized files (>4.5 MB)")

    if not requests:
        print("nothing to send.")
        return

    id_to_slug = {r['custom_id']: s for r, s in zip(requests, target_keys)}
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

    n_ok_yes = n_ok_no = n_err = 0
    total_in = total_out = 0
    classified_at = datetime.utcnow().isoformat() + 'Z'
    for line in raw_text.strip().split('\n'):
        if not line.strip(): continue
        obj = json.loads(line)
        cid = obj.get('custom_id')
        slug = id_to_slug.get(cid)
        if not slug: continue
        result = obj.get('result', {})
        rtype = result.get('type')
        if rtype != 'succeeded':
            n_err += 1
            cache[slug] = {'status': 'error', 'error': f'batch {rtype}',
                           'classified_at': classified_at}
            continue
        msg = result.get('message', {})
        usage = msg.get('usage', {})
        total_in += usage.get('input_tokens', 0)
        total_out += usage.get('output_tokens', 0)
        text_out = ''.join(b.get('text', '') for b in msg.get('content', [])
                           if b.get('type') == 'text').strip()
        parsed = None
        for ln in text_out.split('\n'):
            s = ln.strip().lstrip('`').strip()
            if s.startswith('{') and s.endswith('}'):
                try:
                    parsed = json.loads(s); break
                except Exception:
                    continue
        if parsed is None:
            n_err += 1
            cache[slug] = {'status': 'error', 'error': 'json-parse',
                           'raw': text_out[:200], 'classified_at': classified_at}
            continue
        is_food = bool(parsed.get('is_restaurant_or_food'))
        cache[slug] = {
            'status': 'ok',
            'is_restaurant_or_food': is_food,
            'description': str(parsed.get('description', ''))[:160],
            'raw': text_out[:200],
            'in_tok': usage.get('input_tokens', 0),
            'out_tok': usage.get('output_tokens', 0),
            'via': 'batch',
            'classified_at': classified_at,
        }
        if is_food: n_ok_yes += 1
        else:       n_ok_no  += 1

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    cost = (total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0) * 0.5
    print(f"\nbatch merged: restaurant={n_ok_yes} not-restaurant={n_ok_no} "
          f"err={n_err}  tokens in={total_in:,} out={total_out:,}  "
          f"est ${cost:.3f} (50%-off batch)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from usage_log import log_usage
        log_usage('anthropic.haiku.batch.in',  units=total_in,
                  meta={'script': 'photo_classify_batch', 'batch_id': batch_id})
        log_usage('anthropic.haiku.batch.out', units=total_out,
                  meta={'script': 'photo_classify_batch', 'batch_id': batch_id})
    except Exception:
        pass

    # Surface a few false-negatives for spot-check
    if n_ok_no:
        nos = [(s, v) for s, v in cache.items()
               if v.get('status') == 'ok' and not v.get('is_restaurant_or_food')]
        nos = nos[-min(10, len(nos)):]
        print("\nflagged as NOT restaurant (spot-check these):")
        for s, v in nos:
            print(f"  {s:50s}  {v.get('description', '')[:80]}")


if __name__ == '__main__':
    main()
