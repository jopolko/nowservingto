#!/usr/bin/env python3
"""Citation efficiency - do your AI citations reach humans, or are they fan-out?

The hard GEO truth (documented: a page with 1,000+ AI citations and ~0 human
impressions): AI-crawler reads measure that the model FETCHED you, not that a
human saw, clicked, or bought. This joins two sources we own - AI-crawler reads
per page (Apache logs) and human clicks/impressions per page (GSC) - and sorts
every page into a 2x2 so you can see which "citations" actually convert to humans.

  AI-read heavy + human clicks   -> TRUE WINNER (extracted AND reaching people)
  AI-read heavy + ~0 human clicks-> FAN-OUT ONLY (model uses you; humans don't arrive)
  low AI reads + human clicks    -> CLASSIC SEO (humans via search, AI ignores)
  low both                       -> DORMANT

Run on the VPS (GSC OAuth + /var/log/apache2):
  .venv/bin/python cite_efficiency.py --site joshuaopolko.com --days 90
"""
import argparse, datetime as dt, re
import seo_pull as sp
import crawl_insight as ci

# Infra/non-content paths - never real "pages", exclude from the analysis.
EXCLUDE = re.compile(
    r"(robots\.txt|sitemap|favicon|\.ico$|\.xml$|\.txt$|/feed/?$|wp-json|wp-content|"
    r"wp-includes|/security/?$|\.well-known|oembed|/data/|/js/|/css/|\.json$)", re.I)


def gsc_pages(site, days):
    sp.SITE = sp._norm(site)
    sc = sp.gsc_client()
    props = [s["siteUrl"] for s in sc.sites().list().execute().get("siteEntry", [])]
    prop = sp._match_property(props, sp.SITE)
    if not prop:
        return None, None
    start, end = sp.daterange(days)
    rows = sp.gsc_query(sc, prop, start, end, ["page"], row_limit=1000)
    return {r["keys"][0]: r for r in rows}, f"{start}..{end}"


def _path(url, site):
    return (url.split(site, 1)[-1] if site in url else url) or "/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="joshuaopolko.com")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--read-hi", type=int, default=15, help="AI reads >= this = 'heavy' (14d)")
    ap.add_argument("--clicks-lo", type=int, default=2, help="clicks <= this = 'humans not arriving'")
    args = ap.parse_args()

    pages, window = gsc_pages(args.site, args.days)
    if pages is None:
        print(f"no GSC access to {args.site}"); return
    reads = dict(ci.parse_site(ci.SITE_LOG_PREFIX.get(args.site, ""), dt.date.today(), days=14)["paths"]) \
        if ci.SITE_LOG_PREFIX.get(args.site) else {}

    # union of paths seen in either source
    paths = set(_path(u, args.site) for u in pages)
    paths |= set(reads)
    paths = {p for p in paths if not EXCLUDE.search(p)}  # content pages only
    rows = []
    for p in paths:
        url = f"https://{args.site}{p}"
        g = pages.get(url) or pages.get(url + "/") or pages.get(url.rstrip("/")) or {}
        clicks = g.get("clicks", 0)
        impr = g.get("impressions", 0)
        ar = reads.get(p) or reads.get(p.rstrip("/")) or reads.get(p + "/") or 0
        rows.append({"path": p, "ai": ar, "clk": clicks, "impr": impr})

    hi, lo = args.read_hi, args.clicks_lo
    buckets = {"FAN-OUT ONLY": [], "TRUE WINNER": [], "CLASSIC SEO": [], "DORMANT": []}
    for r in rows:
        heavy = r["ai"] >= hi
        human = r["clk"] > lo
        key = ("TRUE WINNER" if heavy and human else "FAN-OUT ONLY" if heavy else
               "CLASSIC SEO" if human else "DORMANT")
        buckets[key].append(r)

    print(f"\n################  CITATION EFFICIENCY · {args.site} · {window}  ################")
    print(f"  AI reads = 14d access log · clicks/impr = GSC {window} · heavy>={hi} reads, humans>{lo} clicks\n")
    for name in ["FAN-OUT ONLY", "TRUE WINNER", "CLASSIC SEO"]:
        b = sorted(buckets[name], key=lambda x: -x["ai"])
        tag = {"FAN-OUT ONLY": "(model loves you, humans don't arrive - is it worth the crawl?)",
               "TRUE WINNER": "(extracted AND clicked - protect/expand these)",
               "CLASSIC SEO": "(humans find you, AI ignores - add stats/quotes/answer-first)"}[name]
        print(f"  == {name} == {tag}")
        print(f"  {'AIrd':>5} {'clk':>4} {'impr':>6}  path")
        for r in b[:12]:
            print(f"  {r['ai']:5d} {r['clk']:4d} {r['impr']:6d}  {r['path']}")
        if not b:
            print("    (none)")
        print()
    print(f"  DORMANT (low AI + low human): {len(buckets['DORMANT'])} pages - prune/rewrite candidates.")


if __name__ == "__main__":
    main()
