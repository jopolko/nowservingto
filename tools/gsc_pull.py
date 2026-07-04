#!/usr/bin/env python3
"""
Pull Search Console performance data for nowservingto.com.

Outputs three sections:
  1. Top queries (clicks, impressions, CTR, avg position)
  2. Top pages by clicks
  3. CTR opportunities (≥20 impressions, CTR below 3% → meta/title work)
  4. Position 4-15 queries (ranking but not winning → easy gains)

Usage:
  python3 tools/gsc_pull.py              # 28-day report to stdout
  python3 tools/gsc_pull.py --days 7    # 7-day window
  python3 tools/gsc_pull.py --csv       # CSV to stdout (pipe to file)
  python3 tools/gsc_pull.py --json      # JSON (machine-readable)

Requires /var/secrets/nowservingto-google-token.json (OAuth token).
Run ga4_auth.py locally first to generate it, then deploy to VPS.
"""
import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

TOKEN_FILE  = Path('/var/secrets/nowservingto-google-token.json')
SITE        = 'sc-domain:nowservingto.com'
SITE_PREFIX = 'https://nowservingto.com'

ROW_LIMIT = 500
CTR_OPPORTUNITY_MIN_IMPRESSIONS = 20
CTR_OPPORTUNITY_MAX_CTR = 0.03
POSITION_GAP_MIN = 4
POSITION_GAP_MAX = 15


