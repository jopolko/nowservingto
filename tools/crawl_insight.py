#!/usr/bin/env python3
"""Apache-log AI-crawler intelligence for the weekly AEO report.

Parses /var/log/apache2 for the trailing 7 days (vs the prior 7 for deltas),
per site: which AI/LLM engines crawled and how much, what content they read
most, and where they wasted budget on 404s. Then asks an LLM to turn the
combined signals (crawl + AEO head-term gaps + GSC demand) into concrete
"options to consider" — fillable gaps, not raw numbers.

Ground truth, not proxy: this reads the same access log nowservingto.com/usage
trusts. Used by aeo_weekly.py. Stdlib + requests only.
"""
import gzip, json, re, datetime as dt
from collections import Counter
from pathlib import Path

LOG_DIR = Path("/var/log/apache2")
# site -> access-log filename prefix (rotations/.gz are globbed)
SITE_LOG_PREFIX = {
    "joshuaopolko.com": "access.log",
    "nowservingto.com": "nowservingto-access.log",
}
# site -> local sitemap path on the VPS (read on the origin to avoid the
# Cloudflare 403 a default fetch gets; HTTP fallback handles dev runs).
SITE_SITEMAP = {
    "joshuaopolko.com": Path("/var/www/html/sitemap.xml"),
    "nowservingto.com": Path("/var/www/html/nowservingto/sitemap.xml"),
}
INSIGHT_MODEL = "claude-sonnet-4-6"  # weekly, 2 sites — pennies; quality over cost

# ua-substring -> (operator, display, is_ai). Search engines kept as context.
CRAWLERS = {
    "claudebot": ("Anthropic", "ClaudeBot", True),
    "claude-user": ("Anthropic", "Claude-User", True),
    "claude-web": ("Anthropic", "Claude-Web", True),
    "anthropic-ai": ("Anthropic", "anthropic-ai", True),
    "gptbot": ("OpenAI", "GPTBot", True),
    "oai-searchbot": ("OpenAI", "OAI-SearchBot", True),
    "chatgpt-user": ("OpenAI", "ChatGPT-User", True),
    "perplexitybot": ("Perplexity", "PerplexityBot", True),
    "perplexity-user": ("Perplexity", "Perplexity-User", True),
    "google-extended": ("Google-Extended", "Google-Extended", True),
    "ccbot": ("CommonCrawl", "CCBot", True),
    "bytespider": ("ByteDance", "Bytespider", True),
    "meta-externalagent": ("Meta", "Meta-ExternalAgent", True),
    "duckassistbot": ("DuckDuckGo", "DuckAssistBot", True),
    "youbot": ("You.com", "YouBot", True),
    "mistralai-user": ("Mistral", "MistralAI-User", True),
    "cohere-ai": ("Cohere", "cohere-ai", True),
    "amazonbot": ("Amazon", "Amazonbot", True),
    "applebot-extended": ("Apple", "Applebot-Extended", True),
    "bingbot": ("Bing", "Bingbot", False),
    "googlebot": ("Google", "Googlebot", False),
    "applebot": ("Apple", "Applebot", False),
}
LINE = re.compile(
    r'\[([^\]]+)\]\s+"(?:\S+)\s+(\S+)[^"]*"\s+(\d{3})\s+\S+\s+"[^"]*"\s+"([^"]*)"')


def _match(ua):
    u = ua.lower()
    for tok, meta in CRAWLERS.items():
        if tok in u:
            return meta
    return None


