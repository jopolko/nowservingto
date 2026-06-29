#!/usr/bin/env python3
"""
reddit_harvest.py - mine Reddit for real questions worth answering on Josh's
sites, so the answers become AI-citation surface (GEO content mining).

THE BRIDGE
==========
The point is NOT to repost Reddit or scrape it. The point is: a real person
asks a real question in your niche, you answer it better than anyone on YOUR
site, and AI search cites you. This tool finds those questions and ranks them
by which property should own the answer.

WHY RSS-WITH-TOKEN (not the official API)
-----------------------------------------
As of June 2026 Reddit 429s unauthenticated RSS and is killing the old `.json`
scrape path. The official API now needs per-app PRE-APPROVAL even for personal
use (the 2025 crackdown). The clean, no-approval, ToS-sanctioned path is the
RSS feed token Reddit itself hands you in your prefs: it authenticates ANY
feed (public subs, /search.rss, your home feed) and dodges the 429 wall.

ONE-TIME SETUP (you, 60 seconds, your creds)
--------------------------------------------
1. Log into Reddit, open  https://www.reddit.com/prefs/feeds/
2. It shows feed URLs containing  ...?feed=<long-token>&user=<your-username>
3. Put BOTH values in /var/secrets/nowservingto.env (never committed):
       REDDIT_FEED_USER=JoshuaOpolko
       REDDIT_FEED_TOKEN=<the long token>
   (optional digest email reuses the existing SMTP_* keys + MAIL_TO)
That single token unlocks every lane below. If it ever 429s again, the token
rotated - just re-copy it from the same prefs page.

USAGE
-----
    python3 tools/reddit_harvest.py --selftest      # prove the logic, no token
    python3 tools/reddit_harvest.py --dry-run       # show lanes + the URLs it would hit
    python3 tools/reddit_harvest.py                 # live pull -> writes a digest file
    python3 tools/reddit_harvest.py --email         # ...and email the digest
    python3 tools/reddit_harvest.py --lane geo      # only one property's lanes

Exits 0 normally, non-zero on hard failure so cron MAILTO catches it.
"""
import argparse
import html
import json
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SECRETS = Path('/var/secrets/nowservingto.env')
OUT_DIR = ROOT / 'tools' / 'cache' / 'reddit_targets'
SEEN_PATH = ROOT / 'tools' / 'cache' / 'reddit_seen.json'

UA = 'joshuaopolko-geo-research/1.0 (content-mining for joshuaopolko.com; by /u/JoshuaOpolko)'
ATOM = {'a': 'http://www.w3.org/2005/Atom'}

# ---------------------------------------------------------------------------
# LANES: which feeds feed which property. Edit freely.
#   feed:       "r/<sub>/<view>"  (view in new|hot|top|rising; default new)
#               "search:<query>"            (search all of reddit)
#               "search:<query>@<sub>"      (search restricted to one sub)
#   must_match: optional keyword set; in broad subs (r/toronto) this gates out
#               off-topic posts. Search lanes are already scoped, so optional.
# Keep lanes grounded to where you can genuinely give the best answer.
# ---------------------------------------------------------------------------
FOOD_KW = {'restaurant', 'eat', 'food', 'dinner', 'lunch', 'brunch', 'cafe',
           'coffee', 'bar', 'patio', 'takeout', 'menu', 'reservation', 'cuisine',
           'sushi', 'ramen', 'pizza', 'dumpling', 'bakery', 'dessert', 'open',
           'opening', 'new spot', 'where to', 'best place'}
KIDS_KW = {'kid', 'kids', 'child', 'children', 'toddler', 'baby', 'family',
           'stroller', 'playground', 'march break', 'pa day', 'camp',
           'birthday', 'family-friendly', 'things to do with'}
# Hard location gate for the GLOBAL search lanes (sub-scoped lanes like r/askTO
# are already Toronto, so they don't need it). Kills Saigon/Uganda/Japan noise.
TORONTO_KW = {'toronto', 'gta', 'etobicoke', 'scarborough', 'north york',
              'east york', 'mississauga', 'markham', 'vaughan', 'brampton',
              'the 6ix', '6ix', 'tdot', 'danforth', 'leslieville', 'high park',
              'yorkville', 'kensington', 'the annex', 'the junction'}
