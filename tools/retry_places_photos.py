#!/usr/bin/env python3
"""
Places multi-photo retry pass.

When the classifier rejects photos[0] (the first photo Places returned
for a place_id) AND Street View also fails (retry_denied_photos.py),
this script refetches Place Details to get ALL photo references (up to
10), then tries them in order: download → classify → keep first one
that passes.

Common cases this recovers:
  - photos[0] is a customer-uploaded view of the parking lot but
    photos[1] is the actual food / interior / signage
  - photos[0] is a wrong-building image attached to the CID; later
    refs from the owner's own uploads are correct

When all Place Details photo refs are exhausted, the slug stays
denied (we've tried everything reasonable).

Persistent attempt log: tools/cache/photo_attempts.json (shared with
retry_denied_photos.py) - the `approaches` list records which sources
have been tried. `places_refs_tried` records specific photo_references
already attempted so we don't repeat.

Cost: ~$0.017 Place Details refetch + $0.007 per photo download + ~$0.0006
per classification. Typical case finds a good photo in 1-3 retries
= ~$0.04 per slug.
"""
import os, sys, json, base64
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

PHOTO_DIR    = ROOT / 'og' / 'photo'
THUMB_DIR    = ROOT / 'og' / 'thumb'
DATA_PATH    = ROOT / 'data' / 'corridors.json'
PC_PATH      = ROOT / 'tools' / 'cache' / 'places_cache.json'
CLS_PATH     = ROOT / 'tools' / 'cache' / 'photo_classification.json'
ATTEMPT_PATH = ROOT / 'tools' / 'cache' / 'photo_attempts.json'
SECRETS      = Path('/var/secrets/nowservingto.env')
MODEL        = 'claude-haiku-4-5-20251001'

SYSTEM_PROMPT = """You are classifying images returned for a directory of
newly licensed Toronto restaurants. Decide whether the image depicts a
restaurant in ANY form (storefront, interior, food, signage, menu,
food prep) or something clearly NOT restaurant-related (hair salon,
gas station, parking lot, paint section, generic landscape, unrelated
retail).

Be liberal toward restaurant; be strict only when clearly something else.

Return JSON: {"is_restaurant_or_food": true/false, "description": "<one line>"}
"""


def _read_secret(key):
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith(f'{key}='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None


ANTHROPIC_KEY = _read_secret('ANTHROPIC_API_KEY')
GOOGLE_KEY    = _read_secret('GOOGLE_API_KEY')
if not ANTHROPIC_KEY or not GOOGLE_KEY:
    sys.exit("missing ANTHROPIC_API_KEY or GOOGLE_API_KEY")


def _http_get(url, max_bytes=8_000_000, timeout=20):
    try:
        with urlopen(url, timeout=timeout) as r:
            return r.read(max_bytes), r.headers.get('Content-Type', '')
    except Exception as e:
        print(f"  GET error: {e}")
        return None, None


def place_details(place_id):
    """Refetch Place Details to get ALL photo_references. $0.017/call."""
    url = ('https://maps.googleapis.com/maps/api/place/details/json?'
           + urlencode({
               'place_id': place_id,
               'fields': 'photo,name,business_status',
               'key': GOOGLE_KEY,
           }))
    raw, _ = _http_get(url, timeout=30)
    if not raw: return None
    try: return json.loads(raw)
    except Exception: return None


def download_photo(photo_reference, max_width=1600):
    """Places Photo API. $0.007/call. Returns (bytes, content-type)."""
    url = ('https://maps.googleapis.com/maps/api/place/photo?'
           + urlencode({
               'maxwidth': max_width,
               'photo_reference': photo_reference,
               'key': GOOGLE_KEY,
           }))
    return _http_get(url, timeout=30)


def _extract_json(text):
    """Parse Haiku response, handling markdown ```json fences."""
    import re
    s = text.strip()
    m = re.search(r'```(?:json)?\s*\n?(.+?)\n?```', s, re.DOTALL)
    if m: s = m.group(1).strip()
    if s.startswith('{') and s.endswith('}'):
        try: return json.loads(s)
        except Exception: pass
    for ln in s.split('\n'):
        t = ln.strip().lstrip('`').strip()
        if t.startswith('{') and t.endswith('}'):
            try: return json.loads(t)
            except Exception: continue
    return None


def classify_image(jpeg_bytes, media_type='image/jpeg'):
    """Sync Haiku vision call. Returns (is_food: bool|None, desc: str)."""
    b64 = base64.standard_b64encode(jpeg_bytes).decode('ascii')
    body = json.dumps({
        'model': MODEL, 'max_tokens': 100, 'system': SYSTEM_PROMPT,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {
                    'type': 'base64', 'media_type': media_type, 'data': b64}},
                {'type': 'text', 'text': 'Classify this restaurant-directory image.'},
            ],
        }],
    }).encode('utf-8')
    req = Request('https://api.anthropic.com/v1/messages', data=body, headers={
        'x-api-key': ANTHROPIC_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    })
    try:
        with urlopen(req, timeout=60) as r:
            obj = json.loads(r.read())
    except Exception as e:
        print(f"  classify error: {e}")
        return None, None
    text = ''.join(b.get('text', '') for b in obj.get('content', [])
                   if b.get('type') == 'text').strip()
    parsed = _extract_json(text)
    if parsed is None: return None, None
    return bool(parsed.get('is_restaurant_or_food')), parsed.get('description', '')


