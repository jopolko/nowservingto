#!/usr/bin/env python3
"""
Download Toronto Public Health's DineSafe inspection CSV, build an
(address+name)-keyed earliest-inspection-date lookup, cache it to
tools/cache/dinesafe_lookup.json for inject_openings to use as a
pre-existing-restaurant signal.

DineSafe is authoritative government inspection data - if Toronto
Public Health inspected a restaurant on date X, the restaurant was
operating on date X, period. Comparing earliest-DineSafe-inspection
to our City-business-licence-issued date catches restaurants that
had been operating before their current licence event (e.g. ownership
transfer, suite renumbering, licence-type addition).

The CSV is ~22MB, ~105K rows, parses in 2-3 seconds. Updated daily by
the City. Wire into cron between the business-licence fetch and inject.

Output cache shape:
  {
    "<street_num> <street_first_word> <postalcode_no_space>": [
      {"name": "MAKILALA", "earliest": "2025-06-24", "latest": "2026-05-29",
       "count": 6}
    ],
    ...
  }
The list lets us name-overlap-match for the inject's pre-existing gate
without re-scanning the full CSV every cron.
"""
import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_URL = ('https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/'
           'b6b4f3fb-2e2c-47e7-931d-b87d22806948/resource/'
           'af0f5b8a-4b73-4a50-8781-65e949792b40/download/dinesafe.csv')
CACHE_PATH = ROOT / 'tools' / 'cache' / 'dinesafe_lookup.json'
TMP_CSV = Path('/tmp/dinesafe.csv')


def norm_addr(s):
    """Normalize an address to a canonical key: 'STREETNUM STREETFIRSTWORD POSTAL'.
    DineSafe addresses look like '1871 O'Connor Dr None M4A 1X1'; ours look
    like '1871 O'Connor Dr, Toronto, ON M4A 1X1'. Both share street-num +
    street-word + postal as the unique location signal."""
    s = (s or '').upper()
    s = re.sub(r'\s+(NONE|UNIT.*|SUITE.*)\s+', ' ', s)
    s = re.sub(r"[^A-Z0-9 ]+", ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    m = re.match(r'^(\d+) (\w+).*?([A-Z]\d[A-Z] ?\d[A-Z]\d)', s)
    if not m: return None
    return f"{m.group(1)} {m.group(2)} {m.group(3).replace(' ','')}"


def main():
    print(f"fetching DineSafe CSV from CKAN...")
    urllib.request.urlretrieve(CSV_URL, TMP_CSV)
    size = TMP_CSV.stat().st_size
    print(f"  downloaded {size/1024/1024:.1f} MB to {TMP_CSV}")

    # Group inspections by location key, then by name within each location.
    # Same address can host multiple establishments over time (former tenants),
    # so we keep per-name earliest-inspection summaries.
    by_addr_name = defaultdict(lambda: defaultdict(list))  # addr_key -> name_upper -> [dates]
    n_rows = 0
    n_skipped = 0
    with open(TMP_CSV, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            n_rows += 1
            key = norm_addr(r.get('address'))
            if not key:
                n_skipped += 1
                continue
            name = (r.get('estName') or '').upper().strip()
            date = (r.get('inspectionDate') or '').strip()
            if not (name and date): continue
            by_addr_name[key][name].append(date)

    # Build compact per-establishment summaries
    out = {}
    for addr_key, by_name in by_addr_name.items():
        out[addr_key] = []
        for name, dates in by_name.items():
            dates.sort()
            out[addr_key].append({
                'name': name,
                'earliest': dates[0],
                'latest': dates[-1],
                'count': len(dates),
            })

    n_locations = len(out)
    n_establishments = sum(len(v) for v in out.values())
    print(f"  parsed {n_rows:,} inspection rows ({n_skipped:,} skipped - bad address format)")
    print(f"  indexed {n_locations:,} unique location keys, {n_establishments:,} unique establishments")

    payload = {
        '_doc': 'address+name-keyed earliest-inspection-date lookup. Key = "<streetnum> <streetword> <postalcode>". Inner list = per-name inspection summary at that location. Used by inject_openings.py for pre-existing-restaurant detection.',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_csv_url': CSV_URL,
        'n_inspection_rows': n_rows,
        'n_locations': n_locations,
        'lookup': out,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, separators=(',', ':')))
    sz = CACHE_PATH.stat().st_size
    print(f"  wrote {CACHE_PATH} ({sz/1024/1024:.1f} MB)")


if __name__ == '__main__':
    main()
