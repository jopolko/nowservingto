"""
One-off: query Wikidata for the canonical QID of each cuisine in
cuisines.py CUISINE_LABEL. Result cached at tools/data/cuisine_wikidata.json
and read by inject_openings.py to emit `sameAs` triples in cuisine-page
JSON-LD. Re-run only when CUISINE_LABEL gains a new key.
"""
import json, sys, time, re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from cuisines import CUISINE_LABEL  # noqa

OUT_PATH = ROOT / 'tools' / 'data' / 'cuisine_wikidata.json'
SPARQL_URL = 'https://query.wikidata.org/sparql'

# Q1778821 = cuisine (subclass of food culture). Pulling everything that is
# instance-of or subclass-of "cuisine" with an English label, then matching
# against our taxonomy.
SPARQL = """
SELECT ?item ?itemLabel WHERE {
  ?item wdt:P31/wdt:P279* wd:Q1778821 .
  ?item rdfs:label ?itemLabel .
  FILTER(LANG(?itemLabel) = "en")
}
"""

def _slugify(s):
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

def main():
    print("Querying Wikidata for cuisine QIDs...")
    req = Request(
        SPARQL_URL,
        data=f"query={SPARQL}".encode('utf-8'),
        headers={
            'User-Agent': 'nowservingto-wikidata-cuisines/1.0 (https://nowservingto.com)',
            'Accept': 'application/sparql-results+json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    t0 = time.time()
    with urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    rows = data.get('results', {}).get('bindings', [])
    print(f"  {len(rows)} cuisine entities in {time.time()-t0:.0f}s")

    # Build slug -> set of (label, qid). We'll pick the shortest English
    # label that matches "<X> cuisine" pattern, since the disambiguation
    # entities (e.g. "Italian-American cuisine") would otherwise clobber.
    by_slug = {}
    for row in rows:
        qid = row['item']['value'].rsplit('/', 1)[-1]
        label = row['itemLabel']['value'].strip()
        if not label or label.startswith('Q'): continue
        # Normalize: strip "cuisine" / "food" suffixes for matching
        norm = re.sub(r'\s+(cuisine|food|kitchen)$', '', label, flags=re.I).strip()
        by_slug.setdefault(_slugify(norm), []).append((label, qid))

    # Map our keys to WD QIDs. Try exact slug match first, then a manual
    # aliases table for cases where our internal key diverges from
    # Wikipedia's preferred form.
    aliases = {
        'persian': ['iranian', 'persian'],
        'jewish_deli': ['jewish', 'ashkenazi_jewish'],
        'irish_uk': ['british', 'irish'],
        'eastern_eu': ['eastern_european'],
        'african_horn': ['ethiopian', 'horn_of_africa'],
        'african_west': ['west_african'],
        'middle_east': ['middle_eastern', 'arab', 'levantine'],
        'latin': ['latin_american'],
        'south_asian': ['south_asian', 'indian'],
        'caribbean': ['caribbean'],
        'jamaican': ['jamaican'],
        'trinidadian': ['trinidad_and_tobago', 'trinidadian'],
        'argentinian': ['argentine', 'argentinian'],
        'nepalese': ['nepalese', 'nepali'],
    }
    result = {}
    for key, label in CUISINE_LABEL.items():
        # Candidate slugs to try, in order of preference
        cands = [key] + aliases.get(key, [])
        # Also try the display label slugified
        cands.append(_slugify(re.sub(r'\s+\(.*?\)$', '', label)))
        hit = None
        for c in cands:
            if c in by_slug:
                # Pick the shortest label, biased to ones ending in "cuisine"
                matches = sorted(by_slug[c], key=lambda x: (
                    0 if x[0].lower().endswith('cuisine') else 1,
                    len(x[0]),
                ))
                hit = matches[0]
                break
        if hit:
            result[key] = {'label': hit[0], 'qid': hit[1],
                           'wikidata_url': f'https://www.wikidata.org/wiki/{hit[1]}'}
        else:
            print(f"  no Wikidata match for: {key} ({label})")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    print(f"Wrote {len(result)}/{len(CUISINE_LABEL)} mappings to {OUT_PATH}")

if __name__ == '__main__':
    main()
