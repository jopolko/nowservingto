#!/usr/bin/env python3
"""
Weekly all-Toronto digest sender. Cron runs this once a week (Sunday
morning); it picks the top 5 most-recently-registered restaurants from
the last 7 days of data/corridors.json and emails them to every
subscriber with kind='digest_all'.

State:
  tools/cache/digest_sent.json   {"last_sent": "YYYY-MM-DD"}

If last_sent is within 6 days of today, the script is a no-op - guards
against accidental double-runs (manual invocation, cron retry). To
force-resend, delete the file or pass --force.

Mail delivery: same path as send_alerts.py - smtplib to local Postfix
on 127.0.0.1:25, OpenDKIM milter signs on the way out.
"""
import json, re, smtplib, sys, os
from datetime import datetime, date, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, formatdate, formataddr
from html import escape as _esc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / 'data' / 'corridors.json'
SUBS_PATH = ROOT / 'tools' / 'cache' / 'alert_subs.json'
SENT_PATH = ROOT / 'tools' / 'cache' / 'digest_sent.json'
SECRETS = Path('/var/secrets/nowservingto.env')

SITE_BASE = 'https://nowservingto.com'
TOP_N = 5
WINDOW_DAYS = 7
MIN_DAYS_BETWEEN_SENDS = 6   # Sunday-to-Sunday with 1d slack

def _load_env():
    out = {}
    try:
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                out[k.strip()] = v.strip()
    except Exception:
        pass
    return out

ENV = _load_env()
SMTP_HOST = ENV.get('SMTP_HOST', '127.0.0.1')
SMTP_PORT = int(ENV.get('SMTP_PORT', '25'))
MAIL_FROM_ADDR = ENV.get('MAIL_FROM_ADDR', 'alerts@nowservingto.com')
MAIL_FROM_NAME = ENV.get('MAIL_FROM_NAME', 'NowServingTO')
MAIL_DOMAIN = 'nowservingto.com'


def _load_json(path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text())
    except Exception: return default


def _save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)


