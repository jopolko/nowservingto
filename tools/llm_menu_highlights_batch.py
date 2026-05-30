#!/usr/bin/env python3
"""
Menu-highlight extractor. For every /r/<slug>.html candidate that has a
website + non-null cached text in website_text_cache.json, ask Haiku to
return a small JSON list of dish names that appear verbatim in the supplied
text. Strict verbatim-only: no inference, no descriptions, no cuisine words
unless they're actual dish names that appear in the page.

Output: tools/cache/menu_highlights_cache.json keyed by entry _cacheKey:
  {"<cache_key>": {"status": "ok", "dishes": ["mandi", "biryani", ...],
                   "raw": "...", "in_tok": N, "out_tok": N, "via": "batch",
                   "extracted_at": "ISO-8601"}}

When Haiku finds fewer than 2 verbatim dishes, dishes is null - inject
silently skips the menu line for that entry.

Safe to call from cron - already-cached entries are skipped. Designed for
the same Message Batches API + 50%-off pricing as llm_classify_batch.py.
"""
import os, sys, json, time, re
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH         = ROOT / 'data' / 'corridors.json'
WEBSITE_TEXT_PATH = ROOT / 'tools' / 'cache' / 'website_text_cache.json'
CACHE_PATH        = ROOT / 'tools' / 'cache' / 'menu_highlights_cache.json'
SECRETS           = Path('/var/secrets/nowservingto.env')
MODEL             = 'claude-haiku-4-5-20251001'
POLL_INTERVAL_SEC = 30

# Max chars of website text we send to Haiku per request. Cached text caps
# at ~3.2k anyway; trimming here is a belt-and-suspenders against future
# cache-format changes.
MAX_TEXT_CHARS = 3500

