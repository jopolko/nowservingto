#!/usr/bin/env python3
"""SaaS-opportunity scanner: Reddit wish/pain x Observatory AI-demand.

Crosses two real signals:
  1. DEMAND - what AI assistants actually fetch from joshuaopolko.com to answer
     people (top AI-read paths from the access log = aggregate ChatGPT/Claude
     demand). Hardcoded snapshot below; refresh from crawl_insight.signals().
  2. PAIN  - Reddit posts in those same topics that express an unmet need
     ("I wish there was", "is there a tool", "keeps failing", "self-hosting X
     is a nightmare", ...).

A topic scores high when people are clearly in pain AND assistants are already
sourcing answers there. That overlap is the shortlist.

Reuses reddit_harvest's fetch/parse helpers (stdlib only, RSS token from
/var/secrets). Standalone - does NOT touch the daily content pipeline.

  python3 saas_opportunity_scan.py            # live run, prints + writes JSON
"""
import json, time, datetime as dt
from pathlib import Path
import reddit_harvest as rh

OUT = Path(rh.ROOT) / 'tools' / 'cache' / 'saas_opportunities.json'

# DEMAND axis: jo top AI-read paths (7d snapshot). Refresh via crawl_insight.
# topic -> {demand: AI-read hits, kw: aliases to detect the topic in text}
TOPICS = {
    'agent-zero':  {'demand': 133, 'kw': ['agent zero', 'agent-zero', 'agentzero']},
    'dify':        {'demand': 129, 'kw': ['dify']},
    'searxng':     {'demand': 101, 'kw': ['searxng', 'searx']},
    'claude-code': {'demand': 74,  'kw': ['claude code', 'claude-code', ' mcp ', 'mcp server']},
    'n8n':         {'demand': 60,  'kw': ['n8n']},
    'crewai':      {'demand': 39,  'kw': ['crewai', 'crew ai']},
    'self-host-ai':{'demand': 80,  'kw': ['self host', 'self-host', 'selfhost', 'self hosted', 'homelab ai']},
    'geo-aeo':     {'demand': 70,  'kw': ['generative engine optimization', 'ai overview', 'get cited', 'llm seo', 'geo for', 'cited by chatgpt']},
}

# Reddit search lanes (broad topic, sorted new); pain is filtered client-side.
LANES = [
    ('dify self hosted', 'dify'), ('dify ai workflow', 'dify'),
    ('n8n self hosted', 'n8n'), ('n8n automation', 'n8n'),
    ('searxng', 'searxng'),
    ('agent zero ai agent', 'agent-zero'),
    ('crewai', 'crewai'), ('crewai production', 'crewai'),
    ('claude code mcp', 'claude-code'), ('mcp server', 'claude-code'),
    ('self hosted ai agent', 'self-host-ai'), ('self hosted llm', 'self-host-ai'),
    ('ai agent framework', 'self-host-ai'),
    ('generative engine optimization', 'geo-aeo'), ('get cited by chatgpt', 'geo-aeo'),
    ('llm seo', 'geo-aeo'),
]

# Strong intent/pain phrases only (generic ones like "manually"/"there is no"
# produced false positives, so they are deliberately excluded).
PAIN = [
    'is there a tool', 'is there an app', 'is there a service', 'is there any tool',
    'does anyone know a tool', 'looking for a tool', 'looking for an alternative',
    'any alternative to', 'better alternative', 'alternative to',
    'i wish', 'wish there was', 'wish there were', 'wish someone would',
    'keeps failing', 'keeps crashing', 'keeps breaking', 'gave up on',
    "can't get it to work", 'a nightmare', 'wasted hours', 'wasted a day',
    'struggling with', 'frustrated', 'frustrating', 'why is there no', 'no good tool',
    'how do i automate', 'tired of', 'so i built', 'built a tool', 'built an open-source',
    'i built this because', 'pain point',
]
# subs that are pure self-promo / cross-posted profiles (drop)
SUB_BLOCK = ('promotion', 'promo', '_stock', 'stock')

MAXD = max(t['demand'] for t in TOPICS.values())


def topic_of(text):
    """A post only counts for a topic if it ACTUALLY mentions it (co-occurrence
    with a pain phrase is enforced in the loop). No lane-topic fallback - that
    was the source of the off-topic noise in v1."""
    low = text.lower()
    for name, t in TOPICS.items():
        if any(k in low for k in t['kw']):
            return name
    return None


# Moat classifier - the r/microsaas "why wouldn't they just use ChatGPT?" test.
# Defensible classes checked first; a post matching any of them is NOT a wrapper.
# Only posts whose sole signal is wrapper-ish get demoted.
MOAT_SIGNALS = [
    ('regulated',    ['hipaa', 'compliance', 'regulat', 'legal', 'lawyer', 'medical',
                      'patient', ' tax ', 'gdpr', 'soc2', 'soc 2', 'audit', 'phi ']),
    ('private-data', ['my data', 'our data', 'internal', 'proprietary', 'slack', 'crm',
                      'our codebase', 'company data', 'knowledge base', 'private repo',
                      'integrate with', 'connect to my', 'sync with', 'jira',
                      'confluence', 'notion', 'google drive']),
    ('live-data',    ['real-time', 'real time', 'realtime', 'live data', 'up-to-date',
                      'up to date', 'current data', 'monitor', 'scrape', 'scraping',
                      'crawl', 'fresh data', 'price tracking', 'unblockable']),
    ('autonomous',   ['runs on its own', 'unattended', '24/7', '24-7', 'always-on',
                      'always on', 'scheduled', 'cron', 'background', 'autonomous',
                      'agent that', 'runs reliably', 'self-host', 'self host',
                      'self hosted', 'proxy', 'drop-in', 'gateway', 'middleware',
                      'pipeline', 'circuit breaker', 'rate limit', 'cost cap']),
    ('wrapper',      ['just ask chatgpt', 'wrapper', 'rewrite', 'summari',
                      'generate content', 'copywriting', 'blog post',
                      'content generation', 'chatbot', 'ai writer', 'brainstorm',
                      'prompt template']),
]
MOAT_FACTOR = {'regulated': 1.30, 'private-data': 1.25, 'live-data': 1.15,
               'autonomous': 1.10, 'unclear': 1.00, 'wrapper': 0.30}


