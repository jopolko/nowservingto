#!/usr/bin/env python3
"""Earned-target finder - turn AEO head-term gaps into a 'get mentioned here' list.

GEO research consensus: on-page structure gets you RETRIEVED into the consideration
set, but earned third-party corroboration (Reddit, reviews, roundups) is what gets
you PICKED between comparable options. Perplexity leans ~47% on Reddit; ChatGPT
pulls via Bing's index of roundups/reviews. This runs your seed queries through
SearXNG and surfaces the SPECIFIC community + roundup URLs the engines ground on,
ranked by how many of your queries each covers - i.e. where to go get cited.

Run:  .venv-seo/bin/python earned_targets.py --site nowservingto.com [--top 10]
"""
import argparse, re
from collections import defaultdict
from urllib.parse import urlparse
import requests
import seo_pull as sp

COMMUNITY = {"reddit.com", "quora.com", "news.ycombinator.com", "stackexchange.com",
             "medium.com", "substack.com", "facebook.com", "threads.net", "x.com",
             "twitter.com", "tiktok.com", "youtube.com", "instagram.com"}
DIRECTORY = {"yelp.com", "yelp.ca", "tripadvisor.com", "tripadvisor.ca", "opentable.com",
             "opentable.ca", "blogto.com", "narcity.com"}
ROUNDUP_RE = re.compile(r"\b(best|top|new(est)?|where to|guide|\d+\s|must[- ]|ultimate|round[- ]?up|hottest|hot new)\b", re.I)
TYPE_ORDER = {"community": 0, "roundup": 1, "directory": 2, "editorial": 3}


def _domain(u):
    d = urlparse(u).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _base(d):
    return ".".join(d.split(".")[-2:])


def classify(url, title, host):
    d = _domain(url)
    if host and (host in d or d in host):
        return "you"
    if d in COMMUNITY or _base(d) in COMMUNITY:
        return "community"
    if ROUNDUP_RE.search(title or ""):
        return "roundup"
    if d in DIRECTORY or _base(d) in DIRECTORY:
        return "directory"
    return "editorial"


def run(site, top, days):
    secrets = sp.load_secrets()
    sx = (secrets.get("SEARXNG_URL") or "http://127.0.0.1:8888").rstrip("/")
    host = site.replace("https://", "").replace("http://", "").strip("/")
    host = host[4:] if host.startswith("www.") else host
    queries = sp._seed_prompts(host)
    if not queries:
        return {"error": f"no seed file for {host}"}
    targets = defaultdict(lambda: {"queries": set(), "title": "", "type": "", "domain": ""})
    you_in = 0
    for q in queries:
        try:
            res = requests.get(f"{sx}/search", params={"q": q, "format": "json"},
                               timeout=25).json().get("results", [])[:top]
        except Exception:
            continue
        seen_here = set()
        for r in res:
            url, title = r.get("url", ""), r.get("title", "")
            t = classify(url, title, host)
            if t == "you":
                you_in += 1 if host not in seen_here else 0
                seen_here.add(host)
                continue
            key = url.split("?")[0].rstrip("/")
            tgt = targets[key]
            tgt["queries"].add(q)
            tgt["title"] = title[:90]
            tgt["type"] = t
            tgt["domain"] = _domain(url)
    ranked = sorted(targets.items(),
                    key=lambda kv: (-len(kv[1]["queries"]), TYPE_ORDER.get(kv[1]["type"], 9)))
    return {"host": host, "n_queries": len(queries), "you_in": you_in, "ranked": ranked}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="nowservingto.com")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-queries", type=int, default=2, help="only show targets covering >= N queries")
    args = ap.parse_args()
    r = run(args.site, args.top, args.days)
    print(f"\n################  EARNED TARGETS · {r.get('host','')}  ################")
    if "error" in r:
        print("  " + r["error"]); return
    print(f"  {r['n_queries']} seed queries · you already surface in {r['you_in']}")
    print("  Where the engines ground for your category - go get cited/mentioned here.")
    print("  (# = how many of your queries this URL surfaces for)\n")
    for label, typ in [("COMMUNITY (Perplexity leans here ~47%)", "community"),
                       ("ROUNDUPS / 'best of' (get listed)", "roundup"),
                       ("DIRECTORIES / review surfaces", "directory"),
                       ("EDITORIAL / competitor pages (study, don't chase)", "editorial")]:
        rows = [(k, v) for k, v in r["ranked"]
                if v["type"] == typ and len(v["queries"]) >= args.min_queries]
        if not rows:
            continue
        print(f"  == {label} ==")
        for url, v in rows[:12]:
            print(f"    [{len(v['queries'])}q] {url}")
            if v["title"]:
                print(f"          {v['title']}")
        print()


if __name__ == "__main__":
    main()
