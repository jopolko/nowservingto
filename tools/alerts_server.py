#!/usr/bin/env python3
"""
HTTP service for NowServingTO alerts + tip submissions.

Endpoints (Apache reverse-proxies /api/* to this service on localhost:8080):

  POST /api/subscribe   body: {"email": "...", "kind": "cuisine"|"district",
                                "value": "<cuisine_key or district_slug>"}
                        → stores a real-time alert subscription
                        → sends a confirmation email via local SMTP
  POST /api/tip         body: {"name": "...", "address": "...", ...}
                        → stores a tip submission (replaces Tally)
                        → notifies the operator via local SMTP
  GET  /api/unsubscribe?t=<token>
                        → one-click unsubscribe (RFC 8058 List-Unsubscribe-Post)
  GET  /api/health      → liveness check

Storage:
  tools/cache/alert_subs.json     - list of {email, kind, value, token,
                                              subscribed_at, confirmed}
  tools/cache/tips.jsonl          - append-only log of tip submissions

Mail delivery: hand-offs to the local Postfix relay on 127.0.0.1:25.
Postfix is configured with OpenDKIM as a milter so every outbound
message is DKIM-signed for nowservingto.com. DNS must publish SPF, DKIM,
and DMARC for the domain - see deploy/mail-setup.md for the one-time
VPS install and the exact DNS records.

Run as a systemd service on 127.0.0.1:8080. Apache `.htaccess` reverse-
proxies /api/* to here. The service does not directly face the internet
- Cloudflare → Apache → 127.0.0.1:8080 is the chain.
"""
import os, sys, json, re, smtplib, secrets as _secrets, traceback
from pathlib import Path
from email.message import EmailMessage
from email.utils import make_msgid, formatdate, formataddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / 'tools' / 'cache'
SUBS_PATH = CACHE / 'alert_subs.json'
TIPS_PATH = CACHE / 'tips.jsonl'
SECRETS = Path('/var/secrets/nowservingto.env')

PORT = int(os.environ.get('ALERTS_PORT', '8080'))
SITE_BASE = 'https://nowservingto.com'

# --- secrets ---------------------------------------------------------------

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
OPERATOR_EMAIL = ENV.get('OPERATOR_EMAIL', 'mjopolko@gmail.com')

SMTP_HOST = ENV.get('SMTP_HOST', '127.0.0.1')
SMTP_PORT = int(ENV.get('SMTP_PORT', '25'))
MAIL_FROM_ADDR = ENV.get('MAIL_FROM_ADDR', 'alerts@nowservingto.com')
MAIL_FROM_NAME = ENV.get('MAIL_FROM_NAME', 'NowServingTO')
MAIL_DOMAIN = 'nowservingto.com'

# --- storage ---------------------------------------------------------------

def _load_subs():
    if not SUBS_PATH.exists(): return []
    try:
        return json.loads(SUBS_PATH.read_text())
    except Exception:
        return []

def _save_subs(subs):
    SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUBS_PATH.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(subs, indent=2, sort_keys=True))
    tmp.replace(SUBS_PATH)

# --- email via local Postfix ----------------------------------------------