GEO_KW = {'ai overview', 'ai overviews', 'ai mode', 'chatgpt', 'perplexity',
          'gemini', 'claude', 'llm', 'cited', 'citation', 'geo',
          'generative engine', 'aeo', 'answer engine', 'llms.txt', 'schema',
          'structured data', 'e-e-a-t', 'eeat', 'get cited', 'ai search',
          'indexnow', 'sge', 'zero-click', 'featured snippet'}

# r/buildinpublic: weekly megathreads where Josh can post an nsto update.
# Titles don't always have '?', so engage=True bypasses is_question.
BIP_KW = {'what are you working on', 'show and tell', 'share your project',
          'just launched', 'launched today', 'what did you build', 'what have you shipped',
          'introduce yourself', 'side project', 'makers', 'build in public',
          'just shipped', 'weekly thread', 'show your work', 'what are you building'}

# r/toronto: posts requesting new restaurant/cuisine info where nsto data
# is a direct, useful reply. Looser than FOOD_KW - catches "looking for"
# posts that don't frame as a question with '?'.
TORONTO_ENGAGE_KW = {
    'new restaurant', 'new spot', 'new place', 'just opened', 'recently opened',
    'opening soon', 'looking for', 'where to find', 'what opened', "what's new",
    'whats new', 'any new', 'new ethiopian', 'new indian', 'new chinese',
    'new vietnamese', 'new korean', 'new japanese', 'new thai', 'new mexican',
    'new italian', 'new greek', 'new middle eastern', 'new caribbean',
    'new filipino', 'new nigerian', 'new jamaican', 'new pakistani',
    'new bangladeshi', 'new sri lankan', 'new tamil', 'new afghan', 'new persian',
    'new restaurants', 'restaurant opened', 'cuisine toronto',
}
PATOIS_KW = {'patois', 'patwa', 'creole', 'jamaica', 'jamaican', 'caribbean',
             'low-resource', 'low resource', 'minority language', 'dialect',
             'tokeniz', 'language model', 'llm', 'nlp'}

LANES = {
    # engage: threads to reply in directly with nsto data/link.
    # engage=True bypasses the is_question filter (megathreads + "looking for"
    # posts don't always have '?').
    'engage': [
        {'feed': 'r/buildinpublic/new', 'must_match': BIP_KW, 'engage': True},
        {'feed': 'r/buildinpublic/hot', 'must_match': BIP_KW, 'engage': True},
        {'feed': 'r/SideProject/new',   'must_match': BIP_KW, 'engage': True},
        {'feed': 'r/SideProject/hot',   'must_match': BIP_KW, 'engage': True},
        {'feed': 'r/toronto/new',       'must_match': TORONTO_ENGAGE_KW, 'must_geo': TORONTO_KW, 'engage': True},
        {'feed': 'r/toronto/hot',       'must_match': TORONTO_ENGAGE_KW, 'must_geo': TORONTO_KW, 'engage': True},
    ],
    'nowservingto': [
        {'feed': 'search:new restaurant toronto', 'must_match': FOOD_KW, 'must_geo': TORONTO_KW},
        {'feed': 'search:where to eat toronto', 'must_match': FOOD_KW, 'must_geo': TORONTO_KW},
        {'feed': 'r/askTO/new', 'must_match': FOOD_KW},
        {'feed': 'r/toronto/new', 'must_match': FOOD_KW},
        {'feed': 'search:best restaurant@FoodToronto', 'must_match': FOOD_KW},
    ],
    'kidsevents': [
        {'feed': 'search:things to do with kids toronto', 'must_match': KIDS_KW, 'must_geo': TORONTO_KW},
        {'feed': 'search:kids activities toronto', 'must_match': KIDS_KW, 'must_geo': TORONTO_KW},
        {'feed': 'r/askTO/new', 'must_match': KIDS_KW},
        {'feed': 'r/torontized/new', 'must_match': KIDS_KW},
    ],
    'geo': [
        {'feed': 'r/SEO/new', 'must_match': GEO_KW},
        {'feed': 'r/bigseo/new', 'must_match': GEO_KW},
        {'feed': 'search:get cited by chatgpt', 'must_match': GEO_KW},
        {'feed': 'search:generative engine optimization', 'must_match': GEO_KW},
        {'feed': 'search:ai overviews citation', 'must_match': GEO_KW},
    ],
    # 'patois' lane dropped for now - re-enable when ready:
    # 'patois': [
    #     {'feed': 'search:jamaican patois language'},
    #     {'feed': 'search:creole language model'},
    #     {'feed': 'r/LanguageTechnology/new', 'must_match': PATOIS_KW},
    #     {'feed': 'r/Jamaica/new', 'must_match': {'language', 'patois', 'patwa', 'ai', 'translate'}},
    # ],
}

