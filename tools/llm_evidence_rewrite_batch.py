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
operating reality of the kitchen.

You'll be given the restaurant's name, cuisine, address+district, prior
tenant (if the storefront had one), and a verification note containing
what we know about the operation. Write a blurb of **70-110 words**
following this structure:

  Sentence 1 — WHAT + WHERE: identify the cuisine/format and the
  specific neighbourhood + street it sits on. Reference the prior
  tenant if one is provided ("taking over from X" / "in a unit most
  recently held by X").

  Sentence 2-4 — WHO + DIFFERENTIATOR: name the signature dishes,
  the regional cuisine sub-style (Hyderabadi vs. Punjabi, Cantonese
  vs. Sichuan, Tamil vs. Sinhalese, etc.) when the note supports it,
  the operating format (counter, sit-down, family-run, halal, etc.),
  and what distinguishes the kitchen. End on a factual closer about
  the operation — neighbourhood corridor, online ordering presence,
  hours format, sit-down vs takeout, etc.

  DO NOT add a source-attribution sentence ("Verified open via the
  City of Toronto licence registry" or similar). The site-wide
  methodology line on every page already attributes the source —
  repeating it per-entry is redundant boilerplate.

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
  - DO NOT attribute facts to Google, Google Places, Google Maps,
    Google reviews, or "Places reviews". Treat any review snippets in
    the note as raw factual intel — restate the fact directly without
    citing the source. (Reviews citing "great biryani" → write "the
    biryani is the calling card", not "reviewers praise the biryani".)
  - DO NOT fabricate. If the note doesn't name a dish, write about
    the cuisine in general terms or skip that beat. Never invent
    operators, neighbourhoods, or signature dishes.
  - DO NOT use em-dashes or en-dashes. Use commas, periods, or
    parenthetical asides.
  - DO NOT add a source-attribution closing sentence. The site
    methodology line handles source attribution site-wide.
  - Return PURE JSON ONLY — no ```json fences, no markdown wrapper.

Return JSON on one line:
  {"blurb": "<your 70-110 word blurb, no source-attribution closing>"}
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
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"cache state: total={len(cache)}")

    if not DATA_PATH.exists():
        sys.exit(f"{DATA_PATH} missing")
    if not WV_CACHE_PATH.exists():
        sys.exit(f"{WV_CACHE_PATH} missing")

    data = json.loads(DATA_PATH.read_text())
    wv = json.loads(WV_CACHE_PATH.read_text())
    recent = data.get('newOpenings', {}).get('recent', [])

    # Cuisine label lookup (raw keys → display labels)
    labels = {}
    for c in data.get('newOpenings', {}).get('cuisines', []):
        if c.get('key'): labels[c['key']] = c.get('label', c['key'])

    targets = []   # list of (cache_key, name, cuisine_label, address, district, prior, evidence)
    for r in recent:
        ck = r.get('_cacheKey', '')
        if not ck or ck in cache: continue
        wv_e = wv.get(ck) or {}
        ev = (wv_e.get('validator_evidence') or wv_e.get('evidence') or '').strip()
        if not ev: continue
        keys = r.get('cuisines') or ([r['cuisine']] if r.get('cuisine') else [])
        cuisine_label = labels.get(keys[0], keys[0].title()) if keys else 'restaurant'
        addr = (r.get('address') or '').strip()
        district = (r.get('district') or '').strip()
        prior = ((r.get('priorTenant') or {}).get('name') or '').strip()
        targets.append((ck, r.get('operatingName', ''), cuisine_label, addr, district, prior, ev))

    print(f"  candidates: {len(targets)} uncached entries")

    if not targets:
        print("nothing to rewrite.")
        return

    requests = []
    target_keys = []
    for ck, name, cuisine, addr, district, prior, ev in targets:
        custom_id = 'e' + str(abs(hash(ck)) & 0x7fffffff)
        prompt_lines = [
            f"Restaurant: {name}",
            f"Cuisine: {cuisine}",
            f"Address: {addr}" + (f" ({district})" if district else ''),
        ]
        if prior:
            prompt_lines.append(f"Prior tenant at this address: {prior}")
        prompt_lines.append(f"Verification note: {ev}")
        prompt_lines.append("")
        prompt_lines.append(
            "Write an 80-120 word editorial blurb following the structure "
            "in the system prompt. End with the verbatim source-assertion "
            "sentence."
        )
        prompt = '\n'.join(prompt_lines)
        requests.append({
            'custom_id': custom_id,
            'params': {
                'model': MODEL,
                'max_tokens': 400,
                'system': SYSTEM_PROMPT,
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
            'via': 'haiku_editorial_v2',
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
