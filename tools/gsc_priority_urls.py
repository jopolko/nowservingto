#!/usr/bin/env python3
"""
Generate a prioritized URL list for search-engine manual indexing
requests (GSC, BWT).

Strategy: this is a freshness-first site - the value proposition is
"restaurants licensed in the last 365 days". The newest /r/<slug>
entries are the most time-sensitive content (people searching for
"newest X opened in Toronto" want them indexed in days, not weeks).
So push freshness up the priority order, hubs second, long tail last.

Output priority (most-urgent first):
  1. Homepage - top organic landing, top of internal link graph
  2. Newest 30 /r/<slug> entries - freshest content, biggest search-
     intent overlap with the site's freshness USP
  3. Top cuisine hubs by entry count - each carries link signal into
     ~5-70 /r/ pages, so a refresh cascades downstream
  4. District hubs (all 6) - same cascade logic, location-scoped
  5. Wire pages - editorial briefs, long-tail ranking targets
  6. Press kit
  7. Remaining cuisine pages (low-volume cuisines)
  8. Remaining /r/<slug> entries by age (oldest last)

Run:
  python3 tools/gsc_priority_urls.py              # prints all to stdout
  python3 tools/gsc_priority_urls.py | head -10   # for GSC's 10/day quota
  python3 tools/gsc_priority_urls.py | head -100  # for BWT's daily quota
  python3 tools/gsc_priority_urls.py > priority_urls.txt
"""
import json
import sys
from pathlib import Path

ROOT         = Path(__file__).resolve().parent.parent
DATA_PATH    = ROOT / 'data' / 'corridors.json'
WIRE_DIR     = ROOT / 'wire'
CUISINE_DIR  = ROOT / 'cuisine'
DISTRICT_DIR = ROOT / 'district'
LISTING_DIR  = ROOT / 'r'
SITE = 'https://nowservingto.com'

# How many of the freshest /r/<slug> entries go to the top tier vs the
# tail. 30 covers roughly the "opened in the last month" cohort - the
# window where time-relative search queries are most active.
FRESH_TIER_SIZE = 30


if not DATA_PATH.exists():
    sys.exit(f"{DATA_PATH} missing")
d = json.loads(DATA_PATH.read_text())

recent = sorted(d.get('newOpenings', {}).get('recent', []),
                key=lambda r: r.get('daysOpen', 99999))

# Cuisine hubs sorted by entry count (more entries = more downstream
# cascade value when this hub is re-crawled).
cuisine_counts = {c['key']: c.get('count365d', 0)
                  for c in d.get('newOpenings', {}).get('cuisines', [])}
cuisines_by_volume = sorted(
    (p.stem for p in CUISINE_DIR.glob('*.html')) if CUISINE_DIR.exists() else [],
    key=lambda k: -cuisine_counts.get(k, 0),
)

urls = []
def add(u):
    if u not in urls:
        urls.append(u)

# Tier 1: homepage (top of internal link graph)
add(f'{SITE}/')

# Tier 2: newest /r/<slug> entries (freshness USP - search-intent goldmine)
for e in recent[:FRESH_TIER_SIZE]:
    if e.get('slug'):
        add(f'{SITE}/r/{e["slug"]}')

# Tier 3: top cuisine hubs by entry count - high cascade value
for key in cuisines_by_volume:
    add(f'{SITE}/cuisine/{key}')

# Tier 4: district hubs (all 6)
if DISTRICT_DIR.exists():
    for p in sorted(DISTRICT_DIR.glob('*.html')):
        add(f'{SITE}/district/{p.stem}')

# Tier 5: wire pages (editorial briefs)
if WIRE_DIR.exists():
    for p in sorted(WIRE_DIR.glob('*.html')):
        add(f'{SITE}/wire/{p.stem}')

# Tier 6: press kit
add(f'{SITE}/press')

# Tier 7: remaining /r/<slug> entries by age (oldest last)
for e in recent[FRESH_TIER_SIZE:]:
    if e.get('slug'):
        add(f'{SITE}/r/{e["slug"]}')

for u in urls:
    print(u)

sys.stderr.write(
    f'\n{len(urls)} URLs printed in freshness-first priority order.\n'
    f'  GSC:  pipe to `head -10` for daily quota\n'
    f'  BWT:  pipe to `head -100` for daily quota\n'
    f'  Bulk: paste all (IndexNow already submits all daily)\n'
)