# property -> short answer-angle template
ANGLE = {
    'engage': "Reply in this thread directly. For r/buildinpublic: share joshuaopolko.com/geo-observatory/ as a data post - 'been tracking which AI crawlers hit my sites and what they read, built a live dashboard from Apache logs, some interesting patterns if you care about AI visibility.' Data-share, not a pitch. For r/toronto food posts: drop the relevant nsto cuisine page URL with one line on what it shows. Don't pitch - share the data.",
    'nowservingto': "Make/extend a NowServingTO /answers entry that answers this in one canonical sentence, then the supporting list. Match the asker's exact phrasing.",
    'kidsevents': "Add a kidsevents answer-surface block (or calendar filter) that directly resolves this. Lead with the single best pick, then alternatives.",
    'geo': "This is GEO-Field-Manual fuel. Answer it as a falsifiable, first-party how-to (your real numbers), not generic advice. That earns the citation.",
    'patois': "Patois-page / essay angle. Answer from the build-a-Creole-LLM thesis with a concrete, checkable claim.",
}

# property -> display label / accent colour / render order (patois dropped for now)
PROP_LABEL = {'engage': 'Engage opportunities (reply here)',
              'geo': 'joshuaopolko.com / GEO Field Manual',
              'nowservingto': 'NowServingTO',
              'kidsevents': 'kidsevents'}
PROP_ACCENT = {'engage': '#059669', 'geo': '#6366f1', 'nowservingto': '#0d9488', 'kidsevents': '#d97706'}
PROP_ORDER = ['engage', 'geo', 'nowservingto', 'kidsevents']

QUESTION_WORDS = ('how', 'what', 'where', 'when', 'which', 'who', 'why',
                  'anyone', 'recommend', 'suggestion', 'best ', 'worth it',
                  'looking for', 'help', 'tips', 'advice', 'is there',
                  'does anyone', 'can i', 'should i', 'vs ', ' or ')
# Title-strict gate: a genuinely answerable question has '?' or one of these
# clear interrogative openers IN THE TITLE. Body-only matches were too noisy.
STRONG_Q = ('how do i', 'how to', 'how can i', 'how much', 'how long',
            'what is the best', 'what are the best', 'what should i', 'what do you',
            'where can i', 'where to', 'which ', 'is there', 'is it worth',
            'does anyone', 'anyone know', 'anyone have', 'looking for',
            'recommend', 'best way', 'should i', 'can i', 'why is', 'why does',
            'any suggestions', 'any recommendations', 'advice on', 'help with')
DROP_PHRASES = ('[removed]', '[deleted]')
IMG_HOSTS = ('i.redd.it', 'i.imgur.com', 'v.redd.it')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.gifv')


# ---------------------------------------------------------------------------
def _load_env():
    out = {}
    try:
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


ENV = _load_env()