def parse_site(prefix, today, days=7):
    cut = today - dt.timedelta(days=days)
    prev_cut = today - dt.timedelta(days=2 * days)
    cur, prev = Counter(), Counter()          # by display label
    op_cur, op_prev = Counter(), Counter()    # AI operators only
    paths, notfound = Counter(), Counter()    # AI 200s / AI 404s
    for f in sorted(LOG_DIR.glob(prefix + "*")):
        op = gzip.open if f.suffix == ".gz" else open
        try:
            with op(f, "rt", errors="ignore") as fh:
                for line in fh:
                    m = LINE.search(line)
                    if not m:
                        continue
                    meta = _match(m.group(4))
                    if not meta:
                        continue
                    operator, disp, is_ai = meta
                    try:
                        d = dt.datetime.strptime(m.group(1).split()[0],
                                                 "%d/%b/%Y:%H:%M:%S").date()
                    except ValueError:
                        continue
                    path, status = m.group(2).split("?")[0], m.group(3)
                    if d > cut:
                        cur[disp] += 1
                        if is_ai:
                            op_cur[operator] += 1
                            (paths if status == "200" else
                             notfound if status == "404" else Counter())[path] += 1
                    elif d > prev_cut:
                        prev[disp] += 1
                        if is_ai:
                            op_prev[operator] += 1
        except OSError:
            continue
    return {"cur": cur, "prev": prev, "op_cur": op_cur, "op_prev": op_prev,
            "paths": paths, "notfound": notfound}


def _pct(now, was):
    if not was:
        return "new" if now else "-"
    return f"{round((now - was) / was * 100):+d}%"


def signals(crawl):
    """Compact, LLM- and human-friendly summary of one site's crawl week."""
    op = crawl["op_cur"]
    ai_total = sum(op.values())
    operators = [{"operator": o, "hits": n, "delta": _pct(n, crawl["op_prev"].get(o, 0))}
                 for o, n in op.most_common()]
    search = {d: c for d, c in crawl["cur"].items()
              if not CRAWLERS.get(next((t for t in CRAWLERS if t in d.lower()), ""),
                                  (0, 0, True))[2]}
    return {
        "ai_total_7d": ai_total,
        "by_operator": operators,
        "search_context": dict(Counter(
            {CRAWLERS[t][1]: c for d, c in crawl["cur"].items()
             for t in CRAWLERS if t in d.lower() and not CRAWLERS[t][2]}).most_common(4)),
        "top_paths_ai": crawl["paths"].most_common(8),
        "ai_404s": crawl["notfound"].most_common(8),
    }


def render_crawl(site, sig):
    L = [f"  AI crawlers - last 7d (vs prior 7d):"]
    if not sig["by_operator"]:
        L.append("      (no AI-crawler hits parsed this window)")
    for o in sig["by_operator"]:
        L.append(f"      {o['operator']:16s} {o['hits']:5d}  ({o['delta']})")
    if sig["search_context"]:
        ctx = ", ".join(f"{k} {v}" for k, v in sig["search_context"].items())
        L.append(f"      . search context: {ctx}")
    if sig["top_paths_ai"]:
        L.append("  What AI crawlers read most:")
        for p, n in sig["top_paths_ai"][:6]:
            L.append(f"      {n:4d}  {p}")
    if sig["ai_404s"]:
        L.append("  WASTED budget - AI bots hitting 404s (fix/redirect these):")
        for p, n in sig["ai_404s"][:6]:
            L.append(f"      {n:4d}  {p}")
    return "\n".join(L)


def options(site, sig, aeo, sug, api_key):
    """LLM 'options to consider'. Falls back to deterministic notes on failure."""
    if api_key:
        try:
            return _llm_options(site, sig, aeo, sug, api_key)
        except Exception as e:
            return _fallback_options(sig) + f"\n  (LLM insight unavailable: {str(e)[:60]})"
    return _fallback_options(sig)


def _existing_paths(site):
    """Paths already published on `site`, pulled from its sitemap. Gives the LLM
    ground truth so it can tell 'optimize an existing page' apart from 'write a
    new one' instead of recommending content the site already has. Reads the
    local sitemap on the VPS first (the live URL 403s behind Cloudflare), falls
    back to HTTP for dev. Best-effort: returns [] on any failure."""
    try:
        smf = SITE_SITEMAP.get(site)
        if smf and smf.exists():
            xml = smf.read_text(errors="replace")
        else:
            import requests
            r = requests.get(f"https://{site}/sitemap.xml", timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 (aeo-weekly)"})
            r.raise_for_status()
            xml = r.text
        paths = set()
        for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml):
            m = re.match(rf"https?://{re.escape(site)}(/[^?#]*)", loc.strip())
            if m and m.group(1) not in ("", "/"):
                paths.add(m.group(1))
        return sorted(paths)
    except Exception:
        return []


