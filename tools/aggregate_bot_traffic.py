#!/usr/bin/env python3
"""
Parse Apache access logs to a per-day, per-bot summary at
data/bot_traffic.json that /usage renders.

Why: GSC / BWT show indexing status after-the-fact. The crawl logs are
the earliest signal that any of the SEO / IndexNow / sitemap work is
actually pulling search-engine and AI crawlers to the site. Surfacing
the counts on /usage makes the result of "ship a sitemap, ping
IndexNow, write llms.txt" legible to the operator and anyone curious.

Reads (in order of preference):
  /var/log/apache2/nowservingto-access.log*   (per-vhost log)
  /var/log/apache2/access.log*                (shared, filtered by URL)

Both paths default to root:adm 640, so the cron user (john) must be in
the `adm` group:
  sudo usermod -a -G adm john   # then re-login for the group to attach

If neither log is readable, writes an error stub to bot_traffic.json
so the /usage page can render a "permissions needed" hint instead of
silently showing zeros.
"""
import gzip
import ipaddress
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / 'data' / 'bot_traffic.json'

VHOST_LOG_GLOB = '/var/log/apache2/nowservingto-access.log*'
SHARED_LOG_GLOB = '/var/log/apache2/access.log*'

# When we fall back to the shared log, only count requests whose URL
# path starts with one of these prefixes (so traffic for other vhosts
# on the box doesn't pollute the count). "/" alone would match every
# request; we only count it on the homepage explicit path.
NOWSERVINGTO_PATHS = (
    '/cuisine/', '/district/', '/r/', '/wire/',
    '/og/', '/sitemap.xml', '/llms.txt', '/robots.txt',
    '/press', '/usage', '/data/corridors.json', '/contribute',
)

# Exploit-scanner paths. Any request to one of these gets categorized as
# 'exploit' regardless of the UA the client claims, because real search
# crawlers and AI bots never request these. Catches the bot-army traffic
# that spoofs Googlebot/Bingbot UAs to look legitimate but is actually
# probing for leaked credentials, WordPress installs, exposed .git
# directories, etc. Pattern is anchored at the start of the URL path.
EXPLOIT_PATH_RE = re.compile(
    r'^/('
    r'\.env|'                                            # any /.env, /.env.local, /.env.bak ...
    r'\.git/|'
    r'\.svn/|'
    r'\.aws/|'
    r'\.ssh/|'
    r'\.htaccess|\.htpasswd|'
    r'wp-|wordpress/|wp/|'                               # WordPress probes
    r'sftp-?config|sftp\.json|'
    r'phpmyadmin/|pma/|PMA/|'
    r'admin\.php|administrator/|adminer\.php|'
    r'xmlrpc\.php|'
    r'cgi-bin/|'
    r'config\.(php|json|yml|yaml)|configuration\.php|'
    r'server-(status|info)|'
    r'backup/|backups/|\.backup|'
    r'dump\.sql|database\.sql|db\.sql|'
    r'shell\.php|c99\.php|r57\.php|'
    r'remote\.php'
    r')',
    re.I,
)

# Asset-crawler UA patterns. These are LEGITIMATE bot traffic but feed
# separate image/video/news indices that are orthogonal to "is my page
# indexed in regular Search." Used here only to make sure they DON'T
# leak into the Googlebot/Bingbot HTML counts - not surfaced in the
# dashboard, where they'd be noise.
ASSET_UA_RE = re.compile(
    r'Googlebot-(Image|Video|News)|Bingbot-Image|YandexImages',
    re.I,
)

# Search engines - HTML page crawlers only. Patterns are anchored to
# exclude the asset variants above (e.g. Googlebot matches "Googlebot/"
# but not "Googlebot-Image/").
SEARCH_ENGINE_BOTS = [
    ('Googlebot',        r'Googlebot/'),
    ('Bingbot',          r'\bBingbot/'),
    ('YandexBot',        r'\bYandexBot/'),
    ('Baiduspider',      r'Baiduspider'),
    ('DuckDuckBot',      r'DuckDuckBot'),
    ('NaverBot',         r'NaverBot'),
    ('Applebot',         r'\bApplebot/'),                # exclude Applebot-Extended
]