def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def build_url(feed, user, token, limit):
    """Turn a lane 'feed' spec into an authenticated Reddit RSS URL."""
    auth = f'user={quote_plus(user)}&feed={quote_plus(token)}&limit={limit}'
    if feed.startswith('search:'):
        q = feed[len('search:'):]
        sub = None
        if '@' in q:
            q, sub = q.rsplit('@', 1)
        eq = quote_plus(q.strip())
        if sub:
            return (f'https://www.reddit.com/r/{sub}/search.rss'
                    f'?q={eq}&restrict_sr=1&sort=new&{auth}')
        return f'https://www.reddit.com/search.rss?q={eq}&sort=new&{auth}'
    # subreddit feed: r/<sub>[/<view>]
    parts = feed.split('/')
    sub = parts[1] if len(parts) > 1 else parts[0]
    view = parts[2] if len(parts) > 2 else 'new'
    return f'https://www.reddit.com/r/{sub}/{view}/.rss?{auth}'


def fetch(url, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={'User-Agent': UA,
                                        'Accept': 'application/atom+xml, text/xml'})
            with urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except HTTPError as e:
            last = e
            if e.code == 429:
                if attempt < retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(
                    '429 from Reddit. Your RSS token is missing/expired - '
                    're-copy user= and feed= from reddit.com/prefs/feeds/ '
                    'into /var/secrets/nowservingto.env (REDDIT_FEED_USER / '
                    'REDDIT_FEED_TOKEN).') from e
            if e.code in (403, 404):
                return ''  # dead sub / private; skip quietly
            if attempt < retries:
                time.sleep(2)
                continue
        except URLError:
            if attempt < retries:
                time.sleep(2)
                continue
    if last:
        raise last
    return ''


def parse_atom(xml_text):
    """Return list of dicts {id,title,body,author,url,ts,sub} from Reddit Atom."""
    out = []
    if not xml_text.strip():
        return out
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for e in root.findall('a:entry', ATOM):
        def t(tag):
            el = e.find('a:' + tag, ATOM)
            return el.text if el is not None and el.text else ''
        link_el = e.find('a:link', ATOM)
        url = link_el.get('href') if link_el is not None else ''
        author = ''
        au = e.find('a:author/a:name', ATOM)
        if au is not None and au.text:
            author = au.text
        cat = e.find('a:category', ATOM)
        sub = cat.get('label') or cat.get('term') if cat is not None else ''
        content_el = e.find('a:content', ATOM)
        raw = content_el.text if content_el is not None and content_el.text else ''
        body = strip_html(raw)
        out.append({
            'id': t('id'),
            'title': html.unescape(t('title')).strip(),
            'body': body,
            'author': author,
            'url': url,
            'ts': t('published') or t('updated'),
            'sub': re.sub(r'^/?r/', '', (sub or ''), flags=re.I),
        })
    return out


def strip_html(s):
    s = re.sub(r'(?s)<.*?>', ' ', s or '')
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def is_question(text):
    """Title-strict: '?' or a clear interrogative opener. Pass the TITLE only."""
    if '?' in text:
        return True
    low = text.lower()
    return any(p in low for p in STRONG_Q)


def is_noise(item):
    blob = (item['title'] + ' ' + item['body'])
    low = blob.lower()
    if any(p in low for p in DROP_PHRASES):
        return True
    # image/video-only with no real text and no question
    if (not item['body']) and (not is_question(item['title'])):
        u = item['url'].lower()
        if any(h in u for h in IMG_HOSTS) or u.endswith(IMG_EXT):
            return True
    if len((item['title'] + item['body']).strip()) < 20:
        return True
    return False


def kw_hits(text, kwset):
    low = text.lower()
    return sum(1 for k in kwset if k in low)


def hours_old(ts):
    if not ts:
        return 9999
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return 9999


def score(item, must_match):
    blob = item['title'] + ' ' + item['body']
    low = blob.lower()
    s = 0.0
    # question strength
    if '?' in item['title']:
        s += 3
    elif '?' in blob:
        s += 2
    s += min(3, sum(1 for w in QUESTION_WORDS if w in low))
    # relevance to the lane's keyword gate (if any)
    if must_match:
        s += min(4, kw_hits(blob, must_match)) * 1.5
    # freshness: full credit < 24h, decaying to ~0 by a week
    h = hours_old(item['ts'])
    s += max(0.0, 4.0 * (1 - h / 168.0))
    return round(s, 2)