def _send(to, subject, html, text, unsubscribe_url):
    msg = EmailMessage()
    msg['From'] = formataddr((MAIL_FROM_NAME, MAIL_FROM_ADDR))
    msg['To'] = to
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=False)
    msg['Message-ID'] = make_msgid(domain=MAIL_DOMAIN)
    msg['Auto-Submitted'] = 'auto-generated'
    msg['Precedence'] = 'bulk'
    msg['List-Unsubscribe'] = f'<{unsubscribe_url}>'
    msg['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.send_message(msg, from_addr=MAIL_FROM_ADDR, to_addrs=[to])


def _pick_entries(data, window_days, top_n):
    """Top N most-recently-registered entries within the window. The
    feed is already sorted recent-first, so we just filter by age."""
    entries = (data.get('newOpenings') or {}).get('recent') or []
    picks = [e for e in entries if (e.get('daysOpen') or 0) <= window_days]
    return picks[:top_n]


def _row_html(e):
    """Single-row HTML matching the on-site card style. Inlined CSS for
    email-client compatibility (no <style> blocks survive Gmail's stripper)."""
    name = e.get('operatingName') or 'New restaurant'
    addr = e.get('address') or ''
    district = e.get('district') or ''
    cuisines = e.get('cuisines') or ([e['cuisine']] if e.get('cuisine') else [])
    days = e.get('daysOpen', 0)
    when = 'today' if days <= 1 else f'{days}d ago'
    link = e.get('website') or e.get('mapsUrl') or f'{SITE_BASE}/r/{e.get("slug","")}'
    cuisines_str = ' · '.join(c.replace('_', ' ').title() for c in cuisines if c)
    district_str = f' &middot; {_esc(district)}' if district else ''
    return (
        '<tr><td style="padding:14px 0;border-bottom:1px solid #ebecef">'
        f'<div style="color:#74787c;font:600 11px/1 -apple-system,sans-serif;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">{_esc(when)}{district_str}</div>'
        f'<a href="{_esc(link)}" style="color:#131516;font:700 16px/1.3 Georgia,serif;text-decoration:none">{_esc(name)}</a>'
        f'<div style="color:#46494c;font:14px/1.45 -apple-system,sans-serif;margin-top:3px">{_esc(addr)}</div>'
        f'<div style="color:#74787c;font:600 12px/1 -apple-system,sans-serif;text-transform:uppercase;letter-spacing:0.05em;margin-top:6px">{_esc(cuisines_str)}</div>'
        '</td></tr>'
    )


def _build_email(entries, unsubscribe_url):
    """HTML + plaintext digest body. Top-N entries rendered as compact
    rows + a single CTA back to the homepage feed."""
    rows = ''.join(_row_html(e) for e in entries)
    today = date.today().strftime('%b %d')
    subject = f"NowServingTO weekly: {len(entries)} new restaurants in Toronto"
    html = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{_esc(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#131516;-webkit-font-smoothing:antialiased">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#fafafa">
{len(entries)} restaurants newly registered with the City of Toronto in the past 7 days.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fafafa" style="background:#fafafa;padding:24px 0">
  <tr><td align="center" style="padding:0 12px">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #ebecef;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,0.04);overflow:hidden">

      <tr><td style="padding:26px 28px 18px;border-bottom:3px solid #131516">
        <a href="{SITE_BASE}" style="display:inline-block;font:800 28px/1 Georgia,'Iowan Old Style',serif;letter-spacing:-0.02em;color:#131516;text-decoration:none">NowServingTO</a>
        <div style="color:#74787c;font:italic 400 14px/1.4 Georgia,serif;margin-top:6px">Toronto's newest registered restaurants - updated daily.</div>
      </td></tr>

      <tr><td style="padding:24px 28px 0">
        <h1 style="margin:0 0 8px;font:700 22px/1.25 Georgia,'Iowan Old Style',serif;letter-spacing:-0.01em;color:#131516">This week in Toronto</h1>
        <p style="margin:0 0 8px;font:14px/1.55 -apple-system,sans-serif;color:#74787c">Top {len(entries)} restaurants newly registered with the City over the past 7 days, by recency.</p>
      </td></tr>

      <tr><td style="padding:8px 28px 0">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          {rows}
        </table>
      </td></tr>

      <tr><td style="padding:22px 28px 0">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr><td bgcolor="#131516" style="background:#131516;border-radius:8px">
            <a href="{SITE_BASE}" style="display:inline-block;padding:13px 24px;color:#ffffff;font:600 15px/1 -apple-system,sans-serif;text-decoration:none;border-radius:8px">Browse all on the site &rarr;</a>
          </td></tr>
        </table>
      </td></tr>

      <tr><td style="padding:18px 28px 28px"></td></tr>

      <tr><td bgcolor="#f6f7f8" style="padding:18px 28px 22px;background:#f6f7f8;border-top:1px solid #ebecef">
        <p style="margin:0;color:#74787c;font:12.5px/1.55 -apple-system,sans-serif">
          You&rsquo;re subscribed to the <b style="color:#46494c">All Toronto weekly digest</b>.
          <a href="{_esc(unsubscribe_url)}" style="color:#74787c;text-decoration:underline">Unsubscribe</a> - one click, no questions.
        </p>
        <p style="margin:10px 0 0;color:#a8acb0;font:11px/1.5 -apple-system,sans-serif">
          NowServingTO pulls newly registered restaurants from City of Toronto Open Data, classifies cuisine with Anthropic Claude, and verifies operating status via Google Places.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>'''
    text_lines = [
        f"NowServingTO weekly digest - {today}",
        f"{len(entries)} restaurants newly registered with the City of Toronto in the past 7 days.",
        "",
    ]
    for e in entries:
        days = e.get('daysOpen', 0)
        when = 'today' if days <= 1 else f'{days}d ago'
        text_lines.extend([
            f"* {e.get('operatingName','')}",
            f"  {e.get('address','')} ({when}{' · '+e.get('district','') if e.get('district') else ''})",
            f"  Cuisines: {', '.join(c.replace('_',' ').title() for c in (e.get('cuisines') or [e.get('cuisine')]) if c)}",
            "",
        ])
    text_lines.append(f"Browse the live feed: {SITE_BASE}")
    text_lines.append(f"Unsubscribe: {unsubscribe_url}")
    return subject, html, '\n'.join(text_lines)


def main():
    force = '--force' in sys.argv
    today = date.today()

    sent_state = _load_json(SENT_PATH, {})
    if sent_state.get('last_sent') and not force:
        last = date.fromisoformat(sent_state['last_sent'])
        if (today - last).days < MIN_DAYS_BETWEEN_SENDS:
            print(f'send_weekly_digest: last sent {sent_state["last_sent"]} ({(today-last).days}d ago) - skipping')
            return 0

    data = _load_json(DATA_PATH, None)
    if not data or 'newOpenings' not in data:
        print('send_weekly_digest: no newOpenings in corridors.json - skipping', file=sys.stderr)
        return 0

    entries = _pick_entries(data, WINDOW_DAYS, TOP_N)
    if not entries:
        print('send_weekly_digest: no entries in the last 7 days - skipping')
        return 0

    subs = _load_json(SUBS_PATH, [])
    digest_subs = [s for s in subs if s.get('kind') == 'digest_all' and s.get('confirmed', True)]
    if not digest_subs:
        print(f'send_weekly_digest: {len(entries)} new entries but 0 digest subscribers')
        # Don't update last_sent - lets the first real subscriber get this week's batch
        return 0

    n_sent = n_failed = 0
    for s in digest_subs:
        unsubscribe_url = f'{SITE_BASE}/api/unsubscribe?t={s["token"]}'
        subject, html, text = _build_email(entries, unsubscribe_url)
        try:
            _send(s['email'], subject, html, text, unsubscribe_url)
            n_sent += 1
        except Exception as ex:
            print(f'send_weekly_digest: ERROR sending to {s["email"]}: {ex}', file=sys.stderr)
            n_failed += 1

    _save_json(SENT_PATH, {'last_sent': today.isoformat(), 'count': n_sent, 'entries': len(entries)})
    print(f'send_weekly_digest: sent {n_sent} digests ({n_failed} failed), top {len(entries)} entries from last {WINDOW_DAYS}d')
    return 0 if n_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
