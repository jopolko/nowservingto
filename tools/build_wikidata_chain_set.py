#!/usr/bin/env python3
"""
Build an authoritative restaurant-chain set from Wikidata.

Why Wikidata: every named restaurant chain on earth has a Wikidata entity
tagged `instance of: restaurant chain (Q1391085)` (or one of its subclasses
like fast-food chain, coffeehouse chain, etc.). Pulling these is free, fast,
and catches every brand OSM's Toronto-bbox query misses - including chains
that have only one or two Toronto locations but are well-known globally
(Pokeworks, Marugame Udon, Molly Tea, etc.).

Output: tools/cache/wikidata_chain_set.json, same shape as osm_chain_set.json
so the consumer code in inject_openings.py + the places-calling scripts can
merge the two sets with a simple dict-update.

Refresh cadence: weekly via cron. Wikidata SPARQL is rate-limited per IP but
this one query is well under the limit.
"""
import json, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / 'tools' / 'cache' / 'wikidata_chain_set.json'
SPARQL_URL = 'https://query.wikidata.org/sparql'

# All restaurant-chain-ish entity types we care about. Subclass-of chain
# walks the ontology so we pick up sub-categories without listing them all.
CHAIN_QIDS = [
    'Q1391085',    # restaurant chain
    'Q18389854',   # fast-food restaurant chain
    'Q12057132',   # chain store (used by some fast-food brands)
    'Q2360219',    # coffeehouse chain
]

SPARQL_LABELS = """
SELECT DISTINCT ?item ?itemLabel WHERE {
  VALUES ?chainType { """ + ' '.join(f'wd:{q}' for q in CHAIN_QIDS) + """ }
  ?item wdt:P31 ?chainType .
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# Aliases are pulled in a second focused query - joining altLabel in the
# main query blew through Wikidata's 60s timeout.
SPARQL_ALIASES = """
SELECT ?item ?alias WHERE {
  VALUES ?chainType { """ + ' '.join(f'wd:{q}' for q in CHAIN_QIDS) + """ }
  ?item wdt:P31/wdt:P279* ?chainType ;
        skos:altLabel ?alias .
  FILTER(LANG(?alias) = "en")
  FILTER NOT EXISTS { ?item wdt:P576 ?dissolved . }
}
"""

def _sparql(query, label):
    print(f"querying Wikidata SPARQL: {label}...")
    req = Request(
        SPARQL_URL,
        data=f"query={query}".encode('utf-8'),
        headers={
            'User-Agent': 'nowservingto-wikidata-chains/1.0 (https://nowservingto.com)',
            'Accept': 'application/sparql-results+json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    t0 = time.time()
    try:
        with urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except (HTTPError, URLError) as e:
        sys.exit(f"Wikidata SPARQL failed: {e}")
    rows = data.get('results', {}).get('bindings', [])
    print(f"  {len(rows)} rows in {time.time()-t0:.0f}s")
    return rows


def fetch_chains():
    rows = _sparql(SPARQL_LABELS, 'canonical labels')
    brands = {}
    qid_to_key = {}
    for row in rows:
        qid = row.get('item', {}).get('value', '').rsplit('/', 1)[-1]
        label = row.get('itemLabel', {}).get('value', '').strip()
        if not label or label.startswith('Q'):
            continue
        if len(label) < 5 and ' ' not in label:
            continue
        key = label.upper()
        brands.setdefault(key, {'display': label, 'qid': qid, 'aliases': set()})
        qid_to_key[qid] = key
    # Aliases - best-effort. If this second query times out we still have
    # the canonical labels which is the big win.
    try:
        alias_rows = _sparql(SPARQL_ALIASES, 'aliases')
    except SystemExit:
        print('  alias query failed - proceeding with canonical labels only')
        alias_rows = []
    for row in alias_rows:
        qid = row.get('item', {}).get('value', '').rsplit('/', 1)[-1]
        alias = row.get('alias', {}).get('value', '').strip()
        if not alias or qid not in qid_to_key: continue
        if len(alias) < 5 and ' ' not in alias: continue
        if alias.upper() == qid_to_key[qid]: continue
        brands[qid_to_key[qid]]['aliases'].add(alias)
    return brands

def main():
    brands = fetch_chains()
    out = {
        'brands': {
            k: {
                'display': v['display'],
                'qid': v['qid'],
                'aliases': sorted(v['aliases']),
            }
            for k, v in sorted(brands.items())
        },
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': 'Wikidata SPARQL - instance of restaurant chain (Q1391085) + subclasses',
        'note': 'Operating names matched UPPERCASE against keys + aliases; see chain_filter.py for match logic.',
    }
    CACHE_PATH.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {CACHE_PATH}")
    print(f"  {len(brands)} distinct chains globally\n")
    print("sample (alphabetical first 30):")
    for k in sorted(brands)[:30]:
        v = brands[k]
        ali = f" - aliases: {', '.join(list(v['aliases'])[:3])}" if v['aliases'] else ""
        print(f"  {v['display']:<40} [{v['qid']}]{ali}")
    # Spot-check the ones the user explicitly named
    print("\nspot-check (the chains we missed today):")
    for needle in ('POKEWORKS', 'MARUGAME', 'MOLLY TEA', 'MARUGAME UDON'):
        hits = [k for k in brands if needle in k]
        if hits:
            for h in hits[:2]:
                print(f"  ✓ {needle} → {brands[h]['display']} [{brands[h]['qid']}]")
        else:
            print(f"  ✗ {needle} not found in Wikidata chain set")

if __name__ == '__main__':
    main()
