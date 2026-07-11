#!/usr/bin/env python3
"""Record AI citation counts from Bing Webmaster Tools' AI Performance report.

Bing WMT (public preview since Feb 2026) shows how often the site is cited in
Copilot and other AI-generated answers, but exposes no API for it yet. Read
the number off the dashboard (bing.com/webmasters, AI Performance) and record
it here; crawler_stats.py folds the cached value into the GEO Observatory
data.json nightly and the joshuaopolko.com homepage card displays it.

Usage:
  set_bing_citations.py 234            # total citations (dashboard window)
  set_bing_citations.py 234 --week 41  # optionally, citations in the last 7 days
"""
import argparse
import datetime
import json
import os

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'cache', 'bing_ai_citations.json')


def main():
    ap = argparse.ArgumentParser(
        description='Record Bing WMT AI citation counts for the GEO Observatory.')
    ap.add_argument('citations', type=int,
                    help='total citations shown in the AI Performance report')
    ap.add_argument('--week', type=int, default=None,
                    help='citations in the last 7 days (optional)')
    a = ap.parse_args()
    data = {'citations': a.citations,
            'citations7d': a.week,
            'updated': datetime.date.today().isoformat()}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w') as f:
        json.dump(data, f, indent=1)
    print(f'wrote {CACHE}: {data}')


if __name__ == '__main__':
    main()