def regen_thumb(photo_path, thumb_path, size=196):
    """Regen webp thumb via PIL; fall back to deleting stale thumb so
    inject_openings.py regenerates with its _make_thumb on next pass."""
    try:
        from PIL import Image
        with Image.open(photo_path) as im:
            im.thumbnail((size, size))
            im.save(thumb_path, 'WEBP', quality=82, method=6)
        return True
    except Exception:
        try: thumb_path.unlink()
        except FileNotFoundError: pass
        return False


def main():
    cls      = json.loads(CLS_PATH.read_text())     if CLS_PATH.exists() else {}
    pc       = json.loads(PC_PATH.read_text())      if PC_PATH.exists() else {}
    attempts = json.loads(ATTEMPT_PATH.read_text()) if ATTEMPT_PATH.exists() else {}
    data     = json.loads(DATA_PATH.read_text())

    slug_to_ck = {r['slug']: r['_cacheKey'] for r in
                  data.get('newOpenings', {}).get('recent', [])
                  if r.get('slug') and r.get('_cacheKey')}

    # Candidates: still-denied slugs that haven't exhausted Places multi-photo
    candidates = []
    for slug, v in cls.items():
        if v.get('status') != 'ok': continue
        if v.get('is_restaurant_or_food'): continue
        rec = attempts.get(slug) or {}
        if rec.get('places_multi_exhausted'): continue
        if slug not in slug_to_ck: continue
        ck = slug_to_ck[slug]
        pe = pc.get(ck) or {}
        if not pe.get('place_id'): continue
        candidates.append((slug, ck, pe['place_id']))

    print(f"still-denied with place_id available: {len(candidates)}")
    if not candidates:
        return

    n_recovered = n_exhausted = n_error = 0
    pd_cost = photo_cost = classify_cost = 0.0
    now_iso = datetime.utcnow().isoformat() + 'Z'

    for slug, ck, place_id in candidates:
        rec = attempts.setdefault(slug, {'approaches': []})
        tried_refs = set(rec.get('places_refs_tried') or [])

        # Refetch Place Details to get the full photo ref list
        det = place_details(place_id)
        pd_cost += 0.017
        if not det or det.get('status') != 'OK':
            rec['places_multi_exhausted'] = True
            n_error += 1
            print(f"  {slug}: Place Details refetch failed")
            continue
        result = det.get('result') or {}
        all_photos = result.get('photos') or []
        # Filter to unused refs
        candidate_refs = [p.get('photo_reference') for p in all_photos
                          if p.get('photo_reference')
                          and p.get('photo_reference') not in tried_refs]
        if not candidate_refs:
            rec['places_multi_exhausted'] = True
            n_exhausted += 1
            print(f"  {slug}: no more photo refs to try ({len(all_photos)} total)")
            continue

        recovered_here = False
        for ref in candidate_refs:
            tried_refs.add(ref)
            img_bytes, ctype = download_photo(ref)
            photo_cost += 0.007
            if not img_bytes:
                continue
            mt = 'image/jpeg' if 'jpeg' in (ctype or '').lower() else \
                 'image/png'  if 'png'  in (ctype or '').lower() else 'image/jpeg'
            is_food, desc = classify_image(img_bytes, media_type=mt)
            classify_cost += 0.0006
            if is_food is None:
                print(f"  {slug}: classify error on a candidate, skipping")
                continue
            if is_food:
                photo_path = PHOTO_DIR / f'{slug}.jpg'
                thumb_path = THUMB_DIR / f'{slug}.webp'
                photo_path.write_bytes(img_bytes)
                regen_thumb(photo_path, thumb_path)
                cls[slug] = {
                    'status': 'ok',
                    'is_restaurant_or_food': True,
                    'description': desc[:160],
                    'via': 'retry-places-multi',
                    'classified_at': now_iso,
                }
                # Update places_cache.photoRef to point at the new approved ref
                pc.setdefault(ck, {})['photoRef'] = ref
                n_recovered += 1
                recovered_here = True
                print(f"  ✓ {slug}: Places ref passed → {desc[:80]}")
                break
            # else keep iterating, this ref didn't pass
        if not recovered_here:
            rec['places_multi_exhausted'] = True
            n_exhausted += 1
            print(f"  ✗ {slug}: all {len(candidate_refs)} candidate photos failed")
        rec['places_refs_tried'] = list(tried_refs)
        rec['last_attempted'] = now_iso

    CLS_PATH.write_text(json.dumps(cls, separators=(',', ':')))
    PC_PATH.write_text(json.dumps(pc, separators=(',', ':')))
    ATTEMPT_PATH.write_text(json.dumps(attempts, separators=(',', ':')))
    total_cost = pd_cost + photo_cost + classify_cost
    print(f"\nrecovered={n_recovered} exhausted={n_exhausted} error={n_error}  "
          f"spend: ${pd_cost:.3f} PD + ${photo_cost:.3f} photos + ${classify_cost:.4f} classify = ${total_cost:.3f}")


if __name__ == '__main__':
    main()
