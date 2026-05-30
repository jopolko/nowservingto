#!/usr/bin/env python3
"""
Probe every cached restaurant website URL (from Places + web-verify caches),
record HTTP status, and cache the result. Pages that 4xx/5xx or fail to load
are flagged so inject_openings.py drops the broken `website` field (and the
mapsUrl / no-link fallback takes over).

Cache: tools/cache/url_health_cache.json
   { "<url>": {"status": int|None, "checked_at": iso, "ok": bool, "reason": "..."} }

Re-checks any URL whose last check is older than CHECK_DAYS or that was
previously not OK. Stable OK results are skipped to keep this fast.
"""
import os, re, sys, json, time, socket
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
PLACES_CACHE = ROOT / 'tools' / 'cache' / 'places_cache.json'
WEB_CACHE = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
HEALTH_CACHE = ROOT / 'tools' / 'cache' / 'url_health_cache.json'
SECRETS = Path('/var/secrets/nowservingto.env')

CHECK_DAYS = 1   # daily re-check for OK URLs - was 14, dropped 2026-05-29
                 # after a Netlify-hosted listing went 404 within 13 days
                 # of validation. Small-operator sites churn fast; HEAD
                 # requests cost nothing, so check every cron.
TIMEOUT_SEC = 6
WORKERS = 12
UA = 'Mozilla/5.0 (compatible; nowservingto-healthcheck/1.0)'
MODEL = 'claude-haiku-4-5-20251001'


def normalize_url(url):
    """Canonicalize URLs so that http/https, www./bare-host, and uppercase
    scheme variants all share one cache entry. Without this, an entry
    storing `https://www.x.com/` and the cache storing `https://x.com/`
    would be treated as different URLs and the with-www version would
    never get health-checked. Strips:
      - trailing slash on the bare-domain root path
      - leading `www.` on the host
      - tracking query params (utm_*, fbclid, gclid)
      - the scheme/host case (lowercased)
    Keeps the path + non-tracking query params + fragment as-is."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    try:
        s = urlsplit(url.strip())
    except Exception:
        return url
    scheme = (s.scheme or 'https').lower()
    netloc = s.netloc.lower()
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    path = s.path or '/'
    # Drop tracking params; sort the rest for stability
    keep = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
            if not (k.lower().startswith('utm_') or k.lower() in {'fbclid', 'gclid', 'mc_cid', 'mc_eid'})]
    query = urlencode(sorted(keep)) if keep else ''
    return urlunsplit((scheme, netloc, path, query, s.fragment))

def _load_api_key():
    if not SECRETS.exists(): return None
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None

ANTHROPIC_KEY = _load_api_key()

# Social platforms aggressively rate-limit HEAD probes and don't go silently dead the way
# custom domains do. We trust them and skip the probe entirely.
# Social platforms aggressively 429 our HEAD probes (they hate bots) but the pages
# themselves are live for any human browser. We skip probing these - it's a probe
# bypass, NOT a quality endorsement. The verifier prompt still prefers them LAST,
# below own websites and Google Maps profiles.
SKIP_PROBE_DOMAINS = ('instagram.com', 'facebook.com', 'tiktok.com', 'twitter.com', 'x.com', 'threads.net')

# HTTP codes that mean "the page exists but I'm not letting you probe it." Treat as ok.
SOFT_FAIL_CODES = {401, 403, 405, 429, 451, 503}

# When the HTTP probe succeeds, we still need to know whether the page is the
# legitimate business homepage - or whether the domain has been hijacked/parked
# and is now serving SEO spam (gambling, pharmacy, crypto, "domain for sale", etc).
# We delegate that judgment to Haiku rather than hardcoding token lists, so new
# spam variants don't slip through. ~$0.001 per URL on sync pricing.
SNIFF_BYTES = 32768  # 32 KB is plenty for <title> + visible body text

SITE_REVIEW_PROMPT = """You audit whether a URL serves a legitimate business homepage,
or whether the domain has been hijacked / parked / repurposed as SEO spam.

