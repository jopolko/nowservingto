#!/usr/bin/env python3
"""
Enrich data/corridors.json newOpenings entries with Google Places data:
  - website (where available)
  - url (Google Maps profile, always present)
  - rating + user_ratings_total
  - matched place name + lat/lng

Cached in tools/cache/places_cache.json so re-runs are cheap.
Reads GOOGLE_API_KEY from /var/secrets/nowservingto.env.

Cost: ~$0.042 per uncached opening (Find Place + Place Details).
Hard abort at $30 cumulative spend per run for safety.
"""
import os, sys, json, time, re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / 'data' / 'corridors.json'
CACHE_PATH = ROOT / 'tools' / 'cache' / 'places_cache.json'
SECRETS = Path('/var/secrets/nowservingto.env')

COST_FINDPLACE = 0.017
COST_DETAILS   = 0.025  # Basic + Contact + Atmosphere combined
COST_PER_PAIR  = COST_FINDPLACE + COST_DETAILS
COST_HARD_CAP  = 30.00  # USD safety abort
LARGE_RUN_THRESHOLD = 500  # require --confirm above this many lookups
SCRIPT = 'enrich_places'   # tag for usage_log so spikes attribute back here

def load_api_key():
    if not str(ROOT).startswith('/var/www/'):
        sys.exit(
            "Google Places API calls are restricted to the VPS IP.\n"
            "Run this script via SSH or push and let cron handle it."
        )
    if not SECRETS.exists():
        sys.exit(f"missing {SECRETS}")
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('GOOGLE_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit("GOOGLE_API_KEY not found in secrets file")

API_KEY = load_api_key()

def http_get_json(url, params, timeout=15):
    q = urlencode(params)
    req = Request(f"{url}?{q}", headers={'User-Agent': 'nowservingto-enrich/1.0'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def find_place(query):
    r = http_get_json(
        'https://maps.googleapis.com/maps/api/place/findplacefromtext/json',
        {'input': query, 'inputtype': 'textquery',
         'fields': 'place_id,name,formatted_address', 'key': API_KEY}
    )
    try:
        from usage_log import log_usage
        log_usage('places.find_place', meta={'script': SCRIPT, 'q': query[:80]})
    except Exception: pass
    if r.get('status') != 'OK': return None
    cands = r.get('candidates') or []
    return cands[0] if cands else None

def place_details(place_id):
    # `reviews` and `editorial_summary` are within the Atmosphere Data SKU we
    # already hit (via `rating`/`user_ratings_total`), so adding them is free
    # at our scale (well under the 10K/month per-SKU free tier on legacy API).
    # `photos` returns photo_references at no extra cost; downloading the
    # actual bytes via download_place_photo() is what's billed.
    r = http_get_json(
        'https://maps.googleapis.com/maps/api/place/details/json',
        {'place_id': place_id,
         'fields': 'name,website,types,rating,user_ratings_total,formatted_address,geometry/location,url,business_status,reviews,editorial_summary,photos',
         'key': API_KEY}
    )
    try:
        from usage_log import log_usage
        log_usage('places.details', meta={'script': SCRIPT, 'place_id': place_id})
    except Exception: pass
    if r.get('status') != 'OK': return None
    return r.get('result')


def download_place_photo(photo_reference, max_width=1600):
    """Fetch the actual JPEG bytes for a Place photo. Costs ~$0.007 per call
    (Places Photo SKU). Returns (bytes, content_type) or (None, None)."""
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    url = 'https://maps.googleapis.com/maps/api/place/photo?' + urlencode({
        'maxwidth': str(max_width),
        'photo_reference': photo_reference,
        'key': API_KEY,
    })
    req = Request(url, headers={'User-Agent': 'nowservingto-enrich/1.0'})
    try:
        with urlopen(req, timeout=30) as r:
            data = r.read()
            ct = r.headers.get('Content-Type', 'image/jpeg')
            try:
                from usage_log import log_usage
                log_usage('places.photo', meta={'script': SCRIPT})
            except Exception: pass
            return data, ct
    except Exception:
        return None, None


def streetview_metadata(lat, lng):
    """Check whether Street View imagery exists at the given coords. FREE
    (no charge for the metadata endpoint). Returns the dict {'status':...,
    'date':..., 'pano_id':...} or None on error. Used to gate the billable
    streetview_image() call so we don't pay for ZERO_RESULTS responses."""
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    url = 'https://maps.googleapis.com/maps/api/streetview/metadata?' + urlencode({
        'location': f'{lat},{lng}', 'key': API_KEY,
    })
    try:
        req = Request(url, headers={'User-Agent': 'nowservingto-enrich/1.0'})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        try:
            from usage_log import log_usage
            log_usage('streetview.metadata', meta={'script': SCRIPT})   # free, logged for visibility
        except Exception: pass
        return data
    except Exception:
        return None


def streetview_image(lat, lng, size='640x640', fov=80, heading=None, pitch=0):
    """Fetch the Street View Static JPEG bytes for the given coords. Costs
    ~$0.007 per call (Street View Static SKU). Standard tier caps each
    dimension at 640. Returns (bytes, content_type) or (None, None).
    Use streetview_metadata() first to gate this - paying $0.007 only on
    coords Google has imagery for."""
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
    params = {
        'location': f'{lat},{lng}',
        'size': size,
        'fov': str(fov),
        'pitch': str(pitch),
        'key': API_KEY,
    }
    if heading is not None:
        params['heading'] = str(heading)
    url = 'https://maps.googleapis.com/maps/api/streetview?' + urlencode(params)
    req = Request(url, headers={'User-Agent': 'nowservingto-enrich/1.0'})
    try:
        with urlopen(req, timeout=30) as r:
            data = r.read()
            try:
                from usage_log import log_usage
                log_usage('streetview.image', meta={'script': SCRIPT})
            except Exception: pass
            return data, r.headers.get('Content-Type', 'image/jpeg')
    except Exception:
        return None, None

from places_key import cache_key  # canonical shared helper
from chain_filter import is_known_chain, chain_set_summary

def _address_matches(queried_addr, matched_addr):
    """Sanity-check that Google's match actually sits on the same street as the
    queried address. Places' fuzzy text search will confidently return a
    completely different restaurant when the name is garbled ("SONARBANGLA" →
    "Ruposhi Bangla Restaurant" 5 km away)."""
    import re
    if not queried_addr or not matched_addr: return False
    m = re.match(r'^\s*(\d+)\s+([A-Za-z]+)', queried_addr)
    if not m: return True
    num, street = m.group(1), m.group(2).upper()
    addr_up = matched_addr.upper()
    return num in addr_up and street in addr_up


def _address_fuzzy_matches(queried_addr, matched_addr, max_num_delta=8):
    """Looser version of _address_matches that allows the street number to
    differ by up to N. Catches City permit-file typos like AROI THAI listed
    at 1218 Queen St E in the licence file but registered at 1216 in Places
    (real example, 2026-05-27). Same street name + small number delta is
    strong evidence we have the right business, especially when paired with
    a high name-overlap score.

    Only used as a fallback when strict _address_matches fails - we don't
    want to relax the strict path because that catches the truly garbled
    cases (wrong name returning a totally different business 5km away)."""
    import re
    if not queried_addr or not matched_addr: return False
    m1 = re.match(r'^\s*(\d+)\s+([A-Za-z]+)', queried_addr)
    m2 = re.search(r'(\d+)\s+([A-Za-z]+)', matched_addr)
    if not m1 or not m2: return False
    n1, s1 = int(m1.group(1)), m1.group(2).upper()
    n2, s2 = int(m2.group(1)), m2.group(2).upper()
    return s1 == s2 and abs(n1 - n2) <= max_num_delta

def _coords_from_geocode(operating_name, address):
    """Pull lat/lng from the Nominatim geocode cache when find_place fails - we
    can then use Places Nearby Search to find the actual business at those
    coords, which works even when the name is run-together or has hidden
    keywords like 'Premium' that wreck the text-based queries."""
    try:
        import json
        from pathlib import Path
        gc_path = Path(__file__).parent / 'cache' / 'geocode_cache.json'
        if not gc_path.exists(): return None
        c = json.loads(gc_path.read_text())
        # Geocode cache key uses street-only (no postal), so strip postal first
        import re
        a = re.sub(r'\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d$', '', (address or '').upper()).strip()
        key = f"{(operating_name or '').strip().upper()}||{a}"
        e = c.get(key)
        if e and e.get('lat'): return (e['lat'], e['lng'])
    except Exception:
        pass
    return None

def _name_tokens(s):
    """Tokenize a business name for fuzzy comparison. Strips diacritics so
    'Ôi BÁNH MÌ' and 'OI BANH MI' produce identical token sets - Haiku can read
    those as the same, but our regex can't unless we normalize."""
    import re, unicodedata
    # NFD splits "ô" → "o" + combining-circumflex; the Mn-category filter then
    # drops the combining mark, leaving plain ASCII. Handles French/Portuguese/
    # Vietnamese/Spanish/Polish diacritics generically.
    norm = unicodedata.normalize('NFD', (s or '').upper())
    ascii_only = ''.join(c for c in norm if unicodedata.category(c) != 'Mn')
    return {t for t in re.findall(r'[A-Z0-9]{2,}', ascii_only)
            if t not in {'THE','AND','OF','INC','LTD','CO','LLC',
                         'RESTAURANT','CAFE','BAR','GRILL','KITCHEN','HOUSE','SHOP',
                         'PREMIUM','EXPRESS','TAKE','OUT','TAKEOUT','BISTRO','EATERY'}}

def _name_overlap(a, b):
    """Score similarity allowing for run-together names. 'SONARBANGLA' matches
    'SONAR' + 'BANGLA' via substring containment (which exact-set Jaccard misses)."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb: return 0.0
    matches = 0
    for x in ta:
        for y in tb:
            if x == y or (len(x) >= 4 and x in y) or (len(y) >= 4 and y in x):
                matches += 1
                break
    return matches / max(len(ta), len(tb))

def _textsearch_fallback(operating_name, addr_first):
    """Places Text Search ('place/textsearch') with just NAME + Toronto, no
    address. More permissive than find_place: matches against business
    name + type globally, returns candidates with formatted_address we can
    then verify against the licence address. Catches restaurants whose
    City-licence address (suite-level, e.g. "2965 ISLINGTON AVE, #14")
    confuses find_place but whose Google business listing is keyed on
    the building address. Used as a last-resort when find_place AND the
    coords-nearby path both came up empty."""
    q = f"{operating_name} Toronto"
    r = http_get_json('https://maps.googleapis.com/maps/api/place/textsearch/json',
        {'query': q, 'type': 'restaurant', 'key': API_KEY})
    try:
        from usage_log import log_usage
        log_usage('places.text_search', meta={'script': SCRIPT, 'q': q[:80]})
    except Exception: pass
    cands = r.get('results') or []
    if not cands: return None
    # Score by name overlap AND street-token match to the licence address.
    # Avoid picking a same-name spot at a totally different street.
    addr_street = (addr_first or '').upper().split(',')[0]
    addr_tokens = set(re.findall(r'[A-Z]{3,}', addr_street))
    scored = []
    for c in cands[:5]:
        name_score = _name_overlap(operating_name, c.get('name', ''))
        cand_addr = (c.get('formatted_address') or '').upper()
        addr_match = any(t in cand_addr for t in addr_tokens) if addr_tokens else False
        if name_score >= 0.3 and addr_match:
            scored.append((c, name_score))
    if not scored: return None
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]

def _nearby_fallback(lat, lng, name_hint):
    """Places Nearby Search at the geocoded coords. 250m radius accounts for
    Nominatim's typical pin offset from Google's business location. Returns
    the result with highest name overlap so we don't accidentally pick a
    neighbouring restaurant in a strip mall."""
    r = http_get_json('https://maps.googleapis.com/maps/api/place/nearbysearch/json',
        {'location': f'{lat},{lng}', 'radius': 250, 'type': 'restaurant', 'key': API_KEY})
    cands = r.get('results') or []
    if not cands: return None
    # Rank by name overlap to disambiguate when several restaurants are nearby
    scored = [(c, _name_overlap(name_hint, c.get('name', ''))) for c in cands]
    scored.sort(key=lambda x: -x[1])
    best, best_score = scored[0]
    # Require at least one shared content-token (drops random nearby restaurants)
    return best if best_score >= 0.2 else None

def enrich_one(operating_name, address):
    addr_first = (address or '').split('M')[0].strip().rstrip(',')
    query = f"{operating_name} {addr_first} Toronto" if addr_first else f"{operating_name} Toronto"
    cand = find_place(query)
    # If the text query missed the actual restaurant (very common when the name
    # is run-together like "SONARBANGLA" or has hidden marketing keywords like
    # "Premium"), fall back to Nearby Search around the geocoded coords.
    # Also reject when address matches but the name overlap is too thin - Places
    # will happily return a CAR WASH at "828 Eastern Ave" when we queried for
    # "Eastern 828 Cafe & Grill" (real example, 2026-05-14). Address alone isn't
    # enough; require some substantive name-token agreement too.
    name_overlap_score = _name_overlap(operating_name, cand.get('name', '')) if cand else 0.0
    name_ok = name_overlap_score >= 0.25
    addr_ok = cand and _address_matches(addr_first, cand.get('formatted_address'))
    # Fuzzy fallback: same street, off-by-N number, AND strong name overlap.
    # Catches City permit-file typos (e.g. AROI THAI listed at 1218 Queen St E
    # in the licence file but registered at 1216 in Places). We require a
    # higher name_overlap threshold (0.5) than the strict path to avoid
    # false positives - a same-street neighbour with a vaguely similar name
    # could otherwise slip through.
    addr_fuzzy_ok = (cand and not addr_ok and name_overlap_score >= 0.5
                     and _address_fuzzy_matches(addr_first, cand.get('formatted_address')))
    if not cand or (not addr_ok and not addr_fuzzy_ok) or not name_ok:
        coords = _coords_from_geocode(operating_name, address)
        nearby = None
        if coords:
            nearby = _nearby_fallback(coords[0], coords[1], operating_name)
        if nearby:
            cand = nearby  # Nearby Search has same shape (place_id + name + vicinity)
        else:
            # Last resort: Places Text Search with just "NAME Toronto" (no
            # address-suite confusion). Useful when find_place chokes on
            # "2965 ISLINGTON AVE, #14" suite syntax and Nominatim can't
            # geocode that exact address either. Strict name+street-token
            # matching prevents picking up an unrelated same-named spot.
            ts = _textsearch_fallback(operating_name, addr_first)
            if ts:
                cand = ts
            else:
                note = 'no nearby match' if coords else 'no coords + textsearch empty'
                return {'status': 'not_found', 'query': query, 'note': note}
    details = place_details(cand['place_id'])
    if not details:
        return {'status': 'no_details', 'place_id': cand['place_id'], 'query': query}
    loc = (details.get('geometry') or {}).get('location') or {}
    # Trim reviews to text + timestamp + relative-time. Used to be text-only
    # but we now need date data to gate "newly registered" inclusion: a
    # restaurant whose 5 returned reviews include any > 365 days old has
    # been operating before its current City licence, which means our
    # "newly registered" claim is misleading (the City paperwork event is
    # not the same as the restaurant's opening). See the suppression
    # logic in inject_openings.py.
    reviews_raw = details.get('reviews') or []
    reviews = []
    reviews_text = []   # keep the legacy text-only list for backward compat with downstream code
    for r in reviews_raw[:5]:
        t = (r.get('text') or '').strip()
        review_obj = {
            'time': r.get('time'),                                  # unix epoch seconds
            'relative_time': r.get('relative_time_description'),    # "8 months ago" etc.
            'rating': r.get('rating'),
            'text': t[:600] if t else '',
        }
        reviews.append(review_obj)
        if t: reviews_text.append(t[:600])
    editorial = (details.get('editorial_summary') or {}).get('overview') if isinstance(details.get('editorial_summary'), dict) else None
    # First photo reference (if any) - downloading the bytes is a separate
    # billable Places Photo SKU; we cache the ref here and download on demand.
    photos = details.get('photos') or []
    photo_ref = photos[0].get('photo_reference') if photos else None
    # html_attributions per photo — Google's ToS requires displaying author
    # attribution near every cached photo. Strip the wrapping <a> tags and
    # keep the plain author name; we'll render with our own styling.
    import re as _re_attrib
    photo_attribs = []
    if photos and photos[0].get('html_attributions'):
        for raw in photos[0]['html_attributions']:
            # Typical format: '<a href="https://maps.google.com/maps/contrib/...">Author Name</a>'
            txt = _re_attrib.sub(r'<[^>]+>', '', raw).strip()
            if txt: photo_attribs.append(txt)
    return {
        'status': 'ok',
        'place_id': cand['place_id'],
        'matchedName': details.get('name'),
        'matchedAddress': details.get('formatted_address'),
        'website': details.get('website'),
        'mapsUrl': details.get('url'),
        'rating': details.get('rating'),
        'reviewCount': details.get('user_ratings_total'),
        'types': details.get('types'),
        'lat': loc.get('lat'),
        'lng': loc.get('lng'),
        'businessStatus': details.get('business_status'),
        'reviews': reviews_text,             # list[str] - up to 5 trimmed review texts (legacy field, kept for downstream consumers)
        'reviewsDetail': reviews,            # list[dict] - {time, relative_time, rating, text} - date data for opening-gate logic
        'editorialSummary': editorial,       # str or None - Google's curated description (sometimes mentions "since YYYY")
        'photoRef': photo_ref,               # str or None - first photo_reference for og:image
        'photoAttribs': photo_attribs,       # list[str] - per Places ToS, must display author near cached photo
        'query': query,
    }

def main():
    data = json.loads(DATA_PATH.read_text())
    no = data.get('newOpenings')
    if not no:
        sys.exit("data/corridors.json has no newOpenings key - run inject_openings.py first")

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache: {len(cache)} entries already enriched")
    print(chain_set_summary())

    # Pull validator verdicts so we can skip Places for entries already
    # known to be non-restaurants.
    wv_path = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
    wv = json.loads(wv_path.read_text()) if wv_path.exists() else {}

    # Collect unique (name, address) pairs across the recent feed and per-cuisine recent5 lists
    pairs = {}
    def add(e):
        k = e.get('_cacheKey') or cache_key(e.get('operatingName'), e.get('address'))
        if k not in pairs: pairs[k] = e
    for e in no.get('recent', []): add(e)
    for c in no.get('cuisines', []):
        for e in c.get('recent5', []): add(e)
        ne = c.get('newest')
        if ne: add(ne)

    # Apply chain + validator-drop gates BEFORE issuing any API call.
    # These are the single biggest cost savers (added 2026-05-20 after a
    # cron run spent ~$4 looking up Pokeworks/Marugame/Popeyes/etc., all
    # of which the validator drops downstream).
    def _skip_reason(k, e):
        name = e.get('operatingName') or k.split('||', 1)[0]
        if is_known_chain(name): return 'chain'
        if (wv.get(k) or {}).get('validator_drop'): return 'validator-drop'
        return None
    # --refetch-missing-reviews: re-fetch entries already in cache that lack
    # the new `reviewsDetail` field (time + relative_time + rating per review).
    # Used after the 2026-06-01 schema upgrade to backfill date data needed
    # for the opening-gate logic without re-fetching entries we already have
    # full review-detail data for.
    refetch_missing = '--refetch-missing-reviews' in sys.argv
    n_chain = n_drop = 0
    to_fetch = []
    for k, e in pairs.items():
        if k in cache:
            if refetch_missing:
                # Only re-fetch if reviewsDetail is missing (didn't exist
                # in the cache before the schema upgrade)
                c = cache[k]
                if c.get('status') == 'ok' and 'reviewsDetail' not in c:
                    reason = _skip_reason(k, e)
                    if reason == 'chain': n_chain += 1; continue
                    if reason == 'validator-drop': n_drop += 1; continue
                    to_fetch.append((k, e))
            continue
        reason = _skip_reason(k, e)
        if reason == 'chain': n_chain += 1; continue
        if reason == 'validator-drop': n_drop += 1; continue
        to_fetch.append((k, e))
    n_cached = sum(1 for k in pairs if k in cache)
    print(f"openings to enrich: {len(to_fetch)}")
    print(f"  (skipping: {n_cached} cached + {n_chain} known chains + {n_drop} validator-rejected)")
    est_cost = len(to_fetch) * COST_PER_PAIR
    print(f"estimated API spend: ${est_cost:.2f}")
    if est_cost > COST_HARD_CAP:
        print(f"  (will abort at hard cap ${COST_HARD_CAP:.2f}; not all entries will be processed)")
    # Large-run confirm gate. Requires --confirm to proceed past
    # LARGE_RUN_THRESHOLD lookups. Added after a 2026-06-01 manual run
    # silently burned $18 of Places in 6 minutes — visible only in
    # post-hoc usage_log inspection. The cron daily run rarely exceeds
    # ~50 fetches, so this only fires for deliberate backfills.
    if len(to_fetch) > LARGE_RUN_THRESHOLD and '--confirm' not in sys.argv:
        print(f"\n  ABORT: {len(to_fetch)} lookups exceeds LARGE_RUN_THRESHOLD={LARGE_RUN_THRESHOLD}")
        print(f"  Estimated spend ${est_cost:.2f}. Re-run with --confirm to proceed.")
        sys.exit(2)

    spent = 0.0
    ok = err = 0
    t0 = time.time()
    for i, (k, e) in enumerate(to_fetch, 1):
        if spent + COST_PER_PAIR > COST_HARD_CAP:
            print(f"  HARD CAP HIT at ${spent:.2f} after {i-1} requests - stopping")
            break
        try:
            result = enrich_one(e.get('operatingName'), e.get('address'))
            cache[k] = result
            spent += COST_PER_PAIR
            if result['status'] == 'ok': ok += 1
            else: err += 1
            if i % 25 == 0 or i == len(to_fetch):
                el = time.time() - t0
                print(f"  [{i:>4}/{len(to_fetch)}]  ok={ok}  miss={err}  spent=${spent:.2f}  {el:.0f}s elapsed")
                # checkpoint to disk every 25
                CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
        except Exception as ex:
            print(f"  ERROR on {e.get('operatingName')!r}: {ex}")
            err += 1
        # politeness: ~5 req/sec
        time.sleep(0.2)

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    print(f"\nFinal: ok={ok}  miss/err={err}  total spent≈${spent:.2f}  cache now={len(cache)}")

    # Now merge cache → corridors.json newOpenings entries
    print("Merging enrichments back into data/corridors.json…")
    def merge(e):
        k = e.get('_cacheKey') or cache_key(e.get('operatingName'), e.get('address'))
        ent = cache.get(k)
        if not ent or ent.get('status') != 'ok': return
        for key in ('website', 'mapsUrl', 'rating', 'reviewCount', 'matchedName', 'lat', 'lng'):
            if ent.get(key) is not None:
                e[key] = ent[key]
    for e in no.get('recent', []): merge(e)
    for c in no.get('cuisines', []):
        for e in c.get('recent5', []): merge(e)
        ne = c.get('newest')
        if ne: merge(ne)

    # quick stats: how many have website vs maps fallback
    n_recent = len(no.get('recent', []))
    n_web = sum(1 for e in no.get('recent', []) if e.get('website'))
    n_maps = sum(1 for e in no.get('recent', []) if e.get('mapsUrl'))
    print(f"  recent feed coverage: {n_web}/{n_recent} have website, {n_maps}/{n_recent} have any link")

    DATA_PATH.write_text(json.dumps(data, separators=(',', ':')))
    print(f"  wrote {DATA_PATH}")

if __name__ == '__main__':
    main()
