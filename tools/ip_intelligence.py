#!/usr/bin/env python3
"""Weekly IP intelligence for the crawler pages.

Parses 7 days of Apache logs, extracts real client IPs (CF-Connecting-IP field),
strips known bot UAs, batch-looks up orgs via ip-api.com, tracks per-IP page
sequences and request timing, then asks Haiku to write a named-IP breakdown
(who is this, what did they do, what does the pattern suggest).

Run weekly from cron:
  0 7 * * 0 python3 /var/www/html/nowservingto/tools/ip_intelligence.py
  5 7 * * 0 python3 /var/www/html/nowservingto/tools/ip_intelligence.py --site jo
Requires ANTHROPIC_API_KEY in /var/secrets/nowservingto.env.
"""
import gzip, json, re, datetime as dt, os, time, calendar, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import sys as _sys
_SITE = 'jo' if '--site' in _sys.argv and _sys.argv[_sys.argv.index('--site') + 1] == 'jo' else 'nsto'

BASE = Path(__file__).resolve().parent.parent
ENV_PATH = Path('/var/secrets/nowservingto.env')
LOG_DIR = Path('/var/log/apache2')
CACHE_DIR = BASE / 'tools' / 'cache'
IPAPI_CACHE_PATH = CACHE_DIR / 'ip_intel_org_cache.json'

SITE_CFG = {
    'nsto': {
        'log_glob': 'nowservingto-access.log*',
        'out_path': CACHE_DIR / 'ip_intel_nsto.json',  # not web-accessible
        'gsc_host': 'https://nowservingto.com/',
    },
    'jo': {
        'log_glob': 'access.log*',
        'out_path': Path('/var/www/html/geo-observatory/ip_intel.json'),
        'gsc_host': 'https://joshuaopolko.com/',
    },
}
GSC_HOST = SITE_CFG[_SITE]['gsc_host']
LOG_GLOB = SITE_CFG[_SITE]['log_glob']
OUT_PATH = SITE_CFG[_SITE]['out_path']

WINDOW_DAYS = 7
IPAPI_BATCH = 100
IPAPI_RATE_DELAY = 1.5
MAX_IPS = 500        # cap for org lookup
TOP_NOTABLE = 15     # IPs to include in named breakdown

# Filter these IPs out entirely (VPS itself, known internal)
EXCLUDE_IPS = {'143.110.236.86'}

LLM_MODEL = 'claude-haiku-4-5-20251001'

MON = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
       'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}

BOT_UA_PATTERNS = re.compile(
    r'bot|crawler|spider|scraper|curl|python|wget|go-http|java/'
    r'|claudebot|gptbot|bingbot|googlebot|bingpreview|yandex|duckduck|'
    r'amazonbot|applebot|bytespider|ccbot|petalbot|semrush|'
    r'mj12bot|ahrefsbot|dotbot|rogerbot|seznambot',
    re.IGNORECASE,
)

# Apache combined log: time field + path + UA + trailing cfip
LOG_RE = re.compile(
    r'\[(\d{2}/\w{3}/\d{4}):(\d{2}:\d{2}:\d{2})[^\]]*\]'
    r'\s+"[A-Z]+ (\S+) HTTP'
    r'[^"]*"[^"]*"[^"]*"([^"]*)"[^"]*"([^"]*)"$'
)

CATEGORY_RULES = [
    (re.compile(r'datacamp|code200|m247|lonconnect|dzcrd|bright\s*data|'
                r'luminati|oxylabs|smartproxy|geosurf|netnut|proxi\.fy|'
                r'infatica|soax|iproyal|proxyrack|shifter', re.I),
     'Rank-tracking / residential proxy', '#e84e3a'),
    (re.compile(r'hetzner|digitalocean|ovh|linode|vultr|scaleway|'
                r'contabo|amazon|google cloud|microsoft azure|tencent cloud|'
                r'cloudflare|fastly|akamai|leaseweb|choopa|path\.net|oracle', re.I),
     'Cloud / VPS scraper', '#f59e0b'),
    (re.compile(r'anthropic|openai|perplexity|cohere|mistral|'
                r'semrush|ahrefs|moz\b|majestic', re.I),
     'AI / SEO crawler (verified)', '#7c3aed'),
    (re.compile(r'bell canada|rogers|telus|videotron|shaw|cogeco|'
                r'comcast|at&t|verizon|spectrum|cox|charter|sympatico|'
                r'virgin media|bt group|deutsche telekom|orange|'
                r'swisscom|telstra|singtel|tata', re.I),
     'Real visitor (residential ISP)', '#10b981'),
]
UNCLASSIFIED_COLOR = '#9ca3af'