Reply with exactly one JSON object on ONE line, no prose, no markdown:
{"verdict":"legit|spam|off_topic","reason":"<one short sentence>"}

- "legit": real business homepage in any language - restaurant, shop, services,
  agency, personal portfolio for a chef/owner. Imperfect/unprofessional sites are fine.
- "spam": gambling/casino/slots, online pharmacy, crypto/forex scams, link farms,
  SEO bait, "domain for sale" or "buy this domain" parking. Especially common:
  Indonesian/Russian-language gambling fronts that have nothing to do with the URL's
  apparent purpose.
- "off_topic": clearly a different business at a different address, an unrelated
  personal site, an under-construction placeholder with no business identity.

Be generous with "legit". Reserve "spam"/"off_topic" for clear cases."""

def _strip_html(body_bytes):
    """Best-effort HTML → text without BeautifulSoup.
    Also strips inline CSS rules (@font-face / .class{...}) that website builders
    like Squarespace/Vistaweb dump into the body - without this, the "text" sent
    to the reviewer is dominated by font declarations and the page looks empty."""
    try:
        s = body_bytes.decode('utf-8', errors='replace')
    except Exception:
        return ''
    title_m = re.search(r'<title[^>]*>(.*?)</title>', s, re.IGNORECASE | re.DOTALL)
    title = (title_m.group(1).strip() if title_m else '')[:200]
    s = re.sub(r'<script[^>]*>.*?</script>', ' ', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'<style[^>]*>.*?</style>', ' ', s, flags=re.IGNORECASE | re.DOTALL)
    # Squarespace/Wix/etc. dump huge inline scripts whose closing tag falls past our
    # 32KB read window - strip anything from an unclosed <script>/<style> to end-of-input.
    s = re.sub(r'<script\b[^>]*>.*$', ' ', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'<style\b[^>]*>.*$', ' ', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<')
         .replace('&gt;', '>').replace('&#39;', "'").replace('&quot;', '"'))
    # Strip inline CSS rules that escaped <style> tags. Builder platforms inline
    # rules with complex selectors (attribute selectors, multi-selector commas) that
    # the simple `.class { ... }` pattern doesn't catch - go broader here.
    s = re.sub(r'@[a-z-]+\s+[^;]+;', ' ', s, flags=re.IGNORECASE)  # @charset, @import
    s = re.sub(r'@[a-z-]+[^;{]*\{[^{}]*\}', ' ', s, flags=re.IGNORECASE)  # @font-face, @media (one level)
    s = re.sub(r'[.#:\[][\w\s,.#:\[\]=\-_*>+~()"\']{0,200}?\{[^{}]{0,500}\}', ' ', s)  # broad selector { ... }
    s = re.sub(r'\s+', ' ', s).strip()
    return f"TITLE: {title}\n\nTEXT: {s[:2000]}"

def _body_too_short_to_judge(page_text):
    """SPA shells (Squarespace, Wix, etc.) deliver near-empty initial HTML - actual
    content is JS-hydrated. Can't judge what isn't rendered. Two heuristics:
    1. After stripping CSS/JS, body is too short to contain real content
    2. After stripping, body is mostly symbols (CSS leftovers, JS object literals,
       JSON dumps) - not prose. Either way: default to legit."""
    if 'TEXT:' not in page_text: return True
    body = page_text.split('TEXT:', 1)[1].strip()
    if len(body) < 150: return True
    alpha = sum(1 for c in body if c.isalpha())
    if alpha / len(body) < 0.55: return True
    return False

def review_site(url):
    """Fetch up to SNIFF_BYTES of the URL and ask Haiku whether it's a legit business
    homepage. Returns a reason string if the page is spam/off-topic, else None.
    Any error (fetch, parse, API) returns None - give the URL the benefit of the doubt."""
    if not ANTHROPIC_KEY:
        return None
    try:
        req = Request(url, headers={'User-Agent': UA, 'Range': f'bytes=0-{SNIFF_BYTES}'}, method='GET')
        with urlopen(req, timeout=TIMEOUT_SEC) as r:
            body = r.read(SNIFF_BYTES)
    except Exception:
        return None
    page_text = _strip_html(body)
    if not page_text or _body_too_short_to_judge(page_text):
        return None
    try:
        payload = json.dumps({
            'model': MODEL,
            'max_tokens': 80,
            'system': SITE_REVIEW_PROMPT,
            'messages': [{'role': 'user', 'content': f"URL: {url}\n\n{page_text}"}],
        }).encode('utf-8')
        api = Request('https://api.anthropic.com/v1/messages', data=payload, headers={
            'x-api-key': ANTHROPIC_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }, method='POST')
        with urlopen(api, timeout=30) as r:
            msg = json.loads(r.read())
    except Exception:
        return None
    blocks = [b.get('text', '') for b in msg.get('content', []) if b.get('type') == 'text']
    text = (blocks[-1] if blocks else '').strip()
    for line in text.split('\n'):
        s = line.strip().lstrip('`').strip()
        if s.startswith('{') and s.endswith('}'):
            try:
                d = json.loads(s)
                v = d.get('verdict')
                if v in ('spam', 'off_topic'):
                    return f"{v}: {d.get('reason','')[:160]}"
                return None
            except Exception:
                continue
    return None

def collect_urls():
    urls = set()
    if PLACES_CACHE.exists():
        for v in json.loads(PLACES_CACHE.read_text()).values():
            if v.get('status') == 'ok' and v.get('website'):
                urls.add(v['website'])
    if WEB_CACHE.exists():
        for v in json.loads(WEB_CACHE.read_text()).values():
            if v.get('status') == 'ok' and v.get('website'):
                urls.add(v['website'])
    return urls

def needs_check(entry):
    if not entry: return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(entry['checked_at'])).days
    except Exception:
        return True
    # Re-check broken URLs more aggressively too - maybe they came back
    if not entry.get('ok'): return age >= 3
    return age >= CHECK_DAYS

def _host_of(url):
    """Canonical host for cross-domain comparison.
    Strips `www.` prefix AND explicit default ports (:80 for http, :443
    for https) so `parsgrill.ca` and `parsgrill.ca:443` compare equal -
    redirecting from http://x to https://x:443/ is the same host."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        h = (parsed.netloc or '').lower()
        scheme = (parsed.scheme or 'https').lower()
        # Strip default ports
        if h.endswith(':80') and scheme == 'http':   h = h[:-3]
        if h.endswith(':443') and scheme == 'https': h = h[:-4]
        if h.startswith('www.'): h = h[4:]
        return h
    except Exception:
        return ''

