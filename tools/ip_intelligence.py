#!/usr/bin/env python3
"""Weekly IP intelligence for the NowServingTO crawlers page.

Parses 7 days of Apache logs, extracts real client IPs (CF-Connecting-IP field,
post-2026-05-27 logs), strips known bot IPs, batch-looks them up via ip-api.com,
classifies by org pattern, then asks Claude Haiku to write a one-paragraph
narrative. Writes data/ip_intel.json for the crawlers page to render.

Run weekly from cron:
  0 7 * * 0 python3 /var/www/html/nowservingto/tools/ip_intelligence.py
Requires ANTHROPIC_API_KEY in /var/secrets/nowservingto.env.
"""
import gzip, json, re, datetime as dt, os, time, urllib.request, urllib.error
from collections import Counter, defaultdict
from pathlib import Path

import sys as _sys
_SITE = 'jo' if '--site' in _sys.argv and _sys.argv[_sys.argv.index('--site') + 1] == 'jo' else 'nsto'

BASE = Path(__file__).resolve().parent.parent
ENV_PATH = Path('/var/secrets/nowservingto.env')
LOG_DIR = Path('/var/log/apache2')
CACHE_DIR = BASE / 'tools' / 'cache'
IPAPI_CACHE_PATH = CACHE_DIR / 'ip_intel_org_cache.json'  # shared cache across both sites

SITE_CFG = {
    'nsto': {
        'log_glob': 'nowservingto-access.log*',
        'out_path': CACHE_DIR / 'ip_intel_nsto.json',  # tools/cache/ - not web-accessible
    },
    'jo': {
        'log_glob': 'access.log*',
        'out_path': Path('/var/www/html/geo-observatory/ip_intel.json'),
    },
}
LOG_GLOB = SITE_CFG[_SITE]['log_glob']
OUT_PATH = SITE_CFG[_SITE]['out_path']

WINDOW_DAYS = 7
IPAPI_BATCH = 100       # ip-api.com free plan: up to 100 per batch request
IPAPI_RATE_DELAY = 1.5  # seconds between batches (free plan: 45 req/min)
MAX_IPS = 500           # cap to keep runtime sane

# Haiku: cheap enough for weekly editorial, good enough for one paragraph
LLM_MODEL = 'claude-haiku-4-5-20251001'

# UA substrings that mark known bots - skip these IPs for "real visitor" analysis
BOT_UA_PATTERNS = re.compile(
    r'bot|crawler|spider|scraper|curl|python|wget|go-http|java|'
    r'claudebot|gptbot|bingbot|googlebot|bingpreview|yandex|duckduck|'
    r'amazonbot|applebot|bytespider|ccbot|petalbot|semrush|'
    r'mj12bot|ahrefsbot|dotbot|rogerbot|seznambot',
    re.IGNORECASE,
)

# Apache log line: capture CF-Connecting-IP from the last quoted field if present
# Format: ... "ua-string" "real-ip-or-empty"
LINE_RE = re.compile(
    r'"([^"]*?)"(?:\s+"([^"]*)")?$'
)
# Simpler: grab trailing quoted IP field
CFIP_RE = re.compile(r'"([\d\.a-f:]{7,})"$')

