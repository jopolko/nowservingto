#!/usr/bin/env python3
"""
Pull GA4 session/page data for nowservingto.com.

Usage:
  python3 tools/ga4_pull.py              # 28-day report
  python3 tools/ga4_pull.py --days 7    # 7-day window
  python3 tools/ga4_pull.py --json       # machine-readable

Find your GA4 property ID:
  GA4 → Admin → Property Settings → Property ID (numeric, not G-XXXXXX)
  Set GA4_PROPERTY_ID below.
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest, OrderBy,
)

TOKEN_FILE    = Path('/var/secrets/nowservingto-google-token.json')
GA4_PROPERTY_ID = '537718881'   # GA4 Admin → Property Settings → Property ID


def load_creds():
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
        # Persist refreshed token
        TOKEN_FILE.write_text(json.dumps({
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': list(creds.scopes),
        }, indent=2))
    return creds


def date_range(days):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return str(start), str(end)


def run_report(client, prop, start, end, dimensions, metrics, limit=50):
    req = RunReportRequest(
        property=f'properties/{prop}',
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name=metrics[0]),
                           desc=True)],
        limit=limit,
    )
    return client.run_report(req)


def fmt_pct(v):
    return f'{float(v)*100:.1f}%'


def section(title):
    print(f'\n{"─"*60}')
    print(f'  {title}')
    print(f'{"─"*60}')


def run(days, output_fmt):
    creds  = load_creds()
    client = BetaAnalyticsDataClient(credentials=creds)
    start, end = date_range(days)

    print(f'nowservingto.com · GA4 report · {start} → {end} ({days}d)')

    # Top pages by sessions
    pages_resp = run_report(client, GA4_PROPERTY_ID, start, end,
                            dimensions=['pagePath'],
                            metrics=['sessions', 'activeUsers',
                                     'screenPageViews', 'bounceRate'])

    # Top channels
    channel_resp = run_report(client, GA4_PROPERTY_ID, start, end,
                              dimensions=['sessionDefaultChannelGroup'],
                              metrics=['sessions', 'activeUsers'])

    # Top queries (from organic search dimension — only available if site search is on,
    # but sessionSourceMedium gives organic breakdown)
    source_resp = run_report(client, GA4_PROPERTY_ID, start, end,
                             dimensions=['sessionSourceMedium'],
                             metrics=['sessions', 'activeUsers'])

    if output_fmt == 'json':
        out = {
            'period': {'start': start, 'end': end, 'days': days},
            'pages': [
                {
                    'path': row.dimension_values[0].value,
                    'sessions': row.metric_values[0].value,
                    'users': row.metric_values[1].value,
                    'pageviews': row.metric_values[2].value,
                    'bounce_rate': row.metric_values[3].value,
                }
                for row in pages_resp.rows
            ],
            'channels': [
                {
                    'channel': row.dimension_values[0].value,
                    'sessions': row.metric_values[0].value,
                    'users': row.metric_values[1].value,
                }
                for row in channel_resp.rows
            ],
        }
        print(json.dumps(out, indent=2))
        return

    section(f'TOP PAGES by sessions  (top 25, {days}d)')
    print(f'  {"Page":<52} {"Sess":>6} {"Users":>6} {"PVs":>6} {"Bnc%":>6}')
    print(f'  {"-"*52} {"----":>6} {"-----":>6} {"----":>6} {"----":>6}')
    for row in pages_resp.rows[:25]:
        path = row.dimension_values[0].value[:51]
        sess = row.metric_values[0].value
        users = row.metric_values[1].value
        pvs  = row.metric_values[2].value
        bnc  = fmt_pct(row.metric_values[3].value)
        print(f'  {path:<52} {sess:>6} {users:>6} {pvs:>6} {bnc:>6}')

    section('TRAFFIC CHANNELS')
    print(f'  {"Channel":<35} {"Sessions":>9} {"Users":>7}')
    print(f'  {"-"*35} {"--------":>9} {"-----":>7}')
    for row in channel_resp.rows:
        ch   = row.dimension_values[0].value[:34]
        sess = row.metric_values[0].value
        usr  = row.metric_values[1].value
        print(f'  {ch:<35} {sess:>9} {usr:>7}')

    section('SOURCE / MEDIUM breakdown')
    print(f'  {"Source / Medium":<40} {"Sessions":>9} {"Users":>7}')
    print(f'  {"-"*40} {"--------":>9} {"-----":>7}')
    for row in source_resp.rows[:20]:
        src  = row.dimension_values[0].value[:39]
        sess = row.metric_values[0].value
        usr  = row.metric_values[1].value
        print(f'  {src:<40} {sess:>9} {usr:>7}')

    print()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=28)
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    fmt = 'json' if args.json else 'human'
    run(args.days, fmt)
