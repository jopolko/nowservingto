#!/usr/bin/env python3
"""
Rewrite verifier evidence into editorial prose.

The validator's `validator_evidence` field is written by Haiku in a
verification-log register: "Website confirms X serves...", "Google
Places match shows...", "WEB VERIFY reports operational at...". That
voice leaks straight onto the LISTING-EXTRA "What we verified" panel
and the per-listing meta description.

This batch pass rewrites each evidence string into a 1-2 sentence
editorial blurb - what the restaurant is, what it serves, what's
distinctive - with no reference to websites, Places, verifications,
licences, or registries. Cached forever per _cacheKey in
tools/cache/evidence_rewrite_cache.json:
  {<cache_key>: {"blurb": "...", "raw": "...",
                 "in_tok": N, "out_tok": N,
                 "rewrote_at": ISO-8601, "via": "batch"}}

inject_openings.py prefers `validator_blurb` (from this cache) over
`validator_evidence` when rendering the listing-extra panel and the
meta description.

Cost: ~$0.13 for the full backlog (~430 entries), then ~$0.003/day
as new openings get verified.
"""
import os, sys, json, time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import re as _re

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH      = ROOT / 'data' / 'corridors.json'
WV_CACHE_PATH  = ROOT / 'tools' / 'cache' / 'web_verify_cache.json'
WT_CACHE_PATH  = ROOT / 'tools' / 'cache' / 'website_text_cache.json'
CACHE_PATH     = ROOT / 'tools' / 'cache' / 'evidence_rewrite_cache.json'
SECRETS        = Path('/var/secrets/nowservingto.env')
MODEL          = 'claude-haiku-4-5-20251001'
POLL_INTERVAL_SEC = 30

# Word-numbers (one..ninety + hundred). Mirrors the cleanup-pass script in
# tools/scrub_cache.py — any change here must mirror there.
_WORD_NUM = (r'(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
             r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|'
             r'thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)'
             r'(?:[\s-](?:one|two|three|four|five|six|seven|eight|nine))?')

# Defensive scrubber — even when the prompt explicitly bans these phrases,
# Haiku still slips them in occasionally. Anything matching here is stripped
# before the blurb hits the cache. Markers (⟂) preserve sentence boundaries.
_TIMEBOMB_PATTERNS = [
    # "opened just over ten weeks ago" / "opened 29 days ago"
    (_re.compile(rf',?\s*\bopened\s+(?:just\s+over\s+|just\s+under\s+|about\s+|around\s+|nearly\s+|over\s+)?'
                 rf'(?:a\s+|{_WORD_NUM}\s+|\d+\s+)?(?:few\s+|several\s+)?'
                 rf'(?:weeks?|months?|years?|days?)\s+ago\b\.?', _re.I), '⟂'),
    # "thirteen weeks ago" / "29 days old"
    (_re.compile(rf',?\s*\b(?:about\s+|around\s+|nearly\s+|over\s+|just\s+over\s+|just\s+under\s+)?'
                 rf'(?:a\s+|{_WORD_NUM}\s+|\d+\s+)(?:few\s+|several\s+)?'
                 rf'(?:weeks?|months?|years?|days?)\s+(?:ago|old)\b\.?', _re.I), '⟂'),
    # "this/last + month/week/year/season"
    (_re.compile(r',?\s*\b(?:this|last)\s+(?:month|week|year|spring|summer|fall|autumn|winter|quarter|season)\b\.?', _re.I), '⟂'),
    # "Among/One of/Now the freshest ___ openings"
    (_re.compile(r',?\s*\b(?:Among|One\s+of|Now)\s+(?:the\s+)?(?:freshest|newest)\s+[^.]*?openings?(?:\s+in\s+(?:the\s+)?(?:city|area|Toronto))?\b\.?', _re.I), '⟂'),
    # "in the past/last (few) N months"
    (_re.compile(r',?\s*\b(?:in|over|during)\s+(?:the\s+)?(?:past|last)\s+(?:few\s+)?\d*\s*(?:months?|weeks?|years?)\b\.?', _re.I), '⟂'),
    # "newly/recently/just opened/launched/debuted/established/inaugurated"
    (_re.compile(r',?\s*\b(?:newly|recently|just)\s+(?:opened|launched|debuted|established|inaugurated)\b\.?', _re.I), '⟂'),
    # "brand new" / "brand-new"
    (_re.compile(r'\bbrand[\s-]?new\b\s*', _re.I), '⟂'),
]