def norm_tokens(text):
    return set(re.findall(r'[a-z0-9]{3,}', text.lower()))


def dedupe(items):
    """Drop near-duplicate questions (Jaccard > 0.7 on title tokens), keep best."""
    kept = []
    for it in sorted(items, key=lambda x: x['score'], reverse=True):
        tt = norm_tokens(it['title'])
        if not tt:
            continue
        dup = False
        for k in kept:
            kt = k['_toks']
            inter = len(tt & kt)
            union = len(tt | kt) or 1
            if inter / union > 0.7:
                dup = True
                break
        if not dup:
            it['_toks'] = tt
            kept.append(it)
    for k in kept:
        k.pop('_toks', None)
    return kept


def harvest(lanes, user, token, per_feed, dry_run=False, verbose=False):
    results = {}
    for prop, feeds in lanes.items():
        found = []
        for spec in feeds:
            feed = spec['feed']
            mm = spec.get('must_match')
            mg = spec.get('must_geo')
            url = build_url(feed, user, token, per_feed)
            if dry_run:
                print(f'  [{prop}] {feed}')
                print(f'        {url.replace(token, "<TOKEN>") if token else url}')
                continue
            xml = fetch(url)
            entries = parse_atom(xml)
            kept_here = 0
            engage_mode = spec.get('engage', False)
            for it in entries:
                if is_noise(it):
                    continue
                # engage lanes surface megathreads + "looking for" posts that
                # may not have '?' - skip the question gate for those.
                if not engage_mode and not is_question(it['title']):
                    continue
                if mm and kw_hits(it['title'] + ' ' + it['body'], mm) == 0:
                    continue
                if mg and kw_hits(it['title'] + ' ' + it['body'], mg) == 0:
                    continue
                it['property'] = prop
                it['feed'] = feed
                it['score'] = score(it, mm)
                found.append(it)
                kept_here += 1
            if verbose:
                print(f'  [{prop}] {feed}: {len(entries)} entries -> {kept_here} kept',
                      file=sys.stderr)
            time.sleep(1.0)  # be polite between feeds
        results[prop] = dedupe(found)
    return results


def mark_new(results, seen):
    """Tag items not seen before; update the seen store with first-seen date."""
    today = datetime.now(timezone.utc).date().isoformat()
    for prop, items in results.items():
        for it in items:
            rid = it.get('id') or it.get('url')
            it['is_new'] = rid not in seen
            if rid and rid not in seen:
                seen[rid] = today
    return seen


def render_digest(results, cap_per_prop=8):
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    total = sum(len(v) for v in results.values())
    lines = [f'# Reddit -> GEO content targets - {today}',
             '',
             f'{total} ranked questions worth answering on your sites. '
             'Answer one better than anyone and you become the AI-cited source.',
             '']
    order = PROP_ORDER
    label = PROP_LABEL
    for prop in order:
        items = results.get(prop, [])
        if not items:
            continue
        lines.append(f'## {label.get(prop, prop)}')
        lines.append('')
        for it in items[:cap_per_prop]:
            h = hours_old(it['ts'])
            age = f'{int(h)}h ago' if h < 48 else f'{int(h/24)}d ago'
            new = ' **NEW**' if it.get('is_new') else ''
            lines.append(f'- **{it["title"]}**  (score {it["score"]}, {age}, r/{it["sub"]}){new}')
            if it['body']:
                ex = it['body'][:200] + ('...' if len(it['body']) > 200 else '')
                lines.append(f'  > {ex}')
            lines.append(f'  Thread: {it["url"]}')
            lines.append(f'  Angle: {ANGLE.get(prop, "")}')
            lines.append('')
    return '\n'.join(lines)


