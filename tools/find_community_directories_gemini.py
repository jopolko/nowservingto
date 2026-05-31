#!/usr/bin/env python3
"""Gemini-backed twin of find_community_directories.py.

Different search index + different model temperament = different
candidates. Run alongside the Haiku spider, merge the two output sets,
dedupe by domain. Combined coverage > either tool alone.

Why not just Haiku? Gemini's grounding-with-Google-Search surfaces
long-tail community directories that don't rank high enough on
Bing/web for Haiku's web_search tool to catch. Real example: the
Haiku spider missed tamildirectory.ca despite it being a legitimate
Tamil-Canadian directory the user found manually first. Gemini may
surface it (or others like it) on its first sweep.

Output schema matches the Haiku version exactly so build_submission_cheatsheet.py
can consume either one. Each candidate gets a `source` tag so we can
attribute who found what.

Setup:
  1. Get a key: https://aistudio.google.com/app/apikey
  2. Add to /var/secrets/nowservingto.env: GEMINI_API_KEY=...
  3. Run: python tools/find_community_directories_gemini.py [--cuisine X] [--top 15]

Cost: Gemini 2.5 Flash with Google Search grounding. Free tier covers
the full 15-cuisine sweep with room to spare.

After both spiders run, merge with:
  python tools/merge_directory_candidates.py
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent.parent
CORRIDORS_PATH = ROOT / 'data' / 'corridors.json'
OUT_PATH = ROOT / 'data' / 'community_directory_candidates_gemini.json'
CACHE_PATH = ROOT / 'tools' / 'cache' / 'community_directory_cache_gemini.json'
SECRETS = Path('/var/secrets/nowservingto.env')
MODEL = 'gemini-2.5-flash'  # update to latest Flash when needed

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cuisines import CUISINE_LABEL

def load_api_key():
    if not SECRETS.exists():
        sys.exit(f'secrets file missing: {SECRETS}')
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('GEMINI_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit('GEMINI_API_KEY not in /var/secrets/nowservingto.env')

API_KEY = load_api_key()

# Same system instructions as the Haiku version - keeps candidate quality
# comparable so the merge is apples-to-apples. Minor tweak: explicitly ask
# for long-tail / lesser-known directories Gemini might have indexed but
# Bing didn't surface. That's the whole reason for running this twin.
SYSTEM_INSTRUCTION = """You research cultural-community business directories in
Toronto and Canada that accept new business submissions. The user runs a
free aggregator listing newly-registered Toronto restaurants by cuisine
(NowServingTO) and wants to submit cuisine-specific landing pages to
diaspora-focused directories so the right community discovers the resource.

Prioritize LONG-TAIL and lesser-known cultural directories that may not
rank highly in general web search but are well-known within the diaspora
community. Examples of what counts:
  - Cultural-community directories (Tamil Directory, Filipino Channel,
    Persian Toronto, etc.) - narrow audience, NOT generic Yellow Pages
  - Diaspora-language newspapers with a business listings section
  - Ethnic community association websites with member-business directories
  - Faith-community business directories when relevant to the cuisine

EXCLUDE: Yelp, Yellow Pages, Google Maps, blogTO, abandoned sites (no
updates in 12+ months), sites with no submission mechanism, listings that
charge >$100, blogspot/wordpress.com hobby blogs.

Return JSON only - no prose, no markdown fences. Schema:

{
  "candidates": [
    {
      "url": "https://example.ca/",
      "name": "Example Tamil Directory",
      "submission_url": "https://example.ca/add-business",
      "audience": "Tamil-Canadian diaspora, GTA-focused",
      "accepts_submissions": "yes|no|unclear",
      "still_active": "yes|no|unclear",
      "freshness_evidence": "quoted snippet from the site showing a 2025+
                             date, e.g. 'Posted May 14, 2026' or 'New
                             listing added April 2025'",
      "last_dated_content_year": 2024 | 2025 | 2026 | null,
      "confidence": 0.0-1.0,
      "rationale": "one sentence explaining the score"
    }
  ]
}

FRESHNESS IS A FIRST-CLASS GATE (added 2026-05-30):
  Many dead community directories return HTTP 200 with a frozen 2019
  homepage indefinitely. DO NOT trust "the site loads" - require a
  quoted 2025+ date marker before scoring still_active=yes. If the
  homepage has no dates, check sub-paths like /listings, /directory,
  /blog, /news, /recent. Set last_dated_content_year to the most
  recent year you can prove with quoted evidence; null if none found.
  Down-rank confidence sharply if last_dated_content_year <= 2024.
  Exclude entirely if last_dated_content_year <= 2022 OR no year
  evidence AND the site looks like a static brochure.

