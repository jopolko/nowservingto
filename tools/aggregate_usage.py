#!/usr/bin/env python3
"""
Aggregate tools/cache/usage_log.jsonl → data/usage.json that the /usage
page renders. Run at the end of every cron pass so the page always
reflects the latest spend totals.

Output shape:
  {
    "generatedAt": "2026-05-17T...",
    "first": "2026-05-15",   first ledger entry date
    "totals": {
      "all":    {"cost": 12.34, "calls": 1234},
      "today":  {"cost":  0.12, "calls":   42}
    },
    "byProvider": [
      {"provider": "google_places", "cost": 8.42, "calls": 487,
       "skus": [{"sku": "places.details", "cost": 7.50, "calls": 300}, ...]},
      ...
    ],
    "byDay": [
      {"day": "2026-05-15", "cost": 5.21, "calls": 412},
      ...
    ]
  }
"""
import json, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / 'tools' / 'cache' / 'usage_log.jsonl'
OUT    = ROOT / 'data' / 'usage.json'

# sku → provider grouping for the byProvider section
PROVIDER = {
    'places.find_place':   'google_places',
    'places.details':      'google_places',
    'places.photo':        'google_places',
    'streetview.image':    'google_streetview',
    'streetview.metadata': 'google_streetview',
    'anthropic.haiku.batch.in':  'anthropic',
    'anthropic.haiku.batch.out': 'anthropic',
    'anthropic.haiku.sync.in':   'anthropic',
    'anthropic.haiku.sync.out':  'anthropic',
    'anthropic.web_search.batch': 'anthropic',
    'anthropic.web_search.sync':  'anthropic',
    'jina.reader':         'jina',
    'x.tweet':             'x',
    'x.media_upload':      'x',
}

def main():
    if not LEDGER.exists():
        print(f"no ledger at {LEDGER} - writing empty usage.json")
        OUT.write_text(json.dumps({
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'totals': {'all':{'cost':0,'calls':0}, 'today':{'cost':0,'calls':0}},
            'byProvider': [], 'byDay': [],
        }, indent=2))
        return

    rows = []
    for line in LEDGER.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line: continue
        try: rows.append(json.loads(line))
        except: pass

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    by_provider_sku = defaultdict(lambda: {'cost': 0.0, 'calls': 0})
    by_day = defaultdict(lambda: {'cost': 0.0, 'calls': 0})
    # New: per-day per-provider breakdown so the daily-spend chart can
    # render a separate line per provider instead of one aggregate line.
    by_day_provider = defaultdict(lambda: defaultdict(float))
    total_cost = total_calls = 0.0
    today_cost = today_calls = 0
    for r in rows:
        sku = r.get('sku', '?')
        cost = float(r.get('cost') or 0.0)
        day = (r.get('t') or '')[:10]
        provider = PROVIDER.get(sku, 'other')
        by_provider_sku[(provider, sku)]['cost'] += cost
        by_provider_sku[(provider, sku)]['calls'] += 1
        by_day[day]['cost'] += cost
        by_day[day]['calls'] += 1
        by_day_provider[day][provider] += cost
        total_cost += cost
        total_calls += 1
        if day == today:
            today_cost += cost
            today_calls += 1

    # Roll up by provider
    provider_groups = defaultdict(lambda: {'cost': 0.0, 'calls': 0, 'skus': []})
    for (provider, sku), agg in by_provider_sku.items():
        provider_groups[provider]['cost'] += agg['cost']
        provider_groups[provider]['calls'] += agg['calls']
        provider_groups[provider]['skus'].append({
            'sku': sku, 'cost': round(agg['cost'], 4), 'calls': agg['calls'],
        })
    byProvider = []
    for p, g in sorted(provider_groups.items(), key=lambda x: -x[1]['cost']):
        g['skus'].sort(key=lambda s: -s['cost'])
        byProvider.append({
            'provider': p, 'cost': round(g['cost'], 4),
            'calls': g['calls'], 'skus': g['skus'],
        })

    byDay = [{'day': d, 'cost': round(g['cost'], 4), 'calls': g['calls']}
             for d, g in sorted(by_day.items())]

    # Per-day per-provider: each entry is {day, providers: {provider: cost}}
    # Providers absent on a given day = $0 (frontend should default to 0).
    byDayProvider = [{
        'day': d,
        'providers': {p: round(v, 4) for p, v in sorted(provs.items())},
    } for d, provs in sorted(by_day_provider.items())]

    first = (sorted(by_day.keys())[0] if by_day else None)

    payload = {
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'first': first,
        'totals': {
            'all':   {'cost': round(total_cost, 4), 'calls': int(total_calls)},
            'today': {'cost': round(today_cost, 4), 'calls': today_calls},
        },
        'byProvider': byProvider,
        'byDay': byDay,
        'byDayProvider': byDayProvider,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT} - total ${total_cost:.2f} across {int(total_calls)} calls "
          f"({len(byProvider)} providers, {len(byDay)} days)")

if __name__ == '__main__':
    main()