_SENT_STARTERS = r'(?:The|A|An|This|That|Among|One|Now|Verified|Operating|Licensed|Online|Reviewers?|Operators?|No)'
_PERIOD_FIXUP = _re.compile(rf'(\b\w+)(\s+)({_SENT_STARTERS}\s+\w)')
_BANNED_PRIOR = {'and','or','but','to','of','in','at','on','with','for',
                 'from','by','as','than','that','about','around','through',
                 'over','under','across','near','beyond','via','per','off'}


def _scrub_timebombs(text):
    """Run the defensive scrubber + period-restoration pass on a blurb.
    Returns the cleaned text. Idempotent."""
    if not text: return text
    for pat, repl in _TIMEBOMB_PATTERNS:
        text = pat.sub(repl, text)
    # Collapse markers: ⟂ at sentence end → period, mid-sentence → drop
    text = _re.sub(r'⟂\s*\.', '⟂', text)
    text = _re.sub(r'⟂\s*(?=[A-Z][a-z])', '. ', text)
    text = _re.sub(r'⟂', '', text)
    # Restore sentence-boundary periods the strips may have swallowed
    def _maybe_period(m):
        prior = m.group(1)
        if prior.lower() in _BANNED_PRIOR: return m.group(0)
        return prior + '. ' + m.group(3)
    prev = None
    while prev != text:
        prev = text
        text = _PERIOD_FIXUP.sub(_maybe_period, text)
    # Punctuation tidy-up
    text = _re.sub(r'\s{2,}', ' ', text)
    text = _re.sub(r'\s+([,.;:])', r'\1', text)
    text = _re.sub(r',\s*\.', '.', text)
    text = _re.sub(r',\s*,', ',', text)
    text = _re.sub(r'\.\s*\.', '.', text)
    text = _re.sub(r'^\s*,\s*', '', text)
    text = text.strip()
    if text:
        text = text[:1].upper() + text[1:]
    return text

