#!/usr/bin/env python3
"""Find cultural-community directories in Toronto/Canada that accept
business submissions, scoped per cuisine.

Pipeline:
  1. Pick top-N cuisines from data/corridors.json (by count365d)
  2. Per cuisine, prompt Haiku with the web_search tool to research the
     diaspora's directory ecosystem (Tamil-Canadian directory sites,
     Filipino-Canadian newspapers with business sections, etc.)
  3. Haiku searches the web + classifies + returns ranked JSON
  4. Write candidates to data/community_directory_candidates.json for
     manual triage (we don't auto-submit; reputation-sensitive)

Why Haiku web_search vs a raw search API + classifier:
  - Zero extra API keys (reuses ANTHROPIC_API_KEY)
  - Search + classification in one call (cheaper, less coordination)
  - Bing standalone Search API was deprecated ~Aug 2025, no clean
    drop-in successor

Cost: ~$0.05-0.10 per cuisine = $0.75-1.50 for top 15. Cached, so
re-runs are free until you pass --force.

Usage:
  python tools/find_community_directories.py            # top 15
  python tools/find_community_directories.py --top 5    # top 5 only
  python tools/find_community_directories.py --cuisine tamil
  python tools/find_community_directories.py --force    # ignore cache
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
OUT_PATH = ROOT / 'data' / 'community_directory_candidates.json'
CACHE_PATH = ROOT / 'tools' / 'cache' / 'community_directory_cache.json'
SECRETS = Path('/var/secrets/nowservingto.env')
MODEL = 'claude-haiku-4-5-20251001'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cuisines import CUISINE_LABEL

def load_api_key():
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if line.startswith('ANTHROPIC_API_KEY='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    sys.exit('ANTHROPIC_API_KEY not in secrets')

API_KEY = load_api_key()
HEADERS = {
    'x-api-key': API_KEY,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}

SYSTEM_PROMPT = """You research cultural-community business directories in
Toronto and Canada that accept new business submissions. The user runs a
free aggregator listing newly-registered Toronto restaurants by cuisine
(NowServingTO) and wants to submit cuisine-specific landing pages to
diaspora-focused directories so the right community discovers the resource.

For each cuisine you research, return a JSON object on ONE line. Schema:

{
  "candidates": [
    {
      "url": "https://example.ca/",
      "name": "Example Tamil Directory",
      "submission_url": "https://example.ca/add-business",
      "audience": "Tamil-Canadian diaspora, GTA-focused",
      "accepts_submissions": "yes|no|unclear",
      "still_active": "yes|no|unclear",
      "confidence": 0.0-1.0,
      "rationale": "one sentence explaining the score"
    },
    ...
  ]
}

WHAT COUNTS as a good candidate:
  - Cultural-community directory (Tamil Directory, Filipino Channel,
    Persian Toronto, etc.) — narrow audience, NOT generic Yellow Pages
  - Diaspora-language newspaper or community paper with a business
    listings section (Corriere Canadese, Pinoy Times, etc.)
  - Ethnic community association website with a member-business directory
  - Faith-community business directories (kosher restaurants, halal
    directories, gurdwara langar list, etc.) when relevant to the cuisine

WHAT TO EXCLUDE:
  - Generic Canadian directories (Yelp, Yellow Pages, Google Maps, blogTO)
  - Sites with no submission mechanism (read-only article-style listings)
  - Dead / abandoned sites (no updates visible in past ~12 months)
  - Sites that only list restaurants in *one* city outside Toronto
  - Blogspot/WordPress.com hobby blogs without a real submission form
  - Anything paywalled or with a per-listing fee >$100 (we're free, not
    paying to be listed)

For each candidate, search to verify the submission URL actually loads
and looks live. Confidence should reflect both relevance to the cuisine's
diaspora AND likelihood the submission gets approved.

