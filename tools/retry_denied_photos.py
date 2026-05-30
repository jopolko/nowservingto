#!/usr/bin/env python3
"""
Recovery pass for photos the vision classifier flagged as wrong-business.

For each slug where photo_classification.json says
is_restaurant_or_food=false, walk an attempt ladder:

  1. If we've never tried Street View, fetch it at the geocoded lat/lng,
     classify synchronously via Haiku vision. If it passes, replace
     og/photo/<slug>.jpg + regenerate the og/thumb/<slug>.webp + flip
     the photo_classification verdict to True. If it fails, record the
     attempt so we don't retry.
  2. If all approaches recorded, give up - the row renders text-only.

Persistent attempt log: tools/cache/photo_attempts.json
  {<slug>: {"approaches": ["places", "streetview", ...],
            "last_attempted": ISO-8601}}

Safe to call from cron - cheap (~$0.007 Street View + $0.0006 classify
per slug retried, only retries slugs not yet attempted).

Reads ANTHROPIC_API_KEY + GOOGLE_API_KEY from /var/secrets/nowservingto.env.
"""
import os, sys, json, base64
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

PHOTO_DIR  = ROOT / 'og' / 'photo'
THUMB_DIR  = ROOT / 'og' / 'thumb'
DATA_PATH  = ROOT / 'data' / 'corridors.json'
CLS_PATH   = ROOT / 'tools' / 'cache' / 'photo_classification.json'
ATTEMPT_PATH = ROOT / 'tools' / 'cache' / 'photo_attempts.json'
SECRETS    = Path('/var/secrets/nowservingto.env')
MODEL      = 'claude-haiku-4-5-20251001'