def render_html(results, cap_per_prop=12):
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    total = sum(len(v) for v in results.values())
    new = sum(1 for v in results.values() for it in v if it.get('is_new'))
    esc = html.escape

    def chip(text, cls=''):
        return f'<span class="chip {cls}">{esc(text)}</span>'

    sections = []
    for prop in PROP_ORDER:
        items = results.get(prop, [])
        if not items:
            continue
        accent = PROP_ACCENT.get(prop, '#475569')
        cards = []
        for it in items[:cap_per_prop]:
            h = hours_old(it['ts'])
            age = f'{int(h)}h ago' if h < 48 else f'{int(h / 24)}d ago'
            chips = [chip(f'score {it["score"]}', 'score'), chip(age),
                     chip('r/' + (it['sub'] or '?'))]
            if it.get('is_new'):
                chips.append(chip('NEW', 'new'))
            excerpt = ''
            if it['body']:
                ex = it['body'][:240] + ('…' if len(it['body']) > 240 else '')
                excerpt = f'<p class="excerpt">{esc(ex)}</p>'
            cards.append(
                '<article class="card">'
                f'<div class="chips">{"".join(chips)}</div>'
                f'<h3>{esc(it["title"])}</h3>'
                f'{excerpt}'
                f'<p class="angle"><span>Angle</span> {esc(ANGLE.get(prop, ""))}</p>'
                f'<a class="btn" href="{esc(it["url"])}" target="_blank" '
                'rel="noopener">Open thread ›</a>'
                '</article>')
        sections.append(
            f'<section style="--accent:{accent}">'
            f'<h2><span class="dot"></span>{esc(PROP_LABEL.get(prop, prop))}'
            f'<span class="n">{len(items)}</span></h2>'
            f'<div class="grid">{"".join(cards)}</div>'
            '</section>')

    body = '\n'.join(sections) or (
        '<p class="empty">No targets in this run. The harvester ran fine; '
        'nobody asked a matching question recently.</p>')

    css = """
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1e2330;background:#f5f6fa}
header{padding:40px 24px 26px;max-width:1100px;margin:0 auto}
h1{margin:0 0 6px;font-size:30px;letter-spacing:-.02em}
h1 .arrow{color:#6366f1}
.sub{margin:0 0 18px;color:#5b6472;max-width:64ch}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stat{background:#fff;border:1px solid #e3e6ef;border-radius:999px;padding:6px 14px;font-size:14px;color:#5b6472}
.stat b{color:#1e2330}
.stat.hot b{color:#dc2626}
main{max-width:1100px;margin:0 auto;padding:0 24px 60px}
section{margin:30px 0}
section h2{display:flex;align-items:center;gap:10px;font-size:18px;margin:0 0 14px}
section h2 .dot{width:11px;height:11px;border-radius:50%;background:var(--accent)}
section h2 .n{margin-left:auto;font-size:13px;font-weight:600;color:#8a93a6;background:#eef0f6;border-radius:999px;padding:2px 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:#fff;border:1px solid #e3e6ef;border-left:3px solid var(--accent);border-radius:12px;padding:15px 16px 14px;display:flex;flex-direction:column;gap:8px;box-shadow:0 1px 2px rgba(20,30,60,.04)}
.card h3{margin:0;font-size:16px;line-height:1.35;letter-spacing:-.01em}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:11px;font-weight:600;color:#5b6472;background:#eef0f6;border-radius:999px;padding:2px 8px;text-transform:uppercase;letter-spacing:.02em}
.chip.score{background:var(--accent);color:#fff}
.chip.new{background:#fee2e2;color:#dc2626}
.excerpt{margin:0;color:#5b6472;font-size:14px}
.angle{margin:2px 0 0;font-size:13.5px;color:#3b4252;background:#f7f8fc;border-radius:8px;padding:9px 11px}
.angle span{font-weight:700;color:var(--accent);margin-right:6px;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
.btn{align-self:flex-start;margin-top:2px;text-decoration:none;font-size:13.5px;font-weight:600;color:var(--accent)}
.btn:hover{text-decoration:underline}
.empty{color:#8a93a6;background:#fff;border:1px dashed #d6dae6;border-radius:12px;padding:28px;text-align:center}
footer{max-width:1100px;margin:0 auto;padding:0 24px 50px;color:#9aa2b3;font-size:12.5px}
@media(max-width:560px){header{padding:26px 18px 18px}main{padding:0 18px 40px}h1{font-size:25px}}
"""

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f'<title>Reddit → GEO targets · {today}</title>\n'
        '<style>' + css + '</style>\n</head>\n<body>\n'
        '<header>\n'
        '<h1>Reddit <span class="arrow">→</span> GEO targets</h1>\n'
        '<p class="sub">Real questions worth answering on your sites, so the '
        f'answers become AI-citation surface. Generated {today}.</p>\n'
        f'<div class="stats"><span class="stat"><b>{total}</b> targets</span>'
        f'<span class="stat hot"><b>{new}</b> new</span></div>\n'
        '</header>\n'
        f'<main>\n{body}\n</main>\n'
        '<footer>Auto-generated by reddit_harvest.py · score = question '
        'strength + niche relevance + freshness · unlisted working '
        'dashboard (noindex)</footer>\n'
        '</body>\n</html>\n')