def load_env():
    env = {}
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def apache_ts(date_str, time_str):
    """Parse Apache date+time into epoch seconds. Returns None on failure."""
    try:
        d, mon_s, y = date_str.split('/')
        h, m, s = time_str.split(':')
        mon = MON.get(mon_s, 0)
        if not mon:
            return None
        return calendar.timegm((int(y), mon, int(d), int(h), int(m), int(s), 0, 0, 0))
    except Exception:
        return None


def fetch_gsc_pages(env, days=7):
    """Pull top pages by impression from GSC for the past N days.
    Returns list of {page, impressions, clicks, ctr, position} sorted by impressions desc.
    Returns [] on any failure (graceful: IP analysis still runs without it).
    Requires google-auth + google-api-python-client in the active venv.
    """
    try:
        import json as _json
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        raw = env.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
        if not raw:
            return []
        info = _json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=['https://www.googleapis.com/auth/webmasters.readonly'],
        )
        sc = build('searchconsole', 'v1', credentials=creds, cache_discovery=False)

        # Find the matching property (URL-prefix or sc-domain)
        host = GSC_HOST.rstrip('/')
        wanted = {GSC_HOST, host, host.replace('https://', 'sc-domain:')}
        props = [s['siteUrl'] for s in sc.sites().list().execute().get('siteEntry', [])]
        prop = next((p for p in props if p.rstrip('/') in {w.rstrip('/') for w in wanted}), None)
        if not prop:
            print(f'  GSC: no property found for {GSC_HOST} (available: {props[:3]})')
            return []

        end = (dt.date.today() - dt.timedelta(days=2)).isoformat()  # GSC lags ~2d
        start = (dt.date.today() - dt.timedelta(days=days + 2)).isoformat()
        body = {'startDate': start, 'endDate': end, 'dimensions': ['page'],
                'rowLimit': 25, 'dataState': 'all'}
        rows = sc.searchanalytics().query(siteUrl=prop, body=body).execute().get('rows', [])
        return [
            {
                'page': r['keys'][0].replace(GSC_HOST.rstrip('/'), ''),
                'impressions': r.get('impressions', 0),
                'clicks': r.get('clicks', 0),
                'ctr': round(r.get('ctr', 0) * 100, 1),
                'position': round(r.get('position', 0), 1),
            }
            for r in sorted(rows, key=lambda x: x.get('impressions', 0), reverse=True)
        ]
    except Exception as e:
        print(f'  GSC fetch skipped: {e}')
        return []


def parse_logs(window_start):
    """Return (ip_hits, ip_pages, ip_times) for non-bot real-IP requests."""
    ip_hits = Counter()
    ip_pages = defaultdict(Counter)
    ip_times = defaultdict(list)
    cutoff_str = window_start.isoformat()

    for path in sorted(LOG_DIR.glob(LOG_GLOB)):
        opener = gzip.open if path.suffix == '.gz' else open
        try:
            with opener(path, 'rt', errors='ignore') as fh:
                for line in fh:
                    # Quick date pre-filter before full regex
                    dm = re.search(r'\[(\d+)/(\w+)/(\d+):', line)
                    if dm:
                        try:
                            d = dt.date(int(dm.group(3)), MON.get(dm.group(2), 0), int(dm.group(1)))
                            if d < window_start:
                                continue
                        except (ValueError, TypeError):
                            continue

                    m = LOG_RE.search(line)
                    if not m:
                        # fallback: extract from quoted fields
                        quoted = re.findall(r'"([^"]*)"', line)
                        if len(quoted) < 3:
                            continue
                        ua = quoted[-2]
                        cfip = quoted[-1].strip()
                        if BOT_UA_PATTERNS.search(ua):
                            continue
                        if not cfip or cfip in ('-', 'unknown') or not re.match(r'^[\d.a-f:]+$', cfip, re.I):
                            continue
                        if cfip.count('.') < 3 and ':' not in cfip:
                            continue
                        ip_hits[cfip] += 1
                        continue

                    date_s, time_s, page, ua, cfip = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
                    cfip = cfip.strip()

                    if BOT_UA_PATTERNS.search(ua):
                        continue
                    if not cfip or cfip in ('-', 'unknown') or not re.match(r'^[\d.a-f:]+$', cfip, re.I):
                        continue
                    if cfip.count('.') < 3 and ':' not in cfip:
                        continue

                    page = page.split('?', 1)[0]
                    ip_hits[cfip] += 1
                    ip_pages[cfip][page] += 1
                    ts = apache_ts(date_s, time_s)
                    if ts:
                        ip_times[cfip].append(ts)
        except OSError:
            continue
    return ip_hits, ip_pages, ip_times


