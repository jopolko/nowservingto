#!/usr/bin/env python3
"""Merge Haiku + Gemini spider outputs into the canonical candidates JSON
that build_submission_cheatsheet.py consumes.

Dedup strategy:
  - Same domain (host part of url) + same cuisine = duplicate
  - When both spiders surface the same site, keep the one with higher
    confidence; if confidence ties, prefer the one with a non-empty
    submission_url
  - Tag each merged candidate with `sources: ['haiku', 'gemini']` or
    `['haiku']` etc. so you can see which tool found what (and re-run
    the weaker one less often)

Output: data/community_directory_candidates.json (the canonical file
the cheat-sheet generator already reads).
"""
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
HAIKU_PATH = ROOT / 'data' / 'community_directory_candidates.json'
GEMINI_PATH = ROOT / 'data' / 'community_directory_candidates_gemini.json'
OUT_PATH = ROOT / 'data' / 'community_directory_candidates.json'  # overwrite the canonical

def host(url):
    try: return (urlparse(url).hostname or '').lstrip('www.').lower()
    except: return ''

def main():
    inputs = []
    if HAIKU_PATH.exists():
        d = json.loads(HAIKU_PATH.read_text())
        for c in d.get('candidates') or []:
            c.setdefault('source', 'haiku')
            inputs.append(c)
    if GEMINI_PATH.exists():
        d = json.loads(GEMINI_PATH.read_text())
        for c in d.get('candidates') or []:
            c.setdefault('source', 'gemini')
            inputs.append(c)

    if not inputs:
        print('no candidates from either spider - run one of them first')
        return

    # Dedupe by (cuisine_key, host). Merge sources on conflict.
    buckets = defaultdict(list)
    for c in inputs:
        h = host(c.get('url') or '')
        if not h: continue
        buckets[(c['cuisine_key'], h)].append(c)

    merged = []
    for (cuisine, h), cands in buckets.items():
        # Pick winner: highest confidence, prefer non-empty submission_url
        cands.sort(key=lambda x: (
            -(float(x.get('confidence') or 0)),
            0 if x.get('submission_url') else 1,
        ))
        winner = cands[0].copy()
        sources = sorted(set(c.get('source', 'unknown') for c in cands))
        winner['sources'] = sources
        winner.pop('source', None)
        # If multiple sources agreed, bump confidence a hair (0.05 cap) -
        # cross-tool agreement is a quality signal.
        if len(sources) > 1:
            winner['confidence'] = min(1.0, float(winner.get('confidence') or 0) + 0.05)
            winner['rationale'] = (winner.get('rationale', '') +
                                   f" [agreed by {' + '.join(sources)}]").strip()
        merged.append(winner)

    # Final sort: confidence x accepts x active
    def score(c):
        s = float(c.get('confidence') or 0)
        if c.get('accepts_submissions') == 'yes': s += 0.5
        if c.get('still_active') == 'yes': s += 0.3
        return -s
    merged.sort(key=score)

    OUT_PATH.write_text(json.dumps({
        'generated_at': max(p for p in [
            (json.loads(HAIKU_PATH.read_text()).get('generated_at', '') if HAIKU_PATH.exists() else ''),
            (json.loads(GEMINI_PATH.read_text()).get('generated_at', '') if GEMINI_PATH.exists() else ''),
        ] if p),
        'merged_from': ['haiku', 'gemini'],
        'total_candidates': len(merged),
        'candidates': merged,
    }, indent=2, ensure_ascii=False))

    by_source = defaultdict(int)
    for c in merged:
        for s in c.get('sources') or []:
            by_source[s] += 1
    agreed = sum(1 for c in merged if len(c.get('sources') or []) > 1)
    print(f"merged -> {OUT_PATH}")
    print(f"  {len(merged)} unique candidates")
    print(f"  haiku contributed: {by_source['haiku']}")
    print(f"  gemini contributed: {by_source['gemini']}")
    print(f"  agreed by both: {agreed}")
    print(f"  next: python tools/build_submission_cheatsheet.py")

if __name__ == '__main__':
    main()