def send_email(subject, body):
    host = ENV.get('SMTP_HOST', '127.0.0.1')
    port = int(ENV.get('SMTP_PORT', '25'))
    from_addr = ENV.get('MAIL_FROM_ADDR', 'alerts@nowservingto.com')
    from_name = ENV.get('MAIL_FROM_NAME', 'GEO Research')
    to_addr = ENV.get('MAIL_TO', 'mjopolko@gmail.com')
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = formataddr((from_name, from_addr))
    msg['To'] = to_addr
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.sendmail(from_addr, [to_addr], msg.as_string())


# ---- selftest sample (proves filter/rank with no token) --------------------
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><id>t3_a1</id><title>Best new restaurant in Toronto that opened this month?</title>
  <author><name>/u/foo</name></author><category label="askTO"/>
  <content type="html">&lt;p&gt;Visiting next week, where should we eat?&lt;/p&gt;</content>
  <link href="https://www.reddit.com/r/askTO/comments/a1/"/>
  <published>REPL_NOW</published></entry>
 <entry><id>t3_a2</id><title>[deleted]</title><author><name>/u/x</name></author>
  <category label="askTO"/><content type="html"></content>
  <link href="https://www.reddit.com/r/askTO/comments/a2/"/><published>REPL_NOW</published></entry>
 <entry><id>t3_a3</id><title>my cat</title><author><name>/u/y</name></author>
  <category label="askTO"/><content type="html"></content>
  <link href="https://i.redd.it/abc.jpg"/><published>REPL_NOW</published></entry>
 <entry><id>t3_a4</id><title>How do I get my site cited by ChatGPT and AI Overviews?</title>
  <author><name>/u/z</name></author><category label="SEO"/>
  <content type="html">&lt;p&gt;Tried schema and llms.txt, still not showing up in citations.&lt;/p&gt;</content>
  <link href="https://www.reddit.com/r/SEO/comments/a4/"/><published>REPL_NOW</published></entry>