def probe(url):
    """Try HEAD first; some servers refuse, retry GET with range. Treat 200/3xx as OK,
    AND treat known soft-fail codes (429/403/etc.) as OK since they mean the page exists
    but is rate-limiting our probe. Skip social platforms entirely - they always rate-limit.
    Flag cross-domain redirects (e.g. ethioeri.com 301→leonrent.com) as broken - the
    original domain is parked/hijacked and the link is misleading."""
    if any(d in url.lower() for d in SKIP_PROBE_DOMAINS):
        return {'status': None, 'ok': True, 'reason': 'skipped (HEAD probe blocked by site; page assumed live for browser visitors)'}
    origin_host = _host_of(url)
    for method in ('HEAD', 'GET'):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Range': 'bytes=0-0'}, method=method)
            with urlopen(req, timeout=TIMEOUT_SEC) as r:
                code = r.status
                final_host = _host_of(r.geturl())
                if origin_host and final_host and origin_host != final_host:
                    return {'status': code, 'ok': False,
                            'reason': f'cross-domain redirect: {origin_host} → {final_host} (domain hijack/parked)'}
                if 200 <= code < 400:
                    review = review_site(url)
                    if review:
                        return {'status': code, 'ok': False, 'reason': review}
                return {'status': code, 'ok': 200 <= code < 400, 'reason': r.reason}
        except HTTPError as e:
            if e.code in SOFT_FAIL_CODES:
                # rate-limit / soft block - page exists, just won't let us probe it
                return {'status': e.code, 'ok': True, 'reason': f'soft-fail {e.code} (page assumed live)'}
            # 3xx that Python's urlopen raised instead of following (308 in
            # particular - older stdlib doesn't follow it). The redirect
            # target IS the live page; treat the original as alive.
            if 300 <= e.code < 400:
                return {'status': e.code, 'ok': True, 'reason': f'redirect {e.code} (page assumed live)'}
            if method == 'HEAD': continue
            return {'status': e.code, 'ok': False, 'reason': f'HTTP {e.code}'}
        except URLError as e:
            if method == 'HEAD': continue
            reason_str = str(e.reason)
            # URLError-wrapped timeout - soft-OK same as the bare timeout.
            if 'timed out' in reason_str.lower() or isinstance(e.reason, socket.timeout):
                return {'status': None, 'ok': True, 'reason': 'timeout (soft-OK; page assumed live)'}
            return {'status': None, 'ok': False, 'reason': f'URLError: {reason_str[:80]}'}
        except (socket.timeout, TimeoutError):
            if method == 'HEAD': continue
            # Timeout is flaky network state, not a dead site. Mark soft-OK
            # so we don't drop the website link on a transient hiccup -
            # tomorrow's daily re-check will catch a genuinely dead site.
            return {'status': None, 'ok': True, 'reason': 'timeout (soft-OK; page assumed live)'}
        except Exception as e:
            if method == 'HEAD': continue
            return {'status': None, 'ok': False, 'reason': f'{type(e).__name__}: {str(e)[:80]}'}
    return {'status': None, 'ok': False, 'reason': 'unknown'}