def _llm_options(site, sig, aeo, sug, api_key):
    import requests
    gaps = [p["q"] for p in (aeo.get("per") or []) if not p.get("you")] if isinstance(aeo, dict) else []
    blob = {
        "site": site,
        "ai_crawlers_7d": sig["by_operator"],
        "search_context": sig["search_context"],
        "top_paths_ai_read": sig["top_paths_ai"],
        "ai_crawler_404s": sig["ai_404s"],
        "head_term_gaps_in_web_search": gaps,
        "gsc_real_demand_not_in_seed": [s["query"] for s in (sug.get("suggestions") or [])[:8]]
        if isinstance(sug, dict) else [],
        "your_existing_pages": _existing_paths(site),
    }
    prompt = (
        "You are a sharp GEO/SEO analyst writing one section of a weekly report for the "
        "operator of " + site + ", an EXPERIENCED practitioner (~1,800 AI citations). Do NOT "
        "explain GEO basics or congratulate.\n\n"
        "DURABLE-EDGE LENS (apply strictly): only surface gaps this indie site can actually win "
        "AND hold. PRIORITIZE queries/pages where the edge is specificity, first-hand experience, "
        "or original/proprietary data (hands-on self-hosting fixes, unique datasets, lived "
        "detail). EXPLICITLY SKIP and never suggest chasing: breaking/hot AI-product news, "
        "'is X down / not working' reactive pages, or any topic owned by far bigger sites "
        "(official docs, major media). Those rank briefly, get ~0 clicks, aren't durably citable, "
        "and dilute domain quality. If a GSC/head-term gap is one of those traps, name it as a "
        "trap-to-skip in one line and move on.\n\n"
        "GROUND-TRUTH AGAINST EXISTING PAGES (critical, do this before every suggestion): "
        "`your_existing_pages` lists the paths already published on this site. A head-term or GSC "
        "'gap' means the site does NOT rank for that query or it is not in the seed file; it does "
        "NOT mean the page is missing. For each query you act on, check whether an existing page "
        "already covers it (match the topic against the slugs). If one does, the action is to "
        "OPTIMIZE or EXPAND that page (name its exact path), never to 'write' or 'create' it. Only "
        "recommend creating a NEW page when no existing page covers the query. Never tell the "
        "operator to write something they have already published.\n\n"
        "Write 3-5 specific 'options to consider' - each a concrete, fillable gap with the action "
        "and the why, tied to a number in the data. Also flag: AI 404s wasting crawl budget; an "
        "AI engine crawling thin vs peers; high-value pages AI bots aren't reading. Terse and "
        "concrete. Plain text, one '- ' bullet per option, no preamble, no markdown headers."
        "\n\nDATA:\n" + json.dumps(blob, indent=1))
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": INSIGHT_MODEL, "max_tokens": 700,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
    return "\n".join("  " + ln if ln.strip() else ln for ln in text.splitlines())


def _fallback_options(sig):
    out = []
    if sig["ai_404s"]:
        n = sum(c for _, c in sig["ai_404s"])
        out.append(f"  - Fix {n} AI-crawler 404s (top: {sig['ai_404s'][0][0]}) - wasted crawl budget.")
    ops = {o["operator"]: o["hits"] for o in sig["by_operator"]}
    if ops.get("Anthropic") and not ops.get("Perplexity"):
        out.append("  - Perplexity isn't crawling while Claude is - chase a Perplexity-cited source link.")
    if ops.get("Google-Extended", 0) < 10:
        out.append("  - Google-Extended crawl is thin - Gemini/AI-Overview grounding may lag.")
    return "\n".join(out) or "  - No mechanical gaps flagged this week."
