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
import os, sys, json, time, re, argparse
from datetime import datetime, timezone, timedelta
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

SYSTEM_PROMPT = """You read a restaurant's website text and return TWO
menu signals:

A) `dishes` — SPECIFIC DISH NAMES that appear VERBATIM in the text.
B) `categories` — MENU SECTION NAMES / FOOD-TYPE GROUPINGS that appear
                  verbatim in the text, used as a fallback when dish
                  names aren't extractable.

Strict rules:

1. NEVER invent or infer. Both fields must come VERBATIM (or near-verbatim
   with trivial capitalization changes) from the text. Do not translate,
   do not add common items of the cuisine that aren't named.

2. `dishes` = specific, recognizable food items.
   - YES: "mandi", "shawarma", "pho", "banh mi", "jollof rice", "pad thai",
          "injera", "tibs", "kibbeh", "kulcha", "biryani", "tagine",
          "samosa", "beef hari kebab", "dhaka beef tehari"
   - NO: categories ("appetizers", "mains", "desserts", "drinks"), cooking
         styles ("grilled", "fried"), cuisine words ("Italian food").
   - Skip generic items ("salad", "sandwich", "burger", "fries") unless the
     restaurant clearly specializes in them.

3. `categories` = the menu's own section headings / food-type groupings.
   These describe what KINDS of food the restaurant serves, even when
   no specific dishes are named. Examples:
   - "biryanis", "curries", "kebabs", "tandoor specials"
   - "noodles", "rice bowls", "small plates", "wraps"
   - "appetizers", "mains", "sides", "desserts"
   - "vegetarian options", "halal", "seafood"
   Use plural forms ("curries" not "curry") when the menu groups by type.
   Skip pure logistics words ("lunch", "dinner", "happy hour", "to go").

4. Maximum 5 of each. Lowercase the output.

5. Prefer dishes over categories. Only include `categories` when you have
   FEWER than 2 dishes — categories are the fallback signal so we can still
   say something useful about menus that only list section headers. If you
   have 2+ dishes, return categories=null. If you have <2 dishes AND <2
   categories, return both null.

Return JSON on one line, nothing else:
  {"dishes": ["dish1", "dish2"], "categories": null}
or:
  {"dishes": null, "categories": ["biryanis", "curries", "kebabs"]}
or:
  {"dishes": null, "categories": null}
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


_CATEGORY_REJECT = {'menu', 'food', 'cuisine', 'lunch', 'dinner',
                    'breakfast', 'brunch', 'happy hour', 'to go', 'takeout',
                    'pickup', 'delivery'}
_DISH_REJECT = _CATEGORY_REJECT | {'appetizers', 'mains', 'entrees',
                                   'desserts', 'sides', 'drinks',
                                   'beverages', 'specials', 'starters',
                                   'small plates', 'salads', 'soups'}


def _clean_dishes(value):
    """Validate + normalize specific dishes. Returns list[str] (>=2) or None."""
    if not isinstance(value, list): return None
    out = []
    for d in value:
        if not isinstance(d, str): continue
        s = re.sub(r'\s+', ' ', d.strip().lower())
        if not s or len(s) > 60: continue
        if s in _DISH_REJECT: continue
        if s not in out:
            out.append(s)
        if len(out) >= 5: break
    return out if len(out) >= 2 else None


def _clean_categories(value):
    """Validate + normalize menu categories. More permissive than dishes —
    we WANT category words here. Returns list[str] (>=2) or None."""
    if not isinstance(value, list): return None
    out = []
    for c in value:
        if not isinstance(c, str): continue
        s = re.sub(r'\s+', ' ', c.strip().lower())
        if not s or len(s) > 40: continue
        if s in _CATEGORY_REJECT: continue
        if s not in out:
            out.append(s)
        if len(out) >= 5: break
    return out if len(out) >= 2 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--max-age-days', type=int, default=0,
                    help='Re-extract entries whose cached extraction is older '
                         'than N days (in addition to never-extracted ones). '
                         'Default 0 = never re-extract (first-time only). '
                         'Recommended: 90 (~quarterly refresh, ~$0.30/sweep).')
    args = ap.parse_args()

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache state: total={len(cache)}  (max-age-days={args.max_age_days})")

    if not DATA_PATH.exists():
        sys.exit(f"{DATA_PATH} missing - run inject_openings.py first")
    if not WEBSITE_TEXT_PATH.exists():
        sys.exit(f"{WEBSITE_TEXT_PATH} missing - nothing to extract from")

    data = json.loads(DATA_PATH.read_text())
    website_text = json.loads(WEBSITE_TEXT_PATH.read_text())
    recent = data.get('newOpenings', {}).get('recent', [])

    # Threshold for "stale" — entries with extracted_at before this get re-run.
    # When max_age_days=0 (default) the cutoff is unreachable, so re-extract is
    # disabled and only never-cached entries become targets.
    if args.max_age_days > 0:
        stale_cutoff = (datetime.now(timezone.utc)
                        - timedelta(days=args.max_age_days)).isoformat()
    else:
        stale_cutoff = None

    # Build target list: entries with a cached website AND that website has
    # non-null text AND one of:
    #   (a) not in cache yet (first-time)
    #   (b) cache entry is older than max-age-days
    #   (c) cache entry was extracted under the old (pre-categories) prompt
    #       — schema upgrade: dishes=None AND 'categories' key absent. Lets
    #       us backfill the 159 nulls with category fallback without a
    #       blanket re-extract of entries that already returned good dishes.
    targets = []   # list of (cache_key, name, text)
    n_no_website = n_no_text = n_already_fresh = n_restale = n_upgrade = 0
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck: continue
        is_restale = False
        is_upgrade = False
        cached = cache.get(ck)
        if cached:
            needs_upgrade = (cached.get('dishes') is None
                             and 'categories' not in cached)
            if needs_upgrade:
                is_upgrade = True
            elif stale_cutoff is None:
                n_already_fresh += 1; continue
            else:
                cached_at = cached.get('extracted_at') or ''
                if cached_at >= stale_cutoff:
                    n_already_fresh += 1; continue
                is_restale = True
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
        if is_restale: n_restale += 1
        if is_upgrade: n_upgrade += 1

    print(f"  candidates: {len(recent)} recent / "
          f"{len(recent) - n_no_website} with website / "
          f"{len(recent) - n_no_website - n_no_text} with cached text / "
          f"{len(targets)} targets ({n_restale} re-extracts, "
          f"{n_upgrade} schema-upgrades, "
          f"{len(targets) - n_restale - n_upgrade} first-time)")

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

    n_with_dishes = n_with_cats = n_null = n_err = 0
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
        categories = None
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
            # Only honor categories when we have no dishes — keeps the
            # render side simple (dishes win when both exist).
            if not dishes:
                categories = _clean_categories(parsed_obj.get('categories'))
        cache[key] = {
            'status': 'ok',
            'dishes': dishes,
            'categories': categories,
            'raw': text_out[:200],
            'in_tok': usage.get('input_tokens', 0),
            'out_tok': usage.get('output_tokens', 0),
            'via': 'batch',
            'extracted_at': extracted_at,
        }
        if dishes:        n_with_dishes += 1
        elif categories:  n_with_cats += 1
        else:             n_null += 1

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    # Batch API: 50% off Haiku list price ($1/Mtok in, $5/Mtok out)
    cost = (total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0) * 0.5
    print(f"\nbatch merged: with-dishes={n_with_dishes} with-categories={n_with_cats} "
          f"null={n_null} err={n_err}  "
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