SYSTEM_PROMPT = """You're writing editorial blurbs for a Toronto
restaurant directory. Each blurb reads like a directory entry from a
careful neighbourhood guide — factual, specific, and grounded in the
operating reality of the kitchen. The blurbs are indexed by AI
assistants (ChatGPT, Perplexity, Google AI Overviews), so each one
must be long enough to be cited as a complete answer — not a teaser.

You'll be given the restaurant's name, cuisine, address+district, prior
tenant (if the storefront had one), and a verification note containing
what we know about the operation. Write a blurb of **120-160 words**
following this four-sentence structure:

**TARGET REGISTER.** A food writer at Toronto Life or The Globe and
Mail spotting this listing should feel the directory understands the
city's culinary geography: specific, unsentimental, and genuinely
useful to someone deciding whether to make the trip. Not a capsule
review, not a press release. A precise answer to "what is this place
and why does it matter."

  Sentence 1 — WHAT: identify the cuisine and format only. ZERO
  location words anywhere in the blurb — no street name, no street
  suffix (Ave/St/Blvd/Rd/Dr/Cres/Way), no civic number, no district
  (Scarborough/Etobicoke/North York/Downtown/West Toronto/East Toronto).
  The full address and district are already on the card. The ONLY
  exception: a named iconic neighbourhood used for POSITIVE cultural
  framing — Little Jamaica, Thorncliffe Park, Kensington Market,
  Greektown, Corso Italia, Malvern. Frame it as a community asset,
  not a geographic fact: "A Tamil kitchen in Malvern" signals
  diaspora significance. NEVER describe a neighbourhood negatively
  or as marginal ("industrial fringe", "quiet stretch", "overlooked
  corner", "off the beaten path"). Every neighbourhood is someone's
  home and cultural anchor. "A kitchen on Bloor St" or "in
  Scarborough" are not cultural framing — they just repeat what the
  card already shows. When in doubt, drop the location reference.

  Sentence 2 — THE DIFFERENTIATOR: what makes THIS kitchen distinct
  from the generic version of this cuisine. The reader has 20 tabs open.
  Give them one fact that closes the tab. In order of preference:
    • A city or region of origin: if the evidence names Duhok, Hyderabad,
      Lahore, Guangzhou, Oaxaca, Addis Ababa — use that name. "Kurdish
      shawarma rooted in Duhok" is more useful than "Kurdish diaspora
      tradition." The city IS the differentiator.
    • A specific dish or technique not shared by every restaurant of
      this cuisine: Hủ Tiếu Nam Vang is not Pho. Makgeolli brewing is
      not Korean BBQ. Name the specific thing — and then tell the reader
      what it actually is. "Kothu Parotta, flatbread torn and stir-fried
      on a griddle" closes the tab. "Kothu Parotta" alone does not.
    • An operating format that changes who should go: counter-only
      takeout, full sit-down with bar, 24-hour, halal-certified,
      family-run with <30 seats. USE AN OWNERSHIP/FORMAT DESCRIPTOR ONLY
      WHEN THE EVIDENCE EXPLICITLY STATES IT (see GROUNDING below). Do not
      infer "family-run" from an individual operator name, a single
      location, or a homey vibe.

  Sentence 3 — DEPTH: expand on the differentiator. Who does this
  kitchen serve — which community, which diaspora, which occasion?
  If an iconic neighbourhood is genuinely relevant, this is where
  it belongs — but only if it adds meaning beyond the district.
  What gap does this kitchen fill? One concrete detail the evidence
  supports, written as a fact.

  Sentence 4 — THE ANSWER HOOK: a standalone, extractable claim
  that directly answers "what should I order" or "why is this
  worth going to" for someone who has never been. Write it as an
  assertion that can be lifted out of the blurb and cited alone.
  Examples of the register: "The lamb Mandi is slow-roasted whole
  and carved tableside, the kitchen's calling card since day one."
  "The counter runs a rotating selection of Oaxacan tlayudas not
  found elsewhere in the city." If the evidence supports no specific
  dish claim, make the hook about the format or the community need
  it fills: "One of the few halal-certified Ethiopian spots in the
  city, a meaningful address for that community."
  Never invent dishes; only name what the evidence explicitly supports.

  DO NOT add a source-attribution sentence ("Verified open via the
  City of Toronto licence registry" or similar). The site-wide
  methodology line on every page already attributes the source —
  repeating it per-entry is redundant boilerplate.

**FILLER BAN** — these phrases are forbidden because they apply to
every restaurant and therefore say nothing:
  • "time-honored techniques" / "time-honoured"
  • "passed through generations" / "generational recipes"
  • "bold, aromatic cooking that defines the cuisine"
  • "authentic preparations of traditional fare"
  • "authentic flavors" / "authentic taste"
  • "the cuisine in general terms"
  • "a kitchen that takes classic techniques seriously"
  • "drawing on the rich culinary tradition"
  • "vibrant" / "diverse" / "rich tapestry"
  • "inviting atmosphere" / "warm atmosphere"
  • any sentence that would be equally true of every other
    restaurant of the same cuisine in the directory.
If you reach for one of these, stop and ask: what specific fact
from the evidence replaces this? If there is none, end earlier.

**GROUNDING — every operational claim must trace to the evidence note.**
The note is the only source for operational facts. But you know what
dishes ARE. Culinary context is NOT grounding-restricted:
  • DISH DESCRIPTIONS — explaining what a named dish is (ingredients,
    cooking method, texture, regional origin) is ALWAYS allowed. It uses
    your documented culinary knowledge, not inferred restaurant-specific
    facts. "Kothu Parotta is flatbread torn and stir-fried on a hot
    griddle" is a culinary fact, not a claim about this restaurant.
    "Injera is a fermented flatbread used as a communal plate" is a
    culinary fact. Use this latitude to make blurbs informative.
  • NEIGHBOURHOOD CULTURAL CONTEXT — when the address places a restaurant
    in a neighbourhood with a documented diaspora concentration (Malvern
    for Tamil, Agincourt for East Asian, Little Ethiopia on Danforth, etc.),
    you may note that context. It's verifiable geography, not a claim about
    this specific operator.
The grounding restriction applies to OPERATIONAL claims only:
  • OWNERSHIP / OPERATOR STRUCTURE — "family-run", "family-owned",
    "husband-and-wife", "woman-owned", "veteran-owned", "owner-operated",
    "independent", "chain", "franchise": write it ONLY if the note states
    it in those terms. An individual licensee name, a single address, or
    a warm tone is NOT evidence of a family operation. When the note says
    "multi-location", "franchise", "Locations plural", or "corporate", the
    place is a CHAIN BRANCH, not "family-run" — say so plainly.
  • POPULARITY / REPUTATION — a place's standing is review-derived and we
    do not carry it. BANNED outright (they are unverifiable mood, not facts):
    "built / earned / won / gained a (loyal/devoted/steady) following",
    "loyal following", "hidden gem", "go-to (spot)", "neighbourhood
    favourite / institution / gem", "beloved", "draws praise", "winning
    over", "word of mouth", "cult following", "under the radar", "labour
    of love", "without (the) fanfare", "keeps regulars coming back". These
    restate review sentiment in disguise — drop them entirely.
  • A "long history" / "established" / "since YEAR" claim is allowed ONLY
    when the note gives the year or explicitly calls it established /
    pre-existing / a relocation or renewal. Do not infer age from a licence
    date (the licence can post-date the business by decades, or be brand new).
If stripping ungrounded clauses leaves you with two honest sentences,
ship two honest sentences. A short true blurb beats a padded inferred one.

Hard rules:
  - First letter of the blurb MUST be capitalized (full sentence case).
  - **CAPITALIZE proper nouns** correctly:
      • Cuisine adjectives: Indian, Italian, Vietnamese, Sri Lankan,
        Hakka, Hyderabadi, Telangana, Cantonese, Eelam, Habesha.
      • Neighbourhoods: Downtown, Scarborough, Etobicoke, North York,
        East Toronto, West Toronto, Midtown, East York.
      • Street names: Davenport Rd, Queen St W, Bloor St, Spadina Ave.
      • Dish names: Biryani, Mandi, Dosa, Idli, Vada, Paratha, Naan,
        Samosa, Paneer, Tikka, Masala, Tandoori, Kebab, Shawarma,
        Bibimbap, Kimchi, Bulgogi, Sushi, Sashimi, Ramen, Pho, Banh Mi,
        Pad Thai, Tom Yum, Laksa, Satay, Rendang, Hopper, Hoppers,
        Kothu, Parotta, Injera, Tibs, Shiro, Jollof, Empanada, Pupusa,
        Ceviche, Mole, Birria, Pierogi, Borscht, Falafel, Hummus,
        Baklava, Kibbeh, Shakshuka, Tahdig, Koobideh, Ghormeh Sabzi,
        Char Siu, Xiao Long Bao, Dim Sum, Wonton, Bao, Momo, Laphing.
      • When a dish name appears as a multi-word phrase (Pad Thai, Tom
        Yum, Banh Mi, Tikka Masala, Butter Chicken, Char Siu, Pani
        Puri), capitalize each word.
      • Cooking-method words that are not dish names stay lowercase
        (dum-cooked, slow-braised, wood-fired, seekh-skewered).
  - DO NOT start with the restaurant name. Lead with the cuisine
    or kitchen format.
  - **TIME-BOMB BAN** — the blurb is cached permanently, so anything
    relative-to-now goes stale and becomes a lie in production. Forbidden:
      • "opened N weeks/months/years/days ago" (any form, including word
        numbers — "opened just over ten weeks ago", "opened five weeks ago")
      • bare "N weeks/months/years/days ago" or "N days old"
      • "this month / this week / this year / this season"
      • "last month / last year / last quarter"
      • "recently opened / newly opened / just opened / brand new"
      • "Among the freshest ___ openings", "One of the newest ___ in the city"
      • "in the past few months", "in the last year"
    Allowed time references (do not go stale): "licensed in summer 2025",
    "licensed in August 2025", "operating since 2024", "opened in 2024".
    Bare month-year and bare year are fine. "newly registered" is fine —
    it restates the coverage policy, not a relative-to-now claim.
  - DO NOT cite reviews, reviewers, ratings, or sources — ever. Banned:
    "reviewers/diners/customers/patrons (consistently/often) praise/note/
    rave/love/highlight", "highly rated", "well-reviewed", "5-star",
    "N reviews", "according to reviews/diners", and any attribution to
    Google, Google Places, Google Maps, "Google reviews", or "Places
    reviews". We do NOT have review data for every listing, so review
    sentiment is never used — including it would give some listings
    special treatment. Treat any review snippet in the note as raw factual
    intel and restate the fact directly, with no sentiment and no source.
    (Reviews citing "great biryani" → "the biryani is the calling card",
    NOT "reviewers praise the biryani".)
  - DO NOT use research/source artefacts: "the website says", "according
    to their social media", "their online presence", "appears to be",
    "seems to", "reportedly", "based on available information". State facts
    plainly from what the evidence supports.
  - DO NOT fabricate. If the note doesn't name a dish, write about
    the cuisine in general terms or skip that beat. Never invent
    operators, neighbourhoods, or signature dishes.
  - DO NOT use em-dashes or en-dashes. Use commas, periods, or
    parenthetical asides.
  - DO NOT add a source-attribution closing sentence. The site
    methodology line handles source attribution site-wide.
  - Return PURE JSON ONLY — no ```json fences, no markdown wrapper.

Return JSON on one line:
  {"blurb": "<your 40-90 word blurb, no source-attribution closing>"}
"""


