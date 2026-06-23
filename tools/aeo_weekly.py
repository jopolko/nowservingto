#!/usr/bin/env python3
"""Weekly AEO citation-map snapshot + emailed report.

Runs seo_pull.report_aeo() for every site in seo_pull.SITES_ALL (driven by the
per-site seed files), writes a timestamped JSON + text snapshot under
tools/logs/aeo/, diffs against the previous snapshot, and emails the report so
it lands in front of a human. Pure stdlib + seo_pull — no Claude tokens, no
paid API; the only network call is the local SearXNG instance.

Cron (on the VPS, john's crontab), weekly alongside the digest:
  30 14 * * 0  /var/www/html/nowservingto/.venv/bin/python \\
      /var/www/html/nowservingto/tools/aeo_weekly.py \\
      >> /var/www/html/nowservingto/tools/logs/aeo-cron-$(date +\\%Y\\%m\\%d).log 2>&1

  --no-email   just write the snapshot + print the report (used for the first
               manual run / dry runs)
"""
import argparse, json, smtplib, datetime as dt
from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import seo_pull as sp
import crawl_insight as ci
import saas_opportunity_scan as sos

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE / "logs" / "aeo"
RECIPIENT = "mjopolko@gmail.com"
ENV = sp.load_secrets()
SMTP_HOST = ENV.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(ENV.get("SMTP_PORT", "25"))
MAIL_FROM_ADDR = ENV.get("MAIL_FROM_ADDR", "alerts@nowservingto.com")
MAIL_FROM_NAME = ENV.get("MAIL_FROM_NAME", "NowServingTO")


def run_all(today):
    """Per site: real AI-crawler activity from the access log (ground truth),
    the seed-driven AEO map, and GSC discovery suggestions."""
    aeo, sug, crawl = {}, {}, {}
    for site in sp.SITES_ALL:
        sp.SITE = sp._norm(site)
        aeo[site] = sp.report_aeo(ENV)
        sug[site] = sp.suggest_from_gsc(ENV)
        prefix = ci.SITE_LOG_PREFIX.get(site)
        crawl[site] = ci.signals(ci.parse_site(prefix, today)) if prefix else None
    return aeo, sug, crawl


def _prev_snapshot():
    """Most recent prior snapshot JSON, or None."""
    if not SNAP_DIR.exists():
        return None
    snaps = sorted(SNAP_DIR.glob("aeo-*.json"))
    if not snaps:
        return None
    try:
        return json.loads(snaps[-1].read_text())
    except Exception:
        return None


def _delta(site, cur, prev):
    """One-line movement note vs last snapshot for this site."""
    if not prev or site not in prev or "you_in" not in (prev.get(site) or {}):
        return "no prior snapshot"
    p, c = prev[site], cur
    if "you_in" not in c:
        return "no data this run"
    d = c["you_in"] - p["you_in"]
    arrow = "no change" if d == 0 else (f"+{d}" if d > 0 else str(d))
    cur_dom = {x[0] for x in c.get("top_domains", [])}
    prev_dom = {x[0] for x in p.get("top_domains", [])}
    new = cur_dom - prev_dom
    note = f"YOU {p['you_in']}/{p['prompts']} -> {c['you_in']}/{c['prompts']} ({arrow})"
    if new:
        note += f"; new competitor domains: {', '.join(sorted(new))[:120]}"
    return note


def render(results, suggestions, crawl, prev, today):
    lines = [f"GEO weekly - {today}", "=" * 52,
             "Ground truth from the access log first; the SearXNG head-term proxy is",
             "context, not a scoreboard (you have ~1,800 real Bing-WMT citations).", ""]
    api_key = ENV.get("ANTHROPIC_API_KEY", "")
    for site, a in results.items():
        sg = suggestions.get(site, {})
        sig = crawl.get(site)
        lines.append(f"################  {site}  ################")
        # 1) REAL crawler traction (lead)
        if sig:
            lines.append(ci.render_crawl(site, sig))
            # 2) Options to consider (the point of the report)
            lines.append("")
            lines.append("  OPTIONS TO CONSIDER (gaps you can fill):")
            lines.append(ci.options(site, sig, a, sg, api_key))
        lines.append("")
        # 3) Supporting detail: head-term proxy + GSC demand
        lines.append("  -- supporting detail --")
        if "error" in a:
            lines.append(f"  head-term proxy: ERROR {a['error']}")
        else:
            lines.append(f"  head-term proxy (SearXNG): you in {a['you_in']}/{a['prompts']} "
                         f"({_delta(site, a, prev)}); top owners: " +
                         ", ".join(d for d, _ in a["top_domains"][:5]))
        if isinstance(sg, dict) and sg.get("suggestions"):
            top = "; ".join(f"{q['query']} ({q['impr']}imp)" for q in sg["suggestions"][:6])
            lines.append(f"  GSC demand not in seed: {top}")
        elif isinstance(sg, dict) and "error" in sg:
            lines.append(f"  GSC: {sg['error']}")
        lines.append("")
    # SaaS-opportunity scan: Reddit wish/pain x what AI assistants already fetch.
    # Framed honestly (see r/microsaas critique): loud posters rarely buy, so this
    # is leads-to-CHASE, not ideas-to-build. The cross with AI-read demand is the
    # built-in "why not just ChatGPT?" filter: if assistants keep fetching jo to
    # answer a query, the model alone wasn't enough = a real data/reliability gap.
    lines.append("############  SAAS OPPORTUNITIES (where to LOOK, not validated ideas)  ############")
    lines.append("  Reddit wish/pain x topics AI assistants already fetch from jo. Loud posters")
    lines.append("  rarely pay: treat as leads to CHASE (go talk to them), not ideas to build.")
    lines.append("  Filter each by: why wouldn't they just use ChatGPT? (needs private/fresh data,")
    lines.append("  regulated info, or must run reliably on its own). Your unfair edge = AI-citation reach.")
    try:
        lines.append(sos.render_report(sos.scan()))
    except Exception as e:
        lines.append(f"  scan failed: {str(e)[:70]}")
    lines.append("")
    lines.append("Logs: /var/log/apache2 (7d) · also at nowservingto.com/usage")
    lines.append("Snapshot history: tools/logs/aeo/ · seeds: tools/aeo_seeds/<host>.txt")
    return "\n".join(lines)


def save_snapshot(results, today):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"aeo-{today}.json").write_text(json.dumps(results, indent=2))


def email_report(text, today):
    msg = EmailMessage()
    msg["From"] = formataddr((MAIL_FROM_NAME, MAIL_FROM_ADDR))
    msg["To"] = RECIPIENT
    msg["Subject"] = f"GEO weekly - crawler intel + options - {today}"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain="nowservingto.com")
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.send_message(msg, from_addr=MAIL_FROM_ADDR, to_addrs=[RECIPIENT])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true", help="write snapshot + print only")
    args = ap.parse_args()
    today_d = dt.date.today()
    today = today_d.isoformat()
    prev = _prev_snapshot()
    results, suggestions, crawl = run_all(today_d)
    text = render(results, suggestions, crawl, prev, today)
    save_snapshot(results, today)  # snapshot stays AEO-only for clean week-over-week diffs
    print(text)
    if not args.no_email:
        try:
            email_report(text, today)
            print(f"\n[emailed to {RECIPIENT}]")
        except Exception as e:
            print(f"\n[email failed: {e}]")


if __name__ == "__main__":
    main()
