#!/usr/bin/env python3
"""Prune audit - find pages that rank but earn nothing.

The pattern Josh flagged: thin/reactive pages on topics bigger sites own get
impressions, ~0 clicks, no durable citation, and quietly drag domain quality.
This pulls GSC page-level data (impressions/clicks/CTR/position) and cross-
references whether AI crawlers even bother reading each page, then flags the
zero-click-high-impression set as prune/rewrite candidates.

Run on the VPS (needs GSC OAuth + /var/log/apache2):
  .venv/bin/python prune_audit.py --site joshuaopolko.com --days 90
Flags pages with impressions >= --min-impr and CTR <= --max-ctr (%).
"""
import argparse, datetime as dt
import seo_pull as sp
import crawl_insight as ci


def gsc_pages(site, days):
    sp.SITE = sp._norm(site)
    sc = sp.gsc_client()
    props = [s["siteUrl"] for s in sc.sites().list().execute().get("siteEntry", [])]
    prop = sp._match_property(props, sp.SITE)
    if not prop:
        return None
    start, end = sp.daterange(days)
    return sp.gsc_query(sc, prop, start, end, ["page"], row_limit=1000), f"{start}..{end}"


def ai_reads(site, today, days=14):
    prefix = ci.SITE_LOG_PREFIX.get(site)
    if not prefix:
        return {}
    return dict(ci.parse_site(prefix, today, days=days)["paths"])


def _path(url, site):
    p = url.split(site, 1)[-1] if site in url else url
    return p or "/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="joshuaopolko.com")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-impr", type=int, default=30)
    ap.add_argument("--max-ctr", type=float, default=0.5, help="percent")
    args = ap.parse_args()

    host = args.site
    res = gsc_pages(host, args.days)
    if res is None:
        print(f"no GSC access to {host}"); return
    rows, window = res
    reads = ai_reads(host, dt.date.today())

    flagged = []
    for r in rows:
        impr, clk = r["impressions"], r["clicks"]
        ctr = (clk / impr * 100) if impr else 0
        if impr >= args.min_impr and ctr <= args.max_ctr:
            path = _path(r["keys"][0], host)
            ar = reads.get(path) or reads.get(path.rstrip("/")) or reads.get(path + "/") or 0
            flagged.append({"path": path, "impr": impr, "clicks": clk, "ctr": round(ctr, 2),
                            "pos": round(r["position"], 1), "ai_reads": ar})
    flagged.sort(key=lambda x: -x["impr"])

    print(f"\n################  PRUNE AUDIT · {host} · {window}  ################")
    print(f"  pages ranking but earning ~nothing (impr>={args.min_impr}, CTR<={args.max_ctr}%):")
    print(f"  {'impr':>6} {'clk':>4} {'ctr%':>5} {'pos':>5} {'AIrd':>5}  path")
    for f in flagged:
        print(f"  {f['impr']:6d} {f['clicks']:4d} {f['ctr']:5.2f} {f['pos']:5.1f} {f['ai_reads']:5d}  {f['path']}")
    print(f"\n  {len(flagged)} candidates. High impr + 0 clicks + low AI reads + topic big "
          "sites own = prune (410) or rewrite to a durable-edge angle. High AI reads despite "
          "0 clicks may still be earning citations - check before cutting.")


if __name__ == "__main__":
    main()