</feed>"""


def run_selftest():
    now = datetime.now(timezone.utc).isoformat()
    xml = SAMPLE.replace('REPL_NOW', now)
    entries = parse_atom(xml)
    print(f'parsed {len(entries)} raw entries from sample')
    kept = []
    for it in entries:
        if is_noise(it):
            print(f'  drop (noise): {it["title"]!r}')
            continue
        if not is_question(it['title']):
            print(f'  drop (not a question): {it["title"]!r}')
            continue
        it['property'] = 'geo' if 'cited' in it['title'].lower() else 'nowservingto'
        it['feed'] = 'sample'
        it['score'] = score(it, GEO_KW if it['property'] == 'geo' else FOOD_KW)
        it['is_new'] = True
        kept.append(it)
    results = {}
    for it in kept:
        results.setdefault(it['property'], []).append(it)
    for v in results.values():
        v.sort(key=lambda x: x['score'], reverse=True)
    print('\n' + render_digest(results))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sp = OUT_DIR / 'selftest.html'
    sp.write_text(render_html(results), encoding='utf-8')
    print(f'\nrendered sample HTML report -> {sp}')
    print('  open it in a browser to see the look.')
    print('\nselftest OK - filter keeps the 2 real questions, drops the deleted '
          'post and the cat photo.')
    return 0


def main():
    ap = argparse.ArgumentParser(description='Mine Reddit for GEO content targets.')
    ap.add_argument('--selftest', action='store_true',
                    help='run filter/rank on a built-in sample (no token needed)')
    ap.add_argument('--dry-run', action='store_true',
                    help='print the lanes and feed URLs it would hit, no fetch')
    ap.add_argument('--email', action='store_true', help='email the digest')
    ap.add_argument('--lane', help='restrict to one property (geo|nowservingto|kidsevents|patois)')
    ap.add_argument('--per-feed', type=int, default=50, help='entries per feed (default 50)')
    ap.add_argument('--cap', type=int, default=8, help='max items per property in digest')
    ap.add_argument('--html', metavar='PATH',
                    help='also write the HTML report to PATH (e.g. the jo.com web root)')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    if args.selftest:
        return run_selftest()

    lanes = LANES
    if args.lane:
        if args.lane not in LANES:
            print(f'unknown lane {args.lane!r}; choose from {list(LANES)}', file=sys.stderr)
            return 2
        lanes = {args.lane: LANES[args.lane]}

    user = ENV.get('REDDIT_FEED_USER', '')
    token = ENV.get('REDDIT_FEED_TOKEN', '')

    if args.dry_run:
        print('Lanes and the authenticated RSS URLs that would be fetched:\n')
        harvest(lanes, user or '<USER>', token, args.per_feed, dry_run=True)
        if not (user and token):
            print('\n(No token configured yet - add REDDIT_FEED_USER / '
                  'REDDIT_FEED_TOKEN to /var/secrets/nowservingto.env from '
                  'reddit.com/prefs/feeds/ , then drop --dry-run.)')
        return 0

    if not (user and token):
        print('Missing REDDIT_FEED_USER / REDDIT_FEED_TOKEN in '
              '/var/secrets/nowservingto.env .\nGet them from '
              'https://www.reddit.com/prefs/feeds/ (the ?feed=...&user=... in '
              'any feed URL). Try --selftest or --dry-run meanwhile.', file=sys.stderr)
        return 2

    results = harvest(lanes, user, token, args.per_feed, verbose=args.verbose)
    seen = _load_json(SEEN_PATH, {})
    seen = mark_new(results, seen)
    # prune seen store to last ~5000 ids by insertion
    if len(seen) > 5000:
        seen = dict(list(seen.items())[-5000:])
    _save_json(SEEN_PATH, seen)

    digest = render_digest(results, cap_per_prop=args.cap)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    out_file = OUT_DIR / f'{today}.md'
    out_file.write_text(digest, encoding='utf-8')
    _save_json(OUT_DIR / f'{today}.json',
               {p: [{k: v for k, v in it.items() if not k.startswith('_')} for it in items]
                for p, items in results.items()})

    html_report = render_html(results, cap_per_prop=max(args.cap, 12))
    (OUT_DIR / f'{today}.html').write_text(html_report, encoding='utf-8')
    (OUT_DIR / 'latest.html').write_text(html_report, encoding='utf-8')
    if args.html:
        hp = Path(args.html)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(html_report, encoding='utf-8')
        print(f'html report -> {hp}')

    total = sum(len(v) for v in results.values())
    new = sum(1 for v in results.values() for it in v if it.get('is_new'))
    print(f'{total} targets ({new} new) -> {out_file}')

    if args.email:
        if total == 0:
            print('nothing to email today')
        else:
            send_email(f'Reddit GEO targets - {today} ({new} new)', digest)
            print('emailed digest')
    return 0


if __name__ == '__main__':
    sys.exit(main())
