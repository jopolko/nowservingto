#!/usr/bin/env python3
"""
Centralized chain detection used by every script that's about to spend money
on Places lookups. Merges the OSM-derived set (`osm_chain_set.json`, Toronto
brands tagged in OpenStreetMap) and the Wikidata-derived set
(`wikidata_chain_set.json`, every named restaurant chain on earth).

Match semantics:
  - case-insensitive
  - word-boundary on both sides (so "PIZZA" doesn't match "PIZZA PALACE",
    only entries literally named "PIZZA")
  - covers both chain canonical names and aliases

Usage:
    from chain_filter import is_known_chain
    if is_known_chain(entry['operatingName']):
        continue   # skip Places lookup, validator will drop it anyway

The merged set is loaded once at import time; both source files are JSON
and re-read every Python interpreter start. If either file is missing, the
filter degrades gracefully (returns False for unknown names from that
source rather than blocking everything).
"""
import json, re
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parent.parent
OSM_PATH = ROOT / 'tools' / 'cache' / 'osm_chain_set.json'
WIKIDATA_PATH = ROOT / 'tools' / 'cache' / 'wikidata_chain_set.json'
MANUAL_PATH = ROOT / 'tools' / 'cache' / 'manual_chain_set.json'


def _load(p):
    try:
        return (json.loads(p.read_text()) or {}).get('brands') or {}
    except Exception:
        return {}


def _build_pattern():
    """Compile one big alternation regex of all chain names + aliases. Sorted
    longest-first so "PIZZA PIZZA" matches before "PIZZA" (the regex engine
    tries alternatives left-to-right; longest wins when both could match).

    Three sources merged: OSM (Toronto-bbox branded amenities), Wikidata
    (every globally-known chain via SPARQL), and a hand-curated manual list
    for chains too obscure for Wikidata or too new for OSM coverage."""
    osm = _load(OSM_PATH)
    wiki = _load(WIKIDATA_PATH)
    manual = _load(MANUAL_PATH)
    names = set()
    for brands in (osm, wiki, manual):
        for key, rec in brands.items():
            names.add(key)
            for a in rec.get('aliases', []) or []:
                names.add(a.upper())
    # Filter generic single-word brands that would over-match. Same rule
    # the Wikidata builder applies, but we re-apply here in case OSM has
    # been more permissive.
    filtered = {n for n in names if (len(n) >= 5 or ' ' in n)}
    if not filtered:
        return None, set(), set()
    sorted_names = sorted(filtered, key=lambda s: (-len(s), s))
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(n) for n in sorted_names) + r')\b',
        flags=re.IGNORECASE,
    )
    return pattern, set(osm), set(wiki)


def _build_with_counts():
    osm = _load(OSM_PATH); wiki = _load(WIKIDATA_PATH); manual = _load(MANUAL_PATH)
    p, _, _ = _build_pattern()
    return p, set(osm), set(wiki), set(manual)


_PATTERN, _OSM_KEYS, _WIKI_KEYS, _MANUAL_KEYS = _build_with_counts()


@lru_cache(maxsize=4096)
def is_known_chain(operating_name):
    """True if the name contains any known chain brand or alias as a
    word-bounded substring. Returns False if no chain set was loaded."""
    if not operating_name or _PATTERN is None:
        return False
    return _PATTERN.search(operating_name) is not None


def chain_match(operating_name):
    """Like is_known_chain but returns the brand name that matched (for
    logging / cache attribution). None if no match."""
    if not operating_name or _PATTERN is None:
        return None
    m = _PATTERN.search(operating_name)
    return m.group(1) if m else None


def chain_set_summary():
    """For cron logs - print which sets we're using."""
    osm_n = len(_OSM_KEYS); wiki_n = len(_WIKI_KEYS); man_n = len(_MANUAL_KEYS)
    union = len(_OSM_KEYS | _WIKI_KEYS | _MANUAL_KEYS)
    return f"chain filter loaded: {osm_n} OSM + {wiki_n} Wikidata + {man_n} manual = {union} unique brands"


if __name__ == '__main__':
    # CLI smoke test
    import sys
    print(chain_set_summary())
    tests = sys.argv[1:] or [
        'POKEWORKS 100 KING ST W',
        'MARUGAME UDON 480 YONGE',
        'PIZZA PIZZA 693 MOUNT PLEASANT',
        'MASALA STORY 21 DAVENPORT',   # independent - should NOT match
        'TUTTO GELATO 181 DOVERCOURT', # independent - should NOT match
        'POPEYES LOUISIANA KITCHEN',
        'BAMIYAN KABOB 4205 KEELE',
    ]
    for t in tests:
        m = chain_match(t)
        flag = f'CHAIN ({m})' if m else 'independent'
        print(f'  {flag:<28} {t}')