AI_BOTS = [
    ('OAI-SearchBot',    'OAI-SearchBot'),    # ChatGPT Search index
    ('ChatGPT-User',     'ChatGPT-User'),     # ChatGPT on-demand browse
    ('GPTBot',           'GPTBot'),           # OpenAI training crawler
    ('PerplexityBot',    'PerplexityBot'),    # Perplexity index
    ('Perplexity-User',  'Perplexity-User'),  # Perplexity on-demand
    ('ClaudeBot',        'ClaudeBot'),        # Anthropic training
    ('Claude-User',      'Claude-User'),      # Claude on-demand
    ('claude-web',       'claude-web'),       # legacy Anthropic UA
    ('Google-Extended',  'Google-Extended'),  # Gemini training opt-in
    ('Applebot-Extended','Applebot-Extended'),# Apple Intelligence training
    ('Meta-ExternalAgent','Meta-ExternalAgent'),# Llama / Meta AI
    ('Bytespider',       'Bytespider'),       # ByteDance / Doubao
    ('Amazonbot',        'Amazonbot'),
    ('cohere-ai',        'cohere-ai'),
    ('CCBot',            'CCBot'),            # Common Crawl → many LLM corpora
    ('DiffBot',          'DiffBot'),
    ('YouBot',           'YouBot'),           # You.com
]

# Canonical type per known bot. Four buckets, mirrored in usage.html.
#   search      search-engine HTML index crawler
#   ai-search   builds an AI search / answer index (you get cited live)
#   ai-training scrapes to train a model (background, no live user)
#   live-user   on-demand fetch triggered by a real user's prompt (a live citation)
BOT_TYPE = {
    'Googlebot': 'search', 'Bingbot': 'search', 'YandexBot': 'search',
    'Baiduspider': 'search', 'DuckDuckBot': 'search', 'NaverBot': 'search',
    'Applebot': 'search',
    'OAI-SearchBot': 'ai-search', 'PerplexityBot': 'ai-search',
    'GPTBot': 'ai-training', 'ClaudeBot': 'ai-training', 'claude-web': 'ai-training',
    'Google-Extended': 'ai-training', 'Applebot-Extended': 'ai-training',
    'Meta-ExternalAgent': 'ai-training', 'Bytespider': 'ai-training',
    'Amazonbot': 'ai-training', 'cohere-ai': 'ai-training', 'CCBot': 'ai-training',
    'DiffBot': 'ai-training', 'YouBot': 'ai-training',
    'ChatGPT-User': 'live-user', 'Perplexity-User': 'live-user', 'Claude-User': 'live-user',
}

