#!/usr/bin/env python3
"""
Cron job: send per-cuisine + per-district real-time alerts.

Reads the newOpenings.recent feed out of data/corridors.json, finds
entries whose slug is not in tools/cache/alerts_sent.json yet, and for
each one fans out an email to every subscriber whose cuisine OR district
matches.

Runs daily after inject_openings.py inside cron_daily_openings.sh.

First-run behavior: if alerts_sent.json doesn't exist, we DO NOT alert
on the existing backlog - we snapshot all current slugs into the sent
file so subscribers only ever see entries that landed AFTER they signed
up. To force-resend for testing, delete alerts_sent.json.

Idempotency: alerts_sent.json caps at the last 5000 slugs so it doesn't
grow forever (the corridors feed itself is windowed to ~365d).

Mail delivery: smtplib → 127.0.0.1:25 (local Postfix + OpenDKIM milter).
See deploy/mail-setup.md for the one-time VPS install + DNS.
"""
import json, re, smtplib, sys
from pathlib import Path
from email.message import EmailMessage
from email.utils import make_msgid, formatdate, formataddr
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / 'data' / 'corridors.json'
SUBS_PATH = ROOT / 'tools' / 'cache' / 'alert_subs.json'
SENT_PATH = ROOT / 'tools' / 'cache' / 'alerts_sent.json'
SECRETS = Path('/var/secrets/nowservingto.env')

SITE_BASE = 'https://nowservingto.com'
MAX_SENT_HISTORY = 5000


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


def _district_slug(label):
    return re.sub(r'[^a-z0-9]+', '-', (label or '').lower()).strip('-')


def _load_json(path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text())
    except Exception: return default


def _save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True))
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


def _sub_label(sub):
    """Human-readable label for a subscription, used in alert email footer."""
    if sub['kind'] == 'cuisine':
        return f"{sub['value'].replace('_', ' ').title()} cuisine"
    if sub['kind'] == 'district':
        return f"{sub['value'].replace('-', ' ').title()} district"
    ck, _, ds = sub['value'].partition('|')
    return (f"{ck.replace('_', ' ').title()} in "
            f"{ds.replace('-', ' ').title()}")


def _esc(s):
    """Minimal HTML escape for values dropped into the email template. The
    restaurant feed is human-curated names + Google Places matches; we still
    escape because a stray ampersand or quote in an address shouldn't break
    the markup."""
    return (str(s or '').replace('&', '&amp;')
                        .replace('<', '&lt;')
                        .replace('>', '&gt;')
                        .replace('"', '&quot;'))


def _entry_email(entry, sub):
    """Compose one alert email tailored to one subscriber.

    Layout uses table-based markup (still the most reliable email client
    pattern in 2026 - Outlook on Windows ignores flexbox/grid). All styles
    are inline; web fonts are intentionally avoided so we degrade to the
    Georgia / system-sans stack everywhere.
    """
    name = (entry.get('operatingName') or '').title()
    addr = entry.get('address') or ''
    cuisines = entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else [])
    cuisine_labels = ', '.join(c.replace('_', ' ').title() for c in cuisines)
    district = entry.get('district') or ''
    listing_url = f"{SITE_BASE}/r/{entry['slug']}"
    maps_url = entry.get('mapsUrl') or ''
    website = entry.get('website') or ''
    rating = entry.get('rating')
    review_count = entry.get('reviewCount')

    # Pick the largest available photo. Prefer the wide JPEG over the
    # 196×196 webp thumb so the hero image carries the email. Some legacy
    # email clients (older Outlook) don't render webp, so JPEG is safer.
    photo_rel = entry.get('photo') or entry.get('thumb') or ''
    photo_url = f"{SITE_BASE}{photo_rel}" if photo_rel else ''

    # Why this subscriber is being notified - set the lede honestly.
    if sub['kind'] == 'cuisine':
        clabel = sub['value'].replace('_', ' ').title()
        lede = f"A new {clabel} restaurant was just licensed in Toronto."
        subject = f"New {clabel}: {name}"
    elif sub['kind'] == 'district':
        dlabel = sub['value'].replace('-', ' ').title()
        lede = f"A new restaurant was just licensed in {dlabel}."
        subject = f"New in {dlabel}: {name} ({cuisine_labels})"
    else:   # intersection
        ck, _, ds = sub['value'].partition('|')
        clabel = ck.replace('_', ' ').title()
        dlabel = ds.replace('-', ' ').title()
        lede = (f"A new {clabel} restaurant just opened in {dlabel} - "
                f"the exact intersection you signed up for.")
        subject = f"New {clabel} in {dlabel}: {name}"

    unsub_url = f"{SITE_BASE}/api/unsubscribe?t={sub['token']}"

    # --- fragments ----------------------------------------------------------
    hero_html = (
        f'<tr><td style="padding:20px 28px 0">'
        f'<a href="{listing_url}" style="display:block;text-decoration:none">'
        f'<img src="{_esc(photo_url)}" alt="{_esc(name)}" width="544" '
        f'style="display:block;width:100%;max-width:544px;height:auto;'
        f'border-radius:10px;border:0">'
        f'</a></td></tr>'
        if photo_url else ''
    )

    rating_html = ''
    if rating:
        rating_html = (
            f' <span style="color:#74787c">·</span> '
            f'<span style="color:#46494c;white-space:nowrap">'
            f'<span style="color:#e8a01a">★</span> {rating:.1f}'
            f'{f" <span style=\"color:#a8acb0\">({review_count:,})</span>" if review_count else ""}'
            f'</span>'
        )

    addr_html = ''
    if addr:
        addr_inner = _esc(addr)
        if maps_url:
            addr_inner = f'<a href="{_esc(maps_url)}" style="color:#46494c;text-decoration:none;border-bottom:1px solid #d8dade">{_esc(addr)}</a>'
        addr_html = (
            f'<div style="margin:6px 0 0;font:14px/1.5 -apple-system,\'Helvetica Neue\',Arial,sans-serif;color:#46494c">'
            f'{addr_inner}'
            f'</div>'
        )

    secondary_links = []
    if maps_url:
        secondary_links.append(f'<a href="{_esc(maps_url)}" style="color:#c83624;text-decoration:none">Open in Google Maps</a>')
    if website:
        secondary_links.append(f'<a href="{_esc(website)}" style="color:#c83624;text-decoration:none">Their website</a>')
    secondary_html = ''
    if secondary_links:
        secondary_html = (
            f'<tr><td style="padding:14px 28px 28px">'
            f'<p style="margin:0;color:#74787c;font:13px/1.5 -apple-system,sans-serif">'
            f'Or: {" &middot; ".join(secondary_links)}'
            f'</p></td></tr>'
        )

    # --- full email body ----------------------------------------------------
    html = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light">