SYSTEM_PROMPT = """You extract SPECIFIC DISH NAMES from a restaurant's
website text. Strict rules:

1. Return ONLY dishes that appear VERBATIM (or near-verbatim with trivial
   capitalization changes) in the provided text. Do not infer, do not
   translate, do not add common dishes of the cuisine that aren't named.

2. Each dish must be a specific, recognizable food item - not a category
   ("appetizers", "mains", "desserts" are NOT dishes), not a cooking style
   ("grilled", "fried"), not a generic cuisine word ("Italian food",
   "Thai cuisine"). "Biryani" is a dish. "Indian curry" is not.

3. Prefer signature / culturally-distinctive dishes when several appear:
   "mandi", "shawarma", "pho", "banh mi", "jollof rice", "pad thai",
   "injera", "tibs", "kibbeh", "kulcha", "biryani", "tagine", "samosa".
   Skip generic items ("salad", "sandwich", "burger", "fries") unless
   the restaurant clearly specializes in them.

4. Maximum 5 dishes. Minimum 2 to report anything - if you can't find at
   least 2 specific verbatim dishes, return null. NEVER fabricate.

5. Use the form that appears in the text. Lowercase the output.

Return JSON on one line, nothing else:
  {"dishes": ["dish1", "dish2", "dish3"]}
or:
  {"dishes": null}
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


def _clean_dishes(value):
    """Validate + normalize. Returns list[str] capped at 5 or None."""
    if not isinstance(value, list): return None
    out = []
    for d in value:
        if not isinstance(d, str): continue
        s = re.sub(r'\s+', ' ', d.strip().lower())
        # Reject obvious category words / 1-word generic stuff.
        if not s or len(s) > 60: continue
        if s in {'appetizers', 'mains', 'entrees', 'desserts', 'sides',
                 'drinks', 'beverages', 'specials', 'lunch', 'dinner',
                 'breakfast', 'brunch', 'menu', 'food', 'cuisine'}:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= 5: break
    return out if len(out) >= 2 else None


def main():
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache state: total={len(cache)}")

    if not DATA_PATH.exists():
        sys.exit(f"{DATA_PATH} missing - run inject_openings.py first")
    if not WEBSITE_TEXT_PATH.exists():
        sys.exit(f"{WEBSITE_TEXT_PATH} missing - nothing to extract from")

    data = json.loads(DATA_PATH.read_text())
    website_text = json.loads(WEBSITE_TEXT_PATH.read_text())
    recent = data.get('newOpenings', {}).get('recent', [])

    # Build target list: entries with a cached website AND that website has
    # non-null text AND not already in our cache.
    targets = []   # list of (cache_key, name, text)
    n_no_website = n_no_text = n_already = 0
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck: continue
        if ck in cache:
            n_already += 1; continue
        url = r.get('website')
        if not url:
            n_no_website += 1; continue
        wt = website_text.get(url) or {}
        text = (wt.get('text') or '').strip()
        if not text:
            n_no_text += 1; continue
        # Drop the jina-header noise and trim length.
        text = re.sub(r'\s+', ' ', text)[:MAX_TEXT_CHARS]
        targets.append((ck, r.get('operatingName', ''), text))

    print(f"  candidates: {len(recent)} recent / "
          f"{len(recent) - n_no_website} with website / "
          f"{len(recent) - n_no_website - n_no_text} with cached text / "
          f"{len(targets)} not-yet-cached")

    if not targets:
        print("nothing to extract.")
        CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
        return

    requests = []
    target_keys = []
    for ck, name, text in targets:
        custom_id = 'm' + str(abs(hash(ck)) & 0x7fffffff)
        requests.append({
            'custom_id': custom_id,
            'params': {
                'model': MODEL,
                'max_tokens': 120,
                'system': SYSTEM_PROMPT,
                'messages': [{
                    'role': 'user',
                    'content': (
                        f"Restaurant: {name}\n\nWebsite text:\n---\n{text}\n---"
                    ),
                }],
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

    n_with = n_null = n_err = 0
    total_in = total_out = 0
    extracted_at = datetime.utcnow().isoformat() + 'Z'
    for line in raw_text.strip().split('\n'):
        if not line.strip(): continue
        obj = json.loads(line)
        cid = obj.get('custom_id')
        key = id_to_key.get(cid)
        if not key: continue
        result = obj.get('result', {})
        rtype = result.get('type')
        if rtype != 'succeeded':
            n_err += 1
            cache[key] = {'status': 'error', 'error': f'batch {rtype}',
                          'extracted_at': extracted_at}
            continue
        msg = result.get('message', {})
        usage = msg.get('usage', {})
        total_in += usage.get('input_tokens', 0)
        total_out += usage.get('output_tokens', 0)
        text_out = ''.join(b.get('text', '') for b in msg.get('content', [])
                           if b.get('type') == 'text').strip()
        dishes = None
        parsed_obj = None
        for ln in text_out.split('\n'):
            s = ln.strip().lstrip('`').strip()
            if s.startswith('{') and s.endswith('}'):
                try:
                    parsed_obj = json.loads(s); break
                except Exception:
                    continue
        if parsed_obj is not None:
            dishes = _clean_dishes(parsed_obj.get('dishes'))
        cache[key] = {
            'status': 'ok',
            'dishes': dishes,
            'raw': text_out[:200],
            'in_tok': usage.get('input_tokens', 0),
            'out_tok': usage.get('output_tokens', 0),
            'via': 'batch',
            'extracted_at': extracted_at,
        }
        if dishes: n_with += 1
        else:      n_null += 1

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    # Batch API: 50% off Haiku list price ($1/Mtok in, $5/Mtok out)
    cost = (total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0) * 0.5
    print(f"\nbatch merged: with-dishes={n_with} null={n_null} err={n_err}  "
          f"tokens in={total_in:,} out={total_out:,}  est ${cost:.3f} (50%-off)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from usage_log import log_usage
        log_usage('anthropic.haiku.batch.in',  units=total_in,
                  meta={'script': 'menu_highlights_batch', 'batch_id': batch_id})
        log_usage('anthropic.haiku.batch.out', units=total_out,
                  meta={'script': 'menu_highlights_batch', 'batch_id': batch_id})
    except Exception:
        pass


if __name__ == '__main__':
    main()