If you find ZERO good candidates for a cuisine, return {"candidates": []}."""

def build_user_prompt(cuisine_key, label):
    return (
        f"Find directories where I could submit my Toronto restaurant "
        f"aggregator page (https://nowservingto.com/cuisine/{cuisine_key}) "
        f"so the {label}-Canadian community in Toronto and the GTA "
        f"discovers it. Prefer narrow cultural-community directories and "
        f"diaspora-press business sections. Use Google Search to verify "
        f"that each candidate's submission page actually loads. "
        f"Return ONLY the JSON object."
    )

def gemini_call(cuisine_key, label):
    url = (f'https://generativelanguage.googleapis.com/v1beta/models/'
           f'{MODEL}:generateContent?key={API_KEY}')
    body = {
        'systemInstruction': {'parts': [{'text': SYSTEM_INSTRUCTION}]},
        'contents': [{
            'role': 'user',
            'parts': [{'text': build_user_prompt(cuisine_key, label)}]
        }],
        # Google Search grounding - Gemini's equivalent of Haiku's web_search.
        # Surfaces results from Google's index (different from Bing-driven Haiku).
        'tools': [{'google_search': {}}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 2000,
        },
    }
    req = Request(url, data=json.dumps(body).encode('utf-8'),
                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except HTTPError as e:
        err = e.read().decode('utf-8')[:400]
        print(f"  HTTP {e.code}: {err}")
        return {'error': err, 'status_code': e.code}

def parse_response(msg, cuisine_key):
    """Extract candidates from Gemini's response shape:
    {candidates: [{content: {parts: [{text: '...'}]}, ...}], usageMetadata: {...}}
    """
    if msg.get('error'):
        return {'candidates': [], 'error': msg['error'], 'parse_error': True}
    cands = msg.get('candidates') or []
    if not cands:
        return {'candidates': [], 'error': 'no candidates in response', 'parse_error': True}
    parts = (cands[0].get('content') or {}).get('parts') or []
    text = ''.join(p.get('text', '') for p in parts).strip()
    # Strip markdown fences if Gemini adds them despite the instruction
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
        text = text.strip()
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        # Locate {"candidates": ...}
        start = text.find('{"candidates"')
        if start < 0: start = text.find('{')
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{': depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try: parsed = json.loads(text[start:i+1])
                        except: pass
                        break
    if not isinstance(parsed, dict) or 'candidates' not in parsed:
        parsed = {'candidates': [], '_parse_error': True, '_raw_text': text[:500]}
    usage = msg.get('usageMetadata', {})
    return {
        'candidates': parsed.get('candidates') or [],
        'in_tok': usage.get('promptTokenCount', 0),
        'out_tok': usage.get('candidatesTokenCount', 0),
        'parse_error': parsed.get('_parse_error', False),
        'raw_text_excerpt': parsed.get('_raw_text', ''),
        'researched_at': datetime.now(timezone.utc).isoformat(),
    }

def pick_targets(top_n=None, single=None):
    if single:
        if single not in CUISINE_LABEL:
            sys.exit(f"unknown cuisine key: {single}")
        return [(single, CUISINE_LABEL[single])]
    data = json.loads(CORRIDORS_PATH.read_text())
    cs = (data.get('newOpenings') or {}).get('cuisines') or []
    out = []
    for c in cs:
        if top_n and len(out) >= top_n: break
        key = c.get('key')
        if key and key in CUISINE_LABEL:
            out.append((key, CUISINE_LABEL[key]))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cuisine')
    ap.add_argument('--top', type=int, default=15)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    targets = pick_targets(top_n=args.top, single=args.cuisine)
    print(f"researching {len(targets)} cuisine(s) via Gemini {MODEL}: {[k for k,_ in targets]}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    total_in = total_out = 0

    for key, label in targets:
        if not args.force and key in cache:
            print(f"  [{key}] cached - skip (--force to re-research)")
            continue
        print(f"  [{key}] {label}... ", end='', flush=True)
        msg = gemini_call(key, label)
        result = parse_response(msg, key)
        cache[key] = result
        total_in += result.get('in_tok', 0)
        total_out += result.get('out_tok', 0)
        n = len(result.get('candidates') or [])
        flag = ' [PARSE_ERR]' if result.get('parse_error') else ''
        print(f"{n} candidate(s){flag}")
        CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        time.sleep(0.5)

    flat = []
    for key, result in cache.items():
        if key not in CUISINE_LABEL: continue
        for c in (result.get('candidates') or []):
            flat.append({
                'cuisine_key': key,
                'cuisine_label': CUISINE_LABEL[key],
                'source': 'gemini',
                **c,
            })

    def score(c):
        s = float(c.get('confidence') or 0)
        if c.get('accepts_submissions') == 'yes': s += 0.5
        if c.get('still_active') == 'yes': s += 0.3
        return -s
    flat.sort(key=score)
    OUT_PATH.write_text(json.dumps({
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'gemini',
        'model': MODEL,
        'total_candidates': len(flat),
        'candidates': flat,
    }, indent=2, ensure_ascii=False))

    print(f"\nsummary:")
    print(f"  candidates -> {OUT_PATH}")
    print(f"  total: {len(flat)}")
    print(f"  tokens: {total_in:,} in, {total_out:,} out")
    print(f"  next: python tools/merge_directory_candidates.py")

if __name__ == '__main__':
    main()