def main():
    raw_cache = json.loads(HEALTH_CACHE.read_text()) if HEALTH_CACHE.exists() else {}
    # Migrate any non-normalized cache keys to the canonical form. Newer
    # writes always use normalize_url(); this folds older variants in so
    # we don't double-check www. and bare-host forms of the same URL.
    cache = {}
    for k, v in raw_cache.items():
        cache[normalize_url(k)] = v
    urls = {normalize_url(u) for u in collect_urls()}
    targets = [u for u in urls if needs_check(cache.get(u))]
    print(f"total URLs across caches: {len(urls)}  to probe: {len(targets)}")
    if not targets:
        # Still write back the normalized cache so the migration sticks.
        HEALTH_CACHE.write_text(json.dumps(cache, separators=(',', ':')))
        return

    now_iso = lambda: datetime.now(timezone.utc).isoformat()
    n_ok = n_bad = 0
    t0 = time.time()
    done = 0

    def work(u):
        r = probe(u)
        r['checked_at'] = now_iso()
        return u, r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for fut in as_completed([ex.submit(work, u) for u in targets]):
            try: u, r = fut.result()
            except Exception as e: print(f'  worker err: {e}'); continue
            cache[u] = r
            done += 1
            if r['ok']: n_ok += 1
            else: n_bad += 1
            if done % 50 == 0 or done == len(targets):
                HEALTH_CACHE.write_text(json.dumps(cache, separators=(',', ':')))
                print(f"  [{done:>4}/{len(targets)}]  ok={n_ok} bad={n_bad}  ({time.time()-t0:.0f}s)")

    HEALTH_CACHE.write_text(json.dumps(cache, separators=(',', ':')))
    print(f"\ndone: ok={n_ok}  bad={n_bad}  cache_size={len(cache)}")
    if n_bad:
        print("\nbroken URLs (sample first 15):")
        bad_items = sorted([(u, c) for u, c in cache.items() if not c.get('ok')], key=lambda x: x[1].get('checked_at',''), reverse=True)
        for u, c in bad_items[:15]:
            print(f"  [{c.get('status','-')}]  {c.get('reason','')[:50]:50s}  {u[:80]}")

if __name__ == '__main__':
    main()