def load_api_key():
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit("ANTHROPIC_API_KEY not in secrets")


API_KEY = load_api_key()
HEADERS = {
    'x-api-key': API_KEY,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}


def http_request(method, url, data=None):
    body = json.dumps(data).encode('utf-8') if data else None
    req = Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urlopen(req, timeout=120) as r:
            raw = r.read()
            ctype = r.headers.get('Content-Type', '')
            if 'application/json' in ctype:
                return json.loads(raw)
            return raw
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        raise


def main():
    force = '--force' in sys.argv
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache state: total={len(cache)}{' (--force: regenerating all)' if force else ''}")

    if not DATA_PATH.exists():
        sys.exit(f"{DATA_PATH} missing")
    if not WV_CACHE_PATH.exists():
        sys.exit(f"{WV_CACHE_PATH} missing")

    data = json.loads(DATA_PATH.read_text())
    wv = json.loads(WV_CACHE_PATH.read_text())
    wt = json.loads(WT_CACHE_PATH.read_text()) if WT_CACHE_PATH.exists() else {}
    recent = data.get('newOpenings', {}).get('recent', [])

    # Cuisine label lookup (raw keys → display labels)
    labels = {}
    for c in data.get('newOpenings', {}).get('cuisines', []):
        if c.get('key'): labels[c['key']] = c.get('label', c['key'])

    targets = []   # list of (cache_key, name, cuisine_label, address, district, prior, evidence)
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck or (ck in cache and not force): continue
        # NEVER regenerate a hand-authored, fact-checked blurb, even under
        # --force. These (opus_manual_v1) were grounded against the evidence
        # by a human-reviewed pass; a Haiku rewrite would reintroduce the
        # inference/embellishment we removed. --force still regenerates
        # machine blurbs (batch / haiku_editorial_*).
        if cache.get(ck, {}).get('via', '').startswith('opus_manual'): continue
        wv_e = wv.get(ck) or {}
        ev = (wv_e.get('validator_evidence') or wv_e.get('evidence') or '').strip()
        ev_src = 'verify'
        # Prefer own-website text when it's meaningfully richer than the
        # validator_evidence. This covers web_search-only entries (no Places
        # match) whose evidence is a single thin sentence, and any entry
        # whose website has menu/dish detail the verifier didn't capture.
        site = (r.get('website') or '').strip()
        wt_text = ((wt.get(site) or {}).get('text') or '') if site else ''
        wt_text = wt_text.replace('HOMEPAGE (jina-rendered):', '').replace('HOMEPAGE:', '').strip()
        if len(wt_text) >= 300 and len(wt_text) > len(ev) * 2:
            ev, ev_src = wt_text[:2000], 'website'
        if not ev:
            continue
        keys = r.get('cuisines') or ([r['cuisine']] if r.get('cuisine') else [])
        cuisine_label = labels.get(keys[0], keys[0].title()) if keys else 'restaurant'
        addr = (r.get('address') or '').strip()
        district = (r.get('district') or '').strip()
        prior = ((r.get('priorTenant') or {}).get('name') or '').strip()
        targets.append((ck, r.get('operatingName', ''), cuisine_label, addr, district, prior, ev, ev_src))

    print(f"  candidates: {len(targets)} uncached entries")

    if not targets:
        print("nothing to rewrite.")
        return

    requests = []
    target_keys = []
    for ck, name, cuisine, addr, district, prior, ev, ev_src in targets:
        custom_id = 'e' + str(abs(hash(ck)) & 0x7fffffff)
        prompt_lines = [
            f"Restaurant: {name}",
            f"Cuisine: {cuisine}",
            f"Address: {addr}" + (f" ({district})" if district else ''),
        ]
        # prior tenant intentionally omitted — "taking over from X" implies
        # closure which we can't verify; DineSafe address matching is imprecise.
        if ev_src == 'website':
            prompt_lines.append(
                "Source — the restaurant's own website text (extract real "
                "dishes / focus from it; ignore nav labels, hours, and "
                "ordering/catering boilerplate):")
            prompt_lines.append(ev)
        else:
            prompt_lines.append(f"Verification note: {ev}")
        prompt_lines.append("")
        prompt_lines.append(
            "Write a 130-160 word editorial blurb following the "
            "four-sentence structure in the system prompt. Do not add a "
            "source-attribution closing sentence."
        )
        prompt = '\n'.join(prompt_lines)
        requests.append({
            'custom_id': custom_id,
            'params': {
                'model': MODEL,
                'max_tokens': 600,
                # cache_control: the ~3k-token system prompt is identical across
                # every request in the batch. Batch-API cache hits are
                # best-effort, but any hit prices the prefix at -90% vs the
                # +25% write premium on misses, so it pays off past 2-3
                # requests per batch. Same pattern as llm_verify_batch.py.
                'system': [{'type': 'text', 'text': SYSTEM_PROMPT,
                            'cache_control': {'type': 'ephemeral'}}],
                'messages': [{'role': 'user', 'content': prompt}],
            },
        })
        target_keys.append(ck)

    id_to_key = {r['custom_id']: k for r, k in zip(requests, target_keys)}
    print(f"submitting batch of {len(requests)} requests…")
    submit_resp = http_request('POST',
                               'https://api.anthropic.com/v1/messages/batches',
                               {'requests': requests})
    batch_id = submit_resp['id']
    print(f"  batch_id: {batch_id}")
    print(f"  status: {submit_resp['processing_status']}")

    print("polling…")
    t0 = time.time()
    while True:
        time.sleep(POLL_INTERVAL_SEC)
        info = http_request('GET',
                            f'https://api.anthropic.com/v1/messages/batches/{batch_id}')
        st = info['processing_status']
        counts = info.get('request_counts', {})
        el = time.time() - t0
        print(f"  [{el:.0f}s]  status={st}  counts={counts}")
        if st == 'ended': break
        if st in ('cancelling', 'canceled', 'expired'):
            sys.exit(f"batch ended unexpectedly: {st}")

    results_url = info.get('results_url')
    if not results_url:
        sys.exit("no results_url on completed batch")
    print(f"downloading results from {results_url}")
    raw = http_request('GET', results_url)
    raw_text = json.dumps(raw) if isinstance(raw, dict) else raw.decode('utf-8')

    n_ok = n_err = 0
    total_in = total_out = 0
    rewrote_at = datetime.utcnow().isoformat() + 'Z'
    for line in raw_text.strip().split('\n'):
        if not line.strip(): continue
        obj = json.loads(line)
        cid = obj.get('custom_id')
        ck = id_to_key.get(cid)
        if not ck: continue
        result = obj.get('result', {})
        rtype = result.get('type')
        if rtype != 'succeeded':
            n_err += 1
            cache[ck] = {'status': 'error', 'error': f'batch {rtype}',
                         'rewrote_at': rewrote_at}
            continue
        msg = result.get('message', {})
        usage = msg.get('usage', {})
        total_in += usage.get('input_tokens', 0)
        total_out += usage.get('output_tokens', 0)
        text_out = ''.join(b.get('text', '') for b in msg.get('content', [])
                           if b.get('type') == 'text').strip()
        # Parse JSON; if Haiku didn't wrap it in JSON, treat the raw text
        # as the blurb directly (defensive fallback).
        blurb = ''
        parsed = None
        for ln in text_out.split('\n'):
            s = ln.strip().lstrip('`').strip()
            if s.startswith('{') and s.endswith('}'):
                try: parsed = json.loads(s); break
                except Exception: continue
        if parsed and isinstance(parsed.get('blurb'), str):
            blurb = parsed['blurb'].strip()
        else:
            # Fallback: use the raw text minus any leading "blurb:" prefix
            blurb = text_out.strip().strip('"\'')
            if blurb.lower().startswith('blurb:'):
                blurb = blurb[6:].strip().strip('"\'')
        if not blurb:
            n_err += 1
            cache[ck] = {'status': 'error', 'error': 'empty-blurb',
                         'raw': text_out[:200], 'rewrote_at': rewrote_at}
            continue
        # Defensive cleanup: capitalize first letter, strip em/en-dashes,
        # scrub time-bomb phrases (anything relative-to-now that goes stale),
        # and strip any source-attribution closing sentence Haiku still
        # appends despite the prompt ban. The site methodology line handles
        # source attribution site-wide; per-entry repetition is redundant.
        blurb = blurb[:1].upper() + blurb[1:] if blurb else blurb
        blurb = blurb.replace('—', ',').replace('–', ',')
        blurb = _scrub_timebombs(blurb)
        blurb = _re.sub(
            r"\s*Verified\s+open\s+via\s+the\s+City('s|\s+of\s+Toronto)\s+licence\s+registry\.\s*$",
            '', blurb, flags=_re.I).rstrip()
        if blurb and blurb[-1] not in '.!?':
            blurb += '.'
        cache[ck] = {
            'status': 'ok',
            'blurb': blurb,
            'raw': text_out[:280],
            'in_tok': usage.get('input_tokens', 0),
            'out_tok': usage.get('output_tokens', 0),
            'via': 'haiku_editorial_v3_geo',
            'rewrote_at': rewrote_at,
        }
        n_ok += 1

    CACHE_PATH.write_text(json.dumps(cache, separators=(',', ':')))
    cost = (total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0) * 0.5
    print(f"\nbatch merged: ok={n_ok} err={n_err}  "
          f"tokens in={total_in:,} out={total_out:,}  "
          f"est ${cost:.3f} (50%-off batch)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from usage_log import log_usage
        log_usage('anthropic.haiku.batch.in',  units=total_in,
                  meta={'script': 'evidence_rewrite_batch', 'batch_id': batch_id})
        log_usage('anthropic.haiku.batch.out', units=total_out,
                  meta={'script': 'evidence_rewrite_batch', 'batch_id': batch_id})
    except Exception:
        pass


if __name__ == '__main__':
    main()