If you find ZERO good candidates for a cuisine, return {"candidates": []}
rather than padding the list with low-quality results."""

def http(method, url, data=None):
    body = json.dumps(data).encode('utf-8') if data else None
    req = Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        raise

def build_message(cuisine_key, label):
    # User-message phrasing matters: be specific about the audience and
    # the type of resource we'd want to be on. Avoid prescribing search
    # terms (let Haiku pick) but anchor the geographic scope.
    return (
        f"Find directories where I could submit my Toronto restaurant "
        f"aggregator page (https://nowservingto.com/cuisine/{cuisine_key}) "
        f"so the {label}-Canadian community in Toronto and the GTA "
        f"discovers it. Prefer narrow cultural-community directories and "
        f"diaspora-press business sections. Return ONLY the JSON object."
    )

def parse_response(msg):
    """Extract candidates + usage from the API response."""
    usage = msg.get('usage', {})
    server_tool = usage.get('server_tool_use') or {}
    blocks = msg.get('content', [])
    text_blocks = [b.get('text', '') for b in blocks if b.get('type') == 'text']
    text = (text_blocks[-1] if text_blocks else '').strip()
    # Find the JSON object in the text - Haiku sometimes wraps it in prose.
    parsed = None
    # Try whole text first
    try:
        parsed = json.loads(text)
    except Exception:
        # Try to locate {"candidates": ...}
        start = text.find('{"candidates"')
        if start < 0:
            start = text.find('{')
        if start >= 0:
            # Find matching closing brace
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
    return {
        'candidates': parsed.get('candidates') or [],
        'in_tok': usage.get('input_tokens', 0),
        'out_tok': usage.get('output_tokens', 0),
        'searches': server_tool.get('web_search_requests', 0),
        'parse_error': parsed.get('_parse_error', False),
        'raw_text_excerpt': parsed.get('_raw_text', ''),
        'researched_at': datetime.now(timezone.utc).isoformat(),
    }

def research_cuisine(cuisine_key, label, max_searches=5):
    """Single Haiku call with web_search tool. ~$0.05-0.10 per cuisine."""
    req_body = {
        'model': MODEL,
        'max_tokens': 2000,
        'system': SYSTEM_PROMPT,
        'tools': [{
            'type': 'web_search_20250305',
            'name': 'web_search',
            'max_uses': max_searches,
        }],
        'messages': [{
            'role': 'user',
            'content': build_message(cuisine_key, label),
        }],
    }
    msg = http('POST', 'https://api.anthropic.com/v1/messages', req_body)
    return parse_response(msg)

def pick_targets(top_n=None, single=None):
    """Pick which cuisines to research from corridors.json."""
    if single:
        if single not in CUISINE_LABEL:
            sys.exit(f"unknown cuisine key: {single}")
        return [(single, CUISINE_LABEL[single])]
    data = json.loads(CORRIDORS_PATH.read_text())
    cs = (data.get('newOpenings') or {}).get('cuisines') or []
    # cuisines are pre-sorted by count365d descending in inject_openings
    out = []
    for c in cs:
        if top_n and len(out) >= top_n: break
        key = c.get('key')
        if key and key in CUISINE_LABEL:
            out.append((key, CUISINE_LABEL[key]))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cuisine', help='research a single cuisine key (e.g. tamil)')
    ap.add_argument('--top', type=int, default=15, help='research top-N cuisines (default 15)')
    ap.add_argument('--force', action='store_true', help='ignore cache, re-research everything')
    ap.add_argument('--max-searches', type=int, default=5,
                    help='max web_search calls Haiku may make per cuisine (default 5)')
    args = ap.parse_args()

    targets = pick_targets(top_n=args.top, single=args.cuisine)
    print(f"researching {len(targets)} cuisine(s): {[k for k,_ in targets]}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    total_in = total_out = total_searches = 0

    for key, label in targets:
        if not args.force and key in cache:
            print(f"  [{key}] cached - skip (use --force to re-research)")
            continue
        print(f"  [{key}] {label}... ", end='', flush=True)
        try:
            result = research_cuisine(key, label, max_searches=args.max_searches)
        except Exception as e:
            print(f"FAILED: {e}")
            continue
        cache[key] = result
        total_in += result['in_tok']
        total_out += result['out_tok']
        total_searches += result['searches']
        n = len(result['candidates'])
        flag = ' [PARSE_ERR]' if result['parse_error'] else ''
        print(f"{n} candidate(s), {result['searches']} searches{flag}")
        CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
        time.sleep(0.5)  # gentle on the API

    # Flatten into one ranked list for human triage
    flat = []
    for key, result in cache.items():
        if key not in CUISINE_LABEL: continue
        for c in (result.get('candidates') or []):
            flat.append({
                'cuisine_key': key,
                'cuisine_label': CUISINE_LABEL[key],
                **c,
            })
    # Sort: high confidence + accepts_submissions=yes + still_active=yes first
    def score(c):
        s = float(c.get('confidence') or 0)
        if c.get('accepts_submissions') == 'yes': s += 0.5
        if c.get('still_active') == 'yes': s += 0.3
        return -s
    flat.sort(key=score)
    OUT_PATH.write_text(json.dumps({
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_candidates': len(flat),
        'candidates': flat,
    }, indent=2, ensure_ascii=False))

    # Cost summary - Haiku 4.5: $1/MTok in, $5/MTok out, web_search $10/1000
    cost_tok = (total_in / 1_000_000) + (total_out / 1_000_000 * 5)
    cost_search = total_searches * 0.01
    print(f"\nsummary:")
    print(f"  candidates written -> {OUT_PATH}")
    print(f"  total candidates: {len(flat)}")
    print(f"  tokens: {total_in:,} in, {total_out:,} out")
    print(f"  web_search calls: {total_searches}")
    print(f"  estimated spend: ${cost_tok + cost_search:.3f}")

if __name__ == '__main__':
    main()