# Match the prompt the batch classifier uses so verdicts are consistent.
SYSTEM_PROMPT = """You are classifying images returned for a directory of
newly licensed Toronto restaurants. Decide whether the image depicts a
restaurant in ANY form (storefront, interior, food dish, signage, menu
board, food prep) or something clearly NOT restaurant-related (hair
salon, gas station, parking lot, paint section, generic landscape,
unrelated retail).

Be LIBERAL toward restaurant: dim interiors, blurry food shots, awkward
storefronts, hole-in-the-wall counters all qualify if there's any food
signal. Default to true on genuine ambiguity. Be strict only when the
photo is clearly something else.

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
if not ANTHROPIC_KEY:
    sys.exit("ANTHROPIC_API_KEY missing")
if not GOOGLE_KEY:
    sys.exit("GOOGLE_API_KEY missing")


def _http_get(url, max_bytes=8_000_000):
    """Plain GET, returns (bytes, content-type) or (None, None)."""
    try:
        with urlopen(url, timeout=20) as r:
            return r.read(max_bytes), r.headers.get('Content-Type', '')
    except Exception as e:
        print(f"  GET error: {e}")
        return None, None


def streetview_meta(lat, lng):
    """Free metadata check - is there imagery at this coord?"""
    from urllib.parse import urlencode
    url = ('https://maps.googleapis.com/maps/api/streetview/metadata?'
           + urlencode({'location': f'{lat},{lng}', 'key': GOOGLE_KEY}))
    raw, _ = _http_get(url)
    if not raw: return None
    try: return json.loads(raw)
    except Exception: return None


def streetview_image(lat, lng, size='640x640', fov=80):
    """Fetch SV static JPEG. Costs $0.007."""
    from urllib.parse import urlencode
    url = ('https://maps.googleapis.com/maps/api/streetview?'
           + urlencode({'size': size, 'location': f'{lat},{lng}',
                        'fov': fov, 'key': GOOGLE_KEY}))
    return _http_get(url)


def classify_image(jpeg_bytes):
    """Synchronous Haiku vision classification. Returns (is_food, desc) or
    (None, None) on error. Cost ~$0.0006 per call at sync pricing."""
    b64 = base64.standard_b64encode(jpeg_bytes).decode('ascii')
    body = json.dumps({
        'model': MODEL,
        'max_tokens': 100,
        'system': SYSTEM_PROMPT,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {
                    'type': 'base64', 'media_type': 'image/jpeg', 'data': b64}},
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
    except HTTPError as e:
        print(f"  classify HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        return None, None
    text = ''.join(b.get('text', '') for b in obj.get('content', [])
                   if b.get('type') == 'text').strip()
    parsed = _extract_json(text)
    if parsed is None:
        return None, None
    return bool(parsed.get('is_restaurant_or_food')), parsed.get('description', '')


def _extract_json(text):
    """Parse JSON out of a Haiku response. Handles three formats:
    single-line `{...}`, multi-line JSON object, and markdown-fenced
    ```json\\n{...}\\n``` (Haiku's sync responses tend to use the
    fenced form even when asked for one-line JSON)."""
    import re
    s = text.strip()
    # Strip markdown code fences if present
    m = re.search(r'```(?:json)?\s*\n?(.+?)\n?```', s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    # Try parsing the whole block
    if s.startswith('{') and s.endswith('}'):
        try: return json.loads(s)
        except Exception: pass
    # Fall back: scan for any single line that's valid JSON
    for ln in s.split('\n'):
        t = ln.strip().lstrip('`').strip()
        if t.startswith('{') and t.endswith('}'):
            try: return json.loads(t)
            except Exception: continue
    return None


def regen_thumb(photo_path, thumb_path, size=196):
    """Regenerate the webp thumbnail. Tries PIL, falls back to leaving
    the old thumb if PIL isn't installed (inject_openings.py will
    regenerate via its own _make_thumb on the next pass)."""
    try:
        from PIL import Image
        with Image.open(photo_path) as im:
            im.thumbnail((size, size))
            im.save(thumb_path, 'WEBP', quality=82, method=6)
        return True
    except Exception:
        # Best-effort: delete the stale thumb so inject regenerates next pass.
        try: thumb_path.unlink()
        except FileNotFoundError: pass
        return False


def main():
    cls = json.loads(CLS_PATH.read_text()) if CLS_PATH.exists() else {}
    attempts = json.loads(ATTEMPT_PATH.read_text()) if ATTEMPT_PATH.exists() else {}
    data = json.loads(DATA_PATH.read_text())

    # Build slug -> (lat, lng) lookup from corridors.json (every kept entry
    # has its coords). We need coords to try Street View.
    coords = {}
    for r in data.get('newOpenings', {}).get('recent', []):
        slug = r.get('slug')
        if slug and r.get('lat') is not None and r.get('lng') is not None:
            coords[slug] = (r['lat'], r['lng'])

    # Candidates: slugs flagged as not-restaurant and not yet exhausted
    candidates = []
    for slug, v in cls.items():
        if v.get('status') != 'ok': continue
        if v.get('is_restaurant_or_food'): continue
        approaches = (attempts.get(slug) or {}).get('approaches') or []
        if 'streetview' in approaches: continue
        candidates.append(slug)

    print(f"denied photos: {sum(1 for v in cls.values() if v.get('status')=='ok' and not v.get('is_restaurant_or_food'))} total")
    print(f"  to retry with Street View: {len(candidates)}")
    if not candidates:
        return

    n_recovered = n_failed = n_skipped = 0
    sv_cost = classify_cost = 0.0
    now_iso = datetime.utcnow().isoformat() + 'Z'

    for slug in candidates:
        if slug not in coords:
            print(f"  {slug}: no coords, skip")
            n_skipped += 1
            continue
        lat, lng = coords[slug]
        # Free metadata check first - don't pay $0.007 if there's no SV here
        meta = streetview_meta(lat, lng)
        if not meta or meta.get('status') != 'OK':
            attempts.setdefault(slug, {'approaches': []})['approaches'].append('streetview_unavailable')
            attempts[slug]['last_attempted'] = now_iso
            print(f"  {slug}: no SV imagery at {lat},{lng}")
            n_skipped += 1
            continue
        # Reuse cached SV bytes from a prior failed-classify run if present,
        # otherwise pay the $0.007 fetch. Avoids double-billing when the
        # script crashes mid-classification.
        candidate_path = PHOTO_DIR / f'{slug}.streetview-candidate.jpg'
        if candidate_path.exists():
            img_bytes = candidate_path.read_bytes()
        else:
            img_bytes, _ = streetview_image(lat, lng)
            sv_cost += 0.007
            if not img_bytes:
                print(f"  {slug}: SV fetch failed")
                n_skipped += 1
                continue
            candidate_path.write_bytes(img_bytes)
        is_food, desc = classify_image(img_bytes)
        classify_cost += 0.0006
        attempts.setdefault(slug, {'approaches': []})['approaches'].append('streetview')
        attempts[slug]['last_attempted'] = now_iso
        if is_food is None:
            print(f"  {slug}: classify failed")
            n_failed += 1
            continue
        if is_food:
            # Promote candidate to real photo + regen thumb + flip verdict
            photo_path = PHOTO_DIR / f'{slug}.jpg'
            thumb_path = THUMB_DIR / f'{slug}.webp'
            photo_path.write_bytes(img_bytes)
            try: candidate_path.unlink()
            except FileNotFoundError: pass
            regen_thumb(photo_path, thumb_path)
            cls[slug] = {
                'status': 'ok',
                'is_restaurant_or_food': True,
                'description': desc[:160],
                'via': 'retry-streetview',
                'classified_at': now_iso,
            }
            n_recovered += 1
            print(f"  ✓ {slug}: SV passed → {desc[:80]}")
        else:
            # Clean up the candidate - SV failed too, leave denied
            try: candidate_path.unlink()
            except FileNotFoundError: pass
            n_failed += 1
            print(f"  ✗ {slug}: SV rejected → {desc[:80]}")

    CLS_PATH.write_text(json.dumps(cls, separators=(',', ':')))
    ATTEMPT_PATH.write_text(json.dumps(attempts, separators=(',', ':')))
    total_cost = sv_cost + classify_cost
    print(f"\nrecovered={n_recovered} still-failed={n_failed} skipped={n_skipped}  "
          f"spend: ${sv_cost:.3f} SV + ${classify_cost:.4f} classify = ${total_cost:.3f}")


if __name__ == '__main__':
    main()
