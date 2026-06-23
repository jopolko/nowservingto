#!/usr/bin/env python3
"""
robots_guard.py - watchdog for joshuaopolko.com/robots.txt

Emails an alert if the LIVE robots.txt regresses to blocking crawlers, e.g.
Cloudflare's "Managed robots.txt" feature getting re-enabled and re-injecting
Disallow rules for GPTBot / ClaudeBot / Google-Extended and friends.

Healthy state for this site = blanket "User-agent: * / Allow: /" with a Sitemap
line and no managed block. Anything else is treated as a regression.

Stdlib only. Designed for cron. Mail goes through local Postfix (127.0.0.1:25),
the same path send_weekly_digest.py / send_alerts.py use.

  python3 robots_guard.py            # one check; emails only on a state change
  python3 robots_guard.py --selftest # send one sample alert to confirm delivery
"""
import os, sys, json, smtplib, urllib.request, datetime
from email.message import EmailMessage

HERE       = os.path.dirname(os.path.abspath(__file__))
URL        = os.environ.get("ROBOTS_URL", "https://joshuaopolko.com/robots.txt")
STATE_FILE = os.environ.get("ROBOTS_STATE", os.path.join(HERE, "logs", "robots-guard-state.json"))
MAIL_TO    = os.environ.get("ROBOTS_ALERT_TO", "mjopolko@gmail.com")
MAIL_FROM  = os.environ.get("MAIL_FROM_ADDR", "alerts@nowservingto.com")
SMTP_HOST  = os.environ.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "25"))

BAD_MARKERS = ["cloudflare managed"]  # Cloudflare managed-robots signature


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "robots-guard/1.0 (+joshuaopolko)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.getcode(), r.read().decode("utf-8", "replace")


def analyze(body):
    """Return (status, reasons). status is 'OK' or 'BAD'."""
    reasons = []
    low = body.lower()
    for m in BAD_MARKERS:
        if m in low:
            reasons.append('Cloudflare "Managed robots.txt" block is back')
    for line in body.splitlines():
        s = line.split("#", 1)[0].strip().lower().replace(" ", "")
        if s == "disallow:/":
            reasons.append("a blanket 'Disallow: /' rule is present")
            break
    if "allow: /" not in low:
        reasons.append("the blanket 'Allow: /' line is missing")
    return ("BAD" if reasons else "OK"), reasons


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)


def send_mail(subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.send_message(msg)


def main():
    stamp = datetime.datetime.now().isoformat(timespec="seconds")

    if "--selftest" in sys.argv:
        send_mail("[joshuaopolko] robots-guard self-test (you can ignore this)",
                  f"This is a test from robots_guard.py at {stamp}.\n"
                  f"If you got this, alerting works. Watching: {URL}\n")
        print(f"[{stamp}] self-test email sent to {MAIL_TO}")
        return

    today = datetime.date.today().isoformat()
    st = load_state()
    try:
        code, body = fetch(URL)
        status, reasons = ("BAD", [f"HTTP {code}"]) if code != 200 else analyze(body)
    except Exception as e:
        code, body, status, reasons = 0, "", "BAD", [f"fetch failed: {e}"]

    prev = st.get("status")
    print(f"[{stamp}] status={status} prev={prev} reasons={reasons}")

    alert = (status == "BAD" and (prev != "BAD" or st.get("last_alert_date") != today)) \
        or (status == "OK" and prev == "BAD")

    if alert:
        if status == "BAD":
            subject = "[joshuaopolko] robots.txt REGRESSION - crawlers may be blocked"
            text = ("WARNING: joshuaopolko.com/robots.txt looks wrong.\n\n"
                    "Reasons:\n  - " + "\n  - ".join(reasons) +
                    f"\n\nURL: {URL}\nHTTP: {code}\nTime: {stamp}\n\n"
                    "Most likely cause: Cloudflare 'Managed robots.txt' / AI bot blocking got\n"
                    "re-enabled. Fix in the Cloudflare dashboard > this site >\n"
                    "AI Audit / Bot Management / Managed robots.txt -> disable.\n\n"
                    "----- live robots.txt -----\n" + (body or "(no body)"))
            st["last_alert_date"] = today
        else:
            subject = "[joshuaopolko] robots.txt recovered - blanket allow restored"
            text = f"robots.txt is healthy again (blanket Allow: /, no managed block).\nTime: {stamp}\n\n{body}"
        try:
            send_mail(subject, text)
            print(f"[{stamp}] alert sent to {MAIL_TO}: {subject}")
        except Exception as e:
            print(f"[{stamp}] ALERT SEND FAILED: {e}", file=sys.stderr)

    st.update(status=status, last_check=stamp, reasons=reasons)
    save_state(st)
    sys.exit(0 if status == "OK" else 2)


if __name__ == "__main__":
    main()