<title>{_esc(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#131516;-webkit-font-smoothing:antialiased">

<!-- Preheader (hidden in body, surfaces in inbox preview text) -->
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#fafafa">
{_esc(lede)} {_esc(name)} &middot; {_esc(district)}
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fafafa" style="background:#fafafa;padding:24px 0">
  <tr><td align="center" style="padding:0 12px">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #ebecef;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,0.04);overflow:hidden">

      <!-- Header band -->
      <tr><td style="padding:26px 28px 18px;border-bottom:3px solid #131516">
        <a href="{SITE_BASE}" style="display:inline-block;font:800 28px/1 Georgia,'Iowan Old Style',serif;letter-spacing:-0.02em;color:#131516;text-decoration:none">NowServingTO</a>
        <div style="color:#74787c;font:italic 400 14px/1.4 Georgia,serif;margin-top:6px">Toronto's newest registered restaurants &mdash; updated daily.</div>
      </td></tr>

      <!-- Lede -->
      <tr><td style="padding:24px 28px 0">
        <p style="margin:0;color:#46494c;font:16px/1.55 -apple-system,'Helvetica Neue',Arial,sans-serif">{_esc(lede)}</p>
      </td></tr>

      {hero_html}

      <!-- Restaurant card -->
      <tr><td style="padding:20px 28px 0">
        <h1 style="margin:0;font:700 26px/1.2 Georgia,'Iowan Old Style',serif;letter-spacing:-0.01em">
          <a href="{listing_url}" style="color:#131516;text-decoration:none">{_esc(name)}</a>
        </h1>
        <div style="margin:6px 0 0;color:#74787c;font:14px/1.5 -apple-system,sans-serif">
          {_esc(cuisine_labels)}{f' <span style="color:#74787c">&middot;</span> {_esc(district)}' if district else ''}{rating_html}
        </div>
        {addr_html}
      </td></tr>

      <!-- Primary CTA -->
      <tr><td style="padding:24px 28px 0">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr><td bgcolor="#131516" style="background:#131516;border-radius:8px">
            <a href="{listing_url}" style="display:inline-block;padding:13px 24px;color:#ffffff;font:600 15px/1 -apple-system,'Helvetica Neue',Arial,sans-serif;text-decoration:none;border-radius:8px">View on NowServingTO &rarr;</a>
          </td></tr>
        </table>
      </td></tr>

      {secondary_html}

      <!-- Footer -->
      <tr><td bgcolor="#f6f7f8" style="padding:18px 28px 22px;background:#f6f7f8;border-top:1px solid #ebecef">
        <p style="margin:0;color:#74787c;font:12.5px/1.55 -apple-system,sans-serif">
          You&rsquo;re subscribed to <b style="color:#46494c">{_esc(_sub_label(sub))}</b> alerts.
          <a href="{unsub_url}" style="color:#74787c;text-decoration:underline">Unsubscribe</a> &mdash; one click, no questions.
        </p>
        <p style="margin:10px 0 0;color:#a8acb0;font:11px/1.5 -apple-system,sans-serif">
          NowServingTO pulls newly registered restaurants from City of Toronto Open Data, classifies cuisine with Anthropic Claude, and verifies operating status via Google Places.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>

</body></html>'''

    # Plain-text alternative - required for spam-score, and useful for
    # screen-readers / text-mode clients.
    secondary_lines = []
    if maps_url:  secondary_lines.append(f'Google Maps: {maps_url}')
    if website:   secondary_lines.append(f'Website: {website}')
    rating_text = ''
    if rating:
        rating_text = f' (★ {rating:.1f}'
        if review_count: rating_text += f', {review_count:,} reviews'
        rating_text += ')'
    text = (
        f"NowServingTO - Toronto's newest registered restaurants\n"
        f"{'=' * 50}\n\n"
        f"{lede}\n\n"
        f"{name}{rating_text}\n"
        f"{cuisine_labels}{' · ' + district if district else ''}\n"
        f"{addr}\n\n"
        f"View on NowServingTO: {listing_url}\n"
        + ('\n' + '\n'.join(secondary_lines) + '\n' if secondary_lines else '')
        + f"\n---\n"
        f"You're subscribed to {_sub_label(sub)} alerts.\n"
        f"Unsubscribe: {unsub_url}\n"
    )
    return subject, html, text


def main():
    data = _load_json(DATA_PATH, None)
    if not data or 'newOpenings' not in data:
        print('send_alerts: no newOpenings in corridors.json, nothing to do', file=sys.stderr)
        return 0

    entries = data['newOpenings'].get('recent') or []
    current_slugs = {e['slug'] for e in entries if e.get('slug')}

    # First-run snapshot: don't fire on backlog.
    if not SENT_PATH.exists():
        _save_json(SENT_PATH, {'sent': sorted(current_slugs)})
        print(f'send_alerts: first run - snapshotted {len(current_slugs)} existing slugs, no alerts sent')
        return 0

    sent_data = _load_json(SENT_PATH, {'sent': []})
    sent = set(sent_data.get('sent', []))
    new_slugs = [e for e in entries if e['slug'] not in sent]
    if not new_slugs:
        print('send_alerts: no new entries since last run')
        return 0

    subs = _load_json(SUBS_PATH, [])
    if not subs:
        # No subscribers yet - still mark these as "sent" so a future
        # signup doesn't get blasted with backlog.
        sent.update(e['slug'] for e in new_slugs)
        _save_json(SENT_PATH, {'sent': sorted(sent)[-MAX_SENT_HISTORY:]})
        print(f'send_alerts: {len(new_slugs)} new entries but 0 subscribers - marked as sent')
        return 0

    # Index subscribers by axis for O(1) match per entry. Intersection
    # subs need their own bucket keyed by "cuisine|district" so we can
    # cheaply check "does this entry's (cuisine, district) match an
    # intersection sub" without scanning all subs per entry.
    by_cuisine = {}
    by_district = {}
    by_intersection = {}   # "<cuisine_key>|<district_slug>" -> [sub, ...]
    for s in subs:
        if not s.get('confirmed', True): continue
        if s['kind'] == 'cuisine':
            by_cuisine.setdefault(s['value'], []).append(s)
        elif s['kind'] == 'district':
            by_district.setdefault(s['value'], []).append(s)
        elif s['kind'] == 'intersection':
            by_intersection.setdefault(s['value'], []).append(s)

    n_sent = 0
    n_failed = 0
    for entry in new_slugs:
        cuisines = entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else [])
        district_label = entry.get('district', '')
        dslug = _district_slug(district_label)
        # Dedupe: a subscriber matching on multiple axes (e.g. someone
        # subscribed to BOTH "Indian" and "Indian in Downtown") only gets
        # one email per new entry. Intersection subs are checked first so
        # the more-specific subscription claims them; broader cuisine /
        # district subs claim them only if intersection didn't.
        matched_emails = set()
        matched_subs = []
        # 1. Intersection matches (most specific)
        for c in cuisines:
            ikey = f'{c}|{dslug}'
            for sub in by_intersection.get(ikey, []):
                if sub['email'] not in matched_emails:
                    matched_emails.add(sub['email'])
                    matched_subs.append(sub)
        # 2. Cuisine matches
        for c in cuisines:
            for sub in by_cuisine.get(c, []):
                if sub['email'] not in matched_emails:
                    matched_emails.add(sub['email'])
                    matched_subs.append(sub)
        for sub in by_district.get(dslug, []):
            if sub['email'] not in matched_emails:
                matched_emails.add(sub['email'])
                matched_subs.append(sub)
        for sub in matched_subs:
            try:
                subject, html, text = _entry_email(entry, sub)
                unsub = f"{SITE_BASE}/api/unsubscribe?t={sub['token']}"
                _send(sub['email'], subject, html, text, unsub)
                n_sent += 1
            except Exception as e:
                print(f'send_alerts: failed {sub["email"]} <- {entry["slug"]}: {e}', file=sys.stderr)
                n_failed += 1
        sent.add(entry['slug'])

    _save_json(SENT_PATH, {'sent': sorted(sent)[-MAX_SENT_HISTORY:]})
    print(f'send_alerts: {len(new_slugs)} new entries → {n_sent} emails sent, {n_failed} failed')
    return 0 if n_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