def load_org_cache():
    try:
        return json.loads(IPAPI_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_org_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    IPAPI_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def lookup_orgs(ips, cache):
    to_fetch = [ip for ip in ips if ip not in cache]
    if not to_fetch:
        return
    for i in range(0, len(to_fetch), IPAPI_BATCH):
        batch = to_fetch[i:i + IPAPI_BATCH]
        payload = json.dumps([{'query': ip, 'fields': 'query,org,isp,country,countryCode'} for ip in batch]).encode()
        try:
            req = urllib.request.Request(
                'http://ip-api.com/batch?fields=query,org,isp,country,countryCode',
                data=payload, headers={'Content-Type': 'application/json'}, method='POST',
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                for r in json.loads(resp.read()):
                    if isinstance(r, dict) and r.get('query'):
                        cache[r['query']] = {
                            'org': r.get('org', ''),
                            'isp': r.get('isp', ''),
                            'country': r.get('country', ''),
                            'cc': r.get('countryCode', ''),
                        }
        except Exception as e:
            print(f'  ip-api batch error (offset {i}): {e}')
        if i + IPAPI_BATCH < len(to_fetch):
            time.sleep(IPAPI_RATE_DELAY)
    save_org_cache(cache)


def classify_ip(ip, cache):
    info = cache.get(ip, {})
    org_str = (info.get('org', '') + ' ' + info.get('isp', '')).lower()
    for pattern, label, color in CATEGORY_RULES:
        if pattern.search(org_str):
            return label, color, info.get('org', '') or info.get('isp', ''), info.get('country', '')
    return 'Unclassified', UNCLASSIFIED_COLOR, info.get('org', '') or info.get('isp', ''), info.get('country', '')


def build_categories(ip_hits, org_cache):
    cat_counts = defaultdict(int)
    cat_colors = {}
    cat_orgs = defaultdict(Counter)
    for ip, hits in ip_hits.items():
        label, color, org, country = classify_ip(ip, org_cache)
        cat_counts[label] += hits
        cat_colors[label] = color
        if org:
            cat_orgs[label][org] += hits
    total = sum(cat_counts.values())
    categories = []
    for _, label, _ in CATEGORY_RULES:
        if label in cat_counts:
            top_orgs = [o for o, _ in cat_orgs[label].most_common(4)]
            categories.append({
                'label': label,
                'count': cat_counts[label],
                'pct': round(cat_counts[label] / total * 100) if total else 0,
                'color': cat_colors.get(label, UNCLASSIFIED_COLOR),
                'orgs': top_orgs,
            })
    if 'Unclassified' in cat_counts:
        top_orgs = [o for o, _ in cat_orgs['Unclassified'].most_common(4)]
        categories.append({
            'label': 'Unclassified',
            'count': cat_counts['Unclassified'],
            'pct': round(cat_counts['Unclassified'] / total * 100) if total else 0,
            'color': UNCLASSIFIED_COLOR,
            'orgs': top_orgs,
        })
    return categories, total


def behavior_pattern(times):
    """Classify request timing into a behavioral label."""
    if len(times) < 2:
        return 'single visit'
    times = sorted(times)
    gaps = [times[i+1] - times[i] for i in range(len(times)-1)]
    min_gap = min(gaps)
    avg_gap = sum(gaps) / len(gaps)
    if min_gap == 0:
        return 'simultaneous parallel fetches (site auditor / mass crawler)'
    if min_gap < 3:
        return 'near-simultaneous fetches (parallel crawler)'
    if avg_gap < 15:
        return 'rapid sequential scraper'
    if avg_gap < 90:
        return 'methodical sequential crawler (~1 page/minute)'
    return 'occasional visitor'


def build_notable_ips(top_ips, ip_pages, ip_times, org_cache):
    """Build named per-IP summary for top IPs with 2+ hits."""
    notable = []
    for ip, hits in sorted(top_ips.items(), key=lambda x: -x[1])[:TOP_NOTABLE]:
        if hits < 2:
            continue
        info = org_cache.get(ip, {})
        org = re.sub(r'^AS\d+\s+', '', info.get('org', '') or info.get('isp', '') or 'unknown')
        country = info.get('country', '')
        pages = ip_pages.get(ip, Counter())
        times = ip_times.get(ip, [])
        top_pages = [p for p, _ in pages.most_common(6)]
        pattern = behavior_pattern(times)
        notable.append({
            'ip': ip,
            'hits': hits,
            'org': org,
            'country': country,
            'topPages': top_pages,
            'pattern': pattern,
        })
    return notable


def llm_narrative(categories, total_ips, notable_ips, gsc_pages, api_key):
    """Ask Haiku for a named-IP breakdown. Uses 'this site', not 'your site'."""
    if not api_key:
        return ''

    ip_lines = '\n'.join(
        f"- {n['ip']} ({n['hits']} hits, {n['org']}, {n['country']}): "
        f"pages={', '.join(n['topPages'][:4]) or 'unknown'}, "
        f"behavior={n['pattern']}"
        for n in notable_ips
    )
    cat_summary = ', '.join(
        f"{c['pct']}% {c['label']} (e.g. {', '.join(c['orgs'][:2]) or 'various'})"
        for c in categories
    )

    gsc_block = ''
    if gsc_pages:
        gsc_lines = '\n'.join(
            f"  {g['page'] or '/'}: {g['impressions']:,} impressions, "
            f"{g['clicks']} clicks, CTR {g['ctr']}%, pos {g['position']}"
            for g in gsc_pages[:15]
        )
        gsc_block = f"\nGSC page performance (last 7 days, by impression):\n{gsc_lines}\n"

    prompt = (
        f"You're writing an IP traffic breakdown for a developer's internal crawler analysis page. "
        f"This site received {total_ips:,} unique non-bot IPs in the past 7 days. "
        f"Overall breakdown: {cat_summary}.\n\n"
        f"Notable IPs (top by hit count, with org and behavior):\n{ip_lines}\n"
        f"{gsc_block}\n"
        f"Write a bullet-point named-IP breakdown. For each notable IP, one bullet: "
        f"start with the IP address in parentheses, then hit count, org, country, "
        f"and a plain-English interpretation of what the behavior suggests "
        f"(content harvester, parallel SEO auditor, legitimate AI crawler, rank tracker, "
        f"real human visitor, etc.). "
        f"Where GSC data is available, cross-reference: if a page has many impressions "
        f"but near-zero clicks, and the IPs fetching it are rank-tracking proxies, "
        f"call that out explicitly (e.g. '/page has 500 impressions, 1 click — "
        f"rank trackers inflating GSC, not real searchers'). "
        f"ALWAYS say 'this site', never 'your site'. "
        f"Be specific. After the per-IP bullets, one short sentence on real human traffic. "
        f"No intro sentence, no headers, no markdown bold."
    )
    try:
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps({
                'model': LLM_MODEL,
                'max_tokens': 500,
                'messages': [{'role': 'user', 'content': prompt}],
            }).encode(),
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return ''.join(b.get('text', '') for b in data.get('content', [])).strip()
    except Exception as e:
        print(f'  LLM narrative error: {e}')
        return ''


def main():
    now = dt.datetime.utcnow()
    window_start = (now - dt.timedelta(days=WINDOW_DAYS)).date()
    print(f'ip_intelligence [{_SITE}]: window {window_start} to {now.date()}')

    env = load_env()
    api_key = env.get('ANTHROPIC_API_KEY', '')

    print('  parsing logs...')
    ip_hits, ip_pages, ip_times = parse_logs(window_start)
    print(f'  {len(ip_hits)} unique non-bot IPs found')

    for ip in EXCLUDE_IPS:
        ip_hits.pop(ip, None)
    top_ips = dict(ip_hits.most_common(MAX_IPS))

    print('  loading org cache...')
    org_cache = load_org_cache()

    uncached = sum(1 for ip in top_ips if ip not in org_cache)
    if uncached:
        print(f'  fetching {uncached} new IP orgs via ip-api.com...')
        lookup_orgs(list(top_ips.keys()), org_cache)

    print('  classifying...')
    categories, total_ips = build_categories(top_ips, org_cache)

    notable_ips = build_notable_ips(top_ips, ip_pages, ip_times, org_cache)
    print(f'  {len(notable_ips)} notable IPs for named breakdown')

    print('  fetching GSC page performance...')
    gsc_pages = fetch_gsc_pages(env, days=WINDOW_DAYS)
    print(f'  {len(gsc_pages)} GSC pages retrieved')

    print('  requesting named-IP breakdown from Haiku...')
    narrative = llm_narrative(categories, total_ips, notable_ips, gsc_pages, api_key)

    out = {
        'generatedAt': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'windowDays': WINDOW_DAYS,
        'totalIPs': total_ips,
        'categories': categories,
        'narrative': narrative,
        'notableIPs': notable_ips,
        'gscPages': gsc_pages,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f'  wrote {OUT_PATH}')
    for c in categories:
        print(f"  {c['pct']:3d}% {c['label']} ({c['count']} hits)")


if __name__ == '__main__':
    main()