def build_service():
    import json
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    if not TOKEN_FILE.exists():
        sys.exit(f'Missing {TOKEN_FILE} — run ga4_auth.py first, then deploy the token.')
    data = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(
        token=data['token'],
        refresh_token=data['refresh_token'],
        token_uri=data['token_uri'],
        client_id=data['client_id'],
        client_secret=data['client_secret'],
        scopes=data['scopes'],
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
        TOKEN_FILE.write_text(json.dumps({
            'token': creds.token, 'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri, 'client_id': creds.client_id,
            'client_secret': creds.client_secret, 'scopes': list(creds.scopes),
        }, indent=2))
    return build('searchconsole', 'v1', credentials=creds, cache_discovery=False)


def date_range(days):
    end = date.today() - timedelta(days=3)  # GSC has ~3 day lag
    start = end - timedelta(days=days - 1)
    return str(start), str(end)


def query(svc, start, end, dimensions, row_limit=ROW_LIMIT):
    body = {
        'startDate': start,
        'endDate': end,
        'dimensions': dimensions,
        'rowLimit': row_limit,
        'startRow': 0,
    }
    resp = svc.searchanalytics().query(siteUrl=SITE, body=body).execute()
    return resp.get('rows', [])


def fmt_pct(v):
    return f'{v*100:.1f}%'


def fmt_pos(v):
    return f'{v:.1f}'


def short_page(url):
    return url.replace(SITE_PREFIX, '') or '/'


def section(title):
    print(f'\n{"─"*60}')
    print(f'  {title}')
    print(f'{"─"*60}')


def run(days, output_fmt):
    if not TOKEN_FILE.exists():
        sys.exit(f'Missing {TOKEN_FILE} - run ga4_auth.py locally, then deploy the token to the VPS.')

    svc = build_service()
    start, end = date_range(days)

    print(f'nowservingto.com · GSC report · {start} → {end} ({days}d)')

    # --- queries ---
    query_rows = query(svc, start, end, ['query'])
    query_rows.sort(key=lambda r: -r['clicks'])

    # --- pages ---
    page_rows = query(svc, start, end, ['page'])
    page_rows.sort(key=lambda r: -r['clicks'])

    if output_fmt == 'json':
        out = {
            'period': {'start': start, 'end': end, 'days': days},
            'queries': [
                {
                    'query': r['keys'][0],
                    'clicks': r['clicks'],
                    'impressions': r['impressions'],
                    'ctr': r['ctr'],
                    'position': r['position'],
                }
                for r in query_rows
            ],
            'pages': [
                {
                    'page': r['keys'][0],
                    'clicks': r['clicks'],
                    'impressions': r['impressions'],
                    'ctr': r['ctr'],
                    'position': r['position'],
                }
                for r in page_rows
            ],
        }
        print(json.dumps(out, indent=2))
        return

    if output_fmt == 'csv':
        w = csv.writer(sys.stdout)
        w.writerow(['type', 'key', 'clicks', 'impressions', 'ctr', 'position'])
        for r in query_rows:
            w.writerow(['query', r['keys'][0], r['clicks'], r['impressions'],
                        f"{r['ctr']:.4f}", f"{r['position']:.1f}"])
        for r in page_rows:
            w.writerow(['page', short_page(r['keys'][0]), r['clicks'], r['impressions'],
                        f"{r['ctr']:.4f}", f"{r['position']:.1f}"])
        return

    # --- human-readable ---

    section(f'TOP QUERIES by clicks  (top 30 of {len(query_rows)})')
    print(f'  {"Query":<45} {"Clk":>5} {"Imp":>7} {"CTR":>6} {"Pos":>6}')
    print(f'  {"-"*45} {"---":>5} {"---":>7} {"---":>6} {"---":>6}')
    for r in query_rows[:30]:
        q = r['keys'][0][:44]
        print(f'  {q:<45} {r["clicks"]:>5} {r["impressions"]:>7}'
              f' {fmt_pct(r["ctr"]):>6} {fmt_pos(r["position"]):>6}')

    total_clicks = sum(r['clicks'] for r in query_rows)
    total_imp = sum(r['impressions'] for r in query_rows)
    print(f'\n  Totals: {total_clicks:,} clicks · {total_imp:,} impressions'
          f' · {fmt_pct(total_clicks/total_imp if total_imp else 0)} CTR')

    section(f'TOP PAGES by clicks  (top 20 of {len(page_rows)})')
    print(f'  {"Page":<52} {"Clk":>5} {"Imp":>7} {"CTR":>6} {"Pos":>6}')
    print(f'  {"-"*52} {"---":>5} {"---":>7} {"---":>6} {"---":>6}')
    for r in page_rows[:20]:
        pg = short_page(r['keys'][0])[:51]
        print(f'  {pg:<52} {r["clicks"]:>5} {r["impressions"]:>7}'
              f' {fmt_pct(r["ctr"]):>6} {fmt_pos(r["position"]):>6}')

    section(f'CTR OPPORTUNITIES  (≥{CTR_OPPORTUNITY_MIN_IMPRESSIONS} imp, CTR < {CTR_OPPORTUNITY_MAX_CTR*100:.0f}%)')
    opps = [r for r in query_rows
            if r['impressions'] >= CTR_OPPORTUNITY_MIN_IMPRESSIONS
            and r['ctr'] < CTR_OPPORTUNITY_MAX_CTR]
    opps.sort(key=lambda r: -r['impressions'])
    if opps:
        print(f'  {"Query":<45} {"Clk":>5} {"Imp":>7} {"CTR":>6} {"Pos":>6}')
        print(f'  {"-"*45} {"---":>5} {"---":>7} {"---":>6} {"---":>6}')
        for r in opps[:20]:
            q = r['keys'][0][:44]
            print(f'  {q:<45} {r["clicks"]:>5} {r["impressions"]:>7}'
                  f' {fmt_pct(r["ctr"]):>6} {fmt_pos(r["position"]):>6}')
    else:
        print('  None — all high-impression queries are above the CTR floor.')

    section(f'POSITION GAP  (pos {POSITION_GAP_MIN}–{POSITION_GAP_MAX}, ranking but not winning)')
    gaps = [r for r in query_rows
            if POSITION_GAP_MIN <= r['position'] <= POSITION_GAP_MAX
            and r['impressions'] >= 10]
    gaps.sort(key=lambda r: r['position'])
    if gaps:
        print(f'  {"Query":<45} {"Clk":>5} {"Imp":>7} {"CTR":>6} {"Pos":>6}')
        print(f'  {"-"*45} {"---":>5} {"---":>7} {"---":>6} {"---":>6}')
        for r in gaps[:20]:
            q = r['keys'][0][:44]
            print(f'  {q:<45} {r["clicks"]:>5} {r["impressions"]:>7}'
                  f' {fmt_pct(r["ctr"]):>6} {fmt_pos(r["position"]):>6}')
    else:
        print('  No queries in position 4–15 with ≥10 impressions.')

    print()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=28)
    p.add_argument('--csv', action='store_true')
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    fmt = 'csv' if args.csv else ('json' if args.json else 'human')
    run(args.days, fmt)