def _send_email(to, subject, html, text, unsubscribe_url=None):
    """Hand off to local Postfix on 127.0.0.1:25. OpenDKIM milter signs
    on its way out. Returns (ok, info)."""
    msg = EmailMessage()
    msg['From'] = formataddr((MAIL_FROM_NAME, MAIL_FROM_ADDR))
    msg['To'] = to
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=False)
    msg['Message-ID'] = make_msgid(domain=MAIL_DOMAIN)
    msg['Auto-Submitted'] = 'auto-generated'
    msg['Precedence'] = 'bulk'
    # RFC 2369 + RFC 8058 one-click unsubscribe - Gmail/Yahoo bulk-sender
    # requirement. Both headers must be present and the POST must succeed
    # without further user action.
    if unsubscribe_url:
        msg['List-Unsubscribe'] = f'<{unsubscribe_url}>'
        msg['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.send_message(msg, from_addr=MAIL_FROM_ADDR, to_addrs=[to])
        return True, 'queued'
    except Exception as e:
        return False, f'smtp: {e}'

# --- helpers ---------------------------------------------------------------

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

def _valid_email(s):
    return bool(s and isinstance(s, str) and _EMAIL_RE.match(s.strip()) and len(s) < 200)

def _new_token():
    return _secrets.token_urlsafe(16)

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# --- subscription handlers -------------------------------------------------

def handle_subscribe(payload):
    """Create or refresh an alert subscription. Idempotent on (email, kind, value).

    Four subscription kinds supported:
      cuisine       value = cuisine_key            (e.g. "indian")
      district      value = district_slug           (e.g. "east-toronto")
      intersection  value = "cuisine_key|district_slug"
                    (e.g. "indian|east-toronto") - only fires when an entry
                    matches BOTH axes. Lets a subscriber narrow to
                    "Argentine in Scarborough" without getting all of
                    Argentine or all of Scarborough.
      digest_all    value = "toronto" (or empty - normalized) - weekly
                    digest of the top 5 new restaurants across all of
                    Toronto. Sent by send_weekly_digest.py on Sundays.
    """
    email = (payload.get('email') or '').strip().lower()
    kind = payload.get('kind')
    value = (payload.get('value') or '').strip().lower()
    if not _valid_email(email):
        return 400, {'error': 'invalid email'}
    if kind not in ('cuisine', 'district', 'intersection', 'digest_all'):
        return 400, {'error': 'kind must be "cuisine", "district", "intersection", or "digest_all"'}
    if kind == 'intersection':
        # value format: <cuisine_key>|<district_slug>
        if '|' not in value:
            return 400, {'error': 'intersection value must be "cuisine_key|district_slug"'}
        ck, _, ds = value.partition('|')
        if not re.match(r'^[a-z0-9_]+$', ck) or not re.match(r'^[a-z0-9-]+$', ds):
            return 400, {'error': 'invalid intersection value format'}
        if len(value) > 80:
            return 400, {'error': 'value too long'}
    elif kind == 'digest_all':
        # Single canonical value. Normalize any user-supplied junk to "toronto"
        # so dedupe works regardless of what the form posted.
        value = 'toronto'
    else:
        if not value or len(value) > 60 or not re.match(r'^[a-z0-9_-]+$', value):
            return 400, {'error': 'invalid value'}
    subs = _load_subs()
    # Dedupe - refresh subscribed_at if existing
    existing = next(
        (s for s in subs if s['email'] == email and s['kind'] == kind and s['value'] == value),
        None,
    )
    if existing:
        existing['subscribed_at'] = _now_iso()
        token = existing['token']
        first_time = False
    else:
        token = _new_token()
        subs.append({
            'email': email,
            'kind': kind,
            'value': value,
            'token': token,
            'subscribed_at': _now_iso(),
            'confirmed': True,   # no double-opt-in for now - single-click
        })
        first_time = True
    _save_subs(subs)
    # Send a confirmation/welcome email - copy varies by kind so the
    # subscriber sees exactly what they signed up for.
    if kind == 'cuisine':
        label = value.replace('_', ' ').title()
        subject = f'Subscribed: {label} restaurant alerts'
        you_will = f"emails when a new {label} restaurant is registered with the City of Toronto"
        browse_link = f'{SITE_BASE}/cuisine/{value}'
    elif kind == 'district':
        label = value.replace('-', ' ').title()
        subject = f'Subscribed: new restaurants in {label}'
        you_will = f"emails when a new restaurant is registered with the City in {label}"
        browse_link = f'{SITE_BASE}/district/{value}'
    elif kind == 'digest_all':
        label = 'All Toronto'
        subject = 'Subscribed: weekly Toronto restaurant digest'
        you_will = ("a Sunday digest of the top 5 newly registered restaurants across Toronto. "
                    "One email per week, never more")
        browse_link = SITE_BASE
    else:   # intersection
        ck, _, ds = value.partition('|')
        clabel = ck.replace('_', ' ').title()
        dlabel = ds.replace('-', ' ').title()
        label = f'{clabel} in {dlabel}'
        subject = f'Subscribed: {clabel} restaurants in {dlabel}'
        you_will = (f"emails when a new {clabel} restaurant is registered "
                    f"with the City specifically in {dlabel}")
        browse_link = f'{SITE_BASE}/cuisine/{ck}'
    unsub_link = f'{SITE_BASE}/api/unsubscribe?t={token}'

    # Branded welcome email - same shell as the daily alert template in
    # send_alerts.py (NowServingTO header, italic tagline, padded card,
    # branded CTA button, attribution footer). Kept inline so the file
    # has zero non-stdlib deps.
    html = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>Subscribed - NowServingTO</title>
</head>
<body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#131516;-webkit-font-smoothing:antialiased">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#fafafa">
You&rsquo;re subscribed. From now on you&rsquo;ll get {you_will}.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#fafafa" style="background:#fafafa;padding:24px 0">
  <tr><td align="center" style="padding:0 12px">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #ebecef;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,0.04);overflow:hidden">

      <tr><td style="padding:26px 28px 18px;border-bottom:3px solid #131516">
        <a href="{SITE_BASE}" style="display:inline-block;font:800 28px/1 Georgia,'Iowan Old Style',serif;letter-spacing:-0.02em;color:#131516;text-decoration:none">NowServingTO</a>
        <div style="color:#74787c;font:italic 400 14px/1.4 Georgia,serif;margin-top:6px">Toronto's newest registered restaurants - updated daily.</div>
      </td></tr>

      <tr><td style="padding:24px 28px 0">
        <h1 style="margin:0 0 10px;font:700 22px/1.25 Georgia,'Iowan Old Style',serif;letter-spacing:-0.01em;color:#131516">You&rsquo;re subscribed - {label}</h1>
        <p style="margin:0 0 14px;font:15px/1.55 -apple-system,sans-serif;color:#46494c">From now on you&rsquo;ll get {you_will}.</p>
        <p style="margin:0 0 14px;font:14px/1.5 -apple-system,sans-serif;color:#74787c">Toronto sees roughly 5-10 newly registered restaurants per week. Narrow alerts like yours mean you&rsquo;ll only hear from us when something matches - often just a handful of times a year.</p>
      </td></tr>

      <tr><td style="padding:8px 28px 0">
        <div style="background:#fff8e6;border-left:3px solid #c83624;padding:12px 14px;border-radius:0 6px 6px 0;font:14px/1.55 -apple-system,sans-serif;color:#46494c">
          <b style="color:#131516">Quick favor:</b> add <code style="background:#ffefe9;padding:1px 6px;border-radius:3px;color:#a02817;font-size:13px">alerts@nowservingto.com</code> to your contacts so future alerts land in your inbox instead of spam. New sending domains take a few weeks to build reputation with Gmail.
        </div>
      </td></tr>

      <tr><td style="padding:22px 28px 0">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr><td bgcolor="#131516" style="background:#131516;border-radius:8px">
            <a href="{browse_link}" style="display:inline-block;padding:13px 24px;color:#ffffff;font:600 15px/1 -apple-system,sans-serif;text-decoration:none;border-radius:8px">Browse the current list &rarr;</a>
          </td></tr>
        </table>
      </td></tr>

      <tr><td style="padding:18px 28px 28px"></td></tr>

      <tr><td bgcolor="#f6f7f8" style="padding:18px 28px 22px;background:#f6f7f8;border-top:1px solid #ebecef">
        <p style="margin:0;color:#74787c;font:12.5px/1.55 -apple-system,sans-serif">
          You&rsquo;re subscribed to <b style="color:#46494c">{label}</b> alerts.
          <a href="{unsub_link}" style="color:#74787c;text-decoration:underline">Unsubscribe</a> - one click, no questions.
        </p>
        <p style="margin:10px 0 0;color:#a8acb0;font:11px/1.5 -apple-system,sans-serif">
          NowServingTO pulls newly registered restaurants from City of Toronto Open Data, classifies cuisine with Anthropic Claude, and verifies operating status via Google Places.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>'''

    text = (
        f"NowServingTO - Toronto's newest registered restaurants\n"
        f"{'=' * 50}\n\n"
        f"You're subscribed - {label}.\n\n"
        f"From now on you'll get {you_will}.\n\n"
        f"Quick favor: add alerts@nowservingto.com to your contacts so future\n"
        f"alerts land in your inbox instead of spam. New sending domains take\n"
        f"a few weeks to build reputation with Gmail.\n\n"
        f"Browse the current list: {browse_link}\n\n"
        f"---\n"
        f"You're subscribed to {label} alerts.\n"
        f"Unsubscribe: {unsub_link}\n"
    )
    _send_email(email, subject, html, text, unsubscribe_url=unsub_link)
    return 200, {'ok': True, 'first_time': first_time, 'token': token}


def handle_unsubscribe(token):
    """One-click unsubscribe via token."""
    if not token or len(token) > 64:
        return 400, '<h1>Invalid unsubscribe link</h1>'
    subs = _load_subs()
    n_before = len(subs)
    subs = [s for s in subs if s.get('token') != token]
    if len(subs) == n_before:
        return 200, '<h1>Already unsubscribed</h1><p>No active subscription matched that link.</p>'
    _save_subs(subs)
    return 200, (
        '<h1>Unsubscribed</h1>'
        '<p>You won\'t receive any more alerts. '
        f'<a href="{SITE_BASE}/">Browse the directory</a> anytime.</p>'
    )


def handle_tip(payload):
    """Receive a /contribute tip submission, log it, and notify operator."""
    # Soft-validate; nothing required - just capture what's there.
    name = (payload.get('restaurant_name') or '').strip()[:200]
    addr = (payload.get('address') or '').strip()[:200]
    cuisine = (payload.get('cuisine') or '').strip()[:60]
    kind = (payload.get('kind') or 'missing').strip()[:60]
    existing_listing = (payload.get('existing_listing') or '').strip()[:200]
    whats_wrong = (payload.get('whats_wrong') or '').strip()[:60]
    notes = (payload.get('notes') or '').strip()[:2000]
    reporter_email = (payload.get('reporter_email') or '').strip().lower()[:200]
    # Honeypot (form field 'website' should be empty; bots fill it)
    if (payload.get('website') or '').strip():
        return 200, {'ok': True}   # silently accept + drop
    if not (name or addr or existing_listing or notes):
        return 400, {'error': 'please tell us something'}
    entry = {
        't': _now_iso(),
        'kind': kind,
        'restaurant_name': name,
        'address': addr,
        'cuisine': cuisine,
        'existing_listing': existing_listing,
        'whats_wrong': whats_wrong,
        'notes': notes,
        'reporter_email': reporter_email if _valid_email(reporter_email) else '',
    }
    TIPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TIPS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')
    # Notify operator
    if OPERATOR_EMAIL:
        subject = f'[NowServingTO tip] {(name or existing_listing or "(unknown)")[:80]}'
        rows = ''.join(
            f'<p><b>{k}:</b> {v or "-"}</p>'
            for k, v in entry.items() if k != 't'
        )
        html = f'<p><b>Time:</b> {entry["t"]}</p>{rows}'
        text = '\n'.join(f'{k}: {v}' for k, v in entry.items())
        _send_email(OPERATOR_EMAIL, subject, html, text)
    return 200, {'ok': True}

# --- HTTP server -----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = 'NowServingTO-Alerts/1.0'

    def log_message(self, fmt, *args):
        # Quieter logs (default is super verbose); systemd journal still captures.
        sys.stderr.write('[%s] %s\n' % (self.log_date_time_string(), fmt % args))

    def _json(self, status, body):
        data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _html(self, status, body):
        data = (
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>NowServingTO</title>'
            '<style>body{font:15px/1.5 -apple-system,sans-serif;max-width:560px;margin:60px auto;padding:0 20px;color:#131516}'
            'a{color:#c83624}h1{font:700 24px/1.2 Georgia,serif;margin:0 0 12px}</style>'
            + body
        ).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            n = min(n, 64 * 1024)  # 64KB cap; tip notes capped lower in handler
            raw = self.rfile.read(n) if n else b'{}'
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api/health':
            return self._json(200, {'ok': True, 'subs': len(_load_subs())})
        if u.path == '/api/unsubscribe':
            q = parse_qs(u.query)
            token = (q.get('t') or [''])[0]
            status, body = handle_unsubscribe(token)
            return self._html(status, body)
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == '/api/subscribe':
            payload = self._read_json()
            if payload is None: return self._json(400, {'error': 'invalid JSON'})
            try:
                status, body = handle_subscribe(payload)
            except Exception:
                traceback.print_exc()
                return self._json(500, {'error': 'server error'})
            return self._json(status, body)
        if u.path == '/api/tip':
            payload = self._read_json()
            if payload is None: return self._json(400, {'error': 'invalid JSON'})
            try:
                status, body = handle_tip(payload)
            except Exception:
                traceback.print_exc()
                return self._json(500, {'error': 'server error'})
            return self._json(status, body)
        self._json(404, {'error': 'not found'})

def main():
    print(f'NowServingTO alerts service listening on 127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