LOG_LINE_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d+) \S+ "(?P<ref>[^"]*)" "(?P<ua>[^"]*)"'
    r'(?: "(?P<cfip>[^"]*)")?'    # appended by combined_cf, missing in old lines
)

REVERSE_DNS_CACHE_PATH = ROOT / 'tools' / 'cache' / 'ip_reverse_dns.json'
IP_ORG_CACHE_PATH     = ROOT / 'tools' / 'cache' / 'ip_org.json'
# Haiku-classified types for bots NOT in BOT_TYPE (new entrants). One call
# per new bot, cached forever, keyed by normalized bot name.
BOT_TYPES_CACHE_PATH  = ROOT / 'tools' / 'cache' / 'bot_types.json'
SECRETS = Path('/var/secrets/nowservingto.env')
HAIKU_MODEL = 'claude-haiku-4-5-20251001'
MAX_NEW_BOT_CLASSIFY = 12   # cap Haiku calls per run; the rest wait for next run
MIN_HITS_TO_CLASSIFY = 2    # ignore one-off UA-spoof garbage

# Operator-published crawler IP ranges (the authoritative way to verify bots
# that run on cloud infra and so don't reverse-DNS to their own domain, e.g.
# OpenAI on Azure). Standard Google "prefixes" JSON format. Cached RANGE_TTL_DAYS.
RANGES_CACHE_PATH = ROOT / 'tools' / 'cache' / 'bot_ip_ranges.json'
RANGE_TTL_DAYS = 7
IP_RANGE_SOURCES = {
    'Googlebot':       ['https://developers.google.com/search/apis/ipranges/googlebot.json',
                        'https://developers.google.com/search/apis/ipranges/special-crawlers.json'],
    'Google-Extended': ['https://developers.google.com/search/apis/ipranges/googlebot.json',
                        'https://developers.google.com/search/apis/ipranges/special-crawlers.json'],
    # Bing/Anthropic publish no machine-readable list - they verify via reverse-DNS
    # (search.msn.com / anthropic.com), which the rDNS path already handles.
    'GPTBot':          ['https://openai.com/gptbot.json'],
    'OAI-SearchBot':   ['https://openai.com/searchbot.json'],
    'ChatGPT-User':    ['https://openai.com/chatgpt-user.json'],
    'PerplexityBot':   ['https://www.perplexity.ai/perplexitybot.json'],
    'Perplexity-User': ['https://www.perplexity.ai/perplexity-user.json'],
}
# ip-api.com batch endpoint: 100 IPs per POST, free, no key, HTTP only.
# Returns org / ISP / ASN / country per IP. Slower than rDNS but works
# on IPs without PTR records (most bot-farm hosts).
IPAPI_BATCH_URL = 'http://ip-api.com/batch'
IPAPI_BATCH_SIZE = 100

# Map a reverse-DNS hostname to a human-readable "host" label. Order
# matters: most specific first. The label is what surfaces in the
# bot-farm section so the user sees "DigitalOcean" rather than the
# raw rDNS string. If no rule matches, the rDNS itself is shown,
# truncated; if rDNS lookup fails, falls back to "unknown ($IP)".
HOST_LABELS = [
    (r'\.googlebot\.com$|\.google\.com$',          'Google'),
    (r'\.search\.msn\.com$|\.bing\.com$',          'Microsoft / Bing'),
    (r'\.yandex\.(com|net|ru)$',                   'Yandex'),
    (r'\.crawl\.baidu\.com$',                      'Baidu'),
    (r'\.apple\.com$|\.applebot\.apple\.com$',     'Apple'),
    (r'\.duckduckgo\.com$',                        'DuckDuckGo'),
    (r'\.openai\.com$|\.openaiapi-site\.com$',     'OpenAI'),
    (r'\.anthropic\.com$|claude.*\.com$',          'Anthropic'),
    (r'\.perplexity\.ai$',                         'Perplexity'),
    (r'\.facebook\.com$|\.meta\.com$|\.fbsv\.net$','Meta'),
    (r'\.bytedance\.com$|\.tiktokv\.com$',         'ByteDance'),
    (r'\.amazonaws\.com$',                         'AWS'),
    (r'\.amazon\.com$',                            'Amazon'),
    # Hosting providers commonly used by bot farms.
    (r'\.digitalocean\.com$|\.do\.co$',            'DigitalOcean'),
    (r'\.linode\.com$|\.linodeusercontent\.com$',  'Linode'),
    (r'\.hetzner\.(com|de)$|\.hetzner-cloud\.de$', 'Hetzner'),
    (r'\.ovh\.(net|com)$|\.kimsufi\.com$',         'OVH'),
    (r'\.vultr\.com$',                             'Vultr'),
    (r'\.contabo\.(com|host|net)$',                'Contabo'),
    (r'\.scaleway\.com$',                          'Scaleway'),
    (r'\.alibaba(cloud|inc)\.com$|\.aliyun\.com$', 'Alibaba Cloud'),
    (r'\.tencentcloud\.com$',                      'Tencent Cloud'),
    (r'\.azure\.com$|\.azurewebsites\.net$|\.microsoft\.com$', 'Microsoft Azure'),
    (r'\.googleusercontent\.com$|\.gce\.googleusercontent\.com$', 'Google Cloud'),
    (r'\.oracle\.com$|\.oraclecloud\.com$|\.oraclecloud(usercontent)?\.com$', 'Oracle Cloud'),
    (r'\.cloudflare\.com$|\.cf-(ips|workers)\.com$','Cloudflare'),
]
HOST_LABEL_REGEXES = [(re.compile(p, re.I), label) for p, label in HOST_LABELS]


def reverse_dns(ip, cache):
    """Reverse DNS one IP, caching the result. Returns hostname or ''."""
    if ip in cache:
        return cache[ip]
    import socket
    socket.setdefaulttimeout(3)
    try:
        host = socket.gethostbyaddr(ip)[0]
    except Exception:
        host = ''
    cache[ip] = host
    return host


# Org-name regex → friendly label. Catches operators where rDNS won't
# help (no PTR set, or rDNS gives a misleading sub-brand). The ip-api
# org/isp strings carry corporate names like "Microsoft Corporation" or
# "Google LLC" - we want those to fold into the SAME label as their
# bot's expected origin (e.g. real Bingbot from Azure AS8075 should
# verify as "Microsoft / Bing").
ORG_LABEL_REGEXES = [
    (re.compile(r'\bGoogle\b', re.I),                       'Google'),
    (re.compile(r'\bMicrosoft\b|\bBing\b|\bAzure\b', re.I), 'Microsoft / Bing'),
    (re.compile(r'\bYandex\b', re.I),                       'Yandex'),
    (re.compile(r'\bBaidu\b', re.I),                        'Baidu'),
    (re.compile(r'\bApple\b', re.I),                        'Apple'),
    (re.compile(r'\bDuckDuckGo\b', re.I),                   'DuckDuckGo'),
    (re.compile(r'\bOpenAI\b', re.I),                       'OpenAI'),
    (re.compile(r'\bAnthropic\b', re.I),                    'Anthropic'),
    (re.compile(r'\bPerplexity\b', re.I),                   'Perplexity'),
    (re.compile(r'\bMeta\b|\bFacebook\b', re.I),            'Meta'),
    (re.compile(r'\bByteDance\b|\bTikTok\b', re.I),         'ByteDance'),
    (re.compile(r'\bAmazon\b|\bAWS\b', re.I),               'Amazon'),
    (re.compile(r'\bDigitalOcean\b', re.I),                 'DigitalOcean'),
    (re.compile(r'\bLinode\b|\bAkamai\b', re.I),            'Linode / Akamai'),
    (re.compile(r'\bHetzner\b', re.I),                      'Hetzner'),
    (re.compile(r'\bOVH\b|\bKimsufi\b', re.I),              'OVH'),
    (re.compile(r'\bVultr\b', re.I),                        'Vultr'),
    (re.compile(r'\bContabo\b', re.I),                      'Contabo'),
    (re.compile(r'\bScaleway\b|\bOnline SAS\b', re.I),      'Scaleway'),
    (re.compile(r'\bAlibaba\b|\bAliyun\b', re.I),           'Alibaba Cloud'),
    (re.compile(r'\bTencent\b', re.I),                      'Tencent Cloud'),
    (re.compile(r'\bOracle\b', re.I),                       'Oracle Cloud'),
    (re.compile(r'\bCloudflare\b', re.I),                   'Cloudflare'),
    (re.compile(r'\bGoDaddy\b', re.I),                      'GoDaddy'),
    (re.compile(r'\bHostinger\b', re.I),                    'Hostinger'),
    (re.compile(r'\bDataCamp\b|\bM247\b', re.I),            'M247'),
    (re.compile(r'\bChina Telecom\b', re.I),                'China Telecom'),
    (re.compile(r'\bChina Unicom\b|\bChinaNet\b', re.I),    'China Unicom'),
    (re.compile(r'\bChina Mobile\b', re.I),                 'China Mobile'),
]


def host_label(rdns, ip, ip_org=None):
    """Map an IP to a friendly "<Org> (<Country>)" label. Resolution
    order:
      1. rDNS regex match (e.g. googlebot.com → "Google")
      2. ip-api.com org/isp string regex match (catches "Microsoft Azure",
         "Google LLC", etc. via ORG_LABEL_REGEXES)
      3. Raw ip-api org name + country
      4. Second-level rDNS domain
      5. "unknown ($IP)" so the row still renders something.
    """
    if rdns:
        for regex, label in HOST_LABEL_REGEXES:
            if regex.search(rdns):
                return label
    if ip_org:
        # Combine org + isp into one string for matching.
        haystack = ' '.join(filter(None, [ip_org.get('org'), ip_org.get('isp'), ip_org.get('as')]))
        for regex, label in ORG_LABEL_REGEXES:
            if regex.search(haystack):
                return label
        if ip_org.get('org'):
            country = ip_org.get('country') or ''
            return f'{ip_org["org"]} ({country})' if country else ip_org['org']
    if rdns:
        parts = rdns.rstrip('.').split('.')
        return '.'.join(parts[-2:]) if len(parts) >= 2 else rdns
    if ip_org and ip_org.get('country'):
        return f'unknown ({ip_org["country"]})'
    return f'unknown ({ip})'


def enrich_ips_via_ipapi(ips, cache):
    """Batch-lookup IPs at ip-api.com. Free tier, no API key, HTTP only.
    Updates `cache` in-place; subsequent runs only lookup new IPs.
    Skips silently on network failure - dashboard degrades to rDNS only."""
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    pending = [ip for ip in ips if ip not in cache]
    if not pending:
        return
    print(f'  enriching {len(pending)} new IPs via ip-api.com...')
    for i in range(0, len(pending), IPAPI_BATCH_SIZE):
        chunk = pending[i:i + IPAPI_BATCH_SIZE]
        body = [{'query': ip, 'fields': 'status,as,org,isp,countryCode'} for ip in chunk]
        req = Request(
            IPAPI_BATCH_URL,
            data=json.dumps(body).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlopen(req, timeout=15) as r:
                results = json.loads(r.read())
        except (HTTPError, URLError, OSError) as e:
            print(f'  ip-api.com batch failed: {e} - skipping enrichment')
            return
        for ip, res in zip(chunk, results):
            if res.get('status') != 'success':
                cache[ip] = None
                continue
            cache[ip] = {
                'as':      res.get('as') or '',
                'org':     res.get('org') or res.get('isp') or '',
                'isp':     res.get('isp') or '',
                'country': res.get('countryCode') or '',
            }

# AI patterns matched first so ChatGPT-User isn't shadowed by anything
# generic. SEARCH_ENGINE_BOTS regexes are tight (anchored on "/") so they
# already exclude Googlebot-Image and friends.
BOT_PATTERNS_COMPILED = [
    (name, re.compile(pat, re.I), 'ai')
    for name, pat in AI_BOTS
] + [
    (name, re.compile(pat, re.I), 'search')
    for name, pat in SEARCH_ENGINE_BOTS
]


def identify_bot(ua):
    for name, regex, tier in BOT_PATTERNS_COMPILED:
        if regex.search(ua):
            return name, tier
    return None, None


# UA looks like a crawler we don't yet know: carries a bot keyword or the
# "+http(s)://info" self-identification convention, and isn't a plain browser.
# Conservative on purpose - a false positive costs one Haiku call.
UNKNOWN_BOT_RE = re.compile(r'bot\b|crawler|spider|scraper|\+https?://|\bGPT|\bLLM\b|\bAI\b', re.I)
BROWSERISH_RE  = re.compile(r'Mozilla.*(Chrome|Safari|Firefox|Edg)/', re.I)


def extract_bot_name(ua):
    """Best-effort name for an unknown crawler UA, or None if it's not bot-like."""
    if not UNKNOWN_BOT_RE.search(ua):
        return None
    if BROWSERISH_RE.search(ua) and not re.search(r'bot|crawler|spider', ua, re.I):
        return None  # ordinary browser
    m = re.search(r'([A-Za-z][\w.-]*(?:bot|crawler|spider|AI|GPT)[\w.-]*)', ua, re.I)
    if m:
        return m.group(1).strip('/-.')
    m = re.match(r'\s*([A-Za-z][\w.-]{2,40})/', ua)
    if m and m.group(1) not in ('Mozilla', 'AppleWebKit', 'Gecko', 'Chrome',
                                'Safari', 'Opera', 'Version', 'Edg', 'OPR'):
        return m.group(1)
    return None


def _read_secret(key):
    try:
        for line in SECRETS.read_text().splitlines():
            if line.startswith(key + '='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def classify_unknown_bot(name, sample_ua, cache):
    """{'type','operator'} for an unknown bot via Haiku, cached by name.
    type in search|ai-search|ai-training|live-user|other. Degrades to
    {'type':'other','operator':''} on any failure (never raises)."""
    if name in cache:
        return cache[name]
    key = _read_secret('ANTHROPIC_API_KEY')
    out = {'type': 'other', 'operator': ''}
    if key:
        import urllib.request as U, urllib.error as E
        prompt = (
            "Classify this web crawler by its User-Agent. Reply with ONLY a compact "
            'JSON object: {"type":"...","operator":"..."}.\n'
            "type is exactly one of: search (search-engine index crawler), ai-search "
            "(builds an AI search/answer index), ai-training (scrapes to train an AI "
            "model), live-user (on-demand fetch triggered by a real user's prompt), "
            "other (unsure).\noperator is the company (e.g. Google, ByteDance, OpenAI) "
            'or "".\n\n'
            f"User-Agent: {sample_ua[:400]}"
        )
        body = json.dumps({'model': HAIKU_MODEL, 'max_tokens': 80,
                           'messages': [{'role': 'user', 'content': prompt}]}).encode()
        req = U.Request('https://api.anthropic.com/v1/messages', data=body, method='POST',
                        headers={'content-type': 'application/json', 'x-api-key': key,
                                 'anthropic-version': '2023-06-01'})
        try:
            with U.urlopen(req, timeout=20) as r:
                txt = json.loads(r.read())['content'][0]['text']
            obj = json.loads(re.search(r'\{.*\}', txt, re.S).group(0))
            t = str(obj.get('type', 'other')).lower().strip()
            out = {'type': t if t in ('search', 'ai-search', 'ai-training', 'live-user', 'other') else 'other',
                   'operator': str(obj.get('operator', '')).strip()[:40]}
        except (E.URLError, E.HTTPError, OSError, KeyError, ValueError, AttributeError, IndexError):
            pass
    cache[name] = out
    return out


def _fetch_prefixes(url):
    """Fetch one operator IP-range JSON, return a list of CIDR strings.
    utf-8-sig tolerates the BOM Bing prepends."""
    from urllib.request import urlopen
    with urlopen(url, timeout=20) as r:
        d = json.loads(r.read().decode('utf-8-sig', 'replace'))
    out = []
    for p in d.get('prefixes', []) or d.get('Prefixes', []):
        c = p.get('ipv4Prefix') or p.get('ipv6Prefix') or p.get('ipv4') or p.get('ipv6')
        if c:
            out.append(c)
    return out


def load_bot_ranges():
    """{bot_name: [ip_network,...]} from operator-published ranges, cached
    RANGE_TTL_DAYS. Network failure falls back to cache; never raises."""
    try:
        cache = json.loads(RANGES_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    now = datetime.now(timezone.utc)
    for url in {u for urls in IP_RANGE_SOURCES.values() for u in urls}:
        entry = cache.get(url)
        fresh = bool(entry and entry.get('fetched') and
                     now - datetime.fromisoformat(entry['fetched']) < timedelta(days=RANGE_TTL_DAYS))
        if fresh:
            continue
        try:
            cache[url] = {'fetched': now.isoformat(), 'prefixes': _fetch_prefixes(url)}
        except Exception as e:
            print(f'  ip-range fetch failed {url}: {e}')
            cache.setdefault(url, {'fetched': now.isoformat(), 'prefixes': []})
    RANGES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RANGES_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))
    nets = {}
    for bot, srcs in IP_RANGE_SOURCES.items():
        lst = []
        for u in srcs:
            for c in (cache.get(u) or {}).get('prefixes', []):
                try:
                    lst.append(ipaddress.ip_network(c, strict=False))
                except ValueError:
                    pass
        nets[bot] = lst
    return nets


def parse_apache_time(s):
    # 27/May/2026:00:55:30 +0000
    return datetime.strptime(s, '%d/%b/%Y:%H:%M:%S %z')


def iter_log_lines(paths, filter_by_path):
    for p in paths:
        try:
            opener = gzip.open if str(p).endswith('.gz') else open
            with opener(p, 'rt', encoding='utf-8', errors='replace') as f:
                for line in f:
                    m = LOG_LINE_RE.match(line)
                    if not m:
                        continue
                    path = m.group('path')
                    if filter_by_path:
                        if path != '/' and not path.startswith(NOWSERVINGTO_PATHS):
                            continue
                    yield m
        except PermissionError:
            raise
        except FileNotFoundError:
            continue


def pick_log_set():
    """Return (paths, filter_by_path). Per-vhost log is preferred and
    doesn't need URL filtering. Shared log requires URL filtering."""
    vhost_paths = sorted(Path('/').glob(VHOST_LOG_GLOB.lstrip('/')))
    if vhost_paths:
        return vhost_paths, False
    shared_paths = sorted(Path('/').glob(SHARED_LOG_GLOB.lstrip('/')))
    if shared_paths:
        return shared_paths, True
    return [], False


def write_stub(reason):
    """Write a stub bot_traffic.json that the /usage page can render
    a friendly hint for instead of silent zeros."""
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'status': 'unavailable',
        'reason': reason,
        'searchEngines': [],
        'aiBots': [],
        'totals': {'last7d': 0, 'last30d': 0},
    }, indent=2))


