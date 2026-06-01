#!/usr/bin/env python3
"""Read the freshly re-fetched places_cache (with review timestamps) and
report which currently-shown entries WOULD be suppressed by the
'opening-date gate' before flipping it on in inject_openings.py.

Gate rule (Phase A):
  If ANY of the (up to 5) Places-returned reviews has a timestamp more
  than 180 days BEFORE the City licence-issued date, the restaurant was
  demonstrably operating before our 'newly registered' claim - suppress.

We're deliberately conservative (180-day threshold, not 365) because the
5 Places-returned reviews are a sample, not exhaustive - if even ONE of
the 5 is 6+ months old, we have hard evidence the place predates the
licence event by at least that much.

This script is read-only - just prints what WOULD happen.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACES = ROOT / 'tools' / 'cache' / 'places_cache.json'
CORRIDORS = ROOT / 'data' / 'corridors.json'

GAP_THRESHOLD_DAYS = 180  # how much earlier a review can be vs licence before we suppress

pc = json.loads(PLACES.read_text())
data = json.loads(CORRIDORS.read_text())
recent = (data.get('newOpenings') or {}).get('recent') or []

suppressed = []
included = []
ungatable = []  # no review timestamps available - can't gate
for e in recent:
    k = e.get('_cacheKey')
    if not k or k not in pc: continue
    p = pc[k]
    rd = p.get('reviewsDetail') or []
    if not rd:
        ungatable.append((e, 'no reviewsDetail in cache'))
        continue
    times = [r.get('time') for r in rd if r.get('time')]
    if not times:
        ungatable.append((e, 'reviewsDetail has no timestamps'))
        continue
    earliest_review_ts = min(times)
    earliest_review_dt = datetime.fromtimestamp(earliest_review_ts, tz=timezone.utc)
    try:
        licence_dt = datetime.strptime(e['issuedDate'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except Exception:
        continue
    gap_days = (licence_dt - earliest_review_dt).days
    info = {
        'name': e.get('operatingName'),
        'slug': e.get('slug'),
        'licence': e['issuedDate'],
        'earliest_review': earliest_review_dt.strftime('%Y-%m-%d'),
        'gap_days': gap_days,
        'reviewCount': p.get('reviewCount'),
        'relative_times': [r.get('relative_time') for r in rd],
    }
    if gap_days > GAP_THRESHOLD_DAYS:
        suppressed.append(info)
    else:
        included.append(info)

suppressed.sort(key=lambda x: -x['gap_days'])
print(f"Total entries with review-timestamp data: {len(suppressed) + len(included)}")
print(f"Ungatable (no usable timestamps): {len(ungatable)}")
print(f"WOULD SUPPRESS (review > {GAP_THRESHOLD_DAYS}d before licence): {len(suppressed)}")
print(f"Would keep (no pre-licence reviews in returned sample): {len(included)}")
print()
print('=== SUPPRESS LIST (sorted by gap days, biggest first) ===')
for s in suppressed[:50]:
    rt_sample = (s['relative_times'][:2] if s['relative_times'] else [])
    print(f"  [{s['gap_days']:5}d gap] {s['name'][:42]:42}  "
          f"licence={s['licence']}  earliest_review={s['earliest_review']}  "
          f"reviews={s['reviewCount']}  oldest-shown=\"{rt_sample}\"")
if len(suppressed) > 50:
    print(f"  ... and {len(suppressed) - 50} more")

print()
print('=== UNGATABLE ENTRIES (no timestamp data - phase B candidate) ===')
print(f"  {len(ungatable)} entries lack timestamp data - either no reviews returned,")
print(f"  or schema upgrade hasn't propagated to them yet.")
if len(ungatable) <= 20:
    for e, why in ungatable[:20]:
        print(f"    {e.get('operatingName','')[:50]:50}  ({why})")