# org-pattern -> category label + color
CATEGORY_RULES = [
    (re.compile(r'datacamp|code200|m247|lonconnect|dzcrd|bright\s*data|'
                r'luminati|oxylabs|smartproxy|geosurf|netnut|proxi\.fy|'
                r'infatica|soax|iproyal|proxyrack|shifter',
                re.I),
     'Rank-tracking / residential proxy', '#e84e3a'),
    (re.compile(r'hetzner|digitalocean|ovh|linode|vultr|scaleway|'
                r'contabo|amazon|google cloud|microsoft azure|'
                r'cloudflare|fastly|akamai|leaseweb|choopa|path\.net',
                re.I),
     'Cloud / VPS scraper', '#f59e0b'),
    (re.compile(r'anthropic|openai|perplexity|cohere|mistral|'
                r'semrush|ahrefs|moz\b|majestic',
                re.I),
     'AI / SEO crawler (verified)', '#7c3aed'),
    (re.compile(r'bell canada|rogers|telus|videotron|shaw|cogeco|'
                r'comcast|at&t|verizon|spectrum|cox|charter|'
                r'virgin media|bt group|deutsche telekom|orange|'
                r'swisscom|telstra|singtel|tata',
                re.I),
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


def parse_logs(window_start):
    """Return Counter of real-IP -> hit count for non-bot requests."""
    ip_hits = Counter()
    for path in sorted(LOG_DIR.glob(LOG_GLOB)):
        opener = gzip.open if path.suffix == '.gz' else open
        try:
            with opener(path, 'rt', errors='ignore') as fh:
                for line in fh:
                    # Quick date check: skip lines older than window
                    dm = re.search(r'\[(\d+/\w+/\d+):', line)
                    if dm:
                        try:
                            d = dt.datetime.strptime(dm.group(1), '%d/%b/%Y').date()
                        except ValueError:
                            continue
                        if d < window_start:
                            continue

                    # Extract UA and real IP from combined log format
                    # The last two quoted fields are: "ua" "cf-ip"
                    quoted = re.findall(r'"([^"]*)"', line)
                    if len(quoted) < 3:
                        continue
                    ua = quoted[-2] if len(quoted) >= 2 else ''
                    cfip = quoted[-1] if quoted else ''

                    # Skip if UA looks like a bot
                    if BOT_UA_PATTERNS.search(ua):
                        continue

                    # cfip is the real client IP when non-empty and valid
                    ip = cfip.strip()
                    if not ip or ip in ('-', 'unknown', ''):
                        continue
                    # Validate: must look like an IPv4 or IPv6 address
                    if not re.match(r'^[\d\.a-f:]+$', ip, re.I):
                        continue
                    if ip.count('.') < 3 and ':' not in ip:
                        continue

                    ip_hits[ip] += 1
        except OSError:
            continue
    return ip_hits


def load_org_cache():
    try:
        return json.loads(IPAPI_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_org_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    IPAPI_CACHE_PATH.write_text(json.dumps(cache, indent=2))


def lookup_orgs(ips, cache):
    """Batch-lookup orgs for IPs not already in cache. Updates cache in place."""
    to_fetch = [ip for ip in ips if ip not in cache]
    if not to_fetch:
        return

    for i in range(0, len(to_fetch), IPAPI_BATCH):
        batch = to_fetch[i:i + IPAPI_BATCH]
        payload = json.dumps([{'query': ip, 'fields': 'query,org,isp,country'} for ip in batch]).encode()
        try:
            req = urllib.request.Request(
                'http://ip-api.com/batch?fields=query,org,isp,country',
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                results = json.loads(resp.read())
            for r in results:
                if isinstance(r, dict) and r.get('query'):
                    cache[r['query']] = {
                        'org': r.get('org', ''),
                        'isp': r.get('isp', ''),
                        'country': r.get('country', ''),
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
            return label, color, info.get('org', ''), info.get('country', '')
    return 'Unclassified', UNCLASSIFIED_COLOR, info.get('org', ''), info.get('country', '')


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
    order = [r[1] for r in CATEGORY_RULES] + ['Unclassified']
    for label in order:
        if label in cat_counts:
            top_orgs = [o for o, _ in cat_orgs[label].most_common(4)]
            categories.append({
                'label': label,
                'count': cat_counts[label],
                'pct': round(cat_counts[label] / total * 100) if total else 0,
                'color': cat_colors.get(label, UNCLASSIFIED_COLOR),
                'orgs': top_orgs,
            })
    return categories, total


def llm_narrative(categories, total_ips, api_key):
    """Ask Haiku for a brief, plain-language editorial paragraph."""
    if not api_key:
        return ''
    summary = ', '.join(
        f"{c['pct']}% {c['label']} (e.g. {', '.join(c['orgs'][:2]) or 'various'})"
        for c in categories
    )
    prompt = (
        f"You're writing a one-paragraph plain-language summary for a website operator's "
        f"internal traffic analysis page. {total_ips} unique IPs hit the site in the past "
        f"7 days (excluding known bot user-agents). Org breakdown: {summary}. "
        f"Write 2-3 sentences that explain what this means for the operator in plain language: "
        f"who the real visitors are, what rank-tracking proxies are doing, and whether "
        f"the site is getting real human attention. No jargon, no bullet points, no headers. "
        f"Short and direct."
    )
    try:
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps({
                'model': LLM_MODEL,
                'max_tokens': 250,
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
    ip_hits = parse_logs(window_start)
    print(f'  {len(ip_hits)} unique non-bot IPs found')

    # Cap to top-N IPs by hit count for lookup efficiency
    top_ips = dict(ip_hits.most_common(MAX_IPS))

    print('  loading org cache...')
    org_cache = load_org_cache()

    uncached = sum(1 for ip in top_ips if ip not in org_cache)
    if uncached:
        print(f'  fetching {uncached} new IP orgs via ip-api.com...')
        lookup_orgs(list(top_ips.keys()), org_cache)

    print('  classifying...')
    categories, total_ips = build_categories(top_ips, org_cache)

    print('  requesting narrative from Haiku...')
    narrative = llm_narrative(categories, total_ips, api_key)

    # Top orgs across all IPs for supplemental display
    org_counter = Counter()
    for ip in top_ips:
        info = org_cache.get(ip, {})
        if info.get('org'):
            org_counter[info['org']] += top_ips[ip]
    top_orgs = [{'org': o, 'count': n} for o, n in org_counter.most_common(10)]

    out = {
        'generatedAt': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'windowDays': WINDOW_DAYS,
        'totalIPs': total_ips,
        'categories': categories,
        'narrative': narrative,
        'topOrgs': top_orgs,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f'  wrote {OUT_PATH}')
    for c in categories:
        print(f"  {c['pct']:3d}% {c['label']} ({c['count']} hits)")


if __name__ == '__main__':
    main()