def moat_of(text):
    """Strongest defensibility signal in the post; 'wrapper' only if that's all
    it has. Wrappers (things a model just does) get demoted in scoring."""
    low = text.lower()
    for label, kws in MOAT_SIGNALS:
        if any(k in low for k in kws):
            return label
    return 'unclear'


def scan():
    """Run the cross and return the result dict (also writes the JSON snapshot).
    Returns {'error': ...} if the Reddit token is unavailable - callers render
    that gracefully so the weekly email still sends."""
    user = rh.ENV.get('REDDIT_FEED_USER', '')
    token = rh.ENV.get('REDDIT_FEED_TOKEN', '')
    if not user or not token:
        return {'error': 'no Reddit token (REDDIT_FEED_USER / REDDIT_FEED_TOKEN)'}

    seen, posts = set(), []
    lanes_ok = lanes_err = 0
    for q, _lane_topic in LANES:
        url = rh.build_url(f'search:{q}', user, token, 25)
        try:
            items = rh.parse_atom(rh.fetch(url))
            lanes_ok += 1
        except Exception:
            lanes_err += 1
            time.sleep(1.5); continue
        for it in items:
            if it['url'] in seen or rh.is_noise(it):
                continue
            sub = (it['sub'] or '').lower()
            if sub.startswith('u_') or any(b in sub for b in SUB_BLOCK):
                continue
            blob = (it['title'] + ' ' + it['body']).lower()
            topic = topic_of(blob)          # require a real topic mention
            if not topic:
                continue
            markers = [p for p in PAIN if p in blob]   # AND a real pain phrase
            if not markers:
                continue
            if rh.hours_old(it['ts']) > 24 * 120:  # keep ~120d window
                continue
            seen.add(it['url'])
            posts.append({
                'topic': topic, 'moat': moat_of(blob),
                'title': it['title'], 'url': it['url'], 'sub': it['sub'],
                'markers': markers[:4], 'age_h': round(rh.hours_old(it['ts']), 1),
            })
        time.sleep(1.5)

    # aggregate per topic
    agg = {}
    for p in posts:
        a = agg.setdefault(p['topic'], {'pain_n': 0, 'examples': [], 'moats': []})
        a['pain_n'] += 1
        a['moats'].append(p['moat'])
        if len(a['examples']) < 4:
            a['examples'].append(p)
    rows = []
    for topic, a in agg.items():
        demand = TOPICS.get(topic, {}).get('demand', 0)
        # opportunity = pain volume x validated AI-demand x moat (wrappers demoted)
        moat = max(a['moats'], key=lambda m: MOAT_FACTOR.get(m, 1.0))
        base = a['pain_n'] * (0.5 + demand / MAXD)
        score = round(base * MOAT_FACTOR.get(moat, 1.0), 2)
        rows.append({'topic': topic, 'demand': demand, 'pain_n': a['pain_n'],
                     'moat': moat, 'score': score, 'examples': a['examples']})
    rows.sort(key=lambda r: r['score'], reverse=True)

    d = {'generated': dt.datetime.utcnow().isoformat() + 'Z',
         'lanes_ok': lanes_ok, 'lanes_err': lanes_err,
         'total_pain_posts': len(posts), 'ranked': rows}
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    except Exception:
        pass
    return d


def render_report(d, top=5, ex_per=2):
    """Compact plain-text block for the weekly GEO email."""
    if d.get('error'):
        return f"  scan unavailable: {d['error']}"
    rows = d.get('ranked', [])
    out = [f"  {d['total_pain_posts']} pain posts / {d['lanes_ok']} lanes (~120d). "
           "Reddit wish-pain x AI-read demand. Directional; 'so I built' = strongest signal.",
           "  moat = the 'why not just ChatGPT?' answer: regulated/private-data/live-data/"
           "autonomous are defensible; [wrapper] = model does it directly, demoted."]
    if not rows:
        out.append("  no clear pain x demand overlap this week.")
        return "\n".join(out)
    for i, r in enumerate(rows[:top], 1):
        flag = '  <- likely just-ChatGPT, demoted' if r['moat'] == 'wrapper' else ''
        out.append(f"  {i}. {r['topic']} [{r['moat']}] - pain {r['pain_n']} "
                   f"x AI-read {r['demand']} (score {r['score']}){flag}")
        for ex in r['examples'][:ex_per]:
            out.append(f"       r/{ex['sub']}: {ex['title'][:82]}")
            out.append(f"       {ex['url']}")
    return "\n".join(out)


def main():
    d = scan()
    print("=== SaaS OPPORTUNITY SHORTLIST (pain x AI-demand) ===")
    print(render_report(d, top=8, ex_per=3))
    if not d.get('error'):
        print(f"\nwrote {OUT}")


if __name__ == '__main__':
    main()