def main():
    paths, filter_by_path = pick_log_set()
    if not paths:
        write_stub('Apache log files not found at the expected paths.')
        print('no log files found')
        return

    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)

    # Per-bot day-by-day counts. day_counts[bot][YYYY-MM-DD] = hits.
    day_counts = defaultdict(lambda: defaultdict(int))
    # Per-bot unique paths over the full 30d window.
    unique_paths = defaultdict(set)
    # Total hits per path across all legit bots (excl. exploit scanners).
    path_hit_counts = defaultdict(int)
    # Last-seen timestamp per bot.
    last_seen = {}
    tiers = {}
    # Exploit scanners (UA-spoofed) bucket - one combined counter rather
    # than per-UA, because the UAs are unreliable garbage by definition.
    # Also track the most-probed paths so the dashboard can show what
    # the bot farms are actually hunting for (interesting context, and
    # confirms the filter is doing its job).
    exploit_hits_30d = 0
    exploit_hits_7d = 0
    exploit_unique = set()
    exploit_unique_7d = set()
    exploit_path_counts = defaultdict(int)
    # IP collection: for legit bots we'll sample top IPs for verification;
    # for exploits we'll aggregate by host label so the bot-farm section
    # can show "20 hits from Hetzner" instead of just "10 unique paths."
    bot_ips = defaultdict(lambda: defaultdict(int))   # bot -> ip -> hits
    exploit_ips = defaultdict(int)                    # ip -> hits
    other_sample_ua = {}                              # unknown bot name -> a sample UA

    # Reverse-DNS lookup cache (one-shot per IP across all runs).
    try:
        rdns_cache = json.loads(REVERSE_DNS_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        rdns_cache = {}
    # ip-api.com org+country lookup cache (also one-shot per IP).
    try:
        ip_org_cache = json.loads(IP_ORG_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        ip_org_cache = {}

    cutoff_7d = now - timedelta(days=7)

    try:
        for m in iter_log_lines(paths, filter_by_path):
            path = m.group('path')
            try:
                t = parse_apache_time(m.group('time'))
            except ValueError:
                continue
            if t < cutoff_30d:
                continue

            # Exploit scanners get filtered first - their UA usually
            # claims to be Googlebot or a normal browser, so they'd
            # otherwise be miscounted as legitimate crawler traffic.
            # Real client IP comes from the optional CF-Connecting-IP
            # capture (post-2026-05-27 logs only). Apache's %h field is
            # the Cloudflare edge IP which is useless for attribution.
            real_ip = m.group('cfip') or ''

            if EXPLOIT_PATH_RE.match(path):
                exploit_hits_30d += 1
                if t >= cutoff_7d:
                    exploit_hits_7d += 1
                    exploit_unique_7d.add(path)
                exploit_unique.add(path)
                # Strip query string off so /.env?cb=123 buckets with /.env
                exploit_path_counts[path.split('?', 1)[0]] += 1
                if real_ip:
                    exploit_ips[real_ip] += 1
                continue

            ua = m.group('ua')
            # Asset crawlers (Googlebot-Image, etc.) are real Google traffic
            # but feed Image/Video/News indices - orthogonal to "is my page
            # indexed in regular Search." Drop them entirely so they neither
            # inflate the HTML counts nor add a noise section to /usage.
            if ASSET_UA_RE.search(ua):
                continue
            bot, tier = identify_bot(ua)
            if not bot:
                bot = extract_bot_name(ua)
                if not bot:
                    continue
                tier = 'other'
                other_sample_ua.setdefault(bot, ua)
            day = t.date().isoformat()
            day_counts[bot][day] += 1
            unique_paths[bot].add(path)
            path_hit_counts[path.split('?', 1)[0]] += 1
            if bot not in last_seen or t > last_seen[bot]:
                last_seen[bot] = t
            tiers[bot] = tier
            if real_ip:
                bot_ips[bot][real_ip] += 1
    except PermissionError:
        write_stub(
            'cron user cannot read /var/log/apache2/*. '
            'Fix once with: sudo usermod -a -G adm john   (then re-login)'
        )
        print('permission denied on apache logs')
        sys.exit(0)

    cutoff_7d_iso = (now - timedelta(days=7)).date().isoformat()

    def serialize(bot_list):
        rows = []
        for bot in bot_list:
            days = day_counts.get(bot, {})
            hits_30d = sum(days.values())
            hits_7d = sum(v for d, v in days.items() if d >= cutoff_7d_iso)
            if hits_30d == 0:
                continue
            rows.append({
                'bot': bot,
                'type': BOT_TYPE.get(bot),
                'hits30d': hits_30d,
                'hits7d': hits_7d,
                'uniquePaths30d': len(unique_paths.get(bot, ())),
                'lastSeen': last_seen[bot].isoformat() if bot in last_seen else None,
                'daily': sorted([{'day': d, 'hits': v} for d, v in days.items()],
                                key=lambda r: r['day']),
            })
        rows.sort(key=lambda r: r['hits30d'], reverse=True)
        return rows

    # Expected host label for each bot, used to verify the UA isn't spoofed.
    # rDNS sources confirmed against the bot operators' published guidance
    # (Google: googlebot.com / google.com, Bing: search.msn.com, etc.).
    EXPECTED_HOST = {
        'Googlebot': 'Google', 'Bingbot': 'Microsoft / Bing',
        'YandexBot': 'Yandex', 'Baiduspider': 'Baidu',
        'DuckDuckBot': 'DuckDuckGo', 'Applebot': 'Apple',
        'GPTBot': 'OpenAI', 'OAI-SearchBot': 'OpenAI',
        'ChatGPT-User': 'OpenAI', 'PerplexityBot': 'Perplexity',
        'Perplexity-User': 'Perplexity',
        'ClaudeBot': 'Anthropic', 'Claude-User': 'Anthropic',
        'claude-web': 'Anthropic',
        'Meta-ExternalAgent': 'Meta', 'Bytespider': 'ByteDance',
        'Amazonbot': 'Amazon', 'Google-Extended': 'Google',
        'Applebot-Extended': 'Apple',
    }

    # Enrich every unique IP we saw (bot + exploit) at ip-api.com.
    # Caches forever, so steady-state cost is one batch call for the
    # day's new IPs - usually <100.
    all_ips = set(exploit_ips.keys())
    for ip_dict in bot_ips.values():
        all_ips.update(ip_dict.keys())
    enrich_ips_via_ipapi(all_ips, ip_org_cache)

    bot_networks = load_bot_ranges()

    def _ip_in_ranges(ip, bot):
        nets = bot_networks.get(bot)
        if not nets:
            return False
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a in n for n in nets)

    def verify_bot(bot):
        """Verify the IPs claiming this UA. An IP counts as verified if it's in
        the operator's published crawler ranges (authoritative; catches OpenAI /
        Perplexity on cloud infra) OR its reverse-DNS / IP-org resolves to the
        expected operator. Returns the verified share so the dashboard can flag
        spoofing (a 'Googlebot' outside Google's published range + wrong rDNS)."""
        ips = bot_ips.get(bot, {})
        if not ips:
            return None
        expected = EXPECTED_HOST.get(bot)
        has_ranges = bool(bot_networks.get(bot))
        if not expected and not has_ranges:
            return None
        verified_hits = 0
        total = 0
        by_range = 0
        for ip, hits in sorted(ips.items(), key=lambda kv: -kv[1])[:20]:
            total += hits
            if has_ranges and _ip_in_ranges(ip, bot):
                verified_hits += hits
                by_range += hits
            elif expected:
                host = reverse_dns(ip, rdns_cache)
                label = host_label(host, ip, ip_org_cache.get(ip))
                if label == expected or expected.lower() in label.lower():
                    verified_hits += hits
        return {
            'expected': expected,
            'verified': verified_hits,
            'sampled': total,
            'rate': round(verified_hits / total, 3) if total else 0.0,
            'method': 'ip-range' if by_range > (verified_hits - by_range) else 'rdns',
        }

    # Decorate bot rows with verification stats. None until CF-IP data
    # accumulates (apache log format only flipped today).
    for row in serialize([n for n, _ in SEARCH_ENGINE_BOTS]) + serialize([n for n, _ in AI_BOTS]):
        pass  # placeholder so we can rebuild lists below with verify

    def attach_verification(rows):
        for r in rows:
            v = verify_bot(r['bot'])
            r['verification'] = v
        return rows

    search_rows = attach_verification(serialize([n for n, _ in SEARCH_ENGINE_BOTS]))
    ai_rows = attach_verification(serialize([n for n, _ in AI_BOTS]))

    # Bots we don't recognize (new entrants): Haiku-classify once each, cached.
    try:
        bot_types_cache = json.loads(BOT_TYPES_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        bot_types_cache = {}
    other_rows = serialize([n for n, tr in tiers.items() if tr == 'other'])
    _classified = 0
    for r in other_rows:
        known = r['bot'] in bot_types_cache
        if not known and (r['hits30d'] < MIN_HITS_TO_CLASSIFY or _classified >= MAX_NEW_BOT_CLASSIFY):
            r['type'], r['operator'] = 'other', ''
            continue
        info = classify_unknown_bot(r['bot'], other_sample_ua.get(r['bot'], r['bot']), bot_types_cache)
        if not known:
            _classified += 1
        r['type'], r['operator'] = info['type'], info.get('operator', '')
    BOT_TYPES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOT_TYPES_CACHE_PATH.write_text(json.dumps(bot_types_cache, indent=2, sort_keys=True))

    # Aggregate exploit source IPs into "<Org> (<Country>)" buckets.
    # Only works for logs captured after the combined_cf format went
    # live; older lines have no real IP and don't contribute.
    exploit_sources = defaultdict(int)
    for ip, hits in exploit_ips.items():
        host = reverse_dns(ip, rdns_cache)
        exploit_sources[host_label(host, ip, ip_org_cache.get(ip))] += hits
    top_sources = sorted(
        [{'host': h, 'hits': n} for h, n in exploit_sources.items()],
        key=lambda r: r['hits'], reverse=True,
    )[:12]

    # Also break down exploits by country only, useful at-a-glance.
    exploit_countries = defaultdict(int)
    for ip, hits in exploit_ips.items():
        org_info = ip_org_cache.get(ip) or {}
        cc = org_info.get('country') or '??'
        exploit_countries[cc] += hits
    top_countries = sorted(
        [{'country': c, 'hits': n} for c, n in exploit_countries.items()],
        key=lambda r: r['hits'], reverse=True,
    )[:10]

    # Persist both caches so the next run only resolves new IPs.
    REVERSE_DNS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVERSE_DNS_CACHE_PATH.write_text(json.dumps(rdns_cache, indent=2, sort_keys=True))
    IP_ORG_CACHE_PATH.write_text(json.dumps(ip_org_cache, indent=2, sort_keys=True))

    total_30d = sum(r['hits30d'] for r in search_rows + ai_rows)
    total_7d = sum(r['hits7d']  for r in search_rows + ai_rows)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        'generatedAt': now.isoformat(),
        'status': 'ok',
        'logSource': 'vhost' if not filter_by_path else 'shared',
        'searchEngines': search_rows,
        'aiBots': ai_rows,
        'otherBots': other_rows,
        'exploitScanners': {
            'hits30d': exploit_hits_30d,
            'hits7d': exploit_hits_7d,
            'uniquePaths30d': len(exploit_unique),
            'uniquePaths7d': len(exploit_unique_7d),
            'topPaths': sorted(
                [{'path': p, 'hits': n} for p, n in exploit_path_counts.items()],
                key=lambda r: r['hits'], reverse=True,
            )[:12],
            'topSources': top_sources,
            'topCountries': top_countries,
            'sourcesAvailable': sum(exploit_ips.values()),
        },
        'totals': {'last7d': total_7d, 'last30d': total_30d},
        'topPaths': sorted(
            [{'path': p, 'hits': n} for p, n in path_hit_counts.items()],
            key=lambda r: r['hits'], reverse=True,
        )[:25],
    }, indent=2))
    print(f'wrote {OUT_PATH} - {total_30d} HTML-bot hits in 30d, {total_7d} in 7d, '
          f'{len(search_rows)} search engines, {len(ai_rows)} AI bots, '
          f'{exploit_hits_30d} exploit-scanner hits')


if __name__ == '__main__':
    main()
