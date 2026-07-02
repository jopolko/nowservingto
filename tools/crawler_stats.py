#!/usr/bin/env python3
"""GEO observatory for joshuaopolko.com, /geo-observatory/.

Parses the Apache log (combined_cf, real bot IP in the trailing field), verifies
bots against operator IP ranges + reverse-DNS, and emits:
  - data.json  : per-page + per-bot aggregates that power the interactive UI
  - index.html : server-rendered summary + tables (so AI crawlers see them) plus
                 a vanilla-JS layer for the charts / page explorer / filters

Run on the VPS (needs log read access):
    sudo python3 tools/crawler_stats.py
    sudo python3 tools/crawler_stats.py --selftest
"""
import glob, gzip, re, html, collections, datetime as dt, os, json, socket, ipaddress, urllib.request, sys

def _argval(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else default

# self-contained palette for sites that don't ship the joshuaopolko site.css
NSTO_VARS = (":root{--bg:#faf7ef;--panel:#fff;--ink:#16140f;--ink2:#3f3a30;--muted:#6e665a;"
             "--line:#e7e1d2;--accent:#357a7a;--accent-ink:#2a6060;--code-bg:#f3efe7;"
             "--serif:'Fraunces',Georgia,'Times New Roman',serif;"
             "--sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
             "--mono:ui-monospace,'SF Mono',Menlo,monospace}")
NSTO_BASE = ("*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);"
             "font:400 16px/1.6 var(--sans);-webkit-font-smoothing:antialiased}"
             ".article{max-width:72rem;margin:0 auto;padding:6px 20px 56px}"
             ".article h1{font:700 clamp(27px,3.6vw,40px)/1.15 var(--serif);letter-spacing:-.01em;margin:.5em 0 .1em}"
             ".article h2{font:700 clamp(20px,2.4vw,26px)/1.2 var(--serif);margin:1.9em 0 .35em}"
             ".post-body a{color:var(--accent-ink)}.post-body a:hover{color:var(--accent)}"
             ".site-foot{max-width:72rem;margin:0 auto;padding:22px 20px;border-top:1px solid var(--line);color:var(--muted);font:400 13px var(--sans)}")

SITES = {
    'jo': dict(
        logs=sorted(glob.glob('/var/log/apache2/access.log*')),
        webroot='/var/www/html', outdir='/var/www/html/geo-observatory',
        outfile='index.html', datafile='/var/www/html/geo-observatory/data.json', data_url='data.json',
        live_index='/var/www/html/index.html', sitemap='/var/www/html/sitemap.xml',
        canonical='https://joshuaopolko.com/geo-observatory/',
        title='The GEO Observatory: watch AI crawl a live site (joshuaopolko.com)',
        h1='The GEO Observatory', brand='Joshua&nbsp;Opolko', chrome='jo', theme='#fbfaf7',
        rootvars='', base='', cost=None),
    'nsto': dict(
        logs=sorted(glob.glob('/var/log/apache2/nowservingto-access.log*')),
        webroot='/var/www/html/nowservingto', outdir='/var/www/html/nowservingto',
        outfile='usage.html', datafile='/var/www/html/nowservingto/data/observatory.json', data_url='/data/observatory.json',
        live_index='/var/www/html/nowservingto/index.html', sitemap='/var/www/html/nowservingto/sitemap.xml',
        canonical='https://nowservingto.com/usage/',
        title='NowServingTO Usage Observatory: who reads us, and what it costs',
        h1='The Usage Observatory', brand='NowServingTO', chrome='nsto', theme='#f7f1e1',
        rootvars=NSTO_VARS, base=NSTO_BASE, cost='/var/www/html/nowservingto/data/usage.json'),
}
SITE = _argval('--site', 'jo')
CFG = SITES[SITE]
LOGS = CFG['logs']
WEBROOT = CFG['webroot']
OUTDIR = CFG['outdir']
LIVE_INDEX = CFG['live_index']
SITEMAP = CFG['sitemap']
CACHE_DIR = '/var/www/html/nowservingto/tools/cache'
RANGES_CACHE = CACHE_DIR + '/crawler_stats_ranges.json'
RDNS_CACHE = CACHE_DIR + '/crawler_stats_rdns.json'
RANGE_TTL_DAYS = 7
WINDOW_DAYS = 7  # rolling log window for all charts and totals

AI = [
    ('OAI-SearchBot','ChatGPT search'),('ChatGPT-User','ChatGPT user-fetch'),('GPTBot','OpenAI GPTBot'),
    ('Claude-SearchBot','Claude search'),('Claude-User','Claude user-fetch'),('ClaudeBot','Anthropic ClaudeBot'),('anthropic-ai','Anthropic (other)'),
    ('PerplexityBot','Perplexity'),('Perplexity-User','Perplexity user-fetch'),
    ('Google-Extended','Google-Extended'),('Applebot-Extended','Applebot-Extended'),
    ('meta-externalagent','Meta AI'),('FacebookBot','Meta/Facebook'),('Bytespider','ByteDance Bytespider'),('Amazonbot','Amazonbot'),
    ('CCBot','Common Crawl'),('cohere','Cohere'),('Diffbot','Diffbot'),('Timpibot','Timpi'),('Omgilibot','Omgili'),('YouBot','You.com'),
]
SEARCH = [
    ('Googlebot','Googlebot'),('bingbot','Bingbot'),('BingPreview','Bing Preview'),('Applebot','Applebot'),
    ('YandexBot','Yandex'),('DuckDuckBot','DuckDuckGo'),('PetalBot','Petal (Huawei)'),('SeznamBot','Seznam'),
]
TYPE = {
    'ChatGPT search':'ai-search','ChatGPT user-fetch':'live-user','OpenAI GPTBot':'ai-training',
    'Claude search':'ai-search','Claude user-fetch':'live-user','Anthropic ClaudeBot':'ai-training','Anthropic (other)':'ai-training',
    'Perplexity':'ai-search','Perplexity user-fetch':'live-user','Google-Extended':'ai-training','Applebot-Extended':'ai-training',
    'Meta AI':'ai-training','Meta/Facebook':'ai-training','ByteDance Bytespider':'ai-training','Amazonbot':'ai-training',
    'Common Crawl':'ai-training','Cohere':'ai-training','Diffbot':'ai-training','Timpi':'ai-training','Omgili':'ai-training','You.com':'ai-training',
    'Googlebot':'search','Bingbot':'search','Bing Preview':'search','Applebot':'search','Yandex':'search','DuckDuckGo':'search','Petal (Huawei)':'search','Seznam':'search',
}
TYPE_LABEL = {'search':'Search index','ai-search':'AI search','ai-training':'AI training','live-user':'AI live-fetch'}
AI_TYPES = ('ai-search','ai-training','live-user')

# readable page titles for the editorial standfirsts (real <h1>/<title>, fallback to slug)
_ACR = {'ai':'AI','geo':'GEO','vr':'VR','xr':'XR','llm':'LLM','slm':'SLM','etl':'ETL','seo':'SEO','ui':'UI',
        'mcp':'MCP','js':'JS','vs':'vs','3d':'3D','slms':'SLMs','crewai':'CrewAI','n8n':'n8n'}
def _humanize_slug(path):
    seg = (path.strip('/').split('/')[-1] or path.strip('/'))
    words = [w for w in re.split(r'[-_]', seg) if w]
    return ' '.join(_ACR.get(w.lower(), w[:1].upper() + w[1:]) for w in words) or path

def page_title(path):
    fp = WEBROOT + path + ('index.html' if path.endswith('/') else '')
    try:
        txt = open(fp, encoding='utf-8').read(9000)
        m = re.search(r'<h1[^>]*>(.*?)</h1>', txt, re.S) or re.search(r'<title[^>]*>(.*?)</title>', txt, re.S)
        if m:
            t = html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
            t = re.split('\\s*[|\u00b7\u2013\u2014:]\\s*(?:Joshua Opolko|The GEO|AI Systems|NowServingTO|Now Serving)', t)[0].strip()
            if t: return t
    except Exception:
        pass
    return _humanize_slug(path)

VERIFY = {
    'OpenAI GPTBot':('openai','range'),'ChatGPT search':('openai','range'),'ChatGPT user-fetch':('openai','range'),
    'Anthropic ClaudeBot':('anthropic','rdns'),'Claude search':('anthropic','rdns'),'Claude user-fetch':('anthropic','rdns'),'Anthropic (other)':('anthropic','rdns'),
    'Perplexity':('perplexity','range'),'Perplexity user-fetch':('perplexity','range'),
    'Googlebot':('google','range'),'Google-Extended':('google','range'),
    'Bingbot':('bing','rdns'),'Bing Preview':('bing','rdns'),'Applebot':('apple','rdns'),'Applebot-Extended':('apple','rdns'),
    'Yandex':('yandex','rdns'),'DuckDuckGo':('duckduckgo','rdns'),
}
RANGE_URLS = {
    'openai':['https://openai.com/gptbot.json','https://openai.com/searchbot.json','https://openai.com/chatgpt-user.json'],
    'perplexity':['https://www.perplexity.ai/perplexitybot.json','https://www.perplexity.ai/perplexity-user.json'],
    'google':['https://developers.google.com/search/apis/ipranges/googlebot.json','https://developers.google.com/search/apis/ipranges/special-crawlers.json'],
}
RDNS_PATTERN = {
    'bing':re.compile(r'\.search\.msn\.com$|\.bing\.com$',re.I),'anthropic':re.compile(r'\.anthropic\.com$',re.I),
    'apple':re.compile(r'\.applebot\.apple\.com$|\.apple\.com$',re.I),'yandex':re.compile(r'\.yandex\.(com|net|ru)$',re.I),
    'duckduckgo':re.compile(r'\.duckduckgo\.com$',re.I),'google':re.compile(r'\.googlebot\.com$|\.google\.com$',re.I),
}
PROBE = re.compile(r'\.git|\.env|/storage/|/vendor/|/wp-|wp-login|wp-admin|laravel\.log|phpinfo|/api/|\.sql|/backup|/\.aws|/\.ssh|/config\.|/\.vscode|/owa/|/cgi-bin|/phpmyadmin|/\.DS_Store|/server-status|/actuator',re.I)
LOG_LINE_RE = re.compile(
    r'\S+ \S+ \S+ \[(?P<time>[^\]]+)\] "\S+ (?P<path>\S+)[^"]*" (?P<status>\d+) \S+ '
    r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"(?: "(?P<cfip>[^"]*)")?')

# AI platforms that send human click-through referrers
AI_REFERRERS = {
    'chatgpt.com':           'ChatGPT',
    'chat.openai.com':       'ChatGPT',
    'perplexity.ai':         'Perplexity',
    'gemini.google.com':     'Gemini',
    'claude.ai':             'Claude.ai',
    'copilot.microsoft.com': 'Copilot',
    'bing.com':              'Copilot/Bing',
}
GEO_CACHE_PATH = CACHE_DIR + '/ai_referrals_geo.json'
MON = {m:i+1 for i,m in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])}
IGNORE_PATH = re.compile(r'\.(css|js|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|map|xml|txt|json)(\?|$)|/favicon|/assets/', re.I)


def classify(ua, table):
    for sub, lab in table:
        if sub.lower() in ua.lower():
            return lab
    return None


def _load_json(p, d):
    try: return json.loads(open(p).read())
    except Exception: return d


def load_ranges():
    cache = _load_json(RANGES_CACHE, {})
    age = (dt.datetime.utcnow().timestamp() - cache.get('_fetched_epoch', 0)) / 86400
    if cache.get('ranges') and age < RANGE_TTL_DAYS:
        prefixes = cache['ranges']
    else:
        prefixes = {}
        for owner, urls in RANGE_URLS.items():
            got = []
            for u in urls:
                try:
                    data = json.loads(urllib.request.urlopen(u, timeout=20).read().decode())
                    for pfx in data.get('prefixes', []):
                        v = pfx.get('ipv4Prefix') or pfx.get('ipv6Prefix')
                        if v: got.append(v)
                except Exception: pass
            if got: prefixes[owner] = got
        if prefixes:
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                open(RANGES_CACHE, 'w').write(json.dumps({'_fetched_epoch': dt.datetime.utcnow().timestamp(), 'ranges': prefixes}))
            except Exception: pass
        else:
            prefixes = cache.get('ranges', {})
    nets = {}
    for owner, lst in prefixes.items():
        out = []
        for p in lst:
            try: out.append(ipaddress.ip_network(p))
            except Exception: pass
        nets[owner] = out
    return nets


def reverse_dns(ip, cache):
    if ip in cache: return cache[ip]
    socket.setdefaulttimeout(3)
    try: host = socket.gethostbyaddr(ip)[0]
    except Exception: host = ''
    cache[ip] = host
    return host


def verify(label, ip, nets, rc, memo):
    owner, method = VERIFY.get(label, (None, None))
    if not owner or not ip: return None
    key = (owner, ip)
    if key in memo: return memo[key]
    ok = False
    try:
        if method == 'range':
            ipo = ipaddress.ip_address(ip)
            ok = any(ipo in n for n in nets.get(owner, []))
        elif method == 'rdns':
            host = reverse_dns(ip, rc); pat = RDNS_PATTERN.get(owner)
            ok = bool(host and pat and pat.search(host))
    except Exception: ok = False
    memo[key] = ok
    return ok


def load_sitemap():
    """jo.com sitemap paths + lastmod. Returns {path: lastmod}."""
    out = {}
    try:
        xml = open(SITEMAP).read()
    except Exception:
        return out
    for m in re.finditer(r'<url>(.*?)</url>', xml, re.S):
        block = m.group(1)
        loc = re.search(r'<loc>([^<]+)</loc>', block)
        if not loc: continue
        u = loc.group(1)
        if 'joshuaopolko.com' not in u: continue
        path = re.sub(r'^https?://joshuaopolko\.com', '', u) or '/'
        lm = re.search(r'<lastmod>([^<]+)</lastmod>', block)
        out[path] = (lm.group(1)[:10] if lm else '')
    return out


def collect():
    bots = collections.defaultdict(lambda: {'hits':0,'last':'','paths':collections.Counter(),'days':collections.Counter(),'vdays':collections.Counter(),'vok':0,'vtot':0})
    pages = collections.defaultdict(lambda: {'h':0,'ai':0,'lu':0,'t':collections.Counter(),'b':collections.Counter(),'first':'','last':''})
    sc = {'total':0,'paths':collections.Counter(),'spoofed':0,'spoof_ua':collections.Counter()}
    nets = load_ranges(); rc = _load_json(RDNS_CACHE, {}); memo = {}
    total = 0; first = last = None
    cutoff = (dt.date.today() - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    def op(p): return gzip.open(p,'rt',errors='replace') if p.endswith('.gz') else open(p,errors='replace')
    for fp in LOGS:
        try: f = op(fp)
        except Exception: continue
        with f:
            for ln in f:
                total += 1
                m = LOG_LINE_RE.search(ln)
                if not m: continue
                path, ua, cfip = m.group('path'), m.group('ua'), m.group('cfip')
                path = path.split('?', 1)[0]
                t = m.group('time'); day = ''
                if t and len(t) >= 11:
                    day = f"{t[7:11]}-{MON.get(t[3:6],0):02d}-{t[0:2]}"
                    if day < cutoff:
                        continue
                    first = min(first or day, day); last = max(last or day, day)
                botlab = classify(ua, AI) or classify(ua, SEARCH)
                if PROBE.search(path):
                    sc['total'] += 1; sc['paths'][path] += 1
                    if botlab: sc['spoofed'] += 1; sc['spoof_ua'][botlab] += 1
                    continue
                if not botlab: continue
                kind = 'ai' if classify(ua, AI) else 'se'
                b = bots[(kind, botlab)]
                b['hits'] += 1; b['last'] = max(b['last'], day); b['paths'][path] += 1
                if day: b['days'][day] += 1
                if cfip and botlab in VERIFY:
                    v = verify(botlab, cfip, nets, rc, memo)
                    if v is not None:
                        b['vtot'] += 1
                        if v:
                            b['vok'] += 1
                            if day: b['vdays'][day] += 1
                # per-page (skip static assets)
                if not IGNORE_PATH.search(path):
                    typ = TYPE.get(botlab, '')
                    pg = pages[path]
                    pg['h'] += 1; pg['b'][botlab] += 1; pg['t'][typ] += 1
                    if kind == 'ai':
                        pg['ai'] += 1
                        if typ == 'live-user': pg['lu'] += 1
                        if day:
                            pg['first'] = min(pg['first'] or day, day); pg['last'] = max(pg['last'], day)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True); open(RDNS_CACHE, 'w').write(json.dumps(rc))
    except Exception: pass
    return bots, pages, sc, total, first, last


def collect_ai_referrals():
    """Return list of human click-throughs from AI platforms, newest first.
    Skips bot UAs. Only looks at entries with a real IP (cfip field present)."""
    BOT_TOKENS = [t for t, _ in AI + SEARCH]
    events = []
    def op(p): return gzip.open(p, 'rt', errors='replace') if p.endswith('.gz') else open(p, errors='replace')
    for fp in LOGS:
        try: f = op(fp)
        except Exception: continue
        with f:
            for ln in f:
                m = LOG_LINE_RE.search(ln)
                if not m: continue
                ua = m.group('ua')
                if any(t.lower() in ua.lower() for t in BOT_TOKENS): continue
                ref = m.group('ref') or ''
                if not ref or ref == '-': continue
                ref_host = re.sub(r'^https?://([^/?#]+).*', r'\1', ref).lower().lstrip('www.')
                platform = None
                for dom, name in AI_REFERRERS.items():
                    if ref_host == dom or ref_host.endswith('.' + dom):
                        platform = name; break
                if not platform: continue
                path = m.group('path').split('?', 1)[0]
                if IGNORE_PATH.search(path): continue
                # drop scanner bait: env files, login pages, admin panels, wp paths, encoded traversals, Java probes
                if re.search(r'(?:\.env|wp-|/login|/admin|\.sql|\.php|/xmlrpc|/proc/|%2e%2e|%252e|%c0%ae|WEB-INF|\.properties|/wordpress/|/site/$)', path, re.I): continue
                cfip = m.group('cfip') or ''
                t = m.group('time')
                day = f"{t[7:11]}-{MON.get(t[3:6],0):02d}-{t[0:2]}" if t and len(t) >= 11 else ''
                events.append({'day': day, 'platform': platform, 'path': path, 'ip': cfip, 'ref': ref})
    events.sort(key=lambda e: e['day'], reverse=True)
    return events


def geo_lookup(ips):
    """Batch-lookup IPs at ip-api.com; returns {ip: {country, countryCode, city, org}} from cache."""
    cache = _load_json(GEO_CACHE_PATH, {})
    pending = [ip for ip in ips if ip and ip not in cache]
    if pending:
        print(f'  geo-lookup: {len(pending)} new IPs via ip-api.com...')
        for i in range(0, len(pending), 100):
            chunk = pending[i:i + 100]
            body = [{'query': ip, 'fields': 'status,query,country,countryCode,city,org,isp'} for ip in chunk]
            req = urllib.request.Request('http://ip-api.com/batch',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    for res in json.loads(r.read()):
                        ip = res.get('query', '')
                        cache[ip] = ({'country': res.get('country',''), 'countryCode': res.get('countryCode',''),
                                      'city': res.get('city',''), 'org': res.get('org') or res.get('isp','')}
                                     if res.get('status') == 'success' else None)
            except Exception as e:
                print(f'  ip-api batch failed: {e}')
        try:
            os.makedirs(CACHE_DIR, exist_ok=True); open(GEO_CACHE_PATH, 'w').write(json.dumps(cache))
        except Exception: pass
    return cache


# ── styling + client layer (shared by render_page) ────────────────────────
CSS = """
.lede{font:400 16px/1.6 var(--sans);color:var(--ink2);margin:.3em 0 1.2em}
.standfirst{border-top:2px solid var(--ink);border-bottom:1px solid var(--line);padding:13px 0 15px;margin:1.7em 0 .4em}
.standfirst .desk{display:block;font:700 11px/1 var(--sans);letter-spacing:.15em;text-transform:uppercase;color:var(--accent);margin-bottom:9px}
.standfirst p{margin:0;font:400 18px/1.5 var(--serif);color:var(--ink)}
.standfirst b{font-weight:700}.standfirst a{color:var(--accent-ink)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:1.4em 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:15px 17px}
.card .v{font:700 27px/1 var(--sans);color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.card .l{font:600 11.5px/1.3 var(--sans);color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-top:7px}
.card .s{font:400 12px/1.4 var(--sans);color:var(--muted);margin-top:3px}
.card.star{border-color:#e3c9cb;background:linear-gradient(180deg,#fff,#fdf6f6)}.card.star .v{color:var(--accent)}
.card.good .v{color:#0a7c3f}.card.warn .v{color:#9a6a12}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:1.1em 0}
.grid2>*{min-width:0}.panelbox{min-width:0}
@media(max-width:680px){.grid2{grid-template-columns:1fr}}
.panelbox{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:16px 18px}
.panelbox.wide{margin:1.1em 0}
.panelbox h3{margin:0 0 .15em;font:700 15px/1.3 var(--sans)}
.panelbox .sub{font:400 12.5px/1.45 var(--sans);color:var(--muted);margin:0 0 .9em}
figure.chart{margin:0}
.chartnote{font:400 12.5px/1.55 var(--sans);color:var(--muted);margin:.8em 0 0;padding-top:.7em;border-top:1px dashed var(--line)}
.chartnote b{color:var(--ink2);font-weight:600}
.freshrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:.2em 0 1.3em}
.freshchip{display:inline-block;font:600 11.5px/1.45 var(--sans);color:var(--accent-ink);background:var(--code-bg);border:1px solid var(--line);border-radius:13px;padding:6px 11px;letter-spacing:.01em;max-width:100%}
.freshnote{font:400 12px/1.4 var(--sans);color:var(--muted)}.freshnote b{color:var(--ink2)}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px;font:500 12.5px var(--sans);color:var(--ink2)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.legend b{font-variant-numeric:tabular-nums;color:var(--ink)}
.tip{position:fixed;z-index:40;background:#1b1a17;color:#fff;font:500 12px/1.5 var(--sans);padding:8px 11px;border-radius:8px;pointer-events:none;opacity:0;transition:opacity .08s;max-width:230px;box-shadow:0 4px 16px rgba(0,0,0,.25)}
.tip .sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
.ebar{display:grid;grid-template-columns:148px 1fr 96px;gap:9px;align-items:center;margin:6px 0;font:500 13px var(--sans);cursor:pointer}
.ebar .el{color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ebar .etrack{background:#eceae3;border-radius:5px;height:17px;overflow:hidden}
.ebar .et{display:block;height:100%;border-radius:5px;transition:filter .1s}
.ebar:hover .et{filter:brightness(.92)}
.ebar .en{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.ebar.sel .el{font-weight:700;color:var(--accent)}.ebar.sel .etrack{outline:2px solid var(--accent);outline-offset:1px}
.ck{color:#0a7c3f;font-weight:700}
.cs{border-collapse:collapse;width:100%;margin:1em 0;font:400 14px/1.5 var(--sans)}
.cs th,.cs td{text-align:left;padding:7px 11px;border-bottom:1px solid var(--line)}
.cs th{font:700 11.5px/1.2 var(--sans);text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.cs td.n,.cs th.n{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.cs td.eng,.cs td.tg{color:var(--muted)}.cs td.d{color:var(--muted);white-space:nowrap}
.cs td.lu{color:#0a7c3f}.cs td.p{font-size:13px;word-break:break-all}
.cs tr.prow{cursor:pointer}.cs tr.prow:hover{background:var(--code-bg)}
.vok{color:#0a7c3f;font-weight:600}.vbad{color:var(--accent);font-weight:700}
#tools{margin:1em 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
#q{flex:1;min-width:180px;padding:8px 11px;border:1px solid var(--line);border-radius:8px;font:400 14px var(--sans)}
.chip{padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:#fff;font:600 12.5px var(--sans);color:var(--ink2);cursor:pointer}
.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
#eng{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font:400 13.5px var(--sans)}
.showall{margin:6px 0 4px;background:none;border:1px solid var(--line);border-radius:8px;padding:8px 15px;font:600 13px var(--sans);color:var(--ink2);cursor:pointer}
.showall:hover{border-color:var(--accent);color:var(--accent)}
.det{background:var(--code-bg)}.det td{padding:10px 14px}
.bbar{display:grid;grid-template-columns:170px 1fr 48px;gap:8px;align-items:center;margin:2px 0;font:400 12.5px var(--sans)}
.bbar .bn{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.bbar .bt{background:#e7e3da;border-radius:4px;height:11px;overflow:hidden}.bbar .bf{height:100%;background:var(--accent)}
.bd{color:var(--muted);font-variant-numeric:tabular-nums}.bt{background:#eef0f6;border-radius:4px;height:13px;overflow:hidden}.bf{display:block;height:100%;background:var(--accent);border-radius:4px}
.bars{margin:.4em 0}.bar-row{display:grid;grid-template-columns:52px 1fr 56px;gap:10px;align-items:center;margin:3px 0;font:400 13px var(--sans)}.bn{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
ul.blind{columns:2;font:400 13.5px/1.7 var(--sans);margin:1em 0}@media(max-width:600px){ul.blind{columns:1}}
.sbar{display:flex;height:34px;border-radius:9px;overflow:hidden;margin:4px 0 2px;background:#eceae3}
.sbar span{display:flex;align-items:center;justify-content:center;height:100%;color:#fff;font:700 12px var(--sans);overflow:hidden;white-space:nowrap}
.pbar{margin:9px 0;font:500 12.5px var(--sans)}
.pbar .pl{display:flex;justify-content:space-between;gap:12px;margin-bottom:4px;color:var(--ink2)}
.pbar .pl code{font:500 12px var(--mono);background:none;padding:0;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.pbar .pl b{font-variant-numeric:tabular-nums;color:var(--ink);flex:none}
.pbar .ptrack{background:#eceae3;border-radius:5px;height:12px;overflow:hidden}
.pbar .pf{display:block;height:100%;border-radius:5px;background:#7d1d24}
details.raw{margin:1em 0;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
details.raw>summary{cursor:pointer;padding:12px 16px;font:600 13.5px var(--sans);color:var(--ink2);list-style:none}
details.raw>summary::-webkit-details-marker{display:none}
details.raw>summary::before{content:"▸ ";color:var(--accent)}
details.raw[open]>summary::before{content:"▾ "}
details.raw[open]>summary{border-bottom:1px solid var(--line)}
details.raw>div,details.raw>h3{padding:0 16px}details.raw .cs{margin:.6em 0}
.callout{font:500 13.5px/1.5 var(--sans);color:var(--ink2);margin:.7em 0 0}.callout b{color:var(--ink)}
@media(max-width:600px){
  .cs{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .ebar{grid-template-columns:118px 1fr 78px}
  .bbar{grid-template-columns:110px 1fr 40px}
  #tools{gap:6px}#q{min-width:140px}
}
"""

JS = r"""
(function(){
  var D=null, state={type:'all', eng:'all', q:'', all:false};
  var TC={'live-user':'#7d1d24','ai-search':'#c2772e','ai-training':'#2f6f63','search':'#4a5d7e'};
  var TL={'live-user':'AI live-fetch','ai-search':'AI search','ai-training':'AI training','search':'Search index'};
  var AIT=['live-user','ai-search','ai-training'];
  var tip=document.createElement('div'); tip.className='tip'; document.body.appendChild(tip);
  function showTip(h,e){tip.innerHTML=h;tip.style.opacity=1;moveTip(e);}
  function moveTip(e){var x=e.clientX+14,y=e.clientY+16;if(x+240>innerWidth)x=e.clientX-240;tip.style.left=x+'px';tip.style.top=y+'px';}
  function hideTip(){tip.style.opacity=0;}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
  function nf(n){return (n||0).toLocaleString()}

  fetch((window.DATA_URL||'data.json')+'?v='+Date.now()).then(function(r){return r.json()}).then(function(d){D=d;init()}).catch(function(){});

  var SCAT={'WordPress':'#7d1d24','Secrets & config':'#c2772e','Git exposure':'#2f6f63','Admin / RCE':'#4a5d7e','Other':'#9a9388'};
  function init(){
    dailyChart(); mixDonut(); engineBars(); searchBars(); verifyBar(); trafficReality(); scannerCharts();
    var engs={}; D.pages.forEach(function(p){Object.keys(p.b).forEach(function(b){engs[b]=1})});
    var sel=document.getElementById('eng');
    Object.keys(engs).sort().forEach(function(b){var o=document.createElement('option');o.value=b;o.textContent=b;sel.appendChild(o)});
    document.getElementById('q').addEventListener('input',function(e){state.q=e.target.value.toLowerCase();render()});
    sel.addEventListener('change',function(e){state.eng=e.target.value;syncEngSel();render()});
    Array.prototype.forEach.call(document.querySelectorAll('.chip'),function(c){c.addEventListener('click',function(){
      state.type=c.dataset.t;chipSync();render();})});
    document.getElementById('showall').addEventListener('click',function(){state.all=!state.all;render()});
    render();
  }
  function chipSync(){Array.prototype.forEach.call(document.querySelectorAll('.chip'),function(x){x.classList.toggle('on',x.dataset.t===state.type)});}
  function syncEngSel(){Array.prototype.forEach.call(document.querySelectorAll('.ebar'),function(x){x.classList.toggle('sel',state.eng!=='all'&&x.getAttribute('data-e')===state.eng)});}

  function legend(id,items){var el=document.getElementById(id);if(!el)return;
    el.innerHTML=items.map(function(it){return '<span><i style="background:'+it.c+'"></i>'+it.t+(it.n!=null?' <b>'+nf(it.n)+'</b>'+(it.pct!=null?' ('+it.pct+'%)':''):'')+'</span>'}).join('');}

  function dailyChart(){
    var box=document.getElementById('c-daily');if(!box)return;
    var S=(D.series||[]); if(!S.length){var pb=box.closest('.panelbox');if(pb)pb.style.display='none';return;}
    var W=720,H=210,padL=36,padB=22,padT=10,padR=6,iw=W-padL-padR,ih=H-padT-padB;
    var max=1;S.forEach(function(d){var t=0;AIT.forEach(function(k){t+=d[k]||0});if(t>max)max=t;});
    var step=Math.pow(10,Math.floor(Math.log(max)/Math.LN10));var nmax=Math.ceil(max/step)*step||max;
    var bw=iw/S.length,bar=Math.min(36,bw*0.66);
    var g=['<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Daily AI crawler activity by type">'];
    [0,0.5,1].forEach(function(f){var y=padT+ih*(1-f);
      g.push('<line x1="'+padL+'" y1="'+y.toFixed(1)+'" x2="'+(W-padR)+'" y2="'+y.toFixed(1)+'" stroke="#e7e3da"/>');
      g.push('<text x="'+(padL-7)+'" y="'+(y+3).toFixed(1)+'" text-anchor="end" fill="#7a766c" font-size="10">'+nf(Math.round(nmax*f))+'</text>');});
    S.forEach(function(d,i){var cx=padL+bw*i+(bw-bar)/2,yacc=padT+ih;
      AIT.forEach(function(k){var v=d[k]||0;if(!v)return;var h=ih*v/nmax;yacc-=h;
        g.push('<rect x="'+cx.toFixed(1)+'" y="'+yacc.toFixed(1)+'" width="'+bar.toFixed(1)+'" height="'+h.toFixed(1)+'" fill="'+TC[k]+'" data-i="'+i+'"/>');});
      if(S.length<=10||i%2===0)g.push('<text x="'+(cx+bar/2).toFixed(1)+'" y="'+(H-7)+'" text-anchor="middle" fill="#7a766c" font-size="10">'+d.d.slice(5)+'</text>');});
    g.push('</svg>');box.innerHTML=g.join('');
    var svg=box.querySelector('svg');
    svg.addEventListener('mousemove',function(e){var t=e.target;if(t.tagName!=='rect'){hideTip();return;}
      var d=S[+t.getAttribute('data-i')];var tot=AIT.reduce(function(a,k){return a+(d[k]||0)},0);
      var rows=AIT.filter(function(k){return d[k]}).map(function(k){return '<div><span class="sw" style="background:'+TC[k]+'"></span>'+TL[k]+': <b>'+nf(d[k])+'</b></div>'}).join('');
      showTip('<b>'+d.d+'</b> &middot; '+nf(tot)+' AI hits'+rows,e);});
    svg.addEventListener('mouseleave',hideTip);
    legend('l-daily',AIT.map(function(k){return {c:TC[k],t:TL[k]}}));
  }

  function mixDonut(){
    var box=document.getElementById('c-mix');if(!box)return;
    var bt=D.byType||{};var segs=AIT.map(function(k){return {k:k,v:bt[k]||0}}).filter(function(s){return s.v>0});
    var tot=segs.reduce(function(a,s){return a+s.v},0)||1;
    var r=64,sw=26,C=2*Math.PI*r,off=0;
    var g=['<svg viewBox="0 0 168 168" role="img" aria-label="AI crawler request mix">'];
    g.push('<circle cx="84" cy="84" r="'+r+'" fill="none" stroke="#eceae3" stroke-width="'+sw+'"/>');
    segs.forEach(function(s){var len=C*s.v/tot;
      g.push('<circle cx="84" cy="84" r="'+r+'" fill="none" stroke="'+TC[s.k]+'" stroke-width="'+sw+'" stroke-linecap="butt" stroke-dasharray="'+len.toFixed(2)+' '+(C-len).toFixed(2)+'" stroke-dashoffset="'+(-off).toFixed(2)+'" transform="rotate(-90 84 84)"><title>'+TL[s.k]+': '+nf(s.v)+'</title></circle>');off+=len;});
    g.push('<text x="84" y="80" text-anchor="middle" font-size="27" font-weight="700" fill="#1b1a17">'+nf(tot)+'</text>');
    g.push('<text x="84" y="99" text-anchor="middle" font-size="11" fill="#7a766c">AI fetches</text></svg>');
    box.innerHTML=g.join('');
    legend('l-mix',segs.map(function(s){return {c:TC[s.k],t:TL[s.k],n:s.v,pct:Math.round(100*s.v/tot)}}));
  }

  function engineBars(){
    var box=document.getElementById('c-eng');if(!box||!D.byEngine)return;
    var ai=D.byEngine.filter(function(e){return e.k==='ai'}).slice(0,8);
    if(!ai.length){box.innerHTML='<p class="sub">No AI crawlers in the window.</p>';return;}
    var max=ai[0].h||1;
    box.innerHTML=ai.map(function(e){var w=Math.max(3,Math.round(100*e.h/max));
      var ck=(e.v&&e.v[1]>0&&e.v[0]===e.v[1])?' <span class="ck" title="verified real bot">&#10003;</span>':'';
      return '<div class="ebar" data-e="'+esc(e.e)+'" title="Click to filter the page explorer by '+esc(e.e)+'"><span class="el">'+esc(e.e)+'</span><span class="etrack"><span class="et" style="width:'+w+'%;background:'+TC[e.type]+'"></span></span><span class="en">'+nf(e.h)+ck+'</span></div>';}).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.ebar'),function(b){b.addEventListener('click',function(){
      var en=b.getAttribute('data-e');state.eng=(state.eng===en?'all':en);
      document.getElementById('eng').value=state.eng;syncEngSel();render();
      document.getElementById('explorer-top').scrollIntoView({behavior:'smooth',block:'start'});});});
  }

  function hbar(items, max, color){
    return items.map(function(it){var w=Math.max(3,Math.round(100*it.h/max));
      var ck=(it.v&&it.v[1]>0&&it.v[0]===it.v[1])?' <span class="ck" title="verified real bot">&#10003;</span>':'';
      return '<div class="ebar" style="cursor:default"><span class="el">'+esc(it.e)+'</span><span class="etrack"><span class="et" style="width:'+w+'%;background:'+(color||TC[it.type]||'#4a5d7e')+'"></span></span><span class="en">'+nf(it.h)+ck+'</span></div>';
    }).join('');
  }
  function searchBars(){
    var box=document.getElementById('c-se');if(!box||!D.byEngine)return;
    var se=D.byEngine.filter(function(e){return e.k==='se'}).slice(0,10);
    box.innerHTML=se.length?hbar(se, se[0].h||1, '#4a5d7e'):'<p class="sub">No search engines in the window.</p>';
  }
  function verifyBar(){
    var box=document.getElementById('c-verify');if(!box||!D.byEngine)return;
    var V=0,F=0,U=0;
    D.byEngine.forEach(function(e){var ok=e.v?e.v[0]:0, tot=e.v?e.v[1]:0; V+=ok; F+=Math.max(0,tot-ok); U+=Math.max(0,e.h-tot)});
    var checkable=V+F, all=V+F+U||1;
    var cap=document.getElementById('verify-cap');
    if(!checkable){box.innerHTML='<div class="sbar"><span style="width:100%;background:#cfc9bf;color:#7a766c">verification filling in</span></div>';
      if(cap)cap.textContent='Real-IP verification is still collecting; it fills in daily.';return;}
    function seg(v,c,lab){return v?'<span style="width:'+(100*v/checkable)+'%;background:'+c+'" title="'+lab+': '+nf(v)+'">'+(v/checkable>0.1?nf(v):'')+'</span>':''}
    box.innerHTML='<div class="sbar">'+seg(V,'#1f8f4e','Verified genuine')+seg(F,'#c2772e','Unconfirmed')+'</div>';
    legend('l-verify',[{c:'#1f8f4e',t:'Verified genuine',n:V},{c:'#c2772e',t:'Unconfirmed',n:F}]);
    if(cap)cap.innerHTML='<b>'+Math.round(100*V/checkable)+'%</b> of checkable crawler traffic confirmed genuine. Only <b>'+nf(checkable)+'</b> of '+nf(all)+' requests are checkable so far (the rest predate real-IP logging) and this fills in daily. Unconfirmed = operator IP missing or reverse-DNS not resolving (common for Anthropic), not necessarily an impostor.';
  }
  function trafficReality(){
    var box=document.getElementById('c-reality');if(!box||!D.totals)return;
    var segs=[{k:'Scanner probes',v:D.totals.scanners||0,c:'#3a3530'},{k:'AI crawlers',v:D.totals.ai||0,c:'#7d1d24'},{k:'Search engines',v:D.totals.se||0,c:'#4a5d7e'}];
    var T=segs.reduce(function(a,s){return a+s.v},0)||1;
    box.innerHTML='<div class="sbar">'+segs.map(function(s){return s.v?'<span style="width:'+(100*s.v/T)+'%;background:'+s.c+'" title="'+s.k+': '+nf(s.v)+'">'+(s.v/T>0.05?Math.round(100*s.v/T)+'%':'')+'</span>':''}).join('')+'</div>';
    legend('l-reality',segs.map(function(s){return {c:s.c,t:s.k,n:s.v,pct:Math.round(100*s.v/T)}}));
  }
  function scannerCharts(){
    var s=D.scanners;if(!s)return;
    var dbox=document.getElementById('c-scat');
    if(dbox){
      var cats=Object.keys(s.cats||{}).map(function(k){return {k:k,v:s.cats[k]}}).filter(function(x){return x.v>0}).sort(function(a,b){return b.v-a.v});
      var tot=cats.reduce(function(a,c){return a+c.v},0)||1,r=64,sw=26,C=2*Math.PI*r,off=0;
      var g=['<svg viewBox="0 0 168 168" role="img" aria-label="Scanner probe categories"><circle cx="84" cy="84" r="'+r+'" fill="none" stroke="#eceae3" stroke-width="'+sw+'"/>'];
      cats.forEach(function(c){var len=C*c.v/tot;g.push('<circle cx="84" cy="84" r="'+r+'" fill="none" stroke="'+(SCAT[c.k]||'#9a9388')+'" stroke-width="'+sw+'" stroke-dasharray="'+len.toFixed(2)+' '+(C-len).toFixed(2)+'" stroke-dashoffset="'+(-off).toFixed(2)+'" transform="rotate(-90 84 84)"><title>'+esc(c.k)+': '+nf(c.v)+'</title></circle>');off+=len;});
      g.push('<text x="84" y="80" text-anchor="middle" font-size="22" font-weight="700" fill="#1b1a17">'+(tot>=1000?Math.round(tot/1000)+'k':nf(tot))+'</text><text x="84" y="99" text-anchor="middle" font-size="11" fill="#7a766c">probes</text></svg>');
      dbox.innerHTML=g.join('');
      legend('l-scat',cats.map(function(c){return {c:SCAT[c.k]||'#9a9388',t:c.k,n:c.v,pct:Math.round(100*c.v/tot)}}));
    }
    var pbox=document.getElementById('c-spath');
    if(pbox&&s.paths&&s.paths.length){var mx=s.paths[0][1]||1;
      pbox.innerHTML=s.paths.map(function(p){var w=Math.max(2,Math.round(100*p[1]/mx));
        return '<div class="pbar"><div class="pl"><code>'+esc(p[0])+'</code><b>'+nf(p[1])+'</b></div><div class="ptrack"><span class="pf" style="width:'+w+'%"></span></div></div>';}).join('');
    }
  }

  function render(){
    if(!D)return;
    var rows=D.pages.filter(function(p){
      if(state.q && p.p.toLowerCase().indexOf(state.q)<0)return false;
      if(state.eng!=='all' && !(p.b[state.eng]>0))return false;
      if(state.type!=='all' && !(p.t[state.type]>0))return false;
      return true;});
    var key=state.type==='live-user'?'lu':(state.eng!=='all'?'eng':'ai');
    rows.sort(function(a,b){return key==='eng'?(b.b[state.eng]||0)-(a.b[state.eng]||0):b[key]-a[key];});
    var shown=state.all?rows:rows.slice(0,25);
    var engHdr=state.eng!=='all'?esc(state.eng)+' hits':'AI hits';
    var h=['<table class="cs"><thead><tr><th>Page</th><th class="n">'+engHdr+'</th><th class="n">Live-fetch</th><th>Top engine</th></tr></thead><tbody>'];
    shown.forEach(function(p,i){var te=Object.keys(p.b).sort(function(a,b){return p.b[b]-p.b[a]})[0]||'';
      var disp=state.eng!=='all'?(p.b[state.eng]||0):p.ai;
      h.push('<tr class="prow" data-i="'+i+'"><td class="p"><a href="'+esc(p.p)+'">'+esc(p.p)+'</a></td><td class="n">'+nf(disp)+'</td><td class="n lu">'+nf(p.lu)+'</td><td class="eng">'+esc(te)+'</td></tr>');});
    if(!shown.length)h.push('<tr><td colspan="4" class="muted">No pages match this filter.</td></tr>');
    h.push('</tbody></table>');
    var c=document.getElementById('explorer');c.innerHTML=h.join('');
    document.getElementById('pcount').textContent=nf(rows.length);
    var sa=document.getElementById('showall');
    if(rows.length>25){sa.style.display='';sa.textContent=state.all?'Show top 25 only':'Show all '+nf(rows.length)+' pages';}
    else sa.style.display='none';
    Array.prototype.forEach.call(c.querySelectorAll('.prow'),function(tr){tr.addEventListener('click',function(e){
      if(e.target.tagName==='A')return;toggle(tr,shown[+tr.dataset.i]);});});
  }
  function engType(e){var f=(D.byEngine||[]).filter(function(x){return x.e===e})[0];return f?f.type:'live-user';}
  function toggle(tr,p){
    var nx=tr.nextElementSibling;if(nx&&nx.classList.contains('det')){nx.remove();return;}
    var bs=Object.keys(p.b).sort(function(a,b){return p.b[b]-p.b[a]});
    var mx=Math.max.apply(null,bs.map(function(b){return p.b[b]}))||1;
    var rws=bs.map(function(b){var w=Math.round(100*p.b[b]/mx);return '<div class="bbar"><span>'+esc(b)+'</span><span class="bt"><span class="bf" style="width:'+w+'%;background:'+(TC[engType(b)]||'#7d1d24')+'"></span></span><span class="bn">'+nf(p.b[b])+'</span></div>'}).join('');
    var meta='First AI fetch '+(p.first||'?')+' &middot; last '+(p.last||'?')+' &middot; '+nf(p.h)+' total hits';
    var d=document.createElement('tr');d.className='det';
    d.innerHTML='<td colspan="4"><div style="margin-bottom:6px;color:var(--muted);font:400 12.5px var(--sans)">'+meta+'</div>'+rws+'</td>';
    tr.parentNode.insertBefore(d,tr.nextSibling);
  }
})();
"""


def render_page(data, nav, srv):
    """Build the full index.html from the data dict + server-rendered table strings."""
    first, last = data['window']
    now = data['generated']
    t = data['totals']
    try:
        ndays = (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1
        win = f'Rolling {ndays}-day window ({first} to {last})'
    except Exception:
        win = f'Window {first} to {last}'
    # machine-readable summary of every chart on the page (LLMs / no-JS readers get the numbers without executing the SVG layer)
    meta_json = json.dumps({'window': data['window'], 'generated': now, 'totals': t,
                            'byType': data.get('byType', {}), 'byEngine': data.get('byEngine', [])[:25],
                            'scanners': data.get('scanners', {})}, separators=(',', ':'))
    if CFG['chrome'] == 'jo':
        head_links = ('<link rel="icon" href="/favicon.ico?v=6" sizes="any"><link rel="manifest" href="/site.webmanifest?v=6">\n'
                      '<link rel="stylesheet" href="/assets/site.css?v=11">\n')
        nav_js = '<script src="/assets/nav.js?v=6" defer></script>\n'
        header = '<header class="site-head"><a class="brand" href="/">' + CFG['brand'] + '</a>' + nav + '</header>\n'
        lede = ('<p class="lede">AI engines fetch a page <em>before</em> they cite it, so this is the citation pipeline in the open. '
                'The <strong>AI live-fetch</strong> count is pages being pulled into answers right now; the <strong>blind spots</strong> '
                'are pages AI never sees; the <strong>Verified</strong> checks separate real bots from impostors. This is the '
                '"watch your logs" step from <a href="/geo-field-manual/">the GEO Field Manual</a>, made live.</p>\n')
    else:
        head_links = '<link rel="icon" type="image/svg+xml" href="/favicon.svg"><link rel="apple-touch-icon" href="/favicon.svg">\n'
        nav_js = ''
        header = ('<header class="site-head" style="display:flex;align-items:center;justify-content:space-between;'
                  'max-width:72rem;margin:0 auto;padding:16px 20px;border-bottom:1px solid var(--line)">'
                  '<a class="brand" href="/" style="font:700 19px/1 var(--serif);color:var(--ink);text-decoration:none">' + CFG['brand'] + '</a>'
                  '<a href="/" style="font:500 14px var(--sans);color:var(--accent-ink);text-decoration:none">&larr; back to openings</a></header>\n')
        lede = ('<p class="lede">Every bot that hits NowServingTO lands in the raw server log; this reads them back. Which AI engines '
                'fetch our restaurant data, which pages they pull into live answers, what they ignore, whether the traffic is a '
                'verified crawler or an impostor, and what the data costs to run. <strong>AI live-fetch</strong> means a page pulled '
                'into an answer right now.</p>\n')
    # ── plain-English chart explainers + freshness (server-rendered so LLMs ingest them) ──
    series = data.get('series', [])
    def _dsum(r): return r.get('live-user', 0) + r.get('ai-search', 0) + r.get('ai-training', 0)
    peak = max(series, key=_dsum) if series else None
    bt = data.get('byType', {})
    eng = [e for e in data.get('byEngine', []) if e['k'] == 'ai']
    fw, lw = (first or '?'), (last or '?')
    fresh_chip = ('<div class="freshrow"><span class="freshchip">Updated ' + now + ' · data ' + fw
                  + ' → ' + lw + ' · rebuilt daily</span> '
                  '<span class="freshnote">Dates are <b>first-seen in the server log</b>, not publication dates.</span></div>\n')
    daily_note = ('<p class="chartnote"><b>How to read this:</b> daily counts of AI-crawler hits from ' + fw + ' to ' + lw
                  + ', one bar per day, each segmented by crawler intent (AI live-fetch, AI search, AI training).'
                  + (' Busiest day was ' + peak['d'] + ' with ' + format(_dsum(peak), ',') + ' AI hits.' if peak else '')
                  + ' Data window first-seen ' + fw + ', latest ' + lw + '; last updated ' + now + '.</p>\n')
    mix_note = (('<p class="chartnote"><b>How to read this:</b> the ' + format(t['ai'], ',') + ' AI fetches in this window split by intent: '
                 + ', '.join(format(bt.get(k, 0), ',') + ' ' + TYPE_LABEL[k].lower() for k in AI_TYPES if bt.get(k))
                 + '. Window ' + fw + ' to ' + lw + '.</p>\n') if bt else '')
    eng_note = (('<p class="chartnote"><b>How to read this:</b> AI crawlers ranked by hit count, ' + fw + ' to ' + lw
                 + '. Top engine ' + html.escape(eng[0]['e']) + ' with ' + format(eng[0]['h'], ',') + ' fetches'
                 + (', then ' + html.escape(eng[1]['e']) + ' (' + format(eng[1]['h'], ',') + ').' if len(eng) > 1 else '.')
                 + '</p>\n') if eng else '')
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            + head_links +
            '<meta name="theme-color" content="' + CFG['theme'] + '">\n'
            '<meta name="robots" content="index, follow, max-image-preview:large">\n'
            '<title>' + CFG['title'] + '</title>\n'
            '<meta name="description" content="A live, interactive dashboard of which AI and search engines crawl this site, which pages they fetch for answers, what they ignore, and whether the traffic is verified. Built from raw server logs.">\n'
            '<link rel="canonical" href="' + CFG['canonical'] + '">\n'
            '<style>' + CFG['rootvars'] + CFG['base'] + CSS + '</style>\n'
            + nav_js + '</head>\n<body>\n'
            + header +
            '<main class="article"><h1>' + CFG['h1'] + '</h1>\n'
            f'<p class="byline" style="font:400 14px/1.5 var(--sans);color:var(--muted);margin:.2em 0 0">A live dashboard of which AI and search engines crawl this site, which pages they pull for answers, and what they ignore. Parsed from raw server logs, verified against operator IP ranges. {win}. Generated {now}.</p>\n'
            '<div class="post-body">\n'
            + lede
            + srv.get('ip_intel', '')
            # ── stat cards ──
            + srv['cards'] +
            fresh_chip +
            # ── daily activity (full width) ──
            '<div class="panelbox wide">\n'
            '<h3>AI crawler activity, last 14 days</h3>\n'
            '<p class="sub">Daily AI hits, stacked by what the crawler is doing. Hover any day for the breakdown.</p>\n'
            '<figure class="chart" id="c-daily" role="img" aria-label="Bar chart: daily AI-crawler hits over the last 14 days, ' + fw + ' to ' + lw + ', segmented by intent">' + srv['daily_fallback'] + '</figure>\n'
            '<div class="legend" id="l-daily"></div>\n'
            + daily_note +
            '</div>\n'
            # ── two-up: mix donut + engine bars ──
            '<div class="grid2">\n'
            '<div class="panelbox">\n'
            '<h3>What the AI crawlers want</h3>\n'
            '<p class="sub">Every AI fetch in the window, split by intent.</p>\n'
            '<figure class="chart" id="c-mix" role="img" aria-label="Donut chart: AI fetches split by intent (live-fetch, AI search, AI training)" style="max-width:230px;margin:0 auto">' + srv['mix_fallback'] + '</figure>\n'
            '<div class="legend" id="l-mix"></div>\n'
            + mix_note +
            '</div>\n'
            '<div class="panelbox">\n'
            '<h3>Top AI engines</h3>\n'
            '<p class="sub">By hits. Click one to filter the page explorer below.</p>\n'
            '<div id="c-eng" role="img" aria-label="Bar chart: AI engines ranked by hit count, ' + fw + ' to ' + lw + '">' + srv['eng_fallback'] + '</div>\n'
            + eng_note +
            '</div>\n'
            '</div>\n'
            # ── Live Desk standfirst (editorial read of the live-fetch signal) ──
            + srv['live_desk'] +
            # ── explorer (drill-down) ──
            '<h2 id="explorer-top">Pages AI is fetching</h2>\n'
            '<p>Search, filter by crawler intent or engine, and click any row to see which bots pull it. Showing the top 25 by default. <span id="pcount">' + str(len(data['pages'])) + '</span> pages have AI activity.</p>\n'
            '<div id="tools"><input id="q" placeholder="filter pages…" aria-label="filter pages">'
            '<span class="chip on" data-t="all">All</span><span class="chip" data-t="live-user">Live-fetch</span>'
            '<span class="chip" data-t="ai-search">AI search</span><span class="chip" data-t="ai-training">AI training</span>'
            '<select id="eng"><option value="all">All engines</option></select></div>\n'
            '<div id="explorer">\n'
            '<table class="cs"><thead><tr><th>Page</th><th class="n">AI hits</th><th class="n">Live-fetch</th><th>Top type</th></tr></thead><tbody>'
            + srv['top_pages'] + '</tbody></table>\n</div>\n'
            '<button class="showall" id="showall" style="display:none">Show all pages</button>\n'
            '<h2>Blind spots</h2>\n'
            f'<p>Indexed pages AI has <strong>not</strong> fetched in this window, your fix-list (orphan pages, weak internal links, stale content). {len(data["blind"])} total.</p>\n'
            '<ul class="blind">' + srv['blind_rows'] + '</ul>\n'
            '<h2>Freshness: how fast AI picks up updates</h2>\n'
            '<table class="cs"><thead><tr><th>Page</th><th>Updated</th><th>First AI fetch</th><th class="n">Lag</th></tr></thead><tbody>' + srv['fresh_rows'] + '</tbody></table>\n'
            + srv['referrals']
            # ── who is crawling: search engines + verification ──
            + '<h2>Who is crawling</h2>\n'
            '<div class="grid2">\n'
            '<div class="panelbox">\n'
            '<h3>Search engines</h3>\n<p class="sub">Classic index crawlers, by hits.</p>\n'
            '<div id="c-se">' + srv['se_fallback'] + '</div>\n'
            '</div>\n'
            '<div class="panelbox">\n'
            '<h3>Are they who they claim?</h3>\n<p class="sub">Crawler traffic checked against each operator\'s published IP ranges and reverse-DNS.</p>\n'
            '<div class="chart" id="c-verify"></div>\n<div class="legend" id="l-verify"></div>\n'
            '<p class="callout" id="verify-cap"></p>\n'
            '</div>\n'
            '</div>\n'
            '<details class="raw"><summary>Full crawler tables (raw numbers)</summary>\n'
            '<h3>AI crawlers</h3>\n' + srv['bot_ai'] + '\n<h3>Search engines</h3>\n' + srv['bot_se'] + '\n</details>\n'
            # ── under attack: scanner visuals ──
            + (('<h2>Under attack: what scanners hunt for</h2>\n'
                f'<p><b>{srv["scanner_total"]:,}</b> requests probing for exposed files, admin panels, and known exploits, every one a 404 here. '
                + (f'<b>{srv["scanner_spoofed"]:,}</b> forged a real crawler\'s user-agent to blend in.' if srv['scanner_spoofed'] else '') + '</p>\n'
                '<div class="panelbox wide">\n'
                '<h3>Bot traffic reality</h3>\n<p class="sub">Every bot request in the window. Hostile scanning dwarfs the legitimate crawlers.</p>\n'
                '<div class="chart" id="c-reality">' + srv['reality_fallback'] + '</div>\n<div class="legend" id="l-reality"></div>\n'
                '</div>\n'
                '<div class="grid2">\n'
                '<div class="panelbox">\n'
                '<h3>What they hunt for</h3>\n<p class="sub">Probes grouped by target. Mostly WordPress, on a site that runs none.</p>\n'
                '<div class="chart" id="c-scat" style="max-width:230px;margin:0 auto">' + srv['scat_fallback'] + '</div>\n<div class="legend" id="l-scat"></div>\n'
                '</div>\n'
                '<div class="panelbox">\n'
                '<h3>Top probed paths</h3>\n<p class="sub">The most-hammered URLs. None of them exist here.</p>\n'
                '<div id="c-spath">' + srv['spath_fallback'] + '</div>\n'
                '</div>\n'
                '</div>\n'
                '<details class="raw"><summary>Full probed-path table</summary>\n' + srv['scan'] + '\n</details>\n') if srv['scanner_total'] else '')
            + srv.get('cost', '')
            + (('<p class="refnote" style="font:400 13px/1.6 var(--sans);color:var(--muted);margin-top:1.6em">Verified counts cover traffic since real-IP logging was enabled, filling in daily. Log retention is ~2 weeks, so "blind spots" means "not fetched recently." The playbook: <a href="/geo-field-manual/">GEO Field Manual</a>, and the answers it produces: <a href="/geo-answers/">GEO answers</a>.</p>\n')
               if CFG['chrome'] == 'jo' else
               ('<p class="refnote" style="font:400 13px/1.6 var(--sans);color:var(--muted);margin-top:1.6em">Verified counts cover traffic since real-IP logging was enabled, filling in daily. Log retention is ~2 weeks, so "blind spots" means "not fetched recently." This is the same instrument the operator runs on <a href="https://joshuaopolko.com/geo-observatory/">joshuaopolko.com</a>, pointed at NowServingTO\'s logs.</p>\n'))
            + '</div></main>\n<footer class="site-foot"><p>&copy; ' + CFG['brand'].replace('&nbsp;', ' ') + '</p></footer>\n'
            + '<script type="application/json" id="observatory-data">' + meta_json + '</script>\n'
            + '<script>var DATA_URL=' + json.dumps(CFG['data_url']) + ';</script>\n'
            '<script>' + JS + '</script>\n</body>\n</html>\n')


# ── data.json + html ──────────────────────────────────────────────────────
def build():
    bots, pages, sc, total, first, last = collect()
    referrals = collect_ai_referrals()
    ref_ips = list({e['ip'] for e in referrals if e['ip']})
    geo = geo_lookup(ref_ips) if ref_ips else {}
    sm = load_sitemap()
    ai_total = sum(v['hits'] for k, v in bots.items() if k[0] == 'ai')
    se_total = sum(v['hits'] for k, v in bots.items() if k[0] == 'se')
    vok = sum(v['vok'] for v in bots.values()); vtot = sum(v['vtot'] for v in bots.values())
    now = dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    # pages with AI activity, ranked
    ai_pages = sorted(((p, d) for p, d in pages.items() if d['ai'] > 0), key=lambda x: -x[1]['ai'])
    fetched = {p for p, _ in ai_pages}
    blind = sorted(p for p in sm if p not in fetched and not IGNORE_PATH.search(p))
    fresh = []
    for p, d in ai_pages:
        lm = sm.get(p, '')
        if lm and first and lm >= first and d['first']:
            try:
                lag = (dt.date.fromisoformat(d['first']) - dt.date.fromisoformat(lm)).days
                if lag >= 0: fresh.append((p, lm, d['first'], lag, d['ai']))
            except Exception: pass
    fresh.sort(key=lambda x: x[1], reverse=True)

    # aggregates for the charts
    bytype = collections.Counter()
    for k, v in bots.items():
        bytype[TYPE.get(k[1], '')] += v['hits']
    lu_total = bytype.get('live-user', 0)
    byengine = sorted(
        ({'e': k[1], 'k': k[0], 'type': TYPE.get(k[1], ''), 'h': v['hits'], 'v': [v['vok'], v['vtot']]}
         for k, v in bots.items() if v['hits'] > 0), key=lambda x: -x['h'])
    daymap = collections.defaultdict(collections.Counter)
    for k, v in bots.items():
        typ = TYPE.get(k[1], '')
        for d2, c in v['days'].items():
            daymap[d2][typ] += c
    seqdays = sorted(daymap)[-WINDOW_DAYS:]
    series = [dict({'d': d2}, **{tp: daymap[d2].get(tp, 0) for tp in ('live-user', 'ai-search', 'ai-training', 'search')}) for d2 in seqdays]

    # weekly movers: activity in the most recent 7 days of the window (drives the
    # "this week" deltas on the homepage featured block, so the plateaued rolling
    # totals still show visible movement)
    last7 = seqdays[-7:]
    wk_live = sum(daymap[d2].get('live-user', 0) for d2 in last7)
    wk_ai = sum(daymap[d2].get(tp, 0) for d2 in last7 for tp in ('live-user', 'ai-search', 'ai-training'))
    vdaymap = collections.Counter()
    for v in bots.values():
        for d2, c in v['vdays'].items():
            vdaymap[d2] += c
    wk_ver = sum(vdaymap.get(d2, 0) for d2 in last7)

    # scanner probe categories (what the hostile traffic hunts for)
    def scan_cat(p):
        pl = p.lower()
        if 'wp-' in pl or 'wordpress' in pl or 'xmlrpc' in pl: return 'WordPress'
        if '.git' in pl: return 'Git exposure'
        if '.env' in pl or '/.aws' in pl or '/.ssh' in pl or 'config' in pl or '.sql' in pl or 'backup' in pl: return 'Secrets & config'
        if 'phpmyadmin' in pl or 'cgi-bin' in pl or '/owa/' in pl or 'actuator' in pl or 'phpinfo' in pl or '/admin' in pl: return 'Admin / RCE'
        return 'Other'
    scat = collections.Counter()
    for p, c in sc['paths'].items():
        scat[scan_cat(p)] += c

    data = {
        'generated': now, 'window': [first, last],
        'totals': {'ai': ai_total, 'se': se_total, 'live': lu_total, 'verified': f'{vok}/{vtot}',
                   'vok': vok, 'vtot': vtot, 'scanners': sc['total'], 'spoofed': sc['spoofed'],
                   'week': {'ai': wk_ai, 'live': wk_live, 'vok': wk_ver}},
        'byType': {tp: bytype.get(tp, 0) for tp in ('live-user', 'ai-search', 'ai-training', 'search') if bytype.get(tp)},
        'byEngine': byengine,
        'series': series,
        'pages': [{'p': p, 'h': d['h'], 'ai': d['ai'], 'lu': d['lu'],
                   't': dict(d['t']), 'b': dict(d['b'].most_common(20)),
                   'first': d['first'], 'last': d['last']} for p, d in ai_pages[:600]],
        'blind': blind,
        'scanners': {'total': sc['total'], 'spoofed': sc['spoofed'],
                     'paths': sc['paths'].most_common(12),
                     'cats': {k: scat[k] for k in ('WordPress', 'Secrets & config', 'Git exposure', 'Admin / RCE', 'Other') if scat[k]}},
    }
    os.makedirs(os.path.dirname(CFG['datafile']), exist_ok=True)
    open(CFG['datafile'], 'w').write(json.dumps(data, separators=(',', ':')))

    # ── server-rendered strings (so AI crawlers and no-JS readers get everything) ──
    def cards():
        ver = (f'<div class="v">{vok:,}</div><div class="l">Verified bots</div><div class="s">{vok}/{vtot} IP-checked</div>'
               if vtot else '<div class="v">collecting</div><div class="l">Verified bots</div><div class="s">filling in daily</div>')
        return ('<div class="cards">'
                f'<div class="card"><div class="v">{ai_total:,}</div><div class="l">AI crawler hits</div><div class="s">{len(ai_pages)} pages fetched</div></div>'
                f'<div class="card star"><div class="v">{lu_total:,}</div><div class="l">AI live-fetches</div><div class="s">pulled into answers now</div></div>'
                f'<div class="card"><div class="v">{se_total:,}</div><div class="l">Search-engine hits</div><div class="s">classic indexing</div></div>'
                f'<div class="card good">{ver}</div>'
                f'<div class="card warn"><div class="v">{sc["total"]:,}</div><div class="l">Scanner probes</div><div class="s">hostile, all 404</div></div>'
                '</div>\n')

    def bot_rows(kind):
        rows = sorted(((k[1], v) for k, v in bots.items() if k[0] == kind and v['hits'] > 0), key=lambda x: -x[1]['hits'])
        if not rows: return '<p class="muted">None.</p>'
        o = ['<table class="cs"><thead><tr><th>Crawler</th><th>Type</th><th class="n">Hits</th><th>Verified</th><th>Last</th></tr></thead><tbody>']
        for lab, v in rows:
            vc = ('pending' if not v['vtot'] else f'<span class="vok">{v["vok"]}/{v["vtot"]} ✓</span>' if v['vok'] == v['vtot']
                  else f'<span class="vbad">{v["vok"]}/{v["vtot"]}</span>')
            o.append(f'<tr><td>{html.escape(lab)}</td><td class="eng">{TYPE_LABEL.get(TYPE.get(lab,""),"")}</td><td class="n">{v["hits"]:,}</td><td class="vc">{vc}</td><td class="d">{v["last"]}</td></tr>')
        return ''.join(o) + '</tbody></table>'

    top_pages = ''.join(
        f'<tr class="prow"><td class="p"><a href="{html.escape(p)}">{html.escape(p[:54])}</a></td>'
        f'<td class="n">{d["ai"]:,}</td><td class="n lu">{d["lu"]:,}</td>'
        f'<td class="tg">{TYPE_LABEL.get(max(((c,tp) for tp,c in d["t"].items() if tp in AI_TYPES), default=(0,""))[1],"")}</td></tr>'
        for p, d in ai_pages[:25]) or '<tr><td colspan="4" class="muted">No AI page-fetches in the window.</td></tr>'

    blind_rows = ''.join(f'<li><a href="{html.escape(p)}">{html.escape(p)}</a></li>' for p in blind[:40]) or '<li class="muted">None: every indexed page has been fetched by AI in the window.</li>'

    fresh_rows = ''.join(f'<tr><td class="p"><a href="{html.escape(p)}">{html.escape(p[:46])}</a></td><td class="d">{lm}</td><td class="d">{ff}</td><td class="n">{lag}d</td></tr>'
                         for p, lm, ff, lag, _ in fresh[:12]) or '<tr><td colspan="4" class="muted">No pages updated within the log window yet.</td></tr>'

    def daily_fallback():
        days = collections.Counter()
        for k, v in bots.items():
            if k[0] == 'ai':
                for d2, c in v['days'].items(): days[d2] += c
        seq = sorted(days)[-14:]
        if not seq: return ''
        mx = max(days[d2] for d2 in seq) or 1
        return '<div class="bars">' + ''.join(
            f'<div class="bar-row"><span class="bd">{d2[5:]}</span><span class="bt"><span class="bf" style="width:{max(2,round(100*days[d2]/mx))}%"></span></span><span class="bn">{days[d2]:,}</span></div>' for d2 in seq) + '</div>'

    def eng_fallback():
        ai = [e for e in byengine if e['k'] == 'ai'][:8]
        if not ai: return '<p class="sub">No AI crawlers in the window.</p>'
        mx = ai[0]['h'] or 1
        col = {'live-user': '#7d1d24', 'ai-search': '#c2772e', 'ai-training': '#2f6f63', 'search': '#4a5d7e'}
        return ''.join(
            f'<div class="ebar"><span class="el">{html.escape(e["e"])}</span>'
            f'<span class="etrack"><span class="et" style="width:{max(3,round(100*e["h"]/mx))}%;background:{col.get(e["type"],"#7d1d24")}"></span></span>'
            f'<span class="en">{e["h"]:,}</span></div>' for e in ai)

    def mix_fallback():
        parts = ', '.join(f'{bytype.get(tp,0):,} {TYPE_LABEL[tp].lower()}' for tp in AI_TYPES if bytype.get(tp))
        return f'<p class="sub">Of {ai_total:,} AI fetches: {parts}.</p>' if parts else ''

    SCAT = {'WordPress': '#7d1d24', 'Secrets & config': '#c2772e', 'Git exposure': '#2f6f63', 'Admin / RCE': '#4a5d7e', 'Other': '#9a9388'}

    def se_fallback():
        se = [e for e in byengine if e['k'] == 'se'][:10]
        if not se: return '<p class="sub">No search engines in the window.</p>'
        mx = se[0]['h'] or 1
        return ''.join(
            f'<div class="ebar" style="cursor:default"><span class="el">{html.escape(e["e"])}</span>'
            f'<span class="etrack"><span class="et" style="width:{max(3,round(100*e["h"]/mx))}%;background:#4a5d7e"></span></span>'
            f'<span class="en">{e["h"]:,}</span></div>' for e in se)

    def reality_fallback():
        tot = ai_total + se_total + sc['total'] or 1
        return f'<p class="sub">Of {tot:,} bot requests: {sc["total"]:,} scanner probes ({round(100*sc["total"]/tot)}%), {ai_total:,} AI, {se_total:,} search.</p>'

    def spath_fallback():
        if not sc['paths']: return ''
        mx = sc['paths'].most_common(1)[0][1] or 1
        return ''.join(
            f'<div class="pbar"><div class="pl"><code>{html.escape(p[:54])}</code><b>{c:,}</b></div>'
            f'<div class="ptrack"><span class="pf" style="width:{max(2,round(100*c/mx))}%"></span></div></div>'
            for p, c in sc['paths'].most_common(12))

    def scat_fallback():
        if not scat: return ''
        parts = ', '.join(f'{scat[k]:,} {k.lower()}' for k in scat if scat[k])
        return f'<p class="sub">By target: {parts}.</p>'

    scan = ''
    if sc['total']:
        tp = ''.join(f'<tr><td class="p">{html.escape(p[:60])}</td><td class="n">{c:,}</td></tr>' for p, c in sc['paths'].most_common(10))
        scan = f'<table class="cs"><thead><tr><th>Probed path</th><th class="n">Hits</th></tr></thead><tbody>{tp}</tbody></table>'

    def live_desk():
        ed = now[:10]
        try: ed = dt.datetime.strptime((last or now[:10]), '%Y-%m-%d').strftime('%B %-d')
        except Exception: pass
        kick = f'<span class="desk">Live Desk &middot; {ed} edition</span>'
        live = sorted(((p, d) for p, d in ai_pages if d['lu'] > 0), key=lambda x: -x[1]['lu'])
        if not lu_total or not live:
            return (f'<div class="standfirst">{kick}<p>No live-answer fetches in this window yet. '
                    'The moment an assistant pulls one of these pages mid-answer to reply to a real '
                    'question, it surfaces here first.</p></div>\n')
        npages = len(live); top_p, top_d = live[0]
        friendly = [lab.replace(' user-fetch', '') for lab, c in sorted(top_d['b'].items(), key=lambda x: -x[1])
                    if TYPE.get(lab, '') == 'live-user' and c > 0] or ['live-answer agents']
        eng = (friendly[0] if len(friendly) == 1 else ' and '.join(friendly) if len(friendly) == 2
               else ', '.join(friendly[:-1]) + ', and ' + friendly[-1])
        pword = 'page' if npages == 1 else 'pages'
        return (f'<div class="standfirst">{kick}'
                f'<p>AI assistants pulled <b>{npages} {pword}</b> of this site mid-answer in the window '
                f'(<b>{lu_total:,}</b> live fetches in all). The most active was '
                f'<a href="{html.escape(top_p)}">{html.escape(page_title(top_p))}</a>, fetched '
                f'<b>{top_d["lu"]:,}&times;</b> by {html.escape(eng)}: live-answer agents, meaning it was read '
                'to compose a reply to a real question, not archived for training.</p></div>\n')

    nav = '<nav class="site-nav" aria-label="Primary"><ul><li><a href="/">Home</a></li></ul></nav>'
    try:
        mm = re.search(r'<nav class="site-nav".*?</nav>', open(LIVE_INDEX).read(), re.S)
        if mm: nav = mm.group(0)
    except Exception: pass

    def cost_panel():
        if not CFG.get('cost'): return ''
        try:
            u = json.load(open(CFG['cost']))
            tot = u.get('totals', {}); allc = tot.get('all', {}); today = tot.get('today', {})
            prov = sorted(u.get('byProvider', []), key=lambda x: -x.get('cost', 0))[:8]
            rows = ''.join(f'<tr><td>{html.escape(str(p.get("provider","")).replace("_"," "))}</td>'
                           f'<td class="n">{p.get("calls",0):,}</td><td class="n">${p.get("cost",0):,.2f}</td></tr>' for p in prov)
            return ('<h2>The ledger: what the data costs</h2>\n'
                    f'<p>The crawlers above read NowServingTO for free. Building the data they read is metered: '
                    f'every external API call this site makes is logged. Lifetime spend <b>${allc.get("cost",0):,.2f}</b> '
                    f'across <b>{allc.get("calls",0):,}</b> calls, <b>${today.get("cost",0):,.2f}</b> today.</p>\n'
                    f'<table class="cs"><thead><tr><th>Provider</th><th class="n">Calls</th><th class="n">Spend</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>\n') if rows else ''
        except Exception:
            return ''

    FLAG = {'US':'🇺🇸','CA':'🇨🇦','GB':'🇬🇧','AU':'🇦🇺','DE':'🇩🇪','FR':'🇫🇷','IN':'🇮🇳','JP':'🇯🇵',
            'NL':'🇳🇱','SE':'🇸🇪','NO':'🇳🇴','BR':'🇧🇷','MX':'🇲🇽','IT':'🇮🇹','ES':'🇪🇸','KR':'🇰🇷',
            'SG':'🇸🇬','ZA':'🇿🇦','NG':'🇳🇬','PH':'🇵🇭','PK':'🇵🇰','BD':'🇧🇩','PL':'🇵🇱','UA':'🇺🇦',
            'RO':'🇷🇴','NZ':'🇳🇿','IE':'🇮🇪','PT':'🇵🇹','AR':'🇦🇷','CL':'🇨🇱','CO':'🇨🇴','PE':'🇵🇪',
            'TR':'🇹🇷','IL':'🇮🇱','SA':'🇸🇦','AE':'🇦🇪','EG':'🇪🇬','KE':'🇰🇪','GH':'🇬🇭',}

    def referral_section():
        if not referrals: return ''
        # dedupe: same IP+path within same day counts once
        seen = set(); rows = []
        for e in referrals:
            key = (e['day'], e['ip'] or e['ref'], e['path'])
            if key in seen: continue
            seen.add(key)
            g = geo.get(e['ip']) or {} if e['ip'] else {}
            cc = g.get('countryCode', '')
            flag = FLAG.get(cc, '')
            country = g.get('country', cc)
            city = g.get('city', '')
            org = g.get('org', '')
            # strip AS number prefix ("AS12345 Comcast" -> "Comcast")
            org = re.sub(r'^AS\d+\s+', '', org)
            location = ', '.join(filter(None, [city, country]))
            rows.append((e['day'], e['platform'], e['path'], flag, location, org))
            if len(rows) >= 100: break
        if not rows: return ''
        # last-7-days subset
        import datetime as _dt
        cutoff = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
        week_rows = [r for r in rows if r[0] >= cutoff]
        week_by_platform = collections.Counter(r[1] for r in week_rows)
        # summary stats for the heading
        by_platform = collections.Counter(r[1] for r in rows)
        top = by_platform.most_common(1)[0]
        summary = f'{len(rows)} click-through{"s" if len(rows)!=1 else ""} from AI platforms'
        if len(by_platform) > 1:
            summary += f' — {top[0]} leads with {top[1]}'
        week_detail = ', '.join(f'{n} {p}' for p, n in week_by_platform.most_common()) if week_by_platform else 'none'
        week_total = sum(week_by_platform.values())
        tr = ''.join(
            f'<tr>'
            f'<td class="d">{html.escape(r[0])}</td>'
            f'<td><b>{html.escape(r[1])}</b></td>'
            f'<td class="p"><a href="{html.escape(r[2])}">{html.escape(r[2][:50])}</a></td>'
            f'<td>{html.escape(r[3])} {html.escape(r[4])}</td>'
            f'<td class="eng">{html.escape(r[5][:40])}</td>'
            f'</tr>'
            for r in rows)
        return (f'<h2>AI referrals: humans who clicked through</h2>\n'
                f'<p>{html.escape(summary)}. <b>Last 7 days: {week_total} ({html.escape(week_detail)})</b>. '
                f'These are real visitors whose browser sent a <code>Referer</code> '
                f'header from an AI platform — proof the citation converted to a visit. '
                f'Country and ISP come from the real visitor IP (via Cloudflare).</p>\n'
                f'<table class="cs"><thead><tr>'
                f'<th>Date</th><th>Platform</th><th>Page</th><th>Location</th><th>ISP / Org</th>'
                f'</tr></thead><tbody>{tr}</tbody></table>\n')

    def ip_intel_panel():
        intel_path = os.path.join(CFG['outdir'], 'ip_intel.json')
        try:
            intel = json.load(open(intel_path))
        except (FileNotFoundError, json.JSONDecodeError):
            return ''
        cats = intel.get('categories', [])
        total = intel.get('totalIPs', 0)
        gen = intel.get('generatedAt', '')[:10]
        if not cats or not total:
            return ''
        CAT_COLOR = {'Rank-tracking / residential proxy': '#e84e3a',
                     'Cloud / VPS scraper': '#f59e0b',
                     'AI / SEO crawler (verified)': '#7c3aed',
                     'Real visitor (residential ISP)': '#10b981'}
        bars = ''
        for c in cats:
            pct = c.get('pct', 0)
            color = CAT_COLOR.get(c['label'], '#9ca3af')
            orgs = ', '.join(c.get('orgs', [])[:3])
            orgs_note = f' <span style="font-weight:400;color:#888">({orgs})</span>' if orgs else ''
            bars += (f'<div style="display:grid;grid-template-columns:200px 1fr 44px;align-items:center;'
                     f'gap:10px;padding:6px 0;border-top:1px dashed var(--line,#e0ddd6)">'
                     f'<span style="font:600 12px/1.3 var(--sans,sans-serif);color:var(--ink2,#333)">'
                     f'{html.escape(c["label"])}{orgs_note}</span>'
                     f'<div style="background:#f0ede6;border-radius:4px;height:10px;overflow:hidden">'
                     f'<div style="width:{pct}%;height:100%;background:{color};border-radius:4px"></div></div>'
                     f'<span style="font:700 12px/1 monospace;text-align:right">{pct}%</span></div>')
        narrative_raw = intel.get('narrative', '')
        # Convert newlines to <br> so bullet-per-line format renders correctly
        narrative = '<br>'.join(html.escape(ln) for ln in narrative_raw.splitlines())
        narrative_html = f'<p style="font:400 13.5px/1.65 var(--sans,sans-serif);color:var(--ink2,#333);background:var(--bg,#f8f5ec);border-radius:8px;border-left:3px solid var(--line,#e0ddd6);padding:14px 16px;margin:12px 0 0;line-height:1.8">{narrative}</p>' if narrative else ''
        return (f'<h2>Who\'s actually visiting</h2>\n'
                f'<p>Real IP analysis: ip-api.com org lookup on non-bot request IPs, classified by network type. '
                f'{total:,} unique IPs in the past 7 days. Updated weekly (Sundays) &middot; data as of {html.escape(gen)}.</p>\n'
                f'<div style="background:var(--panel,#fff);border:1px solid var(--line,#e0ddd6);border-radius:12px;padding:20px;margin:14px 0">'
                f'{bars}{narrative_html}</div>\n')

    srv = {'cards': cards(), 'bot_ai': bot_rows('ai'), 'bot_se': bot_rows('se'), 'cost': cost_panel(),
           'ip_intel': ip_intel_panel(),
           'top_pages': top_pages, 'blind_rows': blind_rows, 'fresh_rows': fresh_rows,
           'daily_fallback': daily_fallback(), 'eng_fallback': eng_fallback(),
           'mix_fallback': mix_fallback(), 'scan': scan, 'live_desk': live_desk(),
           'se_fallback': se_fallback(), 'reality_fallback': reality_fallback(),
           'spath_fallback': spath_fallback(), 'scat_fallback': scat_fallback(),
           'scanner_total': sc['total'], 'scanner_spoofed': sc['spoofed'],
           'referrals': referral_section()}

    open(os.path.join(OUTDIR, CFG['outfile']), 'w').write(render_page(data, nav, srv))
    print(f"wrote observatory: {len(ai_pages)} AI-fetched pages, {len(blind)} blind spots, {vok}/{vtot} verified, {sc['total']:,} scanner probes")

    # keep the homepage's featured-observatory stats fresh for no-JS / AI readers (jo only;
    # browsers already self-update from data.json on load). Patches only the 3 <b id="obs-*"> spans.
    if SITE == 'jo':
        try:
            hp = WEBROOT + '/index.html'
            hs = open(hp).read()
            for sid, val in [('obs-live', lu_total), ('obs-ai', ai_total), ('obs-ver', vok)]:
                hs = re.sub(r'(<b id="' + sid + r'">)[^<]*(</b>)',
                            lambda m, v=val: m.group(1) + f'{v:,}' + m.group(2), hs)
            for sid, val in [('obs-live-wk', wk_live), ('obs-ai-wk', wk_ai), ('obs-ver-wk', wk_ver)]:
                hs = re.sub(r'(<i class="obs-wk" id="' + sid + r'">)[^<]*(</i>)',
                            lambda m, v=val: m.group(1) + (f'+{v:,} this week' if v else '') + m.group(2), hs)
            open(hp, 'w').write(hs)
            print(f"  patched homepage obs-stats: live={lu_total} ai={ai_total} verified={vok} "
                  f"(week +{wk_live}/+{wk_ai}/+{wk_ver})")
        except Exception as e:
            print(f"  homepage obs-stats patch skipped: {e}")


def selftest():
    nets = load_ranges()
    print("ranges:", {k: len(v) for k, v in nets.items()})
    memo = {}; rc = {}
    for lab, ip, want in [('Googlebot', '66.249.66.1', True), ('Googlebot', '8.8.8.8', False)]:
        got = verify(lab, ip, nets, rc, memo)
        print(f"  verify({lab},{ip})={got} want {want} {'OK' if got==want else 'MISMATCH'}")
    print("sitemap paths:", len(load_sitemap()))


if __name__ == '__main__':
    selftest() if '--selftest' in sys.argv else build()
