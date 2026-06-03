#!/usr/bin/env python3
"""
One-off: read existing data/corridors.json, compute citywide cuisine-tagged
NEW OPENINGS (Issued in last 365 days, no Cancel Date) from /tmp/bl1.csv, and
inject under key 'newOpenings'. Mirrors logic that will live in build_corridors.py.
"""
import csv, json
from datetime import datetime, date, timedelta
from collections import defaultdict
from pathlib import Path

REFERENCE_DATE = date.today()  # use real today; build_corridors.py uses its own TODAY constant
import os
# Derive repo root from this script's location so the same code works on dev (WSL) and prod (VPS).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = '/tmp/business_licences_alt.csv'  # shared with build_corridors.py
LLM_CACHE_PATH = f'{ROOT}/tools/cache/llm_cuisine_cache.json'
PLACES_CACHE_PATH = f'{ROOT}/tools/cache/places_cache.json'
WEB_VERIFY_CACHE_PATH = f'{ROOT}/tools/cache/web_verify_cache.json'
MENU_HIGHLIGHTS_CACHE_PATH = f'{ROOT}/tools/cache/menu_highlights_cache.json'
EVIDENCE_REWRITE_CACHE_PATH = f'{ROOT}/tools/cache/evidence_rewrite_cache.json'
FEATURED_IN_CACHE_PATH = f'{ROOT}/tools/cache/featured_in_cache.json'
GEOCODE_CACHE_PATH = f'{ROOT}/tools/cache/geocode_cache.json'
OWNER_CONTRIBUTIONS_PATH = f'{ROOT}/tools/cache/owner_contributions.json'
DATA_PATH = f'{ROOT}/data/corridors.json'

# Load LLM cache for cuisine override
try:
    LLM_CACHE = json.load(open(LLM_CACHE_PATH))
except FileNotFoundError:
    LLM_CACHE = {}
try:
    PLACES_CACHE = json.load(open(PLACES_CACHE_PATH))
except FileNotFoundError:
    PLACES_CACHE = {}
try:
    WEB_VERIFY_CACHE = json.load(open(WEB_VERIFY_CACHE_PATH))
except FileNotFoundError:
    WEB_VERIFY_CACHE = {}
try:
    MENU_HIGHLIGHTS_CACHE = json.load(open(MENU_HIGHLIGHTS_CACHE_PATH))
except FileNotFoundError:
    MENU_HIGHLIGHTS_CACHE = {}
try:
    EVIDENCE_REWRITE_CACHE = json.load(open(EVIDENCE_REWRITE_CACHE_PATH))
except FileNotFoundError:
    EVIDENCE_REWRITE_CACHE = {}
# Owner contributions: hand-curated overrides keyed by slug. When a
# restaurant owner replies to the per-listing CTA with content, their
# input lands here. Schema (minimal): {slug: {from_owner_text, photo?,
# opened_date?, specialty_dishes?, owner_name?, contributed_at}}.
# Empty by default; populated manually as replies come in.
try:
    OWNER_CONTRIBUTIONS = json.load(open(OWNER_CONTRIBUTIONS_PATH))
    OWNER_CONTRIBUTIONS.pop('_doc', None)
except FileNotFoundError:
    OWNER_CONTRIBUTIONS = {}
try:
    FEATURED_IN_CACHE = json.load(open(FEATURED_IN_CACHE_PATH))
    FEATURED_IN_CACHE.pop('_doc', None)
except FileNotFoundError:
    FEATURED_IN_CACHE = {}
try:
    GEOCODE_CACHE = json.load(open(GEOCODE_CACHE_PATH))
except FileNotFoundError:
    GEOCODE_CACHE = {}
try:
    URL_HEALTH_CACHE = json.load(open(f'{ROOT}/tools/cache/url_health_cache.json'))
except FileNotFoundError:
    URL_HEALTH_CACHE = {}

# OSM-derived chain brand set, built daily by tools/build_osm_chain_set.py
# from OpenStreetMap. Keys are UPPER-CASED brand names ("241 PIZZA", "A&W")
# with osmCount = how many OSM nodes carry that brand tag. Any Toronto
# licence whose operating name matches one of these names is by definition
# a multi-location chain and disqualified from the directory regardless of
# what the per-entry validator decides - the validator can miss chains
# when an entry's specific website/Places data is incomplete, but OSM
# crowd-tagging across many cities never has that gap. Free pre-filter
# that's also cheaper than a Haiku batch call (the dropped entries skip
# all downstream verify/validate work).
try:
    OSM_CHAIN_SET = json.load(open(f'{ROOT}/tools/cache/osm_chain_set.json')).get('brands', {})
except FileNotFoundError:
    OSM_CHAIN_SET = {}

def is_osm_chain(op_raw):
    """True if the operating name matches an OSM-tagged chain brand. Match
    is case-insensitive on the exact name OR a normalized variant (strip
    trailing 'INC'/'LTD' suffixes and trailing licence-numbering like '#3')."""
    if not op_raw or not OSM_CHAIN_SET: return False
    name = op_raw.strip().upper()
    if name in OSM_CHAIN_SET: return True
    import re as _re_chain
    cleaned = _re_chain.sub(r'\s+(INC|LTD|LLC|CORP|CO|LIMITED)\.?$', '', name).strip()
    cleaned = _re_chain.sub(r'\s*#\s*\d+$', '', cleaned).strip()
    return cleaned in OSM_CHAIN_SET

def _validator_best_website(w):
    """Return the website the unified validator approved, or None.

    When `validator_judgment.best_website` is present we honor that verdict
    even when it's explicitly None (validator rejected the website as
    aggregator-redirect / parked / wrong-business). Only fall back to the
    raw `w.website` (the first URL Haiku web_search surfaced) when there's
    no validator verdict yet - early entries where validate_entries_batch
    hasn't run."""
    if not w: return None
    vj = w.get('validator_judgment')
    if isinstance(vj, dict) and 'best_website' in vj:
        return vj.get('best_website')  # str OR explicit None (rejected)
    return w.get('website')             # no verdict yet


def url_is_alive(url):
    """True if URL not in health cache, or last check said ok. False if known-broken.
    Looks up under both the raw URL and a normalized form (lowercased,
    www. stripped, tracking params dropped) so the entry's stored
    website variant and the cache's canonical variant collide correctly."""
    if not url: return False
    h = URL_HEALTH_CACHE.get(url)
    if h is None:
        # Try the normalized form - cache keys may have been canonicalized
        # by check_link_health.py's migration.
        try:
            from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
            s = urlsplit(url.strip())
            netloc = s.netloc.lower()
            if netloc.startswith('www.'): netloc = netloc[4:]
            keep = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
                    if not (k.lower().startswith('utm_') or k.lower() in {'fbclid', 'gclid'})]
            norm = urlunsplit(((s.scheme or 'https').lower(), netloc, s.path or '/',
                               urlencode(sorted(keep)) if keep else '', s.fragment))
            h = URL_HEALTH_CACHE.get(norm)
        except Exception:
            pass
    if not h: return True   # never checked → optimistic
    return bool(h.get('ok'))
WINDOW_365 = REFERENCE_DATE - timedelta(days=365)
WINDOW_30  = REFERENCE_DATE - timedelta(days=30)

# (CUISINE_PATTERNS regex-keyword dictionary removed 2026-05-14 - it was a
# pre-LLM fallback that pattern-matched operating names to cuisines. Now that
# every entry passes through name-only Haiku in llm_classify_batch.py, the
# regex layer is duplicative AND coarser - Haiku reads "Jollof King" + Places
# context and decides; the regex would have committed to african_west on
# substring "JOLLOF" alone with no nuance. Let Haiku do the work.)

# Canonical cuisine taxonomy - defined in tools/cuisines.py so recovery scripts
# share the same set. Adding a bucket there is enough; do NOT re-declare here.
from cuisines import CUISINE_LABEL, normalize_cuisines, cuisine_color
from places_key import cache_key

# Per-cuisine hand-written intro + 3 related cuisines for SEO differentiation
# of /cuisine/* landing pages. Editable in tools/data/cuisine_intros.json -
# next cron run picks up changes. Falls back to empty (markers collapse) when
# the file is missing or a cuisine isn't covered.
_CUISINE_INTROS_PATH = Path(__file__).resolve().parent / 'data' / 'cuisine_intros.json'
try:
    _CUISINE_INTROS = json.loads(_CUISINE_INTROS_PATH.read_text())
    _CUISINE_INTROS.pop('_doc', None)
except FileNotFoundError:
    _CUISINE_INTROS = {}
FOOD_CATS = {
    'EATING OR DRINKING ESTABLISHMENT',
    'TAKE-OUT OR RETAIL FOOD ESTABLISHMENT',
    'EATING ESTABLISHMENT',
    'RETAIL STORE (FOOD)',
}

def parse_d(s):
    if not s: return None
    s = s.strip()
    for fmt in ('%Y-%m-%d','%Y/%m/%d','%m/%d/%Y','%Y-%m-%dT%H:%M:%S'):
        try: return datetime.strptime(s.split(' ')[0], fmt).date()
        except ValueError: pass
    return None

# Map Toronto FSA (first 2 chars of postal) → former municipality / district.
# Toronto's pre-1998 boroughs get treated as natural orientation anchors. Roughly:
#   M1 = Scarborough, M2/M3 = North York, M4 = East York / midtown east,
#   M5 = Downtown, M6 = West Toronto / York, M8/M9 = Etobicoke
DISTRICT_BY_FSA = {
    'M1': 'Scarborough', 'M2': 'North York', 'M3': 'North York',
    'M4': 'East Toronto', 'M5': 'Downtown',  'M6': 'West Toronto',
    'M7': 'Downtown',    'M8': 'Etobicoke',  'M9': 'Etobicoke',
}
def district_from_postal(addr_with_postal):
    """Pull the first 2 chars of a Toronto postal code from any address string."""
    import re
    m = re.search(r'\bM[0-9][A-Z]\b', (addr_with_postal or '').upper())
    if not m: return None
    return DISTRICT_BY_FSA.get(m.group(0)[:2])

# Chain denylist: substring match against UPPERCASE operating name. If any of these appears,
# force cuisine to None regardless of what the LLM said. Cheap, deterministic safety net.
# Add new chains to this list as you spot them.
# REMOVED 2026-05-14: hardcoded chain rules. The unified validator (Haiku
# with full City row + Places + reviews + editorial) decides is_restaurant=no
# for chain franchisees by reading Client Name, Operating Name, Places types,
# and reviews together. No regex denylist. No OSM brand cross-reference. See
# tools/validate_entries_batch.py SYSTEM_PROMPT.


# Institutional / chain-parent detection by Client Name licence count.
# A Client Name holding ≥10 distinct food licence addresses across the City of
# Toronto is, in practice, always one of: (a) a national/regional chain parent
# corporation, (b) a multi-location franchisee LLC, (c) an institutional food
# service contractor (Aramark, Compass Group, Sodexo, TMU, hospital systems),
# or (d) a grocery/retail-food chain (Loblaws, Metro, Bulk Barn, Walmart).
# None of these belong in a "newest INDEPENDENT cultural-cuisine restaurants"
# directory. This complements is_chain() (which keys off the consumer brand
# name) by catching B2B operators whose Operating Name isn't a known consumer
# brand at all - Aramark cafeterias inside hospitals, TMU food courts, etc.
# REMOVED 2026-05-14: hardcoded ≥10-licence Client Name threshold. The
# validator now sees Client Name directly and judges institutional/chain
# from corporation identity + Places types + reviews. No magic threshold.

import re as _re
# Used to be: VALID_LLM_KEYS = set(CUISINE_LABEL.keys()) - a stale snapshot
# taken at import time, BEFORE the main loop calls normalize_cuisines() and
# triggers register_cuisine() on novel cuisines. Result: a brand-new cuisine
# (Uyghur, Palestinian, Kurdish, etc.) coming back from the validator got
# registered to cuisines_dynamic.json but immediately filtered out here
# because the snapshot didn't know about it yet. The entry then fell through
# to the name-only llm_cuisine_cache (which is constrained to the seed list)
# and rendered as Chinese instead of Uyghur. Killed the filter entirely:
# normalize_cuisines already returns canonical keys via register_cuisine, so
# anything it returns IS a valid key (just-registered or pre-existing).

# Brand-level website inheritance: when a multi-location operator (LENA'S ROTI,
# OSMOW'S, etc.) opens a NEW location, the brand-new licence has no Places match
# yet and no own-website verification - but an EARLIER licence at a different
# address may have the brand site cached. Walk web_verify_cache once at startup;
# for each operating name, find the most-common verified non-aggregator website
# across all its rows. Inject can then inherit that website onto rows that
# otherwise have nothing. Stops "links to nowhere on Maps" for brand-new
# locations of established small-chain indies.
# REMOVED 2026-05-14: brand-website inheritance dict. The validator
# returns best_website per entry from full evidence; we honor that directly.

CUISINE_LABEL.setdefault('thai', 'Thai')

PALETTE_HEX = {
    'italian':'#c83624','caribbean':'#1a8a5a','south_asian':'#d4a017','indian':'#e88e2c',
    'pakistani':'#a06030','afghan':'#7a5d3a','bangladeshi':'#b88820','chinese':'#b13e6a',
    'vietnamese':'#4a8b8b','japanese':'#2f3aa3','korean':'#6b2456','filipino':'#e08226',
    'tamil':'#8a5d20','tibetan':'#b15a25','greek':'#1f7a6a','portuguese':'#9b2538',
    'polish':'#4a5a6a','french':'#5a3a7a','irish_uk':'#2a6a40','german':'#6a5a30',
    'jewish_deli':'#4a4a8a','eastern_eu':'#7a4a4a','ukrainian':'#6a5a8a','russian':'#7a4a4a',
    'hungarian':'#8a5050','middle_east':'#b87a25','lebanese':'#c89538','turkish':'#a8662a',
    'syrian':'#9b5520','persian':'#8a4a25','latin':'#cc4a4a','mexican':'#d63d2a',
    'salvadoran':'#c8553a','peruvian':'#b35b50','colombian':'#cc6248','brazilian':'#3d8a47',
    'african_horn':'#a0522d','ethiopian':'#a0522d','eritrean':'#8a4528','somali':'#b06530',
    'african_west':'#5a8a3a','nigerian':'#4a7a30','ghanaian':'#6a8a40','moroccan':'#b87a2a',
    'jamaican':'#1f7a4a','trinidadian':'#2a9560','guyanese':'#3a8060','haitian':'#1a6855',
    'thai':'#7a8a3a','indonesian':'#7a6a40','malaysian':'#5a7a55','burmese':'#8a7050',
}

def get_cuisine(name, address):
    """Returns (cuisines_list, source). cuisines_list is a list of valid cuisine
    keys (1-3 entries for multi-cuisine restaurants); empty list means drop.

    Priority order:
      1. web_verify cache (search-informed by Haiku + web_search, then refined
         by the unified validator that sees the full City row + Places data)
      2. name-only LLM cache (Haiku on operating name alone)
    No chain-denylist short-circuit here - the validator marks chains and
    institutional operators with `validator_drop` directly; inject just honors
    that flag in the main loop.
    """
    key = cache_key(name, address)

    # 1. Web-verified cuisines - richest signal (web search + page content + Places extras).
    w = WEB_VERIFY_CACHE.get(key)
    if w and w.get('status') == 'ok' and w.get('operating') == 'yes':
        cs = normalize_cuisines(w)   # auto-registers novel cuisines via register_cuisine()
        if cs:
            return cs, 'web_search'
        # Verifier returned unknown OR null cuisine - fall through to name-only.

    # 2. Name-only LLM cache - fallback when web_verify is null/unknown.
    # This IS Haiku (just operating on name alone). The unified validator gives
    # Haiku the full Places + verify context when it runs, so high-quality entries
    # should rarely fall through to this layer alone - but the layer remains for
    # entries Places couldn't match and web_verify never visited.
    llm = LLM_CACHE.get(key)
    if llm and llm.get('status') == 'ok':
        # Explicit "unknown" verdict from name-only stays a drop (we have ZERO signal)
        if llm.get('cuisine') == 'unknown' and not llm.get('cuisines'): return [], None
        cs = normalize_cuisines(llm)
        if cs:
            return cs, 'llm'

    # NOTE: removed the regex keyword_classify fallback (it pattern-matched
    # operating names against CUISINE_PATTERNS - duplicative of what the
    # name-only LLM already sees, and a "dumb" signal user explicitly asked to
    # drop on 2026-05-14). Without web_verify or llm cache classification, the
    # entry has no Haiku-evaluated cuisine → drop.
    return [], None

def verification_for(name, address):
    """Returns dict of fields to merge if verified-open, else None. Drops the
    website field when url_health_cache reports it as broken. Coords come from
    Places when available, else from the Nominatim geocode cache."""
    key = cache_key(name, address)
    # Geocode cache is keyed by street address only (no postal code). Try the
    # full key first, then a stripped-postal fallback to match older cache entries.
    addr_no_postal = _re.sub(r'\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d$', '', (address or '').strip().upper())
    geo = GEOCODE_CACHE.get(key) or GEOCODE_CACHE.get(cache_key(name, addr_no_postal))
    geo_coords = (geo.get('lat'), geo.get('lng')) if (geo and geo.get('lat') and geo.get('lng')) else (None, None)
    # Source 1: Google Places
    p = PLACES_CACHE.get(key)
    if p and p.get('status') == 'ok':
        bs = p.get('businessStatus')
        if bs == 'OPERATIONAL':
            out = {'businessStatus': bs, 'verifiedBy': 'places'}
            for k in ('website', 'mapsUrl', 'rating', 'reviewCount', 'matchedName', 'lat', 'lng'):
                if p.get(k) is not None: out[k] = p[k]
            if out.get('website') and not url_is_alive(out['website']):
                del out['website']  # let mapsUrl be the link instead
            # When Places matched but has no own-website (or its URL was
            # dead), fall back to the web_verify-surfaced URL (top Google-
            # search match Haiku found earlier). Without this, JARDIN NOIR
            # had a Places match + a yorkdale.com URL from web_verify, but
            # the Places merge dropped through without ever consulting WV.
            if not out.get('website'):
                w = WEB_VERIFY_CACHE.get(key)
                if w and w.get('status') == 'ok' and w.get('operating') == 'yes':
                    wv_site = _validator_best_website(w)
                    if wv_site and url_is_alive(wv_site):
                        out['website'] = wv_site
            if out.get('lat') is None and geo_coords[0] is not None:
                out['lat'], out['lng'] = geo_coords
            return out
        if bs in ('CLOSED_TEMPORARILY', 'CLOSED_PERMANENTLY'):
            return None
    # Source 2 DISABLED 2026-05-27: previously a web_search-only fallback let
    # entries through when Places returned not_found. User directive: if we
    # can't verify the business via Places, we can't direct visitors to it
    # via Maps either, so it shouldn't appear. Keeping the legacy code below
    # behind a flag in case of later policy reversal. Currently 7 entries
    # got dropped by this tightening; the trade is that we don't surface
    # restaurants we can't link to a real Maps profile.
    ALLOW_WEB_SEARCH_ONLY = False
    w = WEB_VERIFY_CACHE.get(key)
    if ALLOW_WEB_SEARCH_ONLY and w and w.get('status') == 'ok' and w.get('operating') == 'yes':
        out = {'businessStatus': 'OPERATIONAL', 'verifiedBy': 'web_search'}
        wv_site = _validator_best_website(w)
        if wv_site and url_is_alive(wv_site):
            out['website'] = wv_site
        if p and p.get('status') == 'ok':
            for k in ('mapsUrl', 'rating', 'reviewCount', 'matchedName', 'lat', 'lng'):
                if p.get(k) is not None: out.setdefault(k, p[k])
        if out.get('lat') is None and geo_coords[0] is not None:
            out['lat'], out['lng'] = geo_coords
        return out
    return None

from urllib.parse import quote_plus
# Dedupe by (operating_name, street_address). When Toronto's MLS issues two licence rows
# for the same physical business (e.g. "Take-Out" + "Eating Establishment" categories, or
# a renewed licence overlapping the old one), we want one entry. Keep the EARLIEST
# Issued date - that's when the kitchen actually opened, not just when a category was added.
seen_entries = {}
n_food_active = 0; n_food_active_365 = 0; n_tagged_365 = 0; n_tagged_30 = 0
n_dropped_unverified = 0; n_dropped_closed = 0; n_deduped = 0; n_dropped_instore = 0; n_dropped_institutional = 0; n_dropped_weak_match = 0; n_dropped_brand_new_unverified = 0; n_dropped_validator = 0; n_dropped_chain_osm = 0; n_dropped_pre_existing = 0; n_dropped_multi_licence = 0; n_dropped_chain_cond = 0

# Pre-existing-restaurant gate: drop entries where Google Places returned
# at least one review whose timestamp is >180 days BEFORE the City licence-
# issued date. That's hard evidence the restaurant was operating before
# its current licence event, so "newly registered" is misleading. Phase A
# of the opening-date-credibility fix (2026-06-01). Phase B (full review
# history via SerpApi/Outscraper) is queued for entries that PASS this
# gate but still feel suspicious; not shipped yet.
PRE_EXISTING_GAP_DAYS = 180
def _pre_existing_evidence(cache_key_val, issued_date_str):
    """Returns (is_pre_existing, gap_days, earliest_review_date) tuple.
    is_pre_existing=True means at least one Places-returned review predates
    the licence by >PRE_EXISTING_GAP_DAYS. is_pre_existing=False either
    means the gate passes OR there's no review-timestamp data to gate on."""
    from datetime import timezone as _tz
    p = PLACES_CACHE.get(cache_key_val) or {}
    rd = p.get('reviewsDetail') or []
    if not rd: return (False, None, None)
    times = [r.get('time') for r in rd if r.get('time')]
    if not times: return (False, None, None)
    earliest_ts = min(times)
    earliest_dt = datetime.fromtimestamp(earliest_ts, tz=_tz.utc)
    try:
        licence_dt = datetime.strptime(issued_date_str, '%Y-%m-%d').replace(tzinfo=_tz.utc)
    except Exception:
        return (False, None, None)
    gap = (licence_dt - earliest_dt).days
    return (gap > PRE_EXISTING_GAP_DAYS, gap, earliest_dt.strftime('%Y-%m-%d'))


# DineSafe lookup, loaded once at module import. Maps "<streetnum>
# <streetword> <postalcode>" -> list of per-name inspection summaries.
# Source: tools/fetch_dinesafe.py (Toronto Public Health open data).
DINESAFE_LOOKUP_PATH = f'{ROOT}/tools/cache/dinesafe_lookup.json'
try:
    _ds_payload = json.load(open(DINESAFE_LOOKUP_PATH))
    DINESAFE_LOOKUP = _ds_payload.get('lookup') or {}
except FileNotFoundError:
    DINESAFE_LOOKUP = {}


def _dinesafe_key(addr_str):
    """Normalize a licence-feed address to match DineSafe's keying scheme.
    Standard addresses ('1871 O'Connor Dr, Toronto, ON M4A 1X1') get keyed by
    the leading 'streetnum streetword'. Mall / food-court / plaza entries
    ('Eplace RU-04, 6 Eglinton Ave E, Toronto, ON M4P 1A6') don't start with
    the street number - their internal unit prefix sits in front. Fallback:
    find the LAST 'digits + alpha-word' pair before the postal code, which
    naturally picks out the real street number even when the unit code came
    first."""
    s = (addr_str or '').upper()
    s = _re.sub(r'\s+(NONE|UNIT.*|SUITE.*)\s+', ' ', s)
    s = _re.sub(r"[^A-Z0-9 ]+", ' ', s)
    s = _re.sub(r'\s+', ' ', s).strip()
    postal_m = _re.search(r'([A-Z]\d[A-Z] ?\d[A-Z]\d)', s)
    if not postal_m: return None
    postal = postal_m.group(1).replace(' ', '')
    pre = s[:postal_m.start()].strip()
    m = _re.match(r'^(\d+) (\w+)', pre)
    if m:
        return f"{m.group(1)} {m.group(2)} {postal}"
    # Fallback: pick the last 'streetnum + alphabetic-streetword' pair.
    # \w+ requirement on the second token starting with [A-Z] avoids
    # matching internal codes like '04 6' where 6 is the actual street num.
    pairs = _re.findall(r'(\d+)\s+([A-Z]\w*)', pre)
    if not pairs: return None
    num, word = pairs[-1]
    return f"{num} {word} {postal}"


def _name_tokens_for_match(n):
    """Strip generic restaurant words so name overlap reflects the
    distinctive part of the name (MAKILALA, KENKOU SUSHI -> {KENKOU,
    SUSHI} -> distinctive tokens), not the generic 'RESTAURANT KITCHEN
    BAR' chrome that every entry has."""
    n = _re.sub(r'[^A-Z0-9 ]+', ' ', (n or '').upper())
    BAD = {'THE','A','AN','OF','AND','TO','TORONTO','RESTAURANT','CAFE',
           'KITCHEN','BAR','GRILL','FOOD','HOUSE','CO','INC','LTD',
           'LIMITED','BY','ON','AT'}
    return [t for t in n.split() if len(t) >= 3 and t not in BAD]


def _name_overlap(a, b):
    ta, tb = set(_name_tokens_for_match(a)), set(_name_tokens_for_match(b))
    if not ta or not tb: return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _pre_existing_dinesafe(operating_name, addr_str, issued_date_str):
    """Returns (is_pre_existing, gap_days, earliest_inspection, matched_name)
    or (False, None, None, None) when no DineSafe match found.

    Matches by address THEN requires name-overlap >= 0.3 with at least
    one DineSafe inspection at that address. Without the name filter we'd
    suppress new restaurants opening in former-tenant spaces (PROFOUND
    PIZZA opened where THE SWEET POTATO used to be - same address,
    different business, NOT pre-existing)."""
    key = _dinesafe_key(addr_str)
    if not key or not DINESAFE_LOOKUP: return (False, None, None, None)
    entries = DINESAFE_LOOKUP.get(key) or []
    if not entries: return (False, None, None, None)
    matching = [e for e in entries if _name_overlap(operating_name, e.get('name', '')) >= 0.3]
    if not matching: return (False, None, None, None)
    earliest = min(e['earliest'] for e in matching)
    try:
        gap = (datetime.strptime(issued_date_str, '%Y-%m-%d')
               - datetime.strptime(earliest, '%Y-%m-%d')).days
    except Exception:
        return (False, None, None, None)
    return (gap > PRE_EXISTING_GAP_DAYS, gap, earliest, matching[0]['name'])


def _prior_tenant_at_address(operating_name, addr_str):
    """Returns (prior_name, earliest_date) when DineSafe shows
    inspections at this address under a DIFFERENT business name from
    the current operator. (None, None) when no prior-tenant evidence.

    Mirror of _pre_existing_dinesafe but INVERTED: we want the address
    matches whose names DON'T overlap with the current operator. That's
    the "fresh tenant in an old kitchen" signal — high-confidence proof
    that a real new restaurant just took over an existing space (think
    Osteria Alba moving into the Vivoli room, or Wilbur Taco opening
    inside a Petro Canada that already had a different food operator).
    Editorially powerful as a "took over from X" badge."""
    key = _dinesafe_key(addr_str)
    if not key or not DINESAFE_LOOKUP: return (None, None)
    entries = DINESAFE_LOOKUP.get(key) or []
    if not entries: return (None, None)
    different = [e for e in entries
                 if _name_overlap(operating_name, e.get('name', '')) < 0.3
                 and e.get('earliest')]
    if not different: return (None, None)
    different.sort(key=lambda e: e['earliest'])
    return (different[0]['name'], different[0]['earliest'])


# first_seen cache: maps cache_key → ISO date the cacheKey first
# appeared in our daily inject. Backfilled on first run from the
# swapped issuedDate (best evidence we had at the time of seed). From
# then on, only NEW cacheKeys get today's date, so first_seen becomes
# a monotonic, defensible "we first listed this on X" anchor — way
# more honest than asserting an open date from a licence we can't
# verify. Use cases: "First listed on NowServingTO on May 14" badge;
# sort by first_seen for true "new on our directory" feed.
FIRST_SEEN_PATH = f'{ROOT}/tools/cache/first_seen.json'
try:
    FIRST_SEEN_CACHE = json.load(open(FIRST_SEEN_PATH))
except (FileNotFoundError, json.JSONDecodeError):
    FIRST_SEEN_CACHE = {}

# Grocery/retail chains whose in-store sushi/sandwich counters are NOT consumer-
# destination restaurants. Three orthogonal signals catch them:
#   1. City's "Free Form Conditions" - "LOCATED INSIDE FORTINO'S", "WITHIN SOBEYS"
#   2. Operating name = grocery-counter franchise brand (AFC, Zenshi, Bento Nouveau)
#   3. Client Name = franchisor corp (Advanced Fresh Concepts)
INSTORE_CHAINS = (
    'SOBEYS', 'LOBLAWS', 'FORTINO', 'METRO', 'FRESHCO', 'WHOLE FOODS',
    'WALMART', 'COSTCO', 'SHOPPERS DRUG MART', 'NO FRILLS', 'FOOD BASICS',
    'LONGO', 'FARM BOY', 'T&T', 'GALLERIA', 'PUSATERI',
)
KIOSK_BRAND_PATTERNS = (
    'AFC SUSHI', 'AFC/', 'ZENSHI', 'BENTO NOUVEAU', 'BENTO SUSHI', 'GENJI',
)
KIOSK_CLIENTS = ('ADVANCED FRESH CONCEPTS',)

# Renewal detection pre-pass (2026-06-01): scan the FULL CSV (ignoring
# the 365d window) and count distinct Licence No. values per
# (name, address). When >1, the business has demonstrably been licensed
# more than once - the row in our window is a renewal / category change
# / transfer, not a first-time licensing. We use this to drop those
# rows in the main loop. Cheap (~0.5s walk, no API calls), data-driven,
# uses the City's own structured signal rather than inferring from
# downstream evidence.
LICENCE_NO_COUNT_BY_KEY = {}
with open(CSV_PATH, encoding='utf-8', errors='replace') as f:
    for row in csv.DictReader(f):
        if (row.get('Category') or '').strip() not in FOOD_CATS: continue
        nm = (row.get('Operating Name') or '').strip().upper()
        ad = (row.get('Licence Address Line 1') or '').strip().upper()
        ln = (row.get('Licence No.') or '').strip()
        if not (nm and ad and ln): continue
        LICENCE_NO_COUNT_BY_KEY.setdefault(nm + '||' + ad, set()).add(ln)
LICENCE_NO_COUNT_BY_KEY = {k: len(v) for k, v in LICENCE_NO_COUNT_BY_KEY.items()}
print(f"  pre-pass: {sum(1 for v in LICENCE_NO_COUNT_BY_KEY.values() if v > 1):,} of {len(LICENCE_NO_COUNT_BY_KEY):,} name+address pairs have >1 distinct Licence No. (renewal/re-licence candidates)")

with open(CSV_PATH, encoding='utf-8', errors='replace') as f:
    rdr = csv.DictReader(f)
    for row in rdr:
        cat = (row.get('Category') or '').strip()
        if cat not in FOOD_CATS: continue
        # Cancel Date rule: drop only if cancelled more than 10 days ago.
        # Future-dated cancellations (place still operating, scheduled closure)
        # AND recent cancellations within 10 days (transition / wind-down period)
        # are KEPT. Per user directive 2026-05-14.
        cancel_raw = (row.get('Cancel Date') or '').strip()
        if cancel_raw:
            cancel_d = parse_d(cancel_raw)
            if cancel_d and (REFERENCE_DATE - cancel_d).days > 10:
                continue
        n_food_active += 1
        iss = parse_d(row.get('Issued'))
        if not iss or iss < WINDOW_365: continue
        n_food_active_365 += 1
        # (REMOVED 2026-05-14: hardcoded in-store-kiosk filter via Conditions regex
        # and Client Name licence-count threshold. The validator sees Client Name +
        # Conditions directly and flags `validator_drop: not-discovery` for
        # institutional caterers, in-grocery kiosks, packaged-food brands, etc.
        # The validator_drop honoring below handles all of these uniformly.)
        op_raw = (row.get('Operating Name') or '').strip()
        if not op_raw: continue
        # Pre-filter: OSM-tagged chain brands. If OpenStreetMap has tagged
        # this exact operating name as a multi-location brand (e.g. 241
        # Pizza, A&W, Subway), it's a chain regardless of what the per-entry
        # validator decides. Saves the downstream verify/validate spend AND
        # catches chain locations where per-entry Haiku evidence is sparse
        # (e.g. UberEats URL for one location and 241pizza.com for others).
        if is_osm_chain(op_raw):
            n_dropped_chain_osm += 1
            continue
        # CHAIN condition gate: the City's own Conditions field carries an
        # explicit 'CHAIN' code on rows it considers chain locations. Doesn't
        # subsume OSM/Wikidata (the City flags some chains those miss, vice-
        # versa), so it's complementary. Cheap row-field check, runs before
        # any verification spend.
        if 'CHAIN' in (row.get('Conditions') or '').upper():
            n_dropped_chain_cond += 1
            continue
        addr1 = (row.get('Licence Address Line 1') or '').strip()
        addr3 = (row.get('Licence Address Line 3') or '').strip()
        address_full = (addr1 + ' ' + addr3).strip()
        # Multi-licence-number gate: the CSV has >1 distinct Licence No. for
        # this (name, address). Demonstrably not a first-time issuance -
        # the place has been licensed before and this row is a renewal /
        # category change / transfer. Drop. (Data-driven re-licensing
        # detection: complements the operating-evidence gates above.)
        _lk = op_raw.upper() + '||' + addr1.upper()
        if LICENCE_NO_COUNT_BY_KEY.get(_lk, 0) > 1:
            n_dropped_multi_licence += 1
            continue
        cuisines, source = get_cuisine(op_raw, address_full)
        if not cuisines: continue

        # Unified-validator drop: Haiku looked at name + Places match + types +
        # editorial + reviews and concluded this is not a consumer restaurant
        # (institutional caterer, packaged-food brand, grocery counter, etc.).
        # Authoritative - trumps the cuisine signal.
        wv_e = WEB_VERIFY_CACHE.get(cache_key(op_raw, address_full))
        if wv_e and wv_e.get('validator_drop'):
            n_dropped_validator += 1   # Haiku-judged: chain, institutional, ghost, etc.
            continue

        # Address-mismatch drop: validator explicitly said the brand at the
        # web/Places-confirmed address is NOT the business sitting at the
        # licence address. Cases include wrong-building Places matches,
        # different physical locations (kilometers apart), and brand-new
        # licences for a NEW location where the brand still operates at
        # an OLD address per the web. "NowServingTO" implies actively
        # operating at the displayed address - this verdict is the
        # validator telling us we can't confirm that.
        vj = (wv_e or {}).get('validator_judgment') or {}
        if vj.get('is_same_business') == 'no':
            n_dropped_validator += 1
            continue

        # "Newest" gate (2026-05-29): drop licence renewals / relocations of
        # established businesses. The City Issued date ticks on renewals,
        # transfers, and address changes - so a 30-year restaurant getting a
        # fresh licence at a new spot looks like a brand-new opening per the
        # CSV alone. The validator separately judges whether the licence
        # represents a genuinely new business or a continuation (writes
        # is_brand_new = yes|no|unclear in validator_judgment). Drop "no".
        # Keep "yes" and "unclear" - we'd rather over-include borderline
        # cases than miss real new openings.
        is_brand_new = vj.get('is_brand_new')
        # Heuristic fallback for cached entries judged BEFORE the validator
        # prompt grew an is_brand_new field. Scan the validator's existing
        # evidence prose for tell-tale "established / for X years / since
        # 19YY" phrases that mean Haiku already noticed the business is old.
        # When the next validator batch runs and writes is_brand_new
        # directly, this heuristic stops applying for the same entry.
        if is_brand_new is None:
            ev_text = ((vj.get('evidence') or '') + ' '
                       + ((wv_e or {}).get('validator_evidence') or '')).lower()
            patterns = [
                # "for/over/nearly/almost N years" - qualified durations
                _re.compile(r'\b(?:for|over|nearly|almost|past|been)\s+(\d{1,3})\s*\+?\s*(?:years?|yrs?)\b'),
                # "N+ year" / "N+ years" - the explicit + sign is itself a strong
                # "operating duration" marker (covers "30+ year Filipino family
                # operation" - real Pampanguena case 2026-05-29).
                _re.compile(r'\b(\d{1,3})\+\s*(?:years?|yrs?)\b'),
                # "N-year-old" / "N years old"
                _re.compile(r'\b(\d{1,3})[\s\-]+(?:years?|yrs?)[\s\-]+old\b'),
                # "N year(s) + business-context noun"
                _re.compile(r'\b(\d{1,3})[\s\-]+(?:years?|yrs?)\s+(?:operation|operating|veteran|running|business|family|restaurant|institution|tradition|service|kitchen|establishment|legacy|history|run|old|cafe|caf\xe9|deli|bakery|of\s+business)\b'),
                # "since YEAR" / "established YEAR" / "founded YEAR"
                _re.compile(r'\b(?:since|established|founded|operating since)\s+(?:in\s+)?(\d{4})\b'),
                # Pure age adjectives - text only, no number capture
                _re.compile(r'\bdecades(?:[\s\-](?:old|of|long))?\b'),
                _re.compile(r'\b(?:longstanding|long-?running|long-?standing|veteran|legendary|iconic|generations[\s\-]old|family[\s\-]?run\s+(?:for|since))\b'),
            ]
            old_match = False
            for pat in patterns:
                m = pat.search(ev_text)
                if not m:
                    continue
                groups = m.groups()
                # Has numeric capture: enforce a threshold so we don't catch
                # "5 dishes" / "since 2024" style false positives.
                if groups and groups[0]:
                    n = int(groups[0])
                    if 1900 < n <= 2100:    # year
                        if (REFERENCE_DATE.year - n) >= 3:
                            old_match = True
                            break
                    elif n >= 3:            # "for X years"
                        old_match = True
                        break
                else:                       # text-only signal
                    old_match = True
                    break
            if old_match:
                is_brand_new = 'no'

        if is_brand_new == 'no':
            n_dropped_validator += 1
            continue

        # Verification gate: Places=OPERATIONAL OR web_search verified-yes.
        verification = verification_for(op_raw, address_full)
        if verification is None:
            n_dropped_unverified += 1   # no Places + no web_verify yet - pending pipeline data
            continue

        # Build candidate entry
        days_open = max(0, (REFERENCE_DATE - iss).days)
        # Stable, URL-safe ASCII slug - kebab-case the name + leading address
        # number for disambiguation across multi-location chains/branches.
        # Accents stripped via unicode NFKD decomposition because Apache's
        # RewriteRule [\w-]+ pattern is ASCII-only and would 400 on any URL
        # containing à/è/ê/ñ/etc - and most external services prefer ASCII
        # URLs anyway. "Gàima" → "gaima", "rêve" → "reve".
        import unicodedata
        ascii_name = unicodedata.normalize('NFKD', op_raw or '').encode('ascii', 'ignore').decode()
        name_part = _re.sub(r'[^a-zA-Z0-9\s-]', '', ascii_name).strip().lower()
        name_part = _re.sub(r'[\s_]+', '-', name_part).strip('-')
        addr_num_m = _re.match(r'^(\d+)', (addr1 or '').strip())
        addr_num = addr_num_m.group(1) if addr_num_m else ''
        slug = (name_part + (f'-{addr_num}' if addr_num else ''))[:80]
        entry = {
            'operatingName': op_raw,
            'cuisine': cuisines[0],          # primary - backwards-compat for any consumer that reads `cuisine`
            'cuisines': cuisines,             # full multi-cuisine list - what the front-end filters on
            'cuisineSource': source,
            'issuedDate': iss.isoformat(),
            'daysOpen': days_open,
            'address': addr1,                 # default: permit address. Overridden by Places.matchedAddress below when available.
            'slug': slug,
            # Stash the cache-key built from PERMIT name+address so downstream
            # places_cache lookups work even after entry.address has been
            # overridden by Places' formatted matchedAddress.
            '_cacheKey': cache_key(op_raw, address_full),
        }
        district = district_from_postal(address_full)
        if district: entry['district'] = district
        entry.update({k: v for k, v in verification.items() if v is not None})

        # Social handles extracted by the validator from the fetched website
        # (Instagram / X / Facebook). Used by the X posting bot to @-mention
        # the restaurant when announcing it; absent when the validator
        # couldn't find any social links in the page content.
        if wv_e and wv_e.get('socials'):
            entry['socials'] = wv_e['socials']

        # Per user directive 2026-05-14: Google Places data overrides permit
        # data where Places has authoritative info. Use the matchedAddress as
        # the displayed address (cleaner formatting, validated location).
        # Fallback: permit address (when no Places match).
        # 2026-06-01: postal-mismatch guard. When the operator has multiple
        # licences (e.g. commissary at one address + retail at another),
        # Places often returns the retail location for ALL of them via
        # fuzzy name match. If the postal code in the matchedAddress differs
        # from the licence's postal, it's a wrong-business override.
        # Keep the licence address; don't trust Places.
        places_match = PLACES_CACHE.get(entry['_cacheKey'])
        if places_match and places_match.get('status') == 'ok' and places_match.get('matchedAddress'):
            ma = places_match['matchedAddress']
            ma = _re.sub(r',\s*Canada\s*$', '', ma)
            _lp = _re.search(r'[A-Z]\d[A-Z]\s?\d[A-Z]\d', (address_full or '').upper())
            _pp = _re.search(r'[A-Z]\d[A-Z]\s?\d[A-Z]\d', ma.upper())
            _postal_ok = (
                not (_lp and _pp)
                or _lp.group(0).replace(' ', '') == _pp.group(0).replace(' ', '')
            )
            if _postal_ok:
                entry['address'] = ma

        # fallbackMapsUrl removed 2026-05-19. The previous design assumed
        # every entry reaching this code path had been independently verified
        # to exist at this address (the brand-new-unverified gate enforced
        # Places match OR website). After 2026-05-19's gate refinement let
        # web-verify-only entries through (e.g. CAFEMIA: DineSafe + Yelp
        # confirmed but no Places profile yet), a name+address search no
        # longer reliably lands on the right business - Google Maps returns
        # OTHER businesses at nearby addresses (Messina/Amico/Tre Mari
        # bakeries instead of CAFEMIA), which is worse UX than no link at
        # all. The row renderer now shows the address as plain text when no
        # Places-backed mapsUrl exists.

        # (REMOVED 2026-05-14: brand-website inheritance dict - the validator
        # returns best_website per entry directly, computed from full evidence.)

        # Weak-match drop: if NONE of Places / a working website / a real cuisine
        # signal exist, we're sending the user to a location we can't verify is
        # the right place. Better to hide the entry than risk landing them at a
        # neighbouring business (e.g., EASTERN 828 CAFE → adjacent car wash).
        # Conditions for "weak":
        #   - no Places match (no matchedName / no mapsUrl), AND
        #   - no working website (already dropped by url_is_alive if broken), AND
        #   - cuisine came from name-only LLM or keyword guess (no real evidence).
        # These entries will be re-queued for the next cron - their caches'
        # recovered_at timestamps gate the 30-day re-attempt window, by which
        # point Google/Yelp/blogs may have indexed the place and a stronger
        # signal will arrive.
        # Drop only when there's literally no evidence the place exists -
        # no Places match AND no website AND cuisine came from name-only
        # (no web_search evidence the operator is real). For multi-location
        # indies where validator cleared an address-mismatched Places match
        # but web_verify found the brand online (cuisine source = web_search),
        # KEEP the entry - they may show in a brand-search even if Google
        # hasn't indexed this specific location yet.
        if (not entry.get('matchedName')
            and not entry.get('mapsUrl')
            and not entry.get('website')
            and source in ('llm', None)):
            n_dropped_weak_match += 1
            continue

        # No-destination gate (relaxed 2026-05-26). Previously dropped all
        # entries without Places match AND without website, on the theory
        # that /r/<slug> was a thin fallback destination. Now /r/<slug>
        # carries the LISTING-EXTRA editorial blurb, menu signals, and
        # nearby-grid cards - it's a real destination. So we only drop
        # entries when the validator can't even confirm the business
        # exists (no positive web_verify operating signal + no
        # restaurant verdict). This recovers brand-new licences whose
        # only web trace is DineSafe + an Instagram (no Places yet).
        if not entry.get('matchedName') and not entry.get('website'):
            wv_e = WEB_VERIFY_CACHE.get(cache_key(op_raw, address_full)) or {}
            vj = wv_e.get('validator_judgment') or {}
            confirms_restaurant = (
                wv_e.get('operating') == 'yes'
                and vj.get('is_restaurant') == 'yes'
                and vj.get('is_same_business') != 'no'
            )
            if not confirms_restaurant:
                n_dropped_brand_new_unverified += 1
                continue

        # Pre-existing-restaurant gate (Phase A + B, 2026-06-01):
        # EITHER signal triggers suppression:
        #   A) Places-returned review > 180 days before licence
        #   B) DineSafe inspection (TPH inspector visited this address +
        #      name) > 180 days before licence - authoritative gov data
        # B catches what A misses (MAKILALA-class: recent reviews crowd
        # out old ones in the 5-review Places sample) and vice versa.
        is_pre, _, _ = _pre_existing_evidence(cache_key(op_raw, address_full),
                                              iss.isoformat())
        if not is_pre:
            is_pre, _, _, _ = _pre_existing_dinesafe(op_raw, address_full,
                                                     iss.isoformat())
        if is_pre:
            n_dropped_pre_existing += 1
            continue

        # Dedupe by (name_upper, addr_upper). Keep EARLIEST issuedDate.
        dedup_key = (op_raw.upper(), addr1.upper())
        existing = seen_entries.get(dedup_key)
        if existing is None:
            seen_entries[dedup_key] = entry
        else:
            n_deduped += 1
            if iss.isoformat() < existing['issuedDate']:
                seen_entries[dedup_key] = entry  # this row is earlier - keep it

# Dedup-by-place_id (2026-06-01): when two licence rows under the same
# operator name resolve to the same Google Places place_id, they're the
# same physical business. Common pattern: a commissary licence at one
# address + a retail storefront licence at another, where Places matches
# both rows to the storefront via fuzzy name search. Without this dedup
# the page shows two rows for one restaurant, with the commissary row
# carrying a misleading district label (computed from commissary postal,
# not storefront postal). Keep the entry with the latest issuedDate -
# typically the storefront, since commissaries are usually licensed
# earlier than the retail front-of-house.
_pid_groups = {}
for _k, _e in seen_entries.items():
    _pmatch = PLACES_CACHE.get(_e.get('_cacheKey') or '') or {}
    # Cache uses both 'place_id' (canonical, from Places API) and 'placeId'
    # (set by ad-hoc refetch scripts). Check both for safety.
    _pid = (_e.get('placeId') or _pmatch.get('placeId')
            or _pmatch.get('place_id'))
    if _pid:
        _pid_groups.setdefault(_pid, []).append(_k)
_n_dedup_pid = 0
for _pid, _keys in _pid_groups.items():
    if len(_keys) <= 1: continue
    _keep = max(_keys, key=lambda k: seen_entries[k].get('issuedDate', ''))
    for _k in _keys:
        if _k != _keep:
            del seen_entries[_k]
            _n_dedup_pid += 1
if _n_dedup_pid:
    print(f"  place_id dedup: collapsed {_n_dedup_pid} extra entries (same operator + same Places match - commissary/storefront pairs)")

# Date-source swap (2026-06-01): when a stronger operating-since signal
# exists than the licence-issued date, surface it as the displayed
# "registered" date. The licence event answers "when did paperwork
# happen"; the swap targets answer "when was the place definitely
# operating." Priority order:
#   1. DineSafe earliest inspection at this (address, name).
#      Authoritative gov data; if Toronto Public Health inspected on
#      date X, the place was serving food on date X.
#   2. Oldest Places-returned review timestamp.
#      Fallback for entries DineSafe can't match (mall/food-court
#      addresses, no inspections yet, etc.). The pre-existing gate
#      already drops any entry whose oldest review predates the
#      licence by >180d, so any review we'd swap to here is known
#      to post-date the licence event (real operating-since signal,
#      not a re-licensing of a long-running place).
# Original licence date preserved as `licenceIssuedDate` for audit.
_n_date_swapped = 0
_n_swap_dinesafe = 0
_n_swap_review = 0
for _e in seen_entries.values():
    _name = _e.get('operatingName') or ''
    _addr = _e.get('address') or ''
    _licence_iso = _e['issuedDate']
    # Evidence ranking (per user 2026-06-03): DineSafe is the trusted
    # opening signal — TPH inspects at/near opening, no sampling bias.
    # Places review timestamps are an airy heuristic — the API only
    # returns up to 5 reviews per fetch, so for any popular spot the
    # "earliest review we see" is the earliest of the SAMPLE, not the
    # actual first review (could miss months/years of earlier reviews).
    # New rule: use DineSafe unconditionally when present; fall back to
    # review only when no DineSafe AND reviewCount ≤ 5 (full set, no
    # sampling bias). Licence is the implicit default when no other
    # evidence — no swap needed.
    _candidates = []
    _, _, _ds_earliest, _ = _pre_existing_dinesafe(_name, _addr, _licence_iso)
    if _ds_earliest:
        _candidates.append((_ds_earliest, 'dinesafe'))
    else:
        _, _, _rev_earliest = _pre_existing_evidence(_e.get('_cacheKey') or '', _licence_iso)
        _rev_count = _e.get('reviewCount') or 0
        if _rev_earliest and _rev_count <= 5:
            _candidates.append((_rev_earliest, 'review'))
    if not _candidates: continue
    _candidates.sort()
    _swap_date, _swap_src = _candidates[0]
    if _swap_date == _licence_iso: continue  # already matches, no-op swap
    try:
        _swap_dt = datetime.strptime(_swap_date, '%Y-%m-%d').date()
    except Exception:
        continue
    if _swap_dt > REFERENCE_DATE: continue  # future-dated, skip
    _e['licenceIssuedDate'] = _licence_iso
    _e['issuedDate'] = _swap_date
    _e['daysOpen'] = max(0, (REFERENCE_DATE - _swap_dt).days)
    _e['dateSource'] = _swap_src   # 'dinesafe' | 'review' — drives badge label
    _n_date_swapped += 1
    if _swap_src == 'dinesafe': _n_swap_dinesafe += 1
    else: _n_swap_review += 1
print(f"  date swap: {_n_date_swapped} entries reassigned 'registered' date "
      f"({_n_swap_dinesafe} via DineSafe, {_n_swap_review} via oldest Places review)")

# >1yr drop (post-swap): the existing pre-existing gate compares licence
# date vs evidence and drops if evidence predates licence by >180d. That
# catches re-licensings of long-running places, but misses entries where
# the licence-vs-evidence gap is ≤180d AND yet the absolute operating-
# since signal still puts the place past the 365d window. Example: 11mo
# old licence + reviews 6mo before that = 17mo operating, but only 5mo
# licence-evidence gap (passes the 180d gate). Now that the swap surfaces
# the actual operating-since lower bound, just drop anything whose
# daysOpen exceeds 365 - the directory's whole promise is restaurants in
# their first year, and a 17-month-old place doesn't belong even if its
# paperwork looks recent.
_n_dropped_over_1yr = 0
for _k in list(seen_entries.keys()):
    if seen_entries[_k].get('daysOpen', 0) > 365:
        del seen_entries[_k]
        _n_dropped_over_1yr += 1
if _n_dropped_over_1yr:
    print(f"  >1yr drop: {_n_dropped_over_1yr} entries cut (operating evidence dates back >365d, "
          f"licence is recent but the place isn't actually new)")

# Attach firstSeen + priorTenant signals to each surviving entry (runs
# after all the drop gates so we don't bother computing for entries
# that won't make the final feed).
_today_iso_for_firstseen = REFERENCE_DATE.isoformat()
_n_first_seen_new = 0
_n_prior_tenant = 0
for _k, _e in seen_entries.items():
    # firstSeen cache is keyed by the canonical _cacheKey string (the
    # same key shared with places_cache / web_verify_cache), NOT the
    # in-memory tuple key seen_entries uses for dedup. Falls back to
    # the entry name+addr if _cacheKey wasn't set.
    _fs_key = _e.get('_cacheKey') or f'{(_e.get("operatingName") or "").upper()}||{(_e.get("address") or "").upper()}'
    # firstSeen: seed = swapped issuedDate (best evidence we have at
    # first run); never overwrite. Going forward, new keys → today.
    if _fs_key not in FIRST_SEEN_CACHE:
        _seed = _e.get('issuedDate') or _today_iso_for_firstseen
        if _seed > _today_iso_for_firstseen: _seed = _today_iso_for_firstseen
        FIRST_SEEN_CACHE[_fs_key] = _seed
        _n_first_seen_new += 1
    _e['firstSeen'] = FIRST_SEEN_CACHE[_fs_key]
    # priorTenant: address has DineSafe history under different names →
    # this is a fresh tenant in an old kitchen, editorial gold.
    _pt_name, _pt_date = _prior_tenant_at_address(
        _e.get('operatingName') or '', _e.get('address') or '')
    if _pt_name:
        _e['priorTenant'] = {'name': _pt_name, 'since': _pt_date}
        _n_prior_tenant += 1
if _n_first_seen_new:
    import os as _os
    _os.makedirs(_os.path.dirname(FIRST_SEEN_PATH), exist_ok=True)
    with open(FIRST_SEEN_PATH, 'w') as _f:
        json.dump(FIRST_SEEN_CACHE, _f, sort_keys=True, separators=(',', ':'))
print(f"  signals: firstSeen={_n_first_seen_new} new entries cached "
      f"({len(FIRST_SEEN_CACHE)} total), priorTenant flagged on {_n_prior_tenant} entries")

# Now bucket the deduped entries by cuisine and compute counts.
# Multi-cuisine entries (e.g., "Afghan + Pakistani + Indian") appear in EACH
# of their cuisine buckets - totalTagged365d counts entries (not bucket-rows),
# so a 3-cuisine place still counts as 1 toward the total.
# Photo pre-pass REMOVED 2026-06-03. We no longer cache Place/Street View
# photo bytes to disk — site went text-only across all surfaces (Google
# Maps Platform ToS §5.3 caching restriction + curating 300+ owner uploads
# is not the lift we want). The image-helper imports below are kept as a
# stub for the (unused) _make_thumb function so other code paths that
# happen to reference it don't break. download_place_photo / streetview_*
# entry points still exist in enrich_places.py for one-off debugging.
from pathlib import Path as _Path
import subprocess as _sub

def _make_thumb(src, dst, size=196):
    """Center-square-crop + resize to size×size, save as WebP q=80. ~3KB per
    thumb (~50% smaller than the prior 160×160 JPEG q=78). 196×196 is the 2x-
    retina size for a 98×98 CSS box, so it stays crisp on hidpi displays
    while shedding bytes vs the old 160×160 JPEG which was both oversized
    for 1x and undersized for 2x. WebP is supported by ~98% of browsers.

    Tries ImageMagick `convert` first (VPS has it), falls back to PIL (local
    dev has it). Both write WebP at quality 80."""
    try:
        _sub.run(
            ['convert', str(src), '-resize', f'{size}x{size}^',
             '-gravity', 'center', '-extent', f'{size}x{size}',
             '-quality', '80', '-strip', str(dst)],
            check=True, capture_output=True,
        )
        return True
    except (_sub.SubprocessError, FileNotFoundError):
        pass
    try:
        from PIL import Image
        with Image.open(str(src)) as im:
            im = im.convert('RGB')
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w-s)//2, (h-s)//2, (w+s)//2, (h+s)//2))
            im = im.resize((size, size), Image.LANCZOS)
            im.save(str(dst), 'WEBP', quality=80, method=6)
        return True
    except Exception:
        return False

# Photo download loop REMOVED 2026-06-03. Site is text-only; no entry
# carries `photo`, `thumb`, or `photoCredit` anymore. Defensive strip of
# any photo fields that survived in older cache snapshots — the data
# layer should not leak fields the renderer no longer reads.
for entry in seen_entries.values():
    for k in ('photo', 'thumb', 'photoCredit', 'photoRef', 'photoAttribs'):
        entry.pop(k, None)

opens_365_by_cuisine = defaultdict(list)
for entry in seen_entries.values():
    n_tagged_365 += 1
    if entry['daysOpen'] <= 30: n_tagged_30 += 1
    for c in entry.get('cuisines') or [entry['cuisine']]:
        opens_365_by_cuisine[c].append(entry)

print(f"  verification gate: kept {n_tagged_365}, dropped {n_dropped_chain_osm} OSM-known chains + {n_dropped_chain_cond} City-flagged CHAIN condition + {n_dropped_multi_licence} multi-licence-number (renewal/re-licensing) + {n_dropped_validator} validator (Haiku: chain/institutional/ghost) + {n_dropped_unverified} unverified (no Places, no web_verify yet) + {n_dropped_closed} closed/temp + {n_dropped_instore} in-store kiosks + {n_dropped_institutional} institutional-operator rows + {n_dropped_weak_match} weak-match (no Places / no site / name-guess only) + {n_dropped_brand_new_unverified} brand-new-unverified (<30d, no Places/website) + {n_dropped_pre_existing} pre-existing (evidence predates licence by >180d) + {_n_dropped_over_1yr} operating >1yr per evidence + {n_deduped} duplicate rows collapsed")

# Sort each cuisine's list by issued date desc (newest first)
for c in opens_365_by_cuisine:
    opens_365_by_cuisine[c].sort(key=lambda r: r['issuedDate'], reverse=True)

# Summary per cuisine
cuisines_out = []
for c, entries in opens_365_by_cuisine.items():
    # Color: prefer the curated palette below; fall back to a deterministic
    # hash-derived color for novel/dynamic cuisines (Hakka, Uyghur, Cape
    # Verdean, etc. - anything Haiku surfaced that wasn't in the seed list).
    color = PALETTE_HEX.get(c) or cuisine_color(c)
    cuisines_out.append({
        'key': c,
        'label': CUISINE_LABEL.get(c, c),
        'color': color,
        'count365d': len(entries),
        'count30d': sum(1 for e in entries if e['daysOpen'] <= 30),
        'newest': entries[0],          # the absolute newest one
        'recent5': entries[:10],        # for per-cuisine card (bumped to 10, key kept for back-compat)
    })
cuisines_out.sort(key=lambda r: -r['count365d'])

# Prune cuisines_dynamic.json - keep only keys that are actually IN USE by
# the current feed. Sub-cuisines collapsed by the prompt's parent-country
# rule (e.g., Sichuan → Chinese) leave orphan entries in the dynamic dict
# that would otherwise clutter the cuisine dropdown forever. Seed
# (curated) cuisines in CUISINE_LABEL are never pruned - they may have 0
# entries today but reappear tomorrow.
try:
    from cuisines import _load_dynamic, _save_dynamic, _DYNAMIC_PATH
    in_use = {c['key'] for c in cuisines_out}
    dyn = _load_dynamic()
    pruned = {k: v for k, v in dyn.items() if k in in_use}
    if len(pruned) != len(dyn):
        print(f"  pruned {len(dyn) - len(pruned)} unused dynamic cuisines from {_DYNAMIC_PATH.name}")
        _save_dynamic(pruned)
except Exception as ex:
    print(f"  WARN: dynamic-cuisine prune failed: {ex}")

# Flat feed: all openings, newest first. Iterate seen_entries directly (NOT the
# per-cuisine buckets) so multi-cuisine entries - which appear in multiple cuisine
# buckets by design - are NOT duplicated in the flat feed.
all_recent = sorted(seen_entries.values(),
                    key=lambda r: r['issuedDate'], reverse=True)[:1500]

# Inject
from datetime import timezone
data = json.load(open(DATA_PATH))
# Stamp top-level generatedAt too - daily inject regenerates the dataset, so the
# subtitle "updated <date>" should reflect today, not the last build_corridors run.
data['generatedAt'] = datetime.now(timezone.utc).isoformat()
data['newOpenings'] = {
    'asOf': REFERENCE_DATE.isoformat(),
    'windowDays': 365,
    'totalActiveScanned': n_food_active,
    'totalNewActive365d': n_food_active_365,
    'totalTagged365d': n_tagged_365,
    'totalTagged30d': n_tagged_30,
    'tagRate365d': round(n_tagged_365 / max(n_food_active_365, 1) * 100, 1),
    'cuisines': cuisines_out,
    'recent': all_recent,
}
with open(DATA_PATH, 'w') as f:
    json.dump(data, f, separators=(',', ':'))

# ── SEO/LLM-EO injection: sitemap + index.html static-feed + JSON-LD ItemList ──
# Mirrors the dynamic feed for crawlers and no-JS visitors. Re-runs every cron.
SITE_BASE = 'https://nowservingto.com'
SITEMAP_PATH = f'{ROOT}/sitemap.xml'
INDEX_PATH = f'{ROOT}/index.html'

# Python-side cuisine palette mirrors the one in index.html. Used to color the pre-rendered
# static cuisine pills so crawlers see proper structured visual styling too.
# (PALETTE_HEX moved up; see definition near the top of this file.)

def _esc(s):
    """HTML-escape a string."""
    if s is None: return ''
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#39;'))


def _ordinal(n):
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', etc. Used in cohort lede."""
    if 10 <= n % 100 <= 20:
        return f'{n}th'
    return f'{n}{ {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th") }'


def _ago_long(days):
    """Verbose version of _ago() for the listing lede - prose-friendly
    ("First seen 7 days ago") rather than the compact row badge ("7d ago").

    Unified verb 'First seen' across all entries (matches _tier_label).
    Doesn't claim 'opened' or 'registered' or 'inspected' — just states
    when the directory first encountered this restaurant, which is
    always true regardless of which underlying evidence source won the
    earliest-date swap."""
    if days is None: return ''
    if days <= 0: return 'First seen today'
    if days == 1: return 'First seen yesterday'
    if days <= 60: return f'First seen {days} days ago'
    if days <= 365: return f'First seen {round(days / 30)} months ago'
    return 'First seen over a year ago'


def _ago(days):
    # Time-only labels. Kept for backward compatibility with the X tweet
    # snippet builder and any other prose paths; the row pill no longer
    # calls this - see _tier_label() below.
    if days <= 1: return 'today'
    if days <= 60: return f'{days}d ago'
    if days <= 365: return f'{round(days/30)}mo ago'
    return f'{days/365:.1f}y ago'


def _tier_label(days, iso_date=None, date_source=None):
    """Single 'First seen' label across all entries — visitor doesn't
    care whether the underlying date is licence / DineSafe / review;
    two different verbs ('Registered' vs 'First inspected') just
    confuses ("why does this place have a different freshness metric?").
    The date itself is still the earliest-evidence swap result, so the
    accuracy is preserved; the label just stops leaking provenance.

    `date_source` arg kept in signature for back-compat but unused.

    Tiers:
      0d      -> 'First seen today'
      1d      -> 'First seen yesterday'
      2-30d   -> 'First seen Nd ago'
      31-90d  -> 'First seen Nw ago'
      91-365d -> 'First seen Nmo ago'
    """
    if days is None: return ''
    if days <= 0:   return 'First seen today'
    if days == 1:   return 'First seen yesterday'
    if days <= 30:  return f'First seen {days}d ago'
    if days <= 90:
        w = max(5, round(days / 7))
        return f'First seen {w}w ago'
    if days <= 365:
        m = max(3, round(days / 30))
        return f'First seen {m}mo ago'
    return ''


def _native_script(key):
    """Cuisine → native-script word for the decorative-typography graphic
    that replaces photos site-wide. Empty string when the cuisine uses
    Latin script (Italian, French, Vietnamese, etc.) — those entries
    rely on color + serif typography alone, no ornament.

    Verified against Wikipedia language entries 2026-06-03. Single short
    word in the community's primary writing system; RTL scripts (Arabic-
    derived) carry the natural visual flow. Renders via system Noto
    fonts (installed via `apt install fonts-noto fonts-noto-cjk` on the
    rendering boxes)."""
    S = {
        'bangladeshi': 'বাংলা',         # Bengali (LTR)
        'tamil':       'தமிழ்',           # Tamil script (LTR)
        'sri_lankan':  'ලංකා',          # Sinhala (LTR)
        'tibetan':     'བོད་',           # Tibetan (LTR)
        'uyghur':      'ئۇيغۇر',         # Uyghur Arabic (RTL)
        'kurdish':     'کوردی',         # Kurdish Sorani (RTL)
        'pakistani':   'پاکستان',        # Urdu (RTL)
        'persian':     'فارسی',          # Persian (RTL)
        'iranian':     'فارسی',
        'arab':        'عربي',           # Arabic (RTL)
        'lebanese':    'لبنان',          # Arabic (RTL)
        'syrian':      'سوريا',          # Arabic (RTL)
        'turkish':     'türk',           # Turkish (Latin, but distinctive)
        'middle_east': 'شرق',            # Arabic (RTL) — "east"
        'chinese':     '中文',           # Simplified Chinese
        'taiwanese':   '台灣',           # Traditional Chinese
        'japanese':    '日本',           # Japanese kanji
        'korean':      '한국',           # Hangul
        'thai':        'ไทย',            # Thai
        'cambodian':   'ខ្មែរ',          # Khmer
        'burmese':     'မြန်မာ',          # Burmese
        'indonesian':  'Nusantara',     # Indonesian (Latin)
        'malaysian':   'Melayu',         # Malay (Latin)
        'filipino':    'Pilipino',       # Filipino (Latin)
        'vietnamese':  'Việt',           # Vietnamese (Latin w/ diacritics)
        'indian':      'भारत',          # Devanagari (Hindi)
        'nepalese':    'नेपाल',          # Devanagari
        'ethiopian':   'ኢትዮጵያ',         # Amharic (Ge'ez)
        'eritrean':    'ኤርትራ',          # Tigrinya (Ge'ez)
        'somali':      'Soomaali',       # Somali (Latin)
        'nigerian':    'Naijá',          # Nigerian Pidgin (Latin)
        'ghanaian':    'Gaana',          # Akan-ish (Latin)
        'african_west':'Naijá',
        'african_horn':'Habesha',
        'caribbean':   'Caribe',
        'jamaican':    'Yard',           # Jamaican patois-ish
        'trinidadian': 'Trini',
        'guyanese':    'Guyana',
        'haitian':     'Ayiti',          # Haitian Creole
        'salvadoran':  'Cuscatlán',      # Nahuat/indigenous SV name
        'mexican':     'México',
        'colombian':   'Colombia',
        'peruvian':    'Perú',
        'brazilian':   'Brasil',
        'argentinian': 'Argentina',
        'venezuelan':  'Venezuela',
        'cuban':       'Cuba',
        'spanish':     'España',
        'portuguese':  'Portugal',
        # Cuisines using Latin alphabet without script differentiation:
        # italian, french, greek, polish, german, etc. fall back to ''
    }
    return S.get(key, '')


def _is_rtl_script(key):
    """Whether the native script for this cuisine renders right-to-left
    (Arabic-derived scripts). Affects text-anchor / positioning of the
    ornament inside the graphic card."""
    return key in {'uyghur', 'kurdish', 'pakistani', 'persian', 'iranian',
                   'arab', 'lebanese', 'syrian', 'middle_east'}


def _build_cuisine_graphic_html(entry, *, size='hero'):
    """Renders the typographic graphic that replaces Google photos site-
    wide. Cuisine-colored gradient block + native-script ornament +
    typography. Three sizes:

      'hero'   — big featured display (per-listing hero, OG card)
                 ~640×360, full serif name, dishes preview line
      'card'   — medium card (nearby-restaurants grid, hero strip)
                 ~220×165, medium serif name, cuisine + district
      'thumb'  — small row thumb (homepage feed, cuisine/district pages)
                 ~96×96 or 160×160 square, short name only

    All three share the same visual DNA so the brand reads as one
    system at every zoom level."""
    name = entry.get('operatingName') or ''
    cuisine_key = (entry.get('cuisine') or '').lower()
    cuisine_label = CUISINE_LABEL.get(cuisine_key, cuisine_key.replace('_', ' ').title())
    district = entry.get('district') or ''
    color = _flag_color(cuisine_key) or '#7a746a'
    script = _native_script(cuisine_key)
    rtl = _is_rtl_script(cuisine_key)

    # Truncate name for small surfaces
    if size == 'thumb' and len(name) > 22:
        name_disp = name[:20] + '…'
    elif size == 'card' and len(name) > 28:
        name_disp = name[:26] + '…'
    else:
        name_disp = name

    # Script positioning: anchored to opposite corner per LTR/RTL
    script_class = 'cg-script' + (' cg-script-rtl' if rtl else '')

    if size == 'hero':
        return (
            f'<div class="cg cg-hero" style="--cg-color:{color}">'
            f'  <span class="{script_class}">{_esc(script)}</span>'
            f'  <div class="cg-eyebrow">{_esc(cuisine_label.upper())}</div>'
            f'  <div class="cg-name">{_esc(name_disp)}</div>'
            f'  {f"<div class=\"cg-district\">{_esc(district)}</div>" if district else ""}'
            f'</div>'
        )
    if size == 'card':
        return (
            f'<div class="cg cg-card" style="--cg-color:{color}">'
            f'  <span class="{script_class}">{_esc(script)}</span>'
            f'  <div class="cg-name">{_esc(name_disp)}</div>'
            f'</div>'
        )
    # thumb
    return (
        f'<div class="cg cg-thumb" style="--cg-color:{color}">'
        f'  <span class="{script_class}">{_esc(script)}</span>'
        f'  <div class="cg-name">{_esc(name_disp)}</div>'
        f'</div>'
    )


def _flag_color(key):
    F = {
        'italian':    '#009246',   # bright green
        'mexican':    '#c41e3a',   # chili red (differentiate from Italian green)
        'japanese':   '#bc002d',   # darker red (vs Chinese bright red)
        'chinese':    '#de2910',   # vivid red
        'korean':     '#003478',   # blue (differentiate from East Asian reds)
        'vietnamese': '#da251d',   # red
        'thai':       '#241d4f',   # navy blue (differentiate)
        'indian':     '#ff9933',   # saffron
        'french':     '#002395',   # blue
        'greek':      '#0d5eaf',   # blue
        'german':     '#1a1a1a',   # near-black
        'polish':     '#dc143c',
        'spanish':    '#aa151b',
        'portuguese': '#006600',   # darker green (differentiate from Italian)
        'russian':    '#0033a0',
        'turkish':    '#e30a17',
        'lebanese':   '#ed1c24',
        'pakistani':  '#01411c',   # deep green
        'bangladeshi':'#006a4e',
        'persian':    '#da0000',
        'iranian':    '#da0000',
        'ethiopian':  '#fcdd09',   # yellow
        'eritrean':   '#ea0437',
        'filipino':   '#0038a8',   # blue
        'ghanaian':   '#fcd116',   # yellow
        'nigerian':   '#008751',
        'jamaican':   '#009b3a',   # green
        'trinidadian':'#ce1126',
        'guyanese':   '#009e49',
        'colombian':  '#fcd116',   # yellow
        'venezuelan': '#00247d',   # blue (differentiate from Colombian yellow)
        'peruvian':   '#d91023',
        'argentinian':'#74acdf',   # light blue
        'brazilian':  '#009c3b',
        'afghan':     '#d32011',
        'somali':     '#4189dd',
        'indonesian': '#ce1126',
        'sri_lankan': '#8d153a',   # maroon
        'tamil':      '#ce1126',
        'arab':       '#007a3d',
        'middle_east':'#007a3d',
        'caribbean':  '#009b3a',
        'latin':      '#fcd116',
        'south_asian':'#ff9933',
        'jewish_deli':'#0038b8',   # blue
        'ukrainian':  '#005bbb',
    }
    return F.get(key) or PALETTE_HEX.get(key) or cuisine_color(key)


# Country-flag SVGs for the most common cuisines. Used as a subdued
# (50% opacity) visual identifier next to cuisine names in the hero
# VS card. Simplified geometric flags (no chakras/crests/coats of arms)
# - just the recognizable color blocks. Returns '' for cuisines without
# a known flag mapping (graceful fallback - no flag rendered).

# ---------------------------------------------------------------------------
# Static-feed + JSON-LD builders (shared between homepage and per-cuisine pages).
# ---------------------------------------------------------------------------
def _short_street(addr):
    """Extract just the street portion of a full Places-formatted address.
    Examples:
      '1154 St Clair Ave W Unit B, York, ON M6N 1A3, Canada' -> '1154 St Clair Ave W'
      '3776 Bathurst St, North York, ON M3H 3M6, Canada'      -> '3776 Bathurst St'
      '84 OAKDALE RD'                                          -> '84 Oakdale Rd'
    Strips: city + province + postal + country tail, unit/suite suffixes."""
    if not addr: return ''
    import re as _r
    s = addr.strip()
    # Drop the ", City, ON XYZ ABC, Country" tail
    s = _r.sub(
        r',\s*(?:Old\s+|North\s+|East\s+|West\s+)?[A-Z][a-zA-Z\s]+,\s*ON\s+[A-Z]\d[A-Z]\s+\d[A-Z]\d.*$',
        '', s, flags=_r.IGNORECASE)
    # Drop trailing "Unit X" / "# X" / suite numbers
    s = _r.sub(r'\s+(?:Unit|Ste|Suite|#)\s*[\w\-]+\s*$', '', s, flags=_r.IGNORECASE)
    s = _r.sub(r'\s*,\s*#\s*[\w\-]+\s*$', '', s)
    s = s.rstrip(',').strip()
    # Title-case if the whole string is ALL CAPS (from City raw licence
    # data). str.title() correctly handles "ST CLAIR AVE W" -> "St Clair
    # Ave W" without lowercasing the directional/abbreviation tokens.
    if s.isupper():
        s = s.title()
    return s


def _build_listing_title(name, primary_lbl, addr, district, entry):
    """Build the per-listing <title>. Goal: rank for address-style queries
    ('3776 bathurst street'), neighborhood queries ('italian restaurant st
    clair'), AND the restaurant name. Hard cap at 70 chars - over that,
    Google truncates with an ellipsis and Bing flags it as too long.

    Priority order (most droppable last):
      1. NAME · NowServingTO    (always present; brand needed for click-through)
      2. + " - <street>"        (address-style query value)
      3. + " - <qual>, <street>" (qualifier inserts between name and street)
    """
    BRAND = ' · NowServingTO'
    MAX = 70
    street = _short_street(addr)
    # Menu-dish qualifier (more keyword-distinct than cuisine label). Falls
    # back to cuisine, then to nothing.
    cache_key_val = entry.get('_cacheKey', '')
    mh = MENU_HIGHLIGHTS_CACHE.get(cache_key_val) or {}
    dishes = mh.get('dishes') if mh.get('status') == 'ok' else None
    qualifier = ''
    if dishes and len(dishes) >= 2:
        candidate = f"{dishes[0]} & {dishes[1]}"
        qualifier = candidate if len(candidate) <= 28 else dishes[0]
    if not qualifier:
        qualifier = primary_lbl or ''

    # Progressive build: take the longest candidate that still fits in MAX.
    base = f"{name}{BRAND}"
    # Drop redundant qualifier when the name already contains the cuisine
    # word (e.g. "LAYALI MEDITERRANEAN CUISINE" + "Middle Eastern" is noise).
    if qualifier and qualifier.lower().split()[0] in name.lower():
        qualifier = ''

    candidates = [
        f"{name} - {qualifier}, {street}{BRAND}" if qualifier and street else None,
        f"{name} - {street}{BRAND}" if street else None,
        f"{name} - {qualifier}{BRAND}" if qualifier else None,
        base,
    ]
    for c in candidates:
        if c and len(c) <= MAX:
            return c
    return base


def _build_listing_lede(entry, all_entries):
    """Compose the prose lede block shown directly under the H1 on a
    /r/<slug> page. Three facts, dot-separated, that Maps + Instagram
    can't show:

       Opened {N} days ago · {ordinal} of {total} {Cuisine} restaurants
       licensed in {District} in the past 30 days · {dish, dish, dish}

    Every fact is dynamic - `days_open` is recomputed at every cron run,
    the cohort window is a rolling 30 days, and the dish list is pulled
    from MENU_HIGHLIGHTS_CACHE. So the rendered HTML stays fresh as
    long as inject_openings.py runs daily.

    Returns '' if no facts are available."""
    parts = []
    days = entry.get('daysOpen')
    if isinstance(days, int):
        parts.append(_ago_long(days))

    cuisines = entry.get('cuisines') or (
        [entry['cuisine']] if entry.get('cuisine') else [])
    primary = cuisines[0] if cuisines else None
    district = entry.get('district')
    if primary and district and isinstance(days, int) and days <= 30:
        # Cohort = same primary cuisine + same district, opened in last 30d.
        # Rank chronologically with oldest = 1, newest = N.
        cohort = [
            e for e in all_entries
            if isinstance(e.get('daysOpen'), int) and e['daysOpen'] <= 30
            and e.get('district') == district
            and ((e.get('cuisines') or [e.get('cuisine')])[0] == primary)
        ]
        if len(cohort) >= 2:
            cohort_sorted = sorted(cohort, key=lambda e: e.get('daysOpen', 0),
                                   reverse=True)
            rank = next((i for i, e in enumerate(cohort_sorted, 1)
                         if e.get('slug') == entry.get('slug')), None)
            if rank:
                label = CUISINE_LABEL.get(primary, primary)
                parts.append(
                    f'{_ordinal(rank)} of {len(cohort)} {label} restaurants '
                    f'registered in {district} in the past 30 days'
                )

    # Menu-dish highlights are the third differentiator. Same source as the
    # title builder uses for SEO-distinct qualifiers. Up to 3 dishes so the
    # lede stays a single readable line.
    cache_key_val = entry.get('_cacheKey', '')
    mh = MENU_HIGHLIGHTS_CACHE.get(cache_key_val) or {}
    dishes = mh.get('dishes') if mh.get('status') == 'ok' else None
    if dishes:
        parts.append(', '.join(dishes[:3]))

    return ' · '.join(parts)


def _build_listing_meta_desc(entry, primary_lbl, name, desc_addr, fallback):
    """Compose a per-listing <meta description> tuned for SERP CTR.

    Google SERP shows ~155 chars of meta description; the current
    boilerplate ("Part of NowServingTO's daily-updated directory ...")
    is identical across 400+ pages and gets ~0% CTR at position 9-13.
    The verifier evidence + menu-highlights caches already contain
    dish-level, restaurant-specific prose - swap that in.

    Priority order:
      1. menu_highlights dishes (verbatim, ≥2 dishes) - "{cuisine} at
         {addr}. Menu: X, Y, Z. From the City of Toronto's licence
         registry."
      2. validator_evidence (Haiku-written, dish-rich) - strip
         identity-verification preamble that just restates the name,
         drop negative caveats about template websites / aggregators,
         truncate at the last clause boundary that fits ~155 chars.
      3. Fall back to the boilerplate.
    """
    cache_key = entry.get('_cacheKey', '')
    short_addr = desc_addr
    # Drop ", Toronto, ON M\d\w \d\w\d" postal tail so the desc has room
    # for differentiating content instead of postal codes.
    import re as _re_meta
    short_addr = _re_meta.sub(
        r',\s*(?:Old\s+|North\s+|East\s+|West\s+)?[A-Z][a-zA-Z\s]+,\s*ON\s+[A-Z]\d[A-Z]\s+\d[A-Z]\d.*$',
        '', short_addr).strip().rstrip(',')

    # 1) Menu highlights (cleanest signal)
    mh = MENU_HIGHLIGHTS_CACHE.get(cache_key) or {}
    dishes = mh.get('dishes') if mh.get('status') == 'ok' else None
    if dishes and len(dishes) >= 2:
        d_str = ', '.join(dishes[:4])
        desc = f"New {primary_lbl} restaurant at {short_addr}. Menu: {d_str}. From the City of Toronto's licence registry."
        if len(desc) <= 158:
            return desc
        # Too long - try with fewer dishes
        d_str = ', '.join(dishes[:3])
        desc = f"New {primary_lbl} restaurant at {short_addr}. Menu: {d_str}."
        if len(desc) <= 158:
            return desc

    # 2a) Editorial blurb from evidence_rewrite_cache (preferred - reads
    # like prose, no verification-log phrasing). Trim to fit Google's
    # ~155 char SERP budget.
    er = EVIDENCE_REWRITE_CACHE.get(cache_key) or {}
    if er.get('status') == 'ok' and er.get('blurb'):
        b = er['blurb'].strip()
        # Capitalize first letter - LLM blurbs come back lowercase, which
        # reads as unprofessional in SERPs and pushes Google toward picking
        # body text (and appending its own "...Read more" UI affordance)
        # over our meta. Also strip em/en-dashes the LLM bakes in.
        b = _re_meta.sub(r'\s*[—–]\s*', ', ', b)
        # "opened" - overstatement; we only know registration date. Keep body
        # and meta in sync so Google doesn't see inconsistent text and prefer
        # body excerpts (which then get truncated with "...Read more").
        b = _re_meta.sub(r'\bopened\b', 'registered', b, flags=_re_meta.I)
        b = b[:1].upper() + b[1:]
        if len(b) <= 158:
            return b
        # Trim at last sentence boundary that fits
        cut = b[:155]
        if '. ' in cut:
            cut = cut.rsplit('. ', 1)[0] + '.'
        if len(cut) >= 60:
            return cut

    # 2b) Fallback: validator evidence with verification-log clauses stripped
    wv = WEB_VERIFY_CACHE.get(cache_key) or {}
    ev = (wv.get('validator_evidence') or wv.get('evidence') or '').strip()
    if ev:
        # Strip leading identity-verification preamble. Haiku consistently
        # opens with "City licence and Places confirm <NAME> at <ADDR>;"
        # which adds nothing the title doesn't already say and burns the
        # ~155-char SERP budget. The food/menu signal almost always sits
        # in clause 2 onward.
        ev = _re_meta.sub(
            r'^(?:City\s+licence|Licence|Google\s+Places|Places)\b[^;,]*?'
            r'(?:confirm[s]?|match(?:es)?|verif(?:ies|ied))\b[^;]*?'
            r'(?:;\s*|,\s+(?=operational|reviews|menu|serves|offers))',
            '', ev, count=1, flags=_re_meta.IGNORECASE)
        # Split into semicolon-delimited clauses; treat each as a candidate.
        parts = [p.strip() for p in ev.split(';') if p.strip()]
        # Identify the "useful" clauses: ones that mention food / cuisine /
        # dishes / atmosphere, NOT ones about website templates or aggregator
        # rejection.
        FOOD_HINTS = ('dish', 'menu', 'review', 'food', 'cuisine', 'authentic',
                      'pizza', 'pho', 'sushi', 'taco', 'roti', 'kebab',
                      'biryani', 'curry', 'noodle', 'dumpling', 'shawarma',
                      'sandwich', 'soup', 'rice', 'meat', 'vegan', 'vegetarian',
                      'gelato', 'pastry', 'cake', 'bakery', 'cafe', 'specializ',
                      'serves', 'offers', 'family-run', 'street food',
                      'arancini', 'cannoli', 'biscotti', 'jollof', 'injera',
                      'tibs', 'kibbeh', 'samosa', 'banh mi', 'lechon',
                      'thali', 'tagine', 'falafel')
        NEG_HINTS = ('template', 'shell', 'aggregator', 'no menu', 'no usable',
                     'no live content', 'no website', 'no independent',
                     'insufficient', 'rejected', 'failed', 'unable to',
                     "couldn't", 'web verify url is', 'no content available',
                     'no longer', 'broken', '404', 'unreachable')
        useful = []
        for p in parts:
            plow = p.lower()
            if any(n in plow for n in NEG_HINTS): continue
            if any(f in plow for f in FOOD_HINTS): useful.append(p)
        # If no food-bearing clause survived, fall through to boilerplate -
        # giving Google bare identity text isn't worth the swap.
        if useful:
            desc = '. '.join(useful)
            if len(desc) > 158:
                # Trim at last clause boundary that fits
                cut = desc[:155]
                if '. ' in cut:
                    cut = cut.rsplit('. ', 1)[0] + '.'
                elif ', ' in cut[-30:]:
                    cut = cut.rsplit(', ', 1)[0]
                desc = cut.rstrip(',.;: ')
                if not desc.endswith('.'):
                    desc += '.'
            return desc

    return fallback


# Aggregator hostname denylist. Even when the validator approves a
# `best_website`, it sometimes mistakes an aggregator wrapper for the
# real site (Definitely Ours had `ritual.co/order/...` get through).
# Render-time filter: if the website URL's host matches this list,
# treat the entry as having no website and fall through to mapsUrl /
# coord-pin / internal. Keep parallel to the host list in the validator
# prompt (tools/llm_verify_batch.py) - both sources of truth.
_AGGREGATOR_HOSTS = frozenset({
    'ubereats.com', 'doordash.com', 'skipthedishes.com', 'grubhub.com',
    'foodora.com', 'foodora.ca', 'menulog.com', 'seamless.com',
    'chownow.com', 'toasttab.com', 'order.online', 'ritual.co',
    'yelp.com', 'yelp.ca', 'tripadvisor.com', 'tripadvisor.ca',
    'opentable.com', 'opentable.ca', 'resy.com',
    'dinesafe.to', 'blogto.com',
})


def _is_aggregator_url(url):
    """True if URL's host (or any parent domain) is in the aggregator
    denylist. Lowercased + stripped of port + leading 'www.'."""
    if not url: return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower().strip()
    except Exception:
        return False
    if not host: return False
    if host.startswith('www.'): host = host[4:]
    # Match exact or any parent-domain suffix
    parts = host.split('.')
    for i in range(len(parts) - 1):
        if '.'.join(parts[i:]) in _AGGREGATOR_HOSTS:
            return True
    return False


def _coord_pin_url(r):
    """Google Maps URL centered on the licence's geocoded address. Used as
    the second tier of the linking ladder when there's no Places CID match
    (`mapsUrl` is null) but we DO have lat/lng from the geocoder. Drops
    the user on a coord pin, not a name-search - honest about the fact
    that we haven't matched a specific Places business yet, but still
    gives them the map + Street View pegman at the actual address."""
    if r.get('lat') is not None and r.get('lng') is not None:
        return f"https://www.google.com/maps?q={r['lat']},{r['lng']}"
    return ''


def build_static_rows(entries, link_to_listing=False):
    """Pre-rendered HTML rows for the top-N feed. Same markup the JS renderer
    produces so visitors / crawlers see real content before JS hydrates.

    link_to_listing: when True, wrap the time-ago badge in an <a> pointing at
    /r/<slug>. The home, cuisine, and district pages set this so Googlebot has
    a plain-HTML edge into every /r/ detail page (the row's other links go to
    external website/Maps). /r/<slug> itself leaves it False to avoid a
    self-link in the single-entry feed."""
    out = []
    for i, r in enumerate(entries):
        cuisine_keys = r.get('cuisines') or ([r['cuisine']] if r.get('cuisine') else [])
        pills = ''.join(
            f'<a class="pill" href="/cuisine/{k}" style="background:{PALETTE_HEX.get(k) or cuisine_color(k)}" aria-label="See newest {_esc(CUISINE_LABEL.get(k, k))} restaurants">{_esc(CUISINE_LABEL.get(k, k))}</a>'
            for k in cuisine_keys
        )
        # Primary cuisine colour drives a thin left-edge accent strip on
        # each row (.open-row::before in the CSS). Adds a hint of colour
        # without painting the whole row - on a single-cuisine page every
        # strip matches; on the homepage feed a vertical rainbow column
        # telegraphs variety at a glance.
        primary_key = cuisine_keys[0] if cuisine_keys else None
        row_accent = (PALETTE_HEX.get(primary_key) or cuisine_color(primary_key)
                      if primary_key else None)
        accent_style = f' style="--row-accent: {row_accent}"' if row_accent else ''
        name = _esc(r['operatingName'])
        addr = _esc(r.get('address') or '')
        district = _esc(r.get('district') or '')
        # Address link ladder:
        #   1) Places CID (mapsUrl) - exact business profile match
        #   2) coord-pin (?q=lat,lng) - geocoded address, gives map + Street
        #      View pegman without falsely claiming "this IS the restaurant"
        #   3) plain text - no Places, no lat/lng (rare; <5% of no-Places)
        addr_url = r.get('mapsUrl') or _coord_pin_url(r) or ''
        # target=_blank on outbound links so visitors keep the NowServingTO
        # tab open to return to. Internal /r/<slug> stays same-tab. The
        # JS hydration on home/cuisine/district pages strips _blank for
        # mobile (per existing renderFeed logic) - this baseline matters
        # most on /r/ pages where we don't hydrate at all.
        ext_tgt = ' target="_blank" rel="noopener"' if addr_url and not addr_url.startswith('/r/') else ' rel="noopener"'
        addr_inner = f'<a href="{_esc(addr_url)}"{ext_tgt}>{addr}</a>' if addr_url and addr else addr
        addr_html = f'{addr_inner}<span class="oad-d"> · {district}</span>' if district else addr_inner
        ago = _esc(_tier_label(r['daysOpen'], r.get('issuedDate'), r.get('dateSource')))
        # Click-target precedence by intent:
        #   - Name click = "go to the business's own site" → website preferred
        #   - Photo click = "see more photos / business info" → Places card
        #     preferred (Maps has more photos + reviews + hours than a one-page
        #     restaurant website typically does)
        #   - Address click = "get directions" → Places card only (handled
        #     above; plain text when no Places match)
        # Internal /r/<slug> is the fallback when neither external URL exists.
        slug = r.get('slug') or ''
        internal_url = f'/r/{slug}' if slug else ''
        # Aggregator filter: a ritual.co / ubereats / doordash URL isn't a
        # restaurant's "own site" - fall through to mapsUrl / internal.
        site = r.get('website')
        if _is_aggregator_url(site): site = None
        link = site or r.get('mapsUrl') or internal_url
        name_ext_tgt = ' target="_blank" rel="noopener"' if link and not link.startswith('/r/') else ' rel="noopener"'
        # Diagonal-arrow indicator (↗) only when the name link goes to the
        # restaurant's OWN website - not Maps fallback, not internal /r/ page.
        # Tells the visitor "this opens the actual restaurant's site, not
        # another listing or Maps result." Same convention as the .lx-near-cta
        # rows below.
        ext_arrow = '<span class="ext-arrow" aria-hidden="true">↗</span>' if link and link == site else ''
        name_html = f'<a href="{_esc(link)}"{name_ext_tgt}>{name}{ext_arrow}</a>' if link else name
        multi_attr = ' data-multi' if len(cuisine_keys) > 1 else ''
        thumb = r.get('thumb')
        # Thumb-click ladder mirrors the address ladder, with website as
        # a deeper fallback before the internal /r/ page. Coord-pin sits
        # between Places and website because for entries where the thumb
        # IS a Street View image (the photogenic fallback for no-Places
        # entries), the coord-pin lands the user at the exact same view.
        thumb_target = r.get('mapsUrl') or _coord_pin_url(r) or r.get('website') or internal_url
        thumb_ext_tgt = ' target="_blank" rel="noopener"' if thumb_target and not thumb_target.startswith('/r/') else ' rel="noopener"'
        # First row is the LCP candidate above the fold - eager-load it
        # with high priority so Lighthouse / real users get a fast LCP.
        # Subsequent rows stay lazy to keep total image weight low.
        load_attrs = 'loading="eager" fetchpriority="high"' if i == 0 else 'loading="lazy"'
        # alt text: restaurant name. Strictly speaking the image is decorative
        # (the name is right next to it in the row), and W3C accessibility
        # guidance prefers alt="" in that case. But SEO audit tools flag
        # empties and AI crawlers ingest alt as an entity-image binding,
        # so we populate it with the name. The parent anchor's aria-label
        # ("View <name>") still carries the screen-reader hint.
        alt_text = _esc(r["operatingName"])
        # No image slot — graphics were redundant with the restaurant
        # name shown immediately next to them. Row carries cuisine
        # identity via the cuisine-color pill on the right side; the
        # image area is collapsed entirely. CSS handles the layout
        # change (.open-row without .has-pic class).
        thumb_html = ''
        slug_attr = f' data-slug="{_esc(slug)}"' if slug else ''
        # Tier attribute drives the pill styling (CSS reads data-fresh).
        # 0-30d gets the ★ accent treatment; 31-90d gets a quieter recent
        # tag; 91-365d carries no badge and no data-fresh attribute.
        _d = r.get('daysOpen')
        fresh_attr = ''
        if isinstance(_d, int):
            if _d <= 30:    fresh_attr = ' data-fresh="hot"'
            elif _d <= 90:  fresh_attr = ' data-fresh="recent"'
            elif _d <= 365: fresh_attr = ' data-fresh="aged"'
        ago_html = ((f'<a class="ago" href="/r/{_esc(slug)}">{ago}</a>'
                     if link_to_listing and slug
                     else f'<span class="ago">{ago}</span>')
                    if ago else '')
        out.append(
            f'<div class="open-row"{slug_attr}{fresh_attr}{multi_attr}{accent_style}>'
            f'<div class="od">{ago_html}</div>'
            f'<div class="on">{name_html}<span class="oad">{addr_html}</span></div>'
            f'<div class="oc">{pills}</div>'
            f'</div>'
        )
    return '\n    '.join(out)


def build_ld_itemlist(entries, name, description):
    items = []
    for i, r in enumerate(entries, 1):
        rest = {
            '@type': 'Restaurant',
            'name': r['operatingName'],
            'address': {'@type': 'PostalAddress', 'streetAddress': r.get('address') or '', 'addressLocality': 'Toronto', 'addressRegion': 'ON', 'addressCountry': 'CA'},
            'servesCuisine': [CUISINE_LABEL.get(k, k) for k in (r.get('cuisines') or [r.get('cuisine')]) if k],
            'foundingDate': r.get('issuedDate'),
        }
        if r.get('website'): rest['url'] = r['website']
        if r.get('rating'): rest['aggregateRating'] = {'@type': 'AggregateRating', 'ratingValue': r['rating'], 'reviewCount': r.get('reviewCount') or 1}
        items.append({'@type': 'ListItem', 'position': i, 'item': rest})
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': name,
        'description': description,
        'itemListElement': items,
    }


def build_ld_collectionpage(itemlist, *, url, dateModified, about=None):
    """Wrap an ItemList in CollectionPage so it carries url + dateModified
    (ItemList itself has no dateModified property). Boosts the freshness
    signal Google reads - the whole point of the daily refresh.

    about: optional Thing dict (e.g. cuisine entity with Wikidata sameAs)
    that anchors the page to a known entity. Helps AI crawlers
    disambiguate "Ethiopian" the page topic from "Ethiopian" the name."""
    page = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'url': url,
        'name': itemlist['name'],
        'description': itemlist['description'],
        'inLanguage': 'en-CA',
        'dateModified': dateModified,
        'isPartOf': {'@type': 'WebSite', 'name': 'NowServingTO',
                     'url': 'https://nowservingto.com/'},
        'mainEntity': {k: v for k, v in itemlist.items() if k != '@context'},
    }
    if about:
        page['about'] = about
    return page


# Wikidata QID lookup for cuisines. Generated by
# tools/fetch_cuisine_wikidata.py; re-run when CUISINE_LABEL gains a key.
try:
    _CUISINE_WIKIDATA = json.loads(
        (Path(__file__).resolve().parent / 'data' / 'cuisine_wikidata.json').read_text())
except Exception:
    _CUISINE_WIKIDATA = {}


def cuisine_about_thing(cuisine_key, label):
    """Return a schema.org Thing for a cuisine, with Wikidata sameAs when
    available. Used as the `about` of the cuisine landing CollectionPage."""
    thing = {'@type': 'Thing', 'name': f'{label} cuisine'}
    wd = _CUISINE_WIKIDATA.get(cuisine_key)
    if wd and wd.get('wikidata_url'):
        thing['sameAs'] = wd['wikidata_url']
    return thing


def build_ld_breadcrumb(parts):
    """parts: list of (name, url) tuples in trail order. Returns a
    schema.org BreadcrumbList - drives the breadcrumb display Google
    sometimes substitutes for the URL in SERP results, generally lifting CTR."""
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': i, 'name': name, 'item': url}
            for i, (name, url) in enumerate(parts, 1)
        ],
    }


def build_ld_faq(qa_pairs):
    """qa_pairs: list of (question, answer) tuples. Returns FAQPage schema.
    Google has tightened FAQ rich-result eligibility (mostly gov/health now)
    but the structured data still helps the page rank for the underlying
    'how' / 'what' / 'where' query family."""
    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [
            {'@type': 'Question', 'name': q,
             'acceptedAnswer': {'@type': 'Answer', 'text': a}}
            for q, a in qa_pairs
        ],
    }


# slugify: "East Toronto" → "east-toronto" (also used by district page
# generator below; defined here so the xaxis strip on cuisine pages can
# build /district/<slug> links).
def _district_slug(label):
    return _re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')


def build_breadcrumb_html(parts):
    """Visible breadcrumb HTML matching the BreadcrumbList JSON-LD. parts:
    list of (name, url-or-None); the last entry has url=None (current page,
    rendered as text with aria-current)."""
    items = []
    for name, url in parts:
        if url:
            items.append(f'<a href="{_esc(url)}">{_esc(name)}</a>')
        else:
            items.append(f'<span aria-current="page">{_esc(name)}</span>')
    return ('<nav class="breadcrumb" aria-label="Breadcrumb">'
            + '<span class="sep">›</span>'.join(items)
            + '</nav>')


import re

def inject_into_html(html, *, static_block, ld_payloads, breadcrumb_html='',
                     page_intro_html='', related_html='', lcp_preload_url='',
                     listing_extra_html=''):
    """Replace STATIC-FEED, LD-ITEMLIST, BREADCRUMB, PAGE-INTRO,
    RELATED-CUISINES, LCP-PRELOAD, and LISTING-EXTRA marker blocks.

    `ld_payloads` is a list of schema.org dicts (ItemList / CollectionPage /
    BreadcrumbList / FAQPage). Each is emitted as its own <script> tag -
    Google parses them all independently and never penalizes multiple
    JSON-LD blocks on a page.

    Empty page_intro_html / related_html collapses the markers cleanly
    (used on the homepage where the editorial blocks don't apply).

    Lambda replacements keep backslash sequences in the replacement (e.g.
    \\uXXXX in JSON-LD) from being interpreted as regex backreferences.
    """
    html = re.sub(
        r'(<!-- STATIC-FEED-START[^>]*-->).*?(<!-- STATIC-FEED-END -->)',
        lambda m: m.group(1) + '\n    ' + static_block + '\n    ' + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    scripts = []
    for i, p in enumerate(ld_payloads):
        ld_json_str = json.dumps(p, separators=(',', ':'))
        sid = ' id="ld-itemlist"' if i == 0 else ''
        scripts.append(f'<script type="application/ld+json"{sid}>{ld_json_str}</script>')
    html = re.sub(
        r'(<!-- LD-ITEMLIST-START -->).*?(<!-- LD-ITEMLIST-END -->)',
        lambda m: m.group(1) + '\n' + '\n'.join(scripts) + '\n' + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    html = re.sub(
        r'(<!-- BREADCRUMB-START -->).*?(<!-- BREADCRUMB-END -->)',
        lambda m: m.group(1) + breadcrumb_html + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    html = re.sub(
        r'(<!-- PAGE-INTRO-START -->).*?(<!-- PAGE-INTRO-END -->)',
        lambda m: m.group(1) + page_intro_html + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    html = re.sub(
        r'(<!-- RELATED-CUISINES-START -->).*?(<!-- RELATED-CUISINES-END -->)',
        lambda m: m.group(1) + related_html + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    # LCP preload: tells the browser to fetch the above-the-fold first
    # row image before it parses past the <head>. Combined with
    # fetchpriority="high" on the actual <img>, this is the biggest
    # lever for LCP on the static-feed pages.
    preload_tag = (
        f'<link rel="preload" as="image" href="{_esc(lcp_preload_url)}" fetchpriority="high">'
        if lcp_preload_url else ''
    )
    html = re.sub(
        r'(<!-- LCP-PRELOAD-START -->).*?(<!-- LCP-PRELOAD-END -->)',
        lambda m: m.group(1) + preload_tag + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    html = re.sub(
        r'(<!-- LISTING-EXTRA-START -->).*?(<!-- LISTING-EXTRA-END -->)',
        lambda m: m.group(1) + listing_extra_html + m.group(2),
        html, count=1, flags=re.DOTALL,
    )
    return html


def build_alert_section(kind, value, label):
    """Email signup section. Drops into the newsletter-cta slot on every
    page; cuisine/district pages get a per-axis instant-alert form,
    listing + home pages get the weekly all-Toronto digest form.

    kind:  'cuisine', 'district', or 'digest_all'
    value: the URL key - cuisine key, district slug, or 'toronto' for
           digest_all. Stored by alerts_server so dispatch can route.
    label: human display label - surfaces in pitch copy.

    Submit handler lives in index.html (a single block scoped to
    `form.alert-form`); we only emit the form markup.
    """
    if kind == 'cuisine':
        title = f"Get an email when a new {label} restaurant opens"
        blurb = (f"You'll get one email the moment a new {label} restaurant "
                 f"is registered with the City of Toronto - typically a handful of times "
                 f"per year. No weekly digest, no spam, one-click unsub.")
    elif kind == 'digest_all':
        title = "The week's newest Toronto restaurants, in your inbox"
        blurb = ("Every Sunday, the top 5 restaurants newly registered with the City "
                 "of Toronto over the past 7 days. One email a week, never more. "
                 "One-click unsub.")
    else:
        title = f"Get an email when a new restaurant opens in {label}"
        blurb = (f"You'll get one email the moment a new restaurant is "
                 f"registered with the City in {label}. No weekly digest, no spam, "
                 f"one-click unsub.")
    # IDs on the title / blurb let the in-page JS morph copy when the
    # user filters by the cross-axis - so on /cuisine/argentinian, picking
    # Scarborough flips the form to an "Argentine in Scarborough"
    # intersection signup without reloading the page.
    return (
        '<section class="newsletter-cta" aria-label="Email alert signup">'
        '<div class="nl-pitch">'
        f'<h2 id="alert-title">{_esc(title)}</h2>'
        f'<p id="alert-blurb">{_esc(blurb)}</p>'
        '</div>'
        f'<form class="alert-form" data-kind="{_esc(kind)}" '
        f'data-value="{_esc(value)}" data-label="{_esc(label)}" '
        f'data-base-kind="{_esc(kind)}" data-base-value="{_esc(value)}" '
        f'data-base-label="{_esc(label)}" novalidate>'
        '<input type="email" required autocomplete="email" '
        'placeholder="you@example.com" aria-label="Email address">'
        '<button type="submit">Subscribe</button>'
        '<div class="alert-status" role="status" aria-live="polite"></div>'
        '<div class="alert-hp" aria-hidden="true">'
        '<label>Website (leave blank): <input type="text" name="website" '
        'tabindex="-1" autocomplete="off"></label></div>'
        '</form>'
        '</section>'
    )


def swap_newsletter_cta(html, section_html):
    """Replace the homepage's default `<section class="newsletter-cta">`
    block with a targeted alert section (per-cuisine, per-district, or
    digest_all). The lambda keeps backslashes in `section_html` from
    being interpreted as regex backrefs."""
    return re.sub(
        r'<section class="newsletter-cta"[^>]*>.*?</section>',
        lambda m: section_html,
        html, count=1, flags=re.DOTALL,
    )


# ---------------------------------------------------------------------------
# Inject into the HOMEPAGE (index.html).
# ---------------------------------------------------------------------------
top_for_static = all_recent[:30]
static_block = build_static_rows(top_for_static, link_to_listing=True)
home_url = 'https://nowservingto.com/'


home_itemlist = build_ld_itemlist(
    top_for_static,
    name="Toronto's newest registered restaurants by cuisine",
    description='Restaurants newly registered with the City of Toronto in the past 365 days, classified by cuisine. Updated daily from City of Toronto Open Data.',
)
home_collection = build_ld_collectionpage(
    home_itemlist, url=home_url, dateModified=REFERENCE_DATE.isoformat(),
)
try:
    home_html = open(INDEX_PATH).read()
    # Homepage gets no breadcrumb (it IS the root) - just the CollectionPage
    # wrapper to carry dateModified + url; no extra BreadcrumbList script.
    home_lcp_thumb = (top_for_static[0].get('thumb') if top_for_static else '') or ''
    home_html = inject_into_html(home_html,
        static_block=static_block, ld_payloads=[home_collection], breadcrumb_html='',
        lcp_preload_url=home_lcp_thumb)

    # Freshness razzmatazz: dynamic title + description + masthead subtitle
    # all carry today's date and the live count. Re-baked every cron, so
    # the SERP snippet, the visible H1, and Google's cached version all
    # converge on "this site was updated today" - both a Google freshness
    # signal AND a visitor credibility signal.
    home_updated_str = REFERENCE_DATE.strftime('%b %-d, %Y')
    # Title cap: target ≤60 chars so Google doesn't truncate it in SERPs.
    # Updated-date moved to the meta description + h1; the brand stays in
    # title since SERP click-through prefers brand recognition.
    home_title = "Toronto's Newest, Freshest, Independent Restaurants · NowServingTO"
    # Description cap: target ≤160 chars. Stacks the freshness adjectives
    # to match the masthead vibe; "Updated daily" implies recency without
    # the noise of a specific date that anchors expectations.
    home_desc = ("Toronto's newest, freshest, independent restaurants, by cuisine and district. "
                 "Updated daily from City of Toronto open data.")
    home_html = re.sub(r'<title>[^<]*</title>',
                       f'<title>{_esc(home_title)}</title>',
                       home_html, count=1)
    for sel in [
        r'(<meta name="description" content=")[^"]*(")',
        r'(<meta property="og:description" content=")[^"]*(")',
        r'(<meta name="twitter:description" content=")[^"]*(")',
    ]:
        home_html = re.sub(sel,
            lambda m: m.group(1) + _esc(home_desc) + m.group(2),
            home_html, count=1)
    for sel in [
        r'(<meta property="og:title" content=")[^"]*(")',
        r'(<meta name="twitter:title" content=")[^"]*(")',
    ]:
        home_html = re.sub(sel,
            lambda m: m.group(1) + _esc(home_title) + m.group(2),
            home_html, count=1)
    # Visible masthead subtitle. "Newest, freshest, independent" - all three
    # are defensible: newest = licence date, freshest = within 365d window,
    # independent = chain denylist + validator's chain check. "registered
    # restaurants" anchors them in the actual data source (City registration,
    # not editorial curation). The hl span keeps the adjective trio in
    # accent red; "registered" sits outside it in regular ink so the
    # qualifier doesn't fight the energy.
    masthead_sub = ('Tracking Toronto\'s <span class="hl">newest, independent, registered</span> '
                    'restaurants')
    home_html = re.sub(
        r'<h1 class="sub">[\s\S]*?</h1>',
        f'<h1 class="sub">{masthead_sub}</h1>',
        home_html, count=1,
    )

    open(INDEX_PATH, 'w').write(home_html)
    print(f"  pre-rendered {len(top_for_static)} static feed rows + JSON-LD ItemList into index.html")
except Exception as e:
    print(f"  WARN: index.html injection failed: {e}")


def build_page_intro(cuisine_key):
    """Render the editorial intro paragraph for a cuisine landing page.
    Returns '' (markers collapse to nothing) when no intro is on file.

    Appends a "Read the editorial brief →" link when a matching
    /wire/<key>.html exists. Without this link the wire pages were
    orphaned from the internal link graph - Googlebot never visited
    any of the 28 wire pages in 30 days because no /cuisine/* page
    referenced them (caught via Apache log audit 2026-05-29)."""
    rec = _CUISINE_INTROS.get(cuisine_key) or {}
    intro = (rec.get('intro') or '').strip()
    from pathlib import Path as _PathLib
    has_wire = (_PathLib(ROOT) / 'wire' / f'{cuisine_key}.html').exists()
    if not intro and not has_wire: return ''
    # Wire link rides INLINE at the end of the intro paragraph so the
    # editorial reads as one continuous thought, not two stacked blocks.
    # Falls back to a standalone block when there's no intro text to
    # ride on (cuisine with a wire page but no intro entry yet).
    wire_inline = (
        f' <a class="page-intro-wire" href="/wire/{cuisine_key}">Read the editorial brief →</a>'
        if has_wire else ''
    )
    if intro:
        return f'<div class="page-intro"><p>{_esc(intro)}{wire_inline}</p></div>'
    # No intro - render wire link as its own paragraph so the marker
    # block doesn't render empty.
    return (
        f'<div class="page-intro"><p class="page-intro-wire">'
        f'<a href="/wire/{cuisine_key}">Read the editorial brief →</a>'
        f'</p></div>'
    )


def build_related_cuisines(cuisine_key):
    """Three sibling-cuisine links at the bottom of a cuisine page. Pulls from
    cuisine_intros.json's 'related' list - filters out any related key that
    doesn't have a label (i.e. isn't in the canonical taxonomy) so dead links
    can't slip in. Returns '' when no related set is on file."""
    rec = _CUISINE_INTROS.get(cuisine_key) or {}
    related = [k for k in (rec.get('related') or []) if k in CUISINE_LABEL]
    if not related: return ''
    links = ', '.join(
        f'<a href="/cuisine/{k}">{_esc(CUISINE_LABEL[k])}</a>'
        for k in related[:3]
    )
    return f'<nav class="related-cuisines" aria-label="Related cuisines"><span class="rc-label">Also try</span>{links}</nav>'


def build_community_partners(cuisine_key):
    """Reciprocal outbound links to community directories that list our
    cuisine page back. Pulls from cuisine_intros.json's 'community_partners'
    list. Empty / missing = nothing rendered (most cuisines won't have
    partners yet; populated as outreach in data/community_submissions.md
    converts).

    Schema per partner:
      {"name": "Tamilar.ca", "url": "https://tamilar.ca/",
       "blurb": "Tamil business directory, GTA"}

    Render rationale:
      - Tight footer block with rel="noopener" + target="_blank" so visitors
        don't lose the cuisine page on a side-trip.
      - No rel="nofollow": these ARE editorial endorsements of partners
        who reciprocate; nofollow would burn the relational equity.
      - One short sentence per link so the section reads as a helpful
        "community resources" cite, not a link farm. Cap at 4 partners to
        keep it that way.
    """
    rec = _CUISINE_INTROS.get(cuisine_key) or {}
    partners = rec.get('community_partners') or []
    if not partners: return ''
    label = CUISINE_LABEL.get(cuisine_key, cuisine_key)
    items = []
    for p in partners[:4]:
        name = p.get('name') or ''
        url = p.get('url') or ''
        blurb = p.get('blurb') or ''
        if not (name and url): continue
        items.append(
            f'<li class="cp-item">'
            f'<a class="cp-link" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(name)}</a>'
            f'{(" - " + _esc(blurb)) if blurb else ""}'
            f'</li>'
        )
    if not items: return ''
    return (
        f'<aside class="community-partners" aria-label="{_esc(label)}-Canadian community resources">'
        f'<h3 class="cp-heading">{_esc(label)}-Canadian community resources</h3>'
        f'<ul class="cp-list">{"".join(items)}</ul>'
        f'</aside>'
    )


# ---------------------------------------------------------------------------
# Inject PER-CUISINE landing pages at cuisine/<key>.html.
# ---------------------------------------------------------------------------
# Each cuisine gets its own HTML file with:
#   - title / og:title / twitter:title baked in (server-rendered, so first-pass
#     crawls see cuisine-specific signal instead of the generic home title)
#   - meta description scoped to the cuisine + count
#   - canonical pointing at the /cuisine/<key> route
#   - <h1> inserted after the brand line with "New <Cuisine> restaurants in Toronto"
#   - STATIC-FEED block rendered from THIS cuisine's top-30 (not the mixed feed)
#   - JSON-LD ItemList scoped to this cuisine
# Apache .htaccess rewrites /cuisine/<key> → /cuisine/<key>.html when the file
# exists (added in this same commit).
CUISINE_DIR = Path(ROOT) / 'cuisine'
CUISINE_DIR.mkdir(exist_ok=True)
cuisine_pages_written = 0
template = open(INDEX_PATH).read()   # post-homepage-inject - has the fresh JS bundle
for c in cuisines_out:
    key = c['key']; label = c['label']; n365 = c['count365d']; n30 = c['count30d']
    all_for_cuisine = opens_365_by_cuisine.get(key, [])
    entries = all_for_cuisine[:30]   # top 30 power the chronological feed + ItemList
    if not entries: continue

    # Title carries the live count + year for freshness/authority signal
    # in SERP - "Toronto's 40 Newest Italian Restaurants (2026)" reads as
    # a definite, dated list, which converts ~5x better than the generic
    # "New Italian restaurants in Toronto" we shipped earlier (GSC data
    # showed /cuisine/italian at 80 imp / 1.25% CTR before this change).
    title_year = REFERENCE_DATE.year
    if n365 == 1:
        title = f"Toronto's Newest {label} Restaurant ({title_year}) · NowServingTO"
    else:
        title = f"Toronto's {n365} Newest {label} Restaurants ({title_year}) · NowServingTO"
    desc = (f"Every newly registered {label} restaurant in Toronto over the past 365 "
            f"days, updated daily. {n365} entries tracked, {n30} from the last 30 days.")
    canonical = f"https://nowservingto.com/cuisine/{key}"

    page = template
    # Replace meta tags - first occurrence each.
    page = re.sub(r'<title>[^<]*</title>', f'<title>{_esc(title)}</title>', page, count=1)
    for sel, val in [
        (r'(<meta name="description" content=")[^"]*(")',         desc),
        (r'(<meta property="og:title" content=")[^"]*(")',        title),
        (r'(<meta property="og:description" content=")[^"]*(")',  desc),
        (r'(<meta property="og:url" content=")[^"]*(")',          canonical),
        (r'(<meta name="twitter:title" content=")[^"]*(")',       title),
        (r'(<meta name="twitter:description" content=")[^"]*(")', desc),
        (r'(<link rel="canonical" href=")[^"]*(")',               canonical),
    ]:
        page = re.sub(sel, lambda m, v=val: m.group(1) + _esc(v) + m.group(2),
                      page, count=1)

    # Replace the homepage's <h1 class="sub"> with a cuisine-specific
    # one. "Newest registered" anchors the row date labels ("5d ago")
    # to the City business-licence registration date. Avoided "licensed"
    # because in Ontario that colloquially means LLBO/alcohol-licensed,
    # which most entries on the site aren't. Targets "newest <Label>
    # restaurants Toronto" SEO.
    cuisine_h1 = (f'<h1 class="sub">Toronto\'s <span class="hl">newest registered</span> '
                  f'{_esc(label)} restaurants</h1>')
    page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>',
                  lambda m: cuisine_h1, page, count=1)

    # Replace STATIC-FEED + LD-ITEMLIST with cuisine-scoped versions.
    cuisine_static = build_static_rows(entries, link_to_listing=True)
    cuisine_itemlist = build_ld_itemlist(
        entries,
        name=f"Newest {label} restaurants in Toronto",
        description=desc,
    )
    cuisine_collection = build_ld_collectionpage(
        cuisine_itemlist, url=canonical, dateModified=REFERENCE_DATE.isoformat(),
        about=cuisine_about_thing(key, label),
    )
    cuisine_breadcrumb_parts = [
        ('Home',     'https://nowservingto.com/'),
        (f'{label} restaurants', None),
    ]
    cuisine_breadcrumb_ld = build_ld_breadcrumb([
        ('Home', 'https://nowservingto.com/'),
        (f'{label} restaurants', canonical),
    ])
    cuisine_faq = build_ld_faq([
        (f"How often is the {label} restaurant list updated?",
         f"Daily. Every morning we pull the latest City of Toronto business "
         f"licences open data and re-classify any new entries."),
        (f"Where does the {label} restaurant data come from?",
         f"The City of Toronto's Municipal Licensing and Standards open dataset "
         f"of active business licences, cross-checked against Google Places to "
         f"confirm the business is currently operating."),
        (f"How is a restaurant classified as {label}?",
         f"An AI model (Anthropic Claude) reviews the operating name, website "
         f"content, and Google Places category to determine the cuisine. "
         f"Multi-cuisine spots get tagged with every applicable cuisine."),
    ])
    # Cross-axis compound-query nav strip was removed 2026-05-20 - see
    # build_xaxis_strip for the rationale (UX-redundant with the pickers,
    # and SEO benefit was nil because every "X in Y" anchor pointed at
    # the same shared landing URL rather than a unique compound page).
    page = inject_into_html(
        page,
        static_block=cuisine_static,
        ld_payloads=[cuisine_collection, cuisine_breadcrumb_ld, cuisine_faq],
        breadcrumb_html=build_breadcrumb_html(cuisine_breadcrumb_parts),
        page_intro_html=build_page_intro(key),
        related_html=build_related_cuisines(key) + build_community_partners(key),
        lcp_preload_url=(entries[0].get('thumb') or '') if entries else '',
    )
    page = swap_newsletter_cta(page, build_alert_section('cuisine', key, label))
    # Body class lets CSS lay out the cuisine-page masthead differently
    # from the homepage (compact horizontal brand+h1 instead of stacked).
    page = page.replace('<body>', '<body class="page-cuisine">', 1)

    (CUISINE_DIR / f'{key}.html').write_text(page)
    cuisine_pages_written += 1
print(f"  wrote {cuisine_pages_written} per-cuisine SEO landing pages → cuisine/<key>.html")


# ---------------------------------------------------------------------------
# Per-DISTRICT landing pages at district/<slug>.html - parallels the
# /cuisine/ pages but bucketed by Toronto district (Downtown, East Toronto,
# Etobicoke, North York, Scarborough, West Toronto). Targets queries like
# "new restaurants Scarborough" that have real volume and almost no ranked
# competition. Same template + h1/title/og treatment as per-cuisine pages.
DISTRICT_DIR = Path(ROOT) / 'district'
DISTRICT_DIR.mkdir(exist_ok=True)
# Group entries by district from the in-memory feed (no extra inject pass).
by_district = defaultdict(list)
for entry in seen_entries.values():
    d = (entry.get('district') or '').strip()
    if d: by_district[d].append(entry)
# Sort each district's list freshest-first
for d in by_district:
    by_district[d].sort(key=lambda r: r['issuedDate'], reverse=True)

# (_district_slug defined earlier near build_xaxis_strip)

district_template = open(INDEX_PATH).read()
district_pages_written = 0
for label, entries in by_district.items():
    if not entries: continue
    slug = _district_slug(label)
    n365 = len(entries)
    n30  = sum(1 for e in entries if e['daysOpen'] <= 30)

    # Use "in Downtown Toronto" when label is "Downtown" - reads better.
    place = f'{label} Toronto' if label == 'Downtown' else label
    title = (f"Newest Restaurant in {place} ({REFERENCE_DATE.year}) · NowServingTO"
             if n365 == 1
             else f"{n365} Newest Restaurants in {place} ({REFERENCE_DATE.year}) · NowServingTO")
    desc = (f"Every newly registered restaurant in {place}, by cuisine, updated "
            f"weekly. {n365} entries tracked, {n30} from the last 30 days.")
    canonical = f"https://nowservingto.com/district/{slug}"

    page = district_template
    # Replace meta tags
    page = re.sub(r'<title>[^<]*</title>', f'<title>{_esc(title)}</title>', page, count=1)
    for sel, val in [
        (r'(<meta name="description" content=")[^"]*(")',         desc),
        (r'(<meta property="og:title" content=")[^"]*(")',        title),
        (r'(<meta property="og:description" content=")[^"]*(")',  desc),
        (r'(<meta property="og:url" content=")[^"]*(")',          canonical),
        (r'(<meta name="twitter:title" content=")[^"]*(")',       title),
        (r'(<meta name="twitter:description" content=")[^"]*(")', desc),
        (r'(<link rel="canonical" href=")[^"]*(")',               canonical),
    ]:
        page = re.sub(sel, lambda m, v=val: m.group(1) + _esc(v) + m.group(2),
                      page, count=1)

    # District-specific h1. "Newly registered" gives the row date labels
    # ("5d ago") a clear referent without the LLBO/alcohol implication
    # that "licensed" carries in Ontario.
    district_h1 = (f'<h1 class="sub"><span class="hl">Newly registered</span> '
                   f'restaurants in {_esc(place)}</h1>')
    page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>',
                  lambda m: district_h1, page, count=1)

    # District-scoped static feed (top 30) + structured data set
    district_static = build_static_rows(entries[:30], link_to_listing=True)
    district_itemlist = build_ld_itemlist(
        entries[:30],
        name=f"Newest restaurants in {place}",
        description=desc,
    )
    district_collection = build_ld_collectionpage(
        district_itemlist, url=canonical, dateModified=REFERENCE_DATE.isoformat(),
    )
    district_breadcrumb_parts = [
        ('Home', 'https://nowservingto.com/'),
        (f'Restaurants in {place}', None),
    ]
    district_breadcrumb_ld = build_ld_breadcrumb([
        ('Home', 'https://nowservingto.com/'),
        (f'Restaurants in {place}', canonical),
    ])
    district_faq = build_ld_faq([
        (f"How often is the {place} restaurant list updated?",
         f"Daily. We pull fresh City of Toronto business-licences data every "
         f"morning and re-classify any new entries."),
        (f"What counts as {place} in this directory?",
         f"We use the postal-code prefix on each business licence (FSA) to "
         f"map every restaurant to one of six Toronto districts: Downtown, "
         f"East Toronto, West Toronto, North York, Scarborough, or Etobicoke."),
        (f"Where does the {place} restaurant data come from?",
         f"The City of Toronto's Municipal Licensing and Standards open "
         f"dataset of active business licences, cross-checked against "
         f"Google Places to confirm operating status."),
    ])
    # Cross-axis compound-query nav strip removed 2026-05-20 (same reason
    # as the cuisine-page version above - UX-redundant, SEO inert).
    page = inject_into_html(
        page,
        static_block=district_static,
        ld_payloads=[district_collection, district_breadcrumb_ld, district_faq],
        breadcrumb_html=build_breadcrumb_html(district_breadcrumb_parts),
        lcp_preload_url=(entries[0].get('thumb') or '') if entries else '',
    )
    page = swap_newsletter_cta(page, build_alert_section('district', slug, label))
    # Body class - same horizontal-masthead treatment as cuisine pages.
    page = page.replace('<body>', '<body class="page-district">', 1)

    (DISTRICT_DIR / f'{slug}.html').write_text(page)
    district_pages_written += 1
print(f"  wrote {district_pages_written} per-district SEO landing pages → district/<slug>.html")


# ---------------------------------------------------------------------------
# Press / media kit page: fill the numbers + top-cuisines table into
# press.html so the public stats stay current. Hand-authored template
# with marker comments; we just swap the markers in place.
# ---------------------------------------------------------------------------
PRESS_PATH = Path(ROOT) / 'press.html'
if PRESS_PATH.exists():
    press_html = PRESS_PATH.read_text()
    n_total = n_tagged_365
    n_30 = n_tagged_30
    n_cuisines_active = sum(1 for c in cuisines_out if c.get('count365d', 0) > 0)
    n_districts = sum(1 for label, v in by_district.items() if v)
    updated_str = REFERENCE_DATE.strftime('%B %-d, %Y')

    # (Top-N table HTML used to be built here for the PRESS-TOP-CUISINES
    # block; removed 2026-05-31 - replaced by the client-rendered bar
    # charts on /press.)

    swaps = [
        (r'<!-- PRESS-N-TOTAL -->.*?<!-- /PRESS-N-TOTAL -->',
         f'<!-- PRESS-N-TOTAL -->{n_total}<!-- /PRESS-N-TOTAL -->'),
        (r'<!-- PRESS-N-30D -->.*?<!-- /PRESS-N-30D -->',
         f'<!-- PRESS-N-30D -->{n_30}<!-- /PRESS-N-30D -->'),
        (r'<!-- PRESS-N-CUISINES -->.*?<!-- /PRESS-N-CUISINES -->',
         f'<!-- PRESS-N-CUISINES -->{n_cuisines_active}<!-- /PRESS-N-CUISINES -->'),
        (r'<!-- PRESS-N-DISTRICTS -->.*?<!-- /PRESS-N-DISTRICTS -->',
         f'<!-- PRESS-N-DISTRICTS -->{n_districts}<!-- /PRESS-N-DISTRICTS -->'),
        (r'<!-- PRESS-UPDATED-DATE -->.*?<!-- /PRESS-UPDATED-DATE -->',
         f'<!-- PRESS-UPDATED-DATE -->{_esc(updated_str)}<!-- /PRESS-UPDATED-DATE -->'),
        # PRESS-TOP-CUISINES table removed 2026-05-31 - the two side-by-side
        # bar charts (12mo + 30d) above it carry the same data with more
        # visual punch. The cuisine-counts data still flows to the page
        # via the client-side fetch of /data/corridors.json that drives
        # those charts; this cron-injected table block is no longer needed.
    ]
    for pat, rep in swaps:
        press_html = re.sub(pat, rep, press_html, count=1, flags=re.DOTALL)
    PRESS_PATH.write_text(press_html)
    print(f"  refreshed press.html (stats: {n_total} listings, {n_30} in 30d, {n_cuisines_active} cuisines)")


# ---------------------------------------------------------------------------
# Per-LISTING pages at r/<slug>.html  +  OG image cards at og/<slug>.png.
# ---------------------------------------------------------------------------
# Every kept entry gets:
#   r/<slug>.html  - own title/og:image/canonical/h1, single-row static feed,
#                    single-Restaurant JSON-LD. Apache .htaccess rewrites
#                    /r/<slug> → /r/<slug>.html.
#   og/<slug>.png  - 1200×675 branded card used as og:image so X/FB/iMessage
#                    show the personalized image when the URL is shared,
#                    with the IMAGE itself being a click-target to the page.
from og_card import render_card_png as _render_og_card
LISTING_DIR = Path(ROOT) / 'r'
OG_DIR      = Path(ROOT) / 'og'
LISTING_DIR.mkdir(exist_ok=True)
OG_DIR.mkdir(exist_ok=True)

listing_template = open(INDEX_PATH).read()


def _fmt_issued(iso):
    """'2026-05-07' -> 'May 7, 2026'. Returns '' for falsy input."""
    if not iso: return ''
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
        return d.strftime('%B %-d, %Y')
    except Exception:
        return iso


def _haversine_km(a, b):
    """(lat,lng) pairs -> km. Inline so we don't pull a numpy/geopy dep."""
    from math import radians, sin, cos, asin, sqrt
    lat1, lng1 = a; lat2, lng2 = b
    dlat = radians(lat2 - lat1); dlng = radians(lng2 - lng1)
    h = (sin(dlat/2)**2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2)
    return 2 * 6371.0 * asin(sqrt(h))


def _nearby_same_cuisine(entry, all_entries, *, radius_km=3.0, limit=4):
    """Other recent entries that share at least one cuisine key AND are
    within `radius_km` of this entry. Falls back to same-cuisine anywhere
    in the city (recency-sorted) if no geographic neighbors. Excludes
    self. Skips entries without lat/lng for the distance check (they
    still qualify for the fallback)."""
    my_slug = entry.get('slug')
    my_keys = set(entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else []))
    if not my_keys: return []
    my_lat, my_lng = entry.get('lat'), entry.get('lng')
    same_cuisine = []
    for e in all_entries:
        if e.get('slug') == my_slug: continue
        ek = set(e.get('cuisines') or ([e['cuisine']] if e.get('cuisine') else []))
        if not (ek & my_keys): continue
        same_cuisine.append(e)
    # Geographic neighbors first, then fall back to same-cuisine anywhere.
    if my_lat is not None and my_lng is not None:
        near = []
        for e in same_cuisine:
            if e.get('lat') is None or e.get('lng') is None: continue
            d = _haversine_km((my_lat, my_lng), (e['lat'], e['lng']))
            if d <= radius_km: near.append((d, e))
        near.sort(key=lambda t: (t[0], t[1].get('daysOpen', 99999)))
        if near: return [e for _d, e in near[:limit]]
    # Fallback: city-wide same-cuisine by recency.
    same_cuisine.sort(key=lambda e: e.get('daysOpen', 99999))
    return same_cuisine[:limit]


def _build_owner_cta(entry):
    """Per-listing 'Is this your restaurant?' invitation. Generates a
    mailto link with subject + body pre-populated so an owner can reply
    in under a minute. Lives on every /r/<slug> page - both for owners
    who find their own listing via search (passive discovery) and as
    the landing surface for cold-outreach campaigns. Right-side slot
    carries a compact inline cuisine-alert subscribe form so the bottom
    of the page collapses two CTAs into one row."""
    name = entry.get('operatingName') or 'your restaurant'
    slug = entry.get('slug') or ''
    listing_url = f'https://nowservingto.com/r/{slug}' if slug else 'https://nowservingto.com/'
    subject = f'Enhance my listing: {name}'
    body = (
        f'Hi Josh,\n\n'
        f'Re: {name}\n'
        f'Listing: {listing_url}\n\n'
        f"I'd like to enhance my listing with:\n\n"
        f'• Photo (attach to this email):\n'
        f'• What makes us special (one sentence):\n'
        f'• Owner/chef story (1-2 sentences):\n'
        f'• When we actually opened (date):\n'
        f'• Signature dishes:\n'
        f'• Anything incorrect that needs fixing:\n\n'
        f'Thanks!\n'
    )
    mailto = 'mailto:hello@nowservingto.com?subject=' + quote_plus(subject) + '&body=' + quote_plus(body)

    # Compact inline cuisine-alert form REMOVED 2026-06-03 — user
    # feedback called the inline mini-form "shitty little" vs the full
    # alert-section on cuisine pages. The standalone alert-section now
    # gets re-enabled at the bottom of /r/<slug> pages (see the listing
    # page render flow); the owner-CTA stays compact, single-purpose.
    return (
        '<div class="lx-card lx-owner-cta">'
        '<p class="lx-owner-cta-line">Is this your restaurant? '
        f'<a class="lx-owner-cta-btn" href="{_esc(mailto)}">'
        'Send a photo, story, or correction <span aria-hidden="true">→</span></a>'
        '</p>'
        '</div>'
    )


def _build_owner_contributions(entry):
    """If the owner has replied to the CTA with content (stored in
    OWNER_CONTRIBUTIONS keyed by slug), render a prominent 'From the
    owner' block at the top of the listing-extra. Empty string when
    no contribution exists - most listings start without one."""
    slug = entry.get('slug') or ''
    oc = OWNER_CONTRIBUTIONS.get(slug) or {}
    if not oc: return ''
    parts = ['<div class="lx-card lx-owner-content">']
    parts.append('<h2 class="lx-owner-content-h">From the owner</h2>')
    text = (oc.get('from_owner_text') or '').strip()
    if text:
        parts.append(f'<p class="lx-owner-text">{_esc(text)}</p>')
    facts = []
    if oc.get('opened_date'):
        facts.append(f'Opened {_esc(oc["opened_date"])}')
    if oc.get('owner_name'):
        facts.append(f'Run by {_esc(oc["owner_name"])}')
    dishes = oc.get('specialty_dishes') or []
    if dishes:
        facts.append('Signature: ' + _esc(', '.join(dishes)))
    if facts:
        parts.append('<p class="lx-owner-facts">' + ' &middot; '.join(facts) + '</p>')
    parts.append('</div>')
    return ''.join(parts)


def build_listing_extra(entry, all_entries, cuisines_index):
    """Render the differentiated-content block for /r/<slug>.html: verifier
    evidence + license/provenance line + cohort framing + nearby-same-cuisine
    grid. `cuisines_index` is {key: cuisines_out_row}; lets us pull
    count365d / count30d without rescanning."""
    blocks = []
    # Owner contributions get the top slot when present - first-person
    # content from the operator outranks machine-generated editorial.
    _oc_html = _build_owner_contributions(entry)
    if _oc_html:
        blocks.append(_oc_html)

    # 1) What we know about this restaurant. Prefer the editorial
    # rewrite (evidence_rewrite_cache - reads like a human wrote it)
    # over the raw validator_evidence (which leaks "Website confirms..."
    # / "WEB VERIFY reports..." verification-log phrasing onto the page).
    cache_key_val = entry.get('_cacheKey', '')
    wv = WEB_VERIFY_CACHE.get(cache_key_val) or {}
    ev_rewrite = EVIDENCE_REWRITE_CACHE.get(cache_key_val) or {}
    if ev_rewrite.get('status') == 'ok' and ev_rewrite.get('blurb'):
        blurb_text = ev_rewrite['blurb'].strip()
    else:
        blurb_text = (wv.get('validator_evidence') or wv.get('evidence') or '').strip()
    if blurb_text:
        # Capitalize first letter - bare blurb, no eyebrow / no cite line.
        blurb_text = blurb_text[:1].upper() + blurb_text[1:]
        # Scrub two classes of stale phrasing the LLM bakes into cached
        # blurbs (the cache is keyed by _cacheKey and frozen forever):
        #   1. Time-relative phrases like "opened 5 days ago" that were
        #      correct when generated but go stale day by day. The lede
        #      above the row carries today's accurate count.
        #   2. The word "opened" - inaccurate (we only know registration
        #      date, not actual open date) and against the site's vocab
        #      convention (CLAUDE.md prefers "registered").
        # Cheaper than nuking + regenerating the LLM cache.
        # Time-relative scrub: catches any "<verb> N days/weeks/months ago"
        # phrasing the LLM bakes into cached blurbs. The lede above the row
        # carries today's accurate count; cached blurbs go stale day by day.
        blurb_text = re.sub(
            r'\s*\b(opened|registered|licensed|licence\s+issued|operating(?:\s+since)?|launched|established|debuted)\s+\d+\s*(?:d|days?|day|weeks?|wk|months?|mo|years?|yr)\s+ago\b',
            '', blurb_text, flags=re.I)
        # Also catch standalone "N days ago" with no leading verb (e.g. "...
        # operational, 14 days ago, with own website...").
        blurb_text = re.sub(r',?\s*\b\d+\s*(?:d|days?|day|weeks?|wk|months?|mo|years?|yr)\s+ago\b',
                            '', blurb_text, flags=re.I)
        # "N-day-old" / "N day old" / "(2 days old)" - same problem, different
        # grammar. Catches "98-day-old take-out licence" and "Fresh licence
        # (2 days old)" patterns from the LLM rewrites.
        blurb_text = re.sub(
            r'\s*\(?\s*\b\d+[\s-]*(?:d|days?|day|weeks?|wk|months?|mo|years?|yr)[\s-]*old\b\)?',
            '', blurb_text, flags=re.I)
        # "Fresh licence" without a number qualifier still reads as time-
        # relative ("fresh" implies very recent). Strip the leading "Fresh"
        # adjective when paired with "licence".
        blurb_text = re.sub(r'\bFresh\s+licence\b', 'Licence', blurb_text)
        blurb_text = re.sub(r'\bfresh\s+licence\b', 'licence', blurb_text)
        # "opened" → "registered" everywhere (overstatement: we only know the
        # licence registration date, not when the kitchen actually opened).
        blurb_text = re.sub(r'\bopened\b', 'registered', blurb_text, flags=re.I)
        # Strip dangling "no Places match" / "yet crawled" claims that go
        # stale the moment we patch a place_id in.
        blurb_text = re.sub(
            r'\s*(?:with|and)?\s*no\s+(?:Places?\s+match|website\s+content\s+(?:yet\s+)?crawled|maps?\s+listing)\b[^.;]*',
            '', blurb_text, flags=re.I)
        # Clean up double-spaces / stranded commas / dangling connectives.
        blurb_text = re.sub(r'\s{2,}', ' ', blurb_text)
        blurb_text = re.sub(r'\s+([,.;:])', r'\1', blurb_text)
        blurb_text = re.sub(r',\s*(?:with|but|and|;)\s*', ' ', blurb_text)
        # Stranded sentence-internal punctuation runs ";." / ", ." / ";," etc.
        blurb_text = re.sub(r'[;,]+\s*(?=[.;,])', '', blurb_text)
        blurb_text = re.sub(r'[,.;:]\s*$', '.', blurb_text)
        # Stranded empty parens left by the "(N days old)" scrub.
        blurb_text = re.sub(r'\(\s*\)', '', blurb_text)
        # Em/en-dashes out (LLM loves them; we don't ship them).
        blurb_text = re.sub(r'\s*[—–]\s*', ', ', blurb_text)
        blurb_text = re.sub(r'\s{2,}', ' ', blurb_text)
        blurb_text = blurb_text.strip()
        blocks.append(
            '<div class="lx-card">'
            f'<p class="lx-evidence">{_esc(blurb_text)}</p>'
            '</div>'
        )

    # 2b) Menu signal — two-tier from MENU_HIGHLIGHTS_CACHE:
    #   tier 1: specific dishes ("Try the mandi, shawarma, kibbeh.")
    #   tier 2: menu categories ("Menu features biryanis, curries, kebabs.")
    # Categories are the fallback when the restaurant's website only lists
    # section headers — better than rendering nothing for the ~55% of entries
    # that don't surface specific dish names. Cache schema includes both
    # `dishes` and `categories` fields; tier 1 wins when present.
    _mh = MENU_HIGHLIGHTS_CACHE.get(cache_key_val) or {}
    _mh_dishes = [d.strip() for d in (_mh.get('dishes') or []) if d and d.strip()][:5]
    _mh_cats   = [c.strip() for c in (_mh.get('categories') or []) if c and c.strip()][:5]
    if _mh_dishes:
        _dish_html = ', '.join(f'<b>{_esc(d)}</b>' for d in _mh_dishes)
        blocks.append(
            '<div class="lx-card lx-dishes">'
            '<p class="lx-eyebrow">What to order</p>'
            f'<p class="lx-dishes-list">Try the {_dish_html}.</p>'
            '</div>'
        )
    elif _mh_cats:
        _cat_html = ', '.join(f'<b>{_esc(c)}</b>' for c in _mh_cats)
        blocks.append(
            '<div class="lx-card lx-dishes lx-dishes-cats">'
            '<p class="lx-eyebrow">On the menu</p>'
            f'<p class="lx-dishes-list">Menu features {_cat_html}.</p>'
            '</div>'
        )

    # 3) Featured in: Toronto food-press citations (BlogTO, Toronto Life,
    # Eater, Toronto Guardian, etc.). Populated by a separate Haiku
    # web_search pass per restaurant (tools/llm_featured_in_batch.py,
    # to be shipped). Cache-keyed by cache_key. The single most
    # editorially-substantive enrichment we can add - third-party
    # validation, not just our claim.
    fi = FEATURED_IN_CACHE.get(cache_key_val) or {}
    citations = fi.get('citations') if fi.get('status') == 'ok' else None
    if citations:
        # Format publication date as "Jul 2025" style. Citations come pre-
        # sorted by relevance from the Haiku pass; render up to 5.
        def _fmt_date(d):
            if not d: return ''
            try:
                from datetime import datetime as _dt
                return _dt.strptime(d[:7], '%Y-%m').strftime('%b %Y')
            except Exception:
                return d
        items = []
        for c in citations[:5]:
            pub = _esc(c.get('publication') or '')
            url = _esc(c.get('url') or '')
            excerpt = _esc(c.get('excerpt') or '')
            date_s = _esc(_fmt_date(c.get('date') or ''))
            if not (pub and url): continue
            date_html = f'<span class="fi-date">{date_s}</span>' if date_s else ''
            items.append(
                f'<li class="fi-item">'
                f'<a class="fi-link" href="{url}" target="_blank" rel="noopener">'
                f'<span class="fi-pub">{pub}</span>'
                f'{date_html}'
                f'</a>'
                f'{f"<span class=fi-excerpt>{excerpt}</span>" if excerpt else ""}'
                f'</li>'
            )
        if items:
            blocks.append(
                '<div class="lx-card lx-featured">'
                '<p class="lx-eyebrow">Featured in Toronto food press</p>'
                f'<ul class="fi-list">{"".join(items)}</ul>'
                '</div>'
            )

    keys = entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else [])
    primary_key = keys[0] if keys else ''

    # 4) Nearby same-cuisine cards. Internal-link rich, distinct from
    # Google Maps' "similar nearby" because it's scoped to *just-opened*.
    near = _nearby_same_cuisine(entry, all_entries)
    if near:
        label = (cuisines_index.get(primary_key, {}).get('label')
                 or (primary_key.replace('_', ' ').title() if primary_key else 'restaurants'))
        cards = []
        for e in near:
            n_slug = e.get('slug') or ''
            n_name = _esc(e.get('operatingName', ''))
            n_thumb = e.get('thumb') or ''
            n_when = _esc(_tier_label(e.get('daysOpen', 0), e.get('issuedDate'), e.get('dateSource')))
            n_where = _esc(e.get('district') or '')
            # Link ladder: owner website > Places card > coord-pin > internal /r/<slug>.
            # Matches the row name-link convention - "more info" should land
            # on the actual business, not bounce to another internal page.
            # Aggregator filter: skip ritual.co / ubereats / doordash etc.
            # Hybrid card: photo + name link to /r/<slug> (so visitors who
            # want context get it before deciding to click out), with
            # compact "Website" / "Maps" buttons at the bottom for visitors
            # who just want to go. Aggregator filter on website still
            # applies - we don't surface ritual/ubereats/doordash as the
            # "website" CTA.
            internal_url = f'/r/{n_slug}' if n_slug else '#'
            # Website + Maps CTAs removed 2026-06-03 — cards are now name +
            # district only. Visitors click into /r/<slug> for the editorial
            # profile, where the name carries the outbound website link and
            # the address is a Maps link. Tradeoff: +1 click for "just give
            # me the website" hunters, traded for cleaner cards + better
            # engagement signal (directory's job is to deliver context).
            pic_html = ''
            cta_html = ''
            when_html = f'<span class="lx-near-when">{n_when}</span>' if n_when else ''
            # Card-wide click target: an absolutely-positioned <a> covering
            # the whole card so any blank-area click navigates to the /r/<slug>
            # profile. Sits at z-index 1 with the body content z-indexed above
            # it, so inner anchors (name, Website, Maps) win on direct click
            # while the rest of the card stays clickable. Restored 2026-06-03
            # after photo retirement removed the lx-near-pic anchor that used
            # to serve this role.
            cardlink_html = (f'<a class="lx-near-cardlink" href="{_esc(internal_url)}" '
                             f'aria-label="View profile for {n_name}"></a>'
                             if n_slug else '')
            cards.append(
                f'<div class="lx-near-card">'
                f'{cardlink_html}'
                f'{pic_html}'
                f'<div class="lx-near-body">'
                f'{when_html}'
                f'<a class="lx-near-name" href="{_esc(internal_url)}">{n_name}</a>'
                f'<span class="lx-near-where">{n_where}</span>'
                f'{cta_html}'
                f'</div></div>'
            )
        # Owner CTA slots in BEFORE the nearby-grid: groups all
        # "about this restaurant" content together (editorial blurb,
        # cohort/menu, owner invite) and pushes the cross-discovery
        # nearby cards to the end. Reads less cluttered at page bottom.
        blocks.append(_build_owner_cta(entry))
        blocks.append(
            '<div class="lx-card">'
            f'<h2 class="lx-near-h">Other newly registered {_esc(label)} kitchens nearby</h2>'
            f'<div class="lx-near-grid">{"".join(cards)}</div>'
            '</div>'
        )
    else:
        # No nearby cards (rare cuisine, no neighbors) - CTA still appears.
        blocks.append(_build_owner_cta(entry))
    # "Report an error" link — universal, footer-style, low visual
    # weight. Folds wrong-cuisine, wrong-address, wrong-photo, closed-
    # missed, and any other listing error into one correction channel.
    # Pre-fills the email body with the listing URL + a structured
    # checklist so anyone (community member, owner, journalist) can
    # report in under 30 seconds.
    _name_for_report = entry.get('operatingName') or 'this listing'
    _slug_for_report = entry.get('slug') or ''
    _url_for_report = (f'https://nowservingto.com/r/{_slug_for_report}'
                       if _slug_for_report else 'https://nowservingto.com/')
    _report_subject = f'Listing correction: {_name_for_report}'
    _report_body = (
        f'Re: {_name_for_report}\n'
        f'Listing: {_url_for_report}\n\n'
        f"What needs fixing? (one or more)\n\n"
        f'[ ] Wrong cuisine — should be: \n'
        f'[ ] Wrong address\n'
        f'[ ] Wrong photo\n'
        f'[ ] Restaurant closed\n'
        f'[ ] Other:\n\n'
        f'Notes (optional):\n\n'
        f'Thanks!\n'
    )
    _report_mailto = ('mailto:hello@nowservingto.com?subject='
                      + quote_plus(_report_subject) + '&body='
                      + quote_plus(_report_body))
    blocks.append(
        f'<p class="lx-report-error">Spot something wrong? '
        f'<a href="{_esc(_report_mailto)}">Report an error &rsaquo;</a></p>'
    )

    return '<section class="listing-extra" aria-label="Listing detail">' + ''.join(blocks) + '</section>'


# Index cuisines_out by key for O(1) lookups inside the listing loop.
_cuisines_index = {c['key']: c for c in cuisines_out}

n_listing_html = 0
n_listing_png  = 0
n_listing_photo = 0
n_listing_streetview = 0
for entry in seen_entries.values():
    slug = entry.get('slug')
    if not slug: continue

    # 1) PNG card → og/<slug>.png - branded fallback
    try:
        _render_og_card(entry, out_path=str(OG_DIR / f'{slug}.png'))
        n_listing_png += 1
    except Exception as ex:
        print(f"  WARN: og card failed for {slug}: {ex}")
        continue

    # 2) HTML → r/<slug>.html
    name = entry.get('operatingName', '')
    keys = entry.get('cuisines') or ([entry['cuisine']] if entry.get('cuisine') else [])
    primary_key = keys[0] if keys else ''
    primary_lbl = CUISINE_LABEL.get(primary_key, primary_key.replace('_', ' ').title()) if primary_key else 'restaurant'
    addr     = entry.get('address') or ''
    district = entry.get('district') or ''

    # Title now includes the street name + neighborhood so we rank for
    # address-style searches ("3776 bathurst street") + neighborhood
    # queries ("italian restaurant st clair"), not just the entry name.
    # Google shows ~60 chars before truncation; the brand suffix is
    # truncatable. Order: NAME - <cuisine | menu hint>, <street> · brand.
    title = _build_listing_title(name, primary_lbl, addr, district, entry)
    desc_addr = addr + (f', {district}' if district and district not in addr else '')
    fallback_desc = (f"{name} - newly registered {primary_lbl} restaurant at {desc_addr}. "
                     f"Part of NowServingTO's daily-updated directory of Toronto's "
                     f"newest restaurants, by cuisine.")
    desc = _build_listing_meta_desc(entry, primary_lbl, name, desc_addr, fallback_desc)
    canonical = f"https://nowservingto.com/r/{slug}"
    # Branded typographic OG card — same image for every share surface
    # (X/FB/iMessage). Photo route retired 2026-06-03.
    og_image  = f"https://nowservingto.com/og/{slug}.png"

    page = listing_template
    page = re.sub(r'<title>[^<]*</title>',
                  lambda m: f'<title>{_esc(title)}</title>', page, count=1)
    for sel, val in [
        (r'(<meta name="description" content=")[^"]*(")',         desc),
        (r'(<meta property="og:title" content=")[^"]*(")',        title),
        (r'(<meta property="og:description" content=")[^"]*(")',  desc),
        (r'(<meta property="og:url" content=")[^"]*(")',          canonical),
        (r'(<meta property="og:image" content=")[^"]*(")',        og_image),
        # Match the card's actual 1200×675 dimensions (the template defaults
        # to 1200×630 for the homepage og.svg, which is a different image).
        (r'(<meta property="og:image:width" content=")[^"]*(")',  '1200'),
        (r'(<meta property="og:image:height" content=")[^"]*(")', '675'),
        (r'(<meta name="twitter:title" content=")[^"]*(")',       title),
        (r'(<meta name="twitter:description" content=")[^"]*(")', desc),
        (r'(<meta name="twitter:image" content=")[^"]*(")',       og_image),
        (r'(<link rel="canonical" href=")[^"]*(")',               canonical),
    ]:
        page = re.sub(sel, lambda m, v=val: m.group(1) + _esc(v) + m.group(2),
                      page, count=1)

    # Replace the homepage's <h1 class="sub"> with this listing's name + lede.
    # The lede block sits between the H1 and the row, putting the three
    # facts Maps/IG can't show (opened-when, cohort rank, menu dishes)
    # above the fold for both human readers and AI-search citation.
    listing_lede = _build_listing_lede(entry, all_recent)
    listing_h1 = f'<h1 class="sub">{_esc(name)}</h1>'
    if listing_lede:
        listing_h1 += f'<div class="listing-lede">{_esc(listing_lede)}</div>'
    page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>',
                  lambda m: listing_h1, page, count=1)

    # Single-entry static feed + single-Restaurant JSON-LD.
    one_row = build_static_rows([entry])
    # image: pass an array containing both the 1200x630 OG card and the
    # 196x196 thumb. AI crawlers ingest schema.org `image` as an entity-
    # photo signal; multiple resolutions raise citation confidence.
    image_list = [og_image] if og_image else []
    listing_ld = {
        '@context': 'https://schema.org',
        '@type': 'Restaurant',
        'name': name,
        'address': {
            '@type': 'PostalAddress', 'streetAddress': addr,
            'addressLocality': 'Toronto', 'addressRegion': 'ON', 'addressCountry': 'CA',
        },
        'servesCuisine': [CUISINE_LABEL.get(k, k) for k in keys if k],
        'url': entry.get('website') or canonical,
        'image': image_list if len(image_list) > 1 else (image_list[0] if image_list else og_image),
        'foundingDate': entry.get('issuedDate'),
    }
    # geo: GeoCoordinates lets Google/AI parse exact location without
    # text-mining the address. Standard schema.org Restaurant field.
    if entry.get('lat') is not None and entry.get('lng') is not None:
        listing_ld['geo'] = {
            '@type': 'GeoCoordinates',
            'latitude': entry['lat'],
            'longitude': entry['lng'],
        }
    # hasMap: explicit pointer to the Maps card. Same info as the address
    # link but in a machine-readable field.
    if entry.get('mapsUrl'):
        listing_ld['hasMap'] = entry['mapsUrl']
    if entry.get('rating'):
        listing_ld['aggregateRating'] = {
            '@type': 'AggregateRating',
            'ratingValue': entry['rating'],
            'reviewCount': entry.get('reviewCount') or 1,
        }
    # Breadcrumb: Home → {Cuisine} restaurants → {Name}. Lifts SERP CTR
    # and ties this listing back to its cuisine landing page so Google
    # sees them as a hub + spokes for the cuisine query.
    cuisine_slug = primary_key
    listing_breadcrumb_parts = [('Home', 'https://nowservingto.com/')]
    listing_breadcrumb_ld_parts = [('Home', 'https://nowservingto.com/')]
    if cuisine_slug:
        cu_url = f'https://nowservingto.com/cuisine/{cuisine_slug}'
        listing_breadcrumb_parts.append((f'{primary_lbl} restaurants', cu_url))
        listing_breadcrumb_ld_parts.append((f'{primary_lbl} restaurants', cu_url))
    listing_breadcrumb_parts.append((name, None))
    listing_breadcrumb_ld_parts.append((name, canonical))
    listing_breadcrumb_ld = build_ld_breadcrumb(listing_breadcrumb_ld_parts)
    listing_extra_html = build_listing_extra(entry, all_recent, _cuisines_index)
    page = inject_into_html(
        page,
        static_block=one_row,
        ld_payloads=[listing_ld, listing_breadcrumb_ld],
        breadcrumb_html=build_breadcrumb_html(listing_breadcrumb_parts),
        lcp_preload_url=entry.get('thumb') or '',
        listing_extra_html=listing_extra_html,
    )
    # Mark the body so the page-load JS skips feed-hydration and the CSS
    # hides the directory-level filter row + map toggle. /r/<slug>.html
    # is a SINGLE-restaurant view; browsing chrome belongs on the home
    # / cuisine / district pages, not here.
    page = page.replace('<body>', '<body class="page-listing">', 1)

    # 2026-06-03: standalone bottom-of-page newsletter section RESTORED
    # on /r/<slug> pages with the listing's primary cuisine, replacing
    # the compact inline mini-form that lived next to the owner-CTA.
    # User feedback: the inline form looked weak vs the full alert-
    # section on cuisine pages. Visitors on a per-listing page are
    # cuisine-relevant — they're already looking at e.g. an Italian
    # spot, so the "get an email when a new Italian restaurant opens"
    # pitch is a natural CTA.
    _r_cuisines = entry.get('cuisines') or (
        [entry['cuisine']] if entry.get('cuisine') else [])
    _r_pkey = _r_cuisines[0] if _r_cuisines else None
    if _r_pkey:
        _r_plbl = CUISINE_LABEL.get(_r_pkey,
                                    _r_pkey.replace('_', ' ').title())
        page = swap_newsletter_cta(page, build_alert_section('cuisine', _r_pkey, _r_plbl))
    else:
        page = swap_newsletter_cta(page, '')

    (LISTING_DIR / f'{slug}.html').write_text(page)
    n_listing_html += 1

print(f"  wrote {n_listing_html} per-listing pages → r/<slug>.html")
print(f"  wrote {n_listing_png} per-listing OG cards → og/<slug>.png")

# ─────────────────────────────────────────────────────────────────────
# Monthly dispatch page (2026-06-01): publish a curated archive page
# per month showing the freshest entries. Lives at /dispatch/<yyyy-mm>.html
# and /dispatch/latest.html. Updates throughout the current month as
# new entries land; the previous month's file freezes after rollover.
# Serves as:
#   1. A forwardable monthly digest URL (email/X/Reddit distribution)
#   2. A permanent SEO archive page ranking for "newest toronto restaurants
#      [month]" queries
#   3. The landing page our weekly digest email points to
# ─────────────────────────────────────────────────────────────────────
DISPATCH_DIR = Path(ROOT) / 'dispatch'
DISPATCH_DIR.mkdir(exist_ok=True)
_dispatch_today = REFERENCE_DATE
# Dispatch covers the most-recently-COMPLETED calendar month, not the
# current one. Editorial-magazine model: the June issue is published in
# June but is about May. Avoids the "URL says June, content is May"
# semantic mismatch. Each month-start rolls the dispatch URL forward
# and the previous month's file becomes a permanent archive.
import calendar as _cal
if _dispatch_today.month == 1:
    _dm_year, _dm_month = _dispatch_today.year - 1, 12
else:
    _dm_year, _dm_month = _dispatch_today.year, _dispatch_today.month - 1
_dispatch_month = f'{_dm_year}-{_dm_month:02d}'
_dispatch_label = f'{_cal.month_name[_dm_month]} {_dm_year}'
_dm_start = f'{_dm_year}-{_dm_month:02d}-01'
_dm_end_day = _cal.monthrange(_dm_year, _dm_month)[1]
_dm_end = f'{_dm_year}-{_dm_month:02d}-{_dm_end_day:02d}'
_this_month_picks = sorted(
    [e for e in seen_entries.values()
     if _dm_start <= e.get('issuedDate', '') <= _dm_end],
    key=lambda r: r['issuedDate'], reverse=True
)
_dispatch_rows = build_static_rows(_this_month_picks[:30], link_to_listing=True)
_dispatch_template = open(INDEX_PATH).read()
_dispatch_canonical = f'{SITE_BASE}/dispatch/{_dispatch_month}'
_dispatch_title = f"NowServingTO Dispatch, {_dispatch_label}: {len(_this_month_picks)} new Toronto restaurants"
_dispatch_desc = (f"The {len(_this_month_picks)} restaurants newly registered with the City of "
                  f"Toronto in {_dispatch_label}, sorted by freshness, classified by cuisine, "
                  f"verified open. Monthly archive from nowservingto.com.")
_dispatch_h1 = (f'<h1 class="sub">NowServingTO Dispatch <span class="hl">{_esc(_dispatch_label)}</span></h1>'
                f'<div class="listing-lede">{len(_this_month_picks)} restaurants newly registered with '
                f'the City of Toronto in {_esc(_dispatch_label)}, sorted by freshness.</div>')

# Monthly dispatch tweet template — pulls 3 long-tail diaspora spots
# from the month's actual picks (skipping mainstream top-6) and
# generates a tweet that promises exactly what the dispatch page
# delivers. Cache-busted URL keyed on the dispatch month so X re-scrapes
# when a new month's dispatch is published.
_DISPATCH_TWEET_PHRASE = {
    'uyghur':      'Uyghur kebabs',
    'tamil':       'Tamil dosa',
    'salvadoran':  'Salvadoran pupusas',
    'vietnamese':  'Vietnamese banh mi',
    'ethiopian':   'Ethiopian injera',
    'tibetan':     'Tibetan momo',
    'filipino':    'Filipino sisig',
    'bangladeshi': 'Bangladeshi biryani',
    'caribbean':   'Caribbean jerk',
    'jamaican':    'Jamaican patties',
    'nigerian':    'Nigerian jollof',
    'ghanaian':    'Ghanaian waakye',
    'afghan':      'Afghan kabob',
    'pakistani':   'Pakistani karahi',
    'persian':     'Persian kebab',
    'korean':      'Korean BBQ',
    'thai':        'Thai curry',
    'nepalese':    'Nepalese momo',
    'kurdish':     'Kurdish kebab',
    'eritrean':    'Eritrean injera',
    'guyanese':    'Guyanese curry',
    'trinidadian': 'Trini doubles',
    'turkish':     'Turkish kebab',
    'lebanese':    'Lebanese shawarma',
    'syrian':      'Syrian kibbeh',
    'colombian':   'Colombian arepas',
    'peruvian':    'Peruvian ceviche',
    'brazilian':   'Brazilian feijoada',
    'sri_lankan':  'Sri Lankan hoppers',
    'indonesian':  'Indonesian nasi goreng',
    'malaysian':   'Malaysian laksa',
    'taiwanese':   'Taiwanese bubble tea',
    'argentinian': 'Argentine empanadas',
    'venezuelan':  'Venezuelan arepas',
    'polish':      'Polish pierogi',
    'greek':       'Greek souvlaki',
    'portuguese':  'Portuguese custard tarts',
}
_DISPATCH_TWEET_MAINSTREAM = {'italian', 'japanese', 'chinese', 'indian', 'mexican', 'middle_east'}
_dispatch_tweet_picks = []
_dispatch_tweet_seen_cuisines = set()
for _p in _this_month_picks:
    _ck = _p.get('cuisine') or ''
    if not _ck or _ck in _DISPATCH_TWEET_MAINSTREAM: continue
    if _ck in _dispatch_tweet_seen_cuisines: continue
    _phrase = _DISPATCH_TWEET_PHRASE.get(_ck)
    _district = _p.get('district')
    if not _phrase or not _district: continue
    _dispatch_tweet_picks.append(f'{_phrase} in {_district}')
    _dispatch_tweet_seen_cuisines.add(_ck)
    if len(_dispatch_tweet_picks) >= 3: break

# Build the tweet. Cache-bust the URL with epoch so each new monthly
# inject pushes a fresh URL to X (avoids stale card preview).
from time import time as _epoch2
_dispatch_share_url = f'{SITE_BASE}/dispatch/{_dispatch_month}?v={int(_epoch2())}'
if _dispatch_tweet_picks:
    _dispatch_tweet_text = (
        f"Toronto's {len(_this_month_picks)} new restaurant licences from "
        f"{_dispatch_label}, by cuisine and neighbourhood. Including "
        f"{', '.join(_dispatch_tweet_picks)}.\n\n"
        f"{_dispatch_share_url}\n\n"
        "#TorontoEats #TorontoFoodie"
    )
else:
    _dispatch_tweet_text = (
        f"Toronto's {len(_this_month_picks)} new restaurant licences from "
        f"{_dispatch_label}, by cuisine and neighbourhood.\n\n"
        f"{_dispatch_share_url}\n\n"
        "#TorontoEats #TorontoFoodie"
    )
_dispatch_tweet_intent = 'https://twitter.com/intent/tweet?text=' + quote_plus(_dispatch_tweet_text)
_dispatch_share_html = (
    f'<p class="trends-share" style="margin: 32px auto 16px; text-align:center;">'
    f'<a class="trends-tweet-btn" href="{_esc(_dispatch_tweet_intent)}" target="_blank" rel="noopener">'
    f'Share this on X &rsaquo;</a></p>'
)
_dispatch_page = inject_into_html(
    _dispatch_template, static_block=_dispatch_rows, ld_payloads=[],
)
for _sel, _val in [
    (r'<title>[^<]*</title>', f'<title>{_esc(_dispatch_title)}</title>'),
    (r'(<meta name="description" content=")[^"]*(")', _esc(_dispatch_desc)),
    (r'(<meta property="og:title" content=")[^"]*(")', _esc(_dispatch_title)),
    (r'(<meta property="og:description" content=")[^"]*(")', _esc(_dispatch_desc)),
    (r'(<meta property="og:url" content=")[^"]*(")', _esc(_dispatch_canonical)),
    (r'(<meta name="twitter:title" content=")[^"]*(")', _esc(_dispatch_title)),
    (r'(<meta name="twitter:description" content=")[^"]*(")', _esc(_dispatch_desc)),
    (r'(<link rel="canonical" href=")[^"]*(")', _esc(_dispatch_canonical)),
]:
    if _val.startswith('<title'):
        _dispatch_page = re.sub(_sel, _val, _dispatch_page, count=1)
    else:
        _dispatch_page = re.sub(_sel, lambda m, v=_val: m.group(1) + v + m.group(2),
                                _dispatch_page, count=1)
_dispatch_page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>(?:<div class="listing-lede">[\s\S]*?</div>)?',
                        lambda m: _dispatch_h1, _dispatch_page, count=1)
_dispatch_page = _dispatch_page.replace('<body>', '<body class="page-dispatch">', 1)
# Drop the chrome that doesn't belong on a dispatch archive page:
# filter dropdowns, cuisine picker, map toggle, fresh-since badge.
# Body class .page-dispatch hides them via CSS (reusing the existing
# .page-listing hide rules works since both want clean single-purpose layout).
# Inject Share-on-X button right before the </main> closer so it sits
# at the bottom of the dispatch content, tweeting the dispatch URL with
# the month's actual long-tail picks pre-filled.
_dispatch_page = _dispatch_page.replace('</main>', _dispatch_share_html + '\n</main>', 1)
(DISPATCH_DIR / f'{_dispatch_month}.html').write_text(_dispatch_page)
(DISPATCH_DIR / 'latest.html').write_text(_dispatch_page)
print(f"  wrote /dispatch/{_dispatch_month}.html + /dispatch/latest.html ({len(_this_month_picks)} entries)")

# ─────────────────────────────────────────────────────────────────────
# /trends page (2026-06-01): cuisine-velocity chart, monthly. Built as
# a screenshot-shareable artifact for personal-X distribution. Shows
# this-month-vs-prior-12-month-avg per cuisine, plus drought-broken
# and spike callouts. Comes with a "Tweet this" button using Twitter's
# intent URL so the page itself drives one-click sharing.
# ─────────────────────────────────────────────────────────────────────
from collections import defaultdict as _dd
from datetime import date as _date
# Bucket every entry's issuedDate into (cuisine, yyyymm). Walk 12 months
# back from the most-recently-completed month (May 2026 today).
def _ym_back(dt, n):
    y, m = dt.year, dt.month - n
    while m <= 0:
        m += 12; y -= 1
    return f'{y}-{m:02d}'
_trend_months = [_ym_back(_dispatch_today, i) for i in range(12, 0, -1)]
_trend_current_ym = _ym_back(_dispatch_today, 1)  # most recently completed month
# 6-month rolling window: months -6 through -1 (most recent 6 completed)
# Provides ~80 entries / cuisine sample size - enough that the top 3
# cuisines have meaningful percentage differentiation, vs 1-month
# which is noise (3 vs 2 means nothing).
_recent_6_months = [_ym_back(_dispatch_today, i) for i in range(6, 0, -1)]
_cuisine_month_count = _dd(lambda: _dd(int))
for _e in seen_entries.values():
    _iso = _e.get('issuedDate') or ''
    if len(_iso) < 7: continue
    _ym = _iso[:7]
    if _ym not in _trend_months: continue
    for _c in (_e.get('cuisines') or ([_e.get('cuisine')] if _e.get('cuisine') else [])):
        if not _c: continue
        _cuisine_month_count[_c][_ym] += 1

# Compute 6-month rolling count + 12-month average for ranking
_trend_rows = []
for _c, _by_m in _cuisine_month_count.items():
    _curr = sum(_by_m.get(m, 0) for m in _recent_6_months)  # 6-month rolling sum
    _avg = sum(_by_m.values()) / 12.0                        # 12-month monthly avg
    _trend_rows.append({
        'key': _c,
        'label': CUISINE_LABEL.get(_c, _c.replace('_', ' ').title()),
        'curr': _curr, 'avg': _avg,
        'delta_pct': ((_curr - _avg * 6) / (_avg * 6) * 100) if _avg > 0 else None,
        'by_m': dict(_by_m),
        # Most-recently-completed-month count (for monthly callouts)
        'last_month': _by_m.get(_trend_current_ym, 0),
    })
# Movement arrow compares this 6-month window vs the PRIOR 6-month
# window (months -12 through -7). Captures multi-month momentum
# rather than single-month noise.
_prior_6_months = [_ym_back(_dispatch_today, i) for i in range(12, 6, -1)]
for r in _trend_rows:
    r['prior'] = sum(_cuisine_month_count[r['key']].get(m, 0) for m in _prior_6_months)
    r['delta'] = r['curr'] - r['prior']
# Sort: this-month-count desc, then avg desc as tiebreaker
_trend_rows.sort(key=lambda r: (-r['curr'], -r['avg']))
_trend_top = _trend_rows[:12]
# Biggest mover this month - largest absolute delta vs 12-month avg
# (positive). Highlights "this cuisine really had a month" regardless
# of overall size.
_movers = sorted(_trend_rows, key=lambda r: -(r['curr'] - r['avg']))
_biggest_mover = next((r for r in _movers
                       if r['curr'] >= 2 and (r['curr'] - r['avg']) > 0.5), None)

# Drought-broken (single-month signal): cuisines with last_month >= 1
# AND no openings in the 3 months before that.
_drought_broken = []
_recent_3 = [_ym_back(_dispatch_today, i) for i in range(2, 5)]
for r in _trend_rows:
    if r['last_month'] >= 1 and all(r['by_m'].get(m, 0) == 0 for m in _recent_3):
        gap_months = 0
        for i in range(2, 12):
            m = _ym_back(_dispatch_today, i)
            if r['by_m'].get(m, 0) > 0:
                gap_months = i - 1
                break
            gap_months = i
        _drought_broken.append((r['label'], gap_months))
# Spikes (single-month signal): 2x+ vs 12-month avg, with last_month >= 2
_spikes = [(r['label'], r['last_month'], round(r['avg'], 1))
           for r in _trend_rows
           if r['last_month'] >= 2 and r['avg'] > 0 and r['last_month'] >= r['avg'] * 2]

# Build SVG bar chart - horizontal bars, top 12 cuisines this month.
# Per-cuisine colors (from PALETTE_HEX/cuisine_color) so each cuisine
# has its own visual identity instead of uniform coral. Movement arrow
# right-aligned next to the count when there's meaningful change vs
# prior month - gives the chart a little kinetic feel without being
# competitive in tone.
def _movement_arrow(delta):
    if delta >= 3:  return '<tspan fill="#3fb37f" font-weight="800"> ↑↑↑</tspan>'
    if delta == 2:  return '<tspan fill="#3fb37f" font-weight="700"> ↑↑</tspan>'
    if delta == 1:  return '<tspan fill="#3fb37f" font-weight="600"> ↑</tspan>'
    if delta == -1: return '<tspan fill="#9a9a96" font-weight="500"> ↓</tspan>'
    if delta == -2: return '<tspan fill="#9a9a96" font-weight="500"> ↓↓</tspan>'
    if delta <= -3: return '<tspan fill="#9a9a96" font-weight="500"> ↓↓↓</tspan>'
    return ''

_chart_w = 720; _bar_h = 22; _gap = 6; _label_w = 130; _bar_max_w = _chart_w - _label_w - 80
_max_count = max((r['curr'] for r in _trend_top), default=1) or 1
_chart_h = len(_trend_top) * (_bar_h + _gap) + 10
_svg_bars = []
for i, r in enumerate(_trend_top):
    y = i * (_bar_h + _gap) + 5
    bw_curr = (r['curr'] / _max_count) * _bar_max_w if r['curr'] else 0
    bw_avg  = (r['avg']  / _max_count) * _bar_max_w if r['avg']  else 0
    _bar_color = PALETTE_HEX.get(r['key']) or cuisine_color(r['key'])
    _svg_bars.append(
        f'<text x="{_label_w - 10}" y="{y + _bar_h*0.7}" text-anchor="end" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="12.5" font-weight="600" fill="#1a1a1a">{_esc(r["label"])}</text>'
        f'<rect x="{_label_w}" y="{y + 4}" width="{bw_avg:.1f}" height="{_bar_h - 8}" fill="#ebe9e4" rx="2"/>'
        f'<rect x="{_label_w}" y="{y}" width="{bw_curr:.1f}" height="{_bar_h}" fill="{_bar_color}" rx="3"/>'
        f'<text x="{_label_w + max(bw_curr, bw_avg) + 8}" y="{y + _bar_h*0.7}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="11.5" font-weight="700" fill="#1a1a1a">{r["curr"]}{_movement_arrow(r["delta"])}</text>'
    )
_trends_chart_svg = (
    f'<svg viewBox="0 0 {_chart_w} {_chart_h}" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Toronto restaurant registrations by cuisine, this month vs 12-month average, with month-over-month movement" '
    f'style="width:100%;max-width:{_chart_w}px;height:auto;display:block">'
    + ''.join(_svg_bars)
    + '</svg>'
)

# Placeholder - real event computation happens after _y3_rows and
# _long_top_6 exist further down. _callouts_html is set below.
_callouts_html = ''

# Compose the trends page
_trends_label = _cal.month_name[_dm_month] + f' {_dm_year}'
_today_label = _dispatch_today.strftime('%B %-d, %Y')  # e.g. "June 1, 2026"
_trends_canonical = f'{SITE_BASE}/trends'
_trends_title = f'Toronto\'s Freshest Restaurants, updated daily | NowServingTO ({_today_label})'
_trends_desc = (f'The newest restaurants licensed in Toronto, by cuisine and neighbourhood, '
                f'including the Uyghur, Tamil, and Salvadoran spots the mainstream food press never covers. '
                f'Updated {_today_label} from City open data.')
# Twitter intent: prefilled tweet with summary + URL. Numbers match the
# Last-3-months treemap on the page so a user clicking Share doesn't get
# a different leaderboard than the one they're looking at. Tweet text is
# built later (after _short_rows exists); placeholder here.
_tweet_intent = ''  # filled below after _short_rows is built
_trends_h1 = (
    '<h1 class="sub">Toronto\'s Freshest Restaurants'
    '<span class="hl">updated daily from the City of Toronto Registry</span></h1>'
    '<div class="trends-deck">New permits sourced from City of Toronto open datasets, '
    'cross-referenced with DineSafe and social media signals to bring you the '
    'freshest, newest kitchens in the city.</div>'
)
# 3-year cuisine leaderboard. Pulls from LLM cuisine cache (populated
# by `python3 tools/llm_classify_batch.py --years=3`). Walks the FULL
# CSV (no date filter on dispatch's seen_entries) and counts per-cuisine
# per-month over the past 36 months. Requires the historical batch to
# have been run; otherwise this section gracefully shows only the
# months that have classifications.
_y3_months_back = 36
_y3_months = [_ym_back(_dispatch_today, i) for i in range(_y3_months_back, 0, -1)]
from datetime import timedelta as _td3
_y3_cutoff_date = _dispatch_today - _td3(days=365 * 3)
_y3_cuisine_count = _dd(int)
_y3_total = 0
with open(CSV_PATH, encoding='utf-8', errors='replace') as _f:
    for _row in csv.DictReader(_f):
        if (_row.get('Category') or '').strip() not in FOOD_CATS: continue
        if (_row.get('Cancel Date') or '').strip(): continue  # exclude cancelled
        _iss_s = (_row.get('Issued') or '').split(' ')[0]
        _iss_d = parse_d(_iss_s)
        if not _iss_d or _iss_d < _y3_cutoff_date: continue
        _name = (_row.get('Operating Name') or '').strip()
        _addr1 = (_row.get('Licence Address Line 1') or '').strip()
        _addr3 = (_row.get('Licence Address Line 3') or '').strip()
        _addr = (_addr1 + ' ' + _addr3).strip() or '-'
        _ck = cache_key(_name, _addr)
        _llm = LLM_CACHE.get(_ck) or {}
        if _llm.get('status') != 'ok': continue
        _cs = _llm.get('cuisines') or ([_llm.get('cuisine')] if _llm.get('cuisine') else [])
        # Skip 'unknown' (chain stubs + unclassifiable)
        _cs = [c for c in _cs if c and c != 'unknown']
        if not _cs: continue
        _y3_total += 1
        for _c in _cs:
            _y3_cuisine_count[_c] += 1
_y3_rows = sorted(
    [{'key': _c, 'label': CUISINE_LABEL.get(_c, _c.replace('_', ' ').title()),
      'count': _n, 'pct': round((_n / _y3_total) * 100, 1) if _y3_total else 0}
     for _c, _n in _y3_cuisine_count.items()],
    key=lambda r: -r['count']
)[:10]

# Render as horizontal bars (numbered ranks, cuisine-colored).
_y3_chart_h = len(_y3_rows) * 30 + 12 if _y3_rows else 0
_y3_label_w = 32  # rank number column
_y3_cuisine_w = 140
_y3_bar_max = _chart_w - _y3_label_w - _y3_cuisine_w - 70
_y3_max_n = max((r['count'] for r in _y3_rows), default=1) or 1
_y3_svg_parts = []
for i, r in enumerate(_y3_rows):
    y = i * 30 + 8
    bw = (r['count'] / _y3_max_n) * _y3_bar_max
    color = PALETTE_HEX.get(r['key']) or cuisine_color(r['key'])
    _y3_svg_parts.append(
        f'<text x="0" y="{y + 16}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="13" font-weight="800" fill="#9a9a96">#{i+1}</text>'
        f'<text x="{_y3_label_w}" y="{y + 16}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="13" font-weight="700" fill="#1a1a1a">{_esc(r["label"])}</text>'
        f'<rect x="{_y3_label_w + _y3_cuisine_w}" y="{y + 4}" width="{bw:.1f}" height="22" fill="{color}" rx="3"/>'
        f'<text x="{_y3_label_w + _y3_cuisine_w + bw + 8}" y="{y + 19}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="12" font-weight="700" fill="#1a1a1a">{r["count"]} <tspan fill="#6f6e6a" font-weight="500">({r["pct"]}%)</tspan></text>'
    )
_y3_chart_svg = (
    f'<svg viewBox="0 0 {_chart_w} {_y3_chart_h}" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Top 10 cuisines by new registrations, last 3 years" '
    f'style="width:100%;max-width:{_chart_w}px;height:auto;display:block">'
    + ''.join(_y3_svg_parts)
    + '</svg>'
) if _y3_rows else ''

# Composability check - if no entries classified yet, surface a stub
# explaining what's needed to populate this section
if _y3_total > 0 and len(_y3_rows) >= 3:
    _y3_section = (
        '<section class="trends-section">'
        '<h2 class="trends-h2">The 3-year picture</h2>'
        f'<p class="trends-pies-note" style="text-align:left;margin-bottom:14px">'
        f'{_y3_total:,} classified openings in the past 3 years. '
        f'Top cuisine ({_esc(_y3_rows[0]["label"])}) at {_y3_rows[0]["pct"]}%. '
        'Contrast with the 6-month view above to see who\'s currently moving against the longer baseline.</p>'
        f'<div class="trends-chart-wrap">{_y3_chart_svg}</div>'
        '</section>'
    )
else:
    _y3_section = (
        '<section class="trends-section">'
        '<h2 class="trends-h2">The 3-year picture</h2>'
        f'<p class="trends-pies-note" style="text-align:left">'
        f'Currently classified: {_y3_total:,} openings in the past 3 years '
        f'(of ~7,000+ total). Run <code>python3 tools/llm_classify_batch.py --years=3</code> '
        'to backfill historical cuisine classification (~$1 Haiku spend, one-time).</p>'
        '</section>'
    )

# 16-year macro chart: total food licences per year, 2010-present.
# Pure CSV-driven (no LLM dependency), shows COVID crater + recovery.
# Designed to fill out /trends with editorial backbone and visible
# historical context beneath the recent cuisine chart.
_macro_years = list(range(2010, _dispatch_today.year + 1))
_macro_counts = _dd(int)
with open(CSV_PATH, encoding='utf-8', errors='replace') as f:
    for _row in csv.DictReader(f):
        if (_row.get('Category') or '').strip() not in FOOD_CATS: continue
        _iss_s = (_row.get('Issued') or '').split(' ')[0]
        if len(_iss_s) < 4: continue
        try:
            _y = int(_iss_s[:4])
            if _y in _macro_years:
                _macro_counts[_y] += 1
        except (ValueError, TypeError):
            continue
_m_chart_w = 720; _m_bar_w = 32; _m_gap = 6; _m_chart_h = 210
_m_max = max(_macro_counts.values()) if _macro_counts else 1
_m_left_pad = 12; _m_bottom_pad = 28; _m_top_pad = 22
_m_inner_h = _m_chart_h - _m_top_pad - _m_bottom_pad
_m_bars = []
for _i, _y in enumerate(_macro_years):
    _cnt = _macro_counts.get(_y, 0)
    _x = _m_left_pad + _i * (_m_bar_w + _m_gap)
    _bh = (_cnt / _m_max) * _m_inner_h if _cnt else 0
    _by = _m_top_pad + (_m_inner_h - _bh)
    _is_covid = _y == 2020
    _is_partial = _y == _dispatch_today.year and _dispatch_today.month < 12
    _color = '#e84e3a' if _is_covid else ('#cfcfcf' if _is_partial else '#3a3a38')
    _m_bars.append(
        f'<rect x="{_x}" y="{_by:.1f}" width="{_m_bar_w}" height="{_bh:.1f}" fill="{_color}" rx="2"/>'
        f'<text x="{_x + _m_bar_w/2}" y="{_by - 5:.1f}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="9.5" font-weight="700" fill="#1a1a1a">{_cnt:,}</text>'
        f'<text x="{_x + _m_bar_w/2}" y="{_m_chart_h - 10}" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="10" fill="#6f6e6a">{_y}</text>'
    )
_macro_chart_svg = (
    f'<svg viewBox="0 0 {_m_chart_w} {_m_chart_h}" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Toronto food licences issued per year, 2010 to present" '
    f'style="width:100%;max-width:{_m_chart_w}px;height:auto;display:block">'
    + ''.join(_m_bars)
    + '</svg>'
)
# Editorial context with the COVID story numerically grounded.
_pre_covid_avg = sum(_macro_counts.get(_y, 0) for _y in range(2015, 2020)) // 5
_covid_2020 = _macro_counts.get(2020, 0)
_covid_pct = round((1 - _covid_2020 / _pre_covid_avg) * 100) if _pre_covid_avg else 0
_recovery_year = next((_y for _y in range(2021, _dispatch_today.year + 1)
                       if _macro_counts.get(_y, 0) >= _pre_covid_avg * 0.95), None)
_macro_context = (
    f"Toronto issues ~{_pre_covid_avg:,} new restaurant licences per year on average "
    f"(2015-19 baseline). COVID 2020 crashed it to {_covid_2020:,} ({_covid_pct}% drop). "
    + (f"Volume recovered to baseline by {_recovery_year}. " if _recovery_year else "Volume has not yet returned to the baseline. ")
    + f"Coral bar = 2020 COVID year. Grey bar = {_dispatch_today.year} (partial)."
)

# Biggest-mover hero stat - the cuisine that "really had a month".
# Rendered as a single-slice pie chart showing that cuisine's share
# of TOTAL new openings this month, beside the editorial callout.
# The pie visual makes the "slice of the pie" framing literal and
# screenshot-friendly.
import math as _math
def _pie_slice_path(pct, cx, cy, r):
    """SVG path for a single pie slice starting at 12 o'clock,
    extending clockwise by pct% of full circle."""
    angle = (pct / 100.0) * 2 * _math.pi
    end_x = cx + r * _math.sin(angle)
    end_y = cy - r * _math.cos(angle)
    large_arc = 0 if pct <= 50 else 1
    return f'M{cx},{cy} L{cx},{cy - r} A{r},{r} 0 {large_arc},1 {end_x:.2f},{end_y:.2f} Z'

# Top 3 by share of this month's openings - each gets its own pie.
# Separate pies (not a unified pie) so the eye does the comparison
# and the screenshot-share unit is the row of 3. Cuisine name beneath
# each; percentage in the slice's center. The visual ratio between
# the three slices does all the editorial work.
# Dominant flag color per cuisine. Replaces PALETTE_HEX in the trends
# pies + VS card so each cuisine's pie slice reads as a flag-color
# association. Where two flags share a dominant color (Italian/Mexican
# both green/white/red, Chinese/Japanese both red, etc.), assignments
# differentiate: Italian = bright green, Mexican = chili red, Chinese
# = vivid red, Japanese = darker red, etc. Falls back to PALETTE_HEX /
# cuisine_color for cuisines without a flag-color mapping.
def _flag_svg(cuisine_key):
    F = {
        'italian':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#009246"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#ce2b37"/></svg>',
        'indian':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#ff9933"/><rect y="6.67" width="30" height="6.67" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#138808"/><circle cx="15" cy="10" r="2" fill="none" stroke="#000088" stroke-width="0.4"/></svg>',
        'mexican':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#003f1f"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#a91b0d"/><ellipse cx="15" cy="10" rx="2.4" ry="1.8" fill="#5a3a1a" opacity="0.85"/></svg>',
        'french':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#002395"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#ed2939"/></svg>',
        'chinese':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#de2910"/><polygon points="6,4 7,7 10,7 7.5,9 8.5,12 6,10 3.5,12 4.5,9 2,7 5,7" fill="#ffde00"/></svg>',
        'japanese':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="6" fill="#bc002d"/></svg>',
        'korean':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="5" fill="#003478"/><path d="M10,10 A5,5 0 0 1 20,10 A2.5,2.5 0 0 0 15,10 A2.5,2.5 0 0 1 10,10" fill="#cd2e3a"/></svg>',
        'vietnamese': '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#da251d"/><polygon points="15,5 16.5,9.5 21,9.5 17.3,12.3 18.7,17 15,14 11.3,17 12.7,12.3 9,9.5 13.5,9.5" fill="#ffff00"/></svg>',
        'thai':       '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="4" fill="#ed1c24"/><rect y="4" width="30" height="3" fill="#fff"/><rect y="7" width="30" height="6" fill="#241d4f"/><rect y="13" width="30" height="3" fill="#fff"/><rect y="16" width="30" height="4" fill="#ed1c24"/></svg>',
        'german':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#000"/><rect y="6.67" width="30" height="6.67" fill="#dd0000"/><rect y="13.33" width="30" height="6.67" fill="#ffce00"/></svg>',
        'polish':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="10" fill="#fff"/><rect y="10" width="30" height="10" fill="#dc143c"/></svg>',
        'ukrainian':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="10" fill="#005bbb"/><rect y="10" width="30" height="10" fill="#ffd500"/></svg>',
        'russian':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#fff"/><rect y="6.67" width="30" height="6.67" fill="#0033a0"/><rect y="13.33" width="30" height="6.67" fill="#da291c"/></svg>',
        'spanish':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="5" fill="#aa151b"/><rect y="5" width="30" height="10" fill="#f1bf00"/><rect y="15" width="30" height="5" fill="#aa151b"/></svg>',
        'portuguese': '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="12" height="20" fill="#006600"/><rect x="12" width="18" height="20" fill="#ff0000"/></svg>',
        'greek':      '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#fff"/><rect y="2.2" width="30" height="2.2" fill="#0d5eaf"/><rect y="6.6" width="30" height="2.2" fill="#0d5eaf"/><rect y="11" width="30" height="2.2" fill="#0d5eaf"/><rect y="15.4" width="30" height="2.2" fill="#0d5eaf"/><rect width="12" height="11" fill="#0d5eaf"/><rect x="4.8" width="2.4" height="11" fill="#fff"/><rect y="4.4" width="12" height="2.2" fill="#fff"/></svg>',
        'turkish':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#e30a17"/><circle cx="11" cy="10" r="4" fill="#fff"/><circle cx="12.4" cy="10" r="3.4" fill="#e30a17"/></svg>',
        'pakistani':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#01411c"/><rect width="8" height="20" fill="#fff"/></svg>',
        'bangladeshi':'<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#006a4e"/><circle cx="13.5" cy="10" r="5" fill="#f42a41"/></svg>',
        'persian':    '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#239f40"/><rect y="6.67" width="30" height="6.67" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#da0000"/></svg>',
        'lebanese':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="5" fill="#ed1c24"/><rect y="5" width="30" height="10" fill="#fff"/><rect y="15" width="30" height="5" fill="#ed1c24"/></svg>',
        'ethiopian':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#078930"/><rect y="6.67" width="30" height="6.67" fill="#fcdd09"/><rect y="13.33" width="30" height="6.67" fill="#da121a"/></svg>',
        'eritrean':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><polygon points="0,0 30,10 0,20" fill="#ea0437"/><polygon points="0,0 30,0 30,10" fill="#12ad2b"/><polygon points="0,10 30,10 0,20" fill="#418fde"/></svg>',
        'ghanaian':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#ce1126"/><rect y="6.67" width="30" height="6.67" fill="#fcd116"/><rect y="13.33" width="30" height="6.67" fill="#006b3f"/></svg>',
        'nigerian':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#008751"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#008751"/></svg>',
        'jamaican':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#fed100"/><polygon points="0,0 15,10 0,20" fill="#009b3a"/><polygon points="30,0 15,10 30,20" fill="#009b3a"/><polygon points="0,0 15,10 30,0" fill="#000"/><polygon points="0,20 15,10 30,20" fill="#000"/></svg>',
        'trinidadian':'<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#ce1126"/><polygon points="0,3 27,20 30,20 30,17 3,0 0,0" fill="#fff"/><polygon points="0,6 24,20 27,20 27,18 3,2 0,2" fill="#000"/></svg>',
        'guyanese':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#009e49"/><polygon points="0,0 30,10 0,20" fill="#fcd116"/><polygon points="0,0 22,10 0,20" fill="#ce1126"/></svg>',
        'colombian':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="10" fill="#fcd116"/><rect y="10" width="30" height="5" fill="#003893"/><rect y="15" width="30" height="5" fill="#ce1126"/></svg>',
        'venezuelan': '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#fcd116"/><rect y="6.67" width="30" height="6.67" fill="#00247d"/><rect y="13.33" width="30" height="6.67" fill="#ce1126"/></svg>',
        'peruvian':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#d91023"/><rect x="10" width="10" height="20" fill="#fff"/><rect x="20" width="10" height="20" fill="#d91023"/></svg>',
        'argentinian':'<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="6.67" fill="#74acdf"/><rect y="6.67" width="30" height="6.67" fill="#fff"/><rect y="13.33" width="30" height="6.67" fill="#74acdf"/></svg>',
        'brazilian':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#009c3b"/><polygon points="15,3 27,10 15,17 3,10" fill="#fedf00"/><circle cx="15" cy="10" r="3" fill="#002776"/></svg>',
        'afghan':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="10" height="20" fill="#000"/><rect x="10" width="10" height="20" fill="#d32011"/><rect x="20" width="10" height="20" fill="#007a36"/></svg>',
        'somali':     '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#4189dd"/><polygon points="15,6 16,9 19,9 16.5,11 17.5,14 15,12 12.5,14 13.5,11 11,9 14,9" fill="#fff"/></svg>',
        'filipino':   '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="10" fill="#0038a8"/><rect y="10" width="30" height="10" fill="#ce1126"/><polygon points="0,0 0,20 17,10" fill="#fff"/></svg>',
        'malaysian':  '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#cc0001"/><rect width="30" height="2.86" fill="#cc0001"/><rect y="2.86" width="30" height="2.86" fill="#fff"/><rect y="5.71" width="30" height="2.86" fill="#cc0001"/><rect y="8.57" width="30" height="2.86" fill="#fff"/><rect y="11.43" width="30" height="2.86" fill="#cc0001"/><rect y="14.29" width="30" height="2.86" fill="#fff"/><rect y="17.14" width="30" height="2.86" fill="#cc0001"/><rect width="15" height="11.43" fill="#000066"/></svg>',
        'indonesian': '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="10" fill="#ce1126"/><rect y="10" width="30" height="10" fill="#fff"/></svg>',
        'sri_lankan': '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#8d153a"/><rect width="6" height="20" fill="#00534e"/><rect x="6" width="3" height="20" fill="#ff8200"/></svg>',
        'tamil':      '<svg class="cuisine-flag" viewBox="0 0 30 20" aria-hidden="true"><rect width="30" height="20" fill="#ce1126"/><polygon points="15,7 16,10 19,10 16.5,12 17.5,15 15,13 12.5,15 13.5,12 11,10 14,10" fill="#fcd116"/></svg>',
        'caribbean':  '',  # umbrella, no single flag
        'middle_east':'',  # umbrella
        'latin':      '',  # umbrella
        'south_asian':'',  # umbrella
    }
    return F.get(cuisine_key, '')


# DRY pie card builder - used for both short-term and long-term rows.
# Pie slice color = dominant flag color (so the visual reads as the
# country/cuisine's flag color at a glance).
def _build_pie_card(label, key, pct, aria_period):
    color = _flag_color(key)
    slice_path = _pie_slice_path(pct, 50, 50, 45)
    svg = (
        '<svg viewBox="0 0 100 100" width="105" height="105" '
        'xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{_esc(label)}: {pct} percent of {_esc(aria_period)}">'
        f'<circle cx="50" cy="50" r="45" fill="#ebe9e4"/>'
        f'<path d="{slice_path}" fill="{color}"/>'
        f'<text x="50" y="58" text-anchor="middle" '
        'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" '
        f'font-size="22" font-weight="800" fill="#1a1a1a">{pct}%</text>'
        '</svg>'
    )
    name_html = f'<a href="/cuisine/{_esc(key)}" class="trends-pie-link">{_esc(label)}</a>'
    # No flag SVG beneath the name - the pie slice color IS the flag now.
    return f'<div class="trends-pie-card">{svg}<div class="trends-pie-name">{name_html}</div></div>'

# Short-term: last 90 days from verified seen_entries (currently-operating).
# This is what's HAPPENING - the dramatic, recent shifts.
_short_months_n = 3
_short_window = [_ym_back(_dispatch_today, i) for i in range(_short_months_n, 0, -1)]
_short_cuisine_count = _dd(int)
_short_total = 0
for _e in seen_entries.values():
    _iso = _e.get('issuedDate') or ''
    if len(_iso) < 7 or _iso[:7] not in _short_window: continue
    _cs = [c for c in (_e.get('cuisines') or ([_e.get('cuisine')] if _e.get('cuisine') else []))
           if c and c != 'unknown']
    if not _cs: continue
    _short_total += 1
    for _c in _cs:
        _short_cuisine_count[_c] += 1
_short_rows = sorted(
    [{'key': _c, 'label': CUISINE_LABEL.get(_c, _c.replace('_', ' ').title()),
      'count': _n, 'pct': round((_n / _short_total) * 100) if _short_total else 0}
     for _c, _n in _short_cuisine_count.items()],
    key=lambda r: -r['count']
)[:6]
_short_pies = ''.join(
    _build_pie_card(r['label'], r['key'], r['pct'], 'last 90 days')
    for r in _short_rows
)
# Long-term pies (3-year top 6 from already-computed _y3_rows)
_long_top_6 = _y3_rows[:6] if _y3_rows else []
_long_pies = ''.join(
    _build_pie_card(r['label'], r['key'], int(r['pct']), 'last 3 years')
    for r in _long_top_6
)

# --- Squarified treemap for the full 3-year cuisine landscape ---------
# Shows every cuisine sized by count, coloured by flag dominant, so the
# long tail is visible alongside the giants. Squarified layout (Bruls et
# al. 2000) — keeps rectangles close to square so labels remain readable.
def _treemap_worst_ratio(row, side):
    s = sum(v for v, _ in row)
    if s <= 0: return float('inf')
    mn = min(v for v, _ in row)
    mx = max(v for v, _ in row)
    return max((side*side*mx)/(s*s), (s*s)/(side*side*mn))

def _treemap_squarify(values, x, y, w, h, out):
    if not values: return
    if len(values) == 1:
        v, p = values[0]
        out.append(((x, y, w, h), p))
        return
    side = min(w, h) if min(w, h) > 0 else 1
    row = [values[0]]
    rest = values[1:]
    best = _treemap_worst_ratio(row, side)
    while rest:
        cand = row + [rest[0]]
        cw = _treemap_worst_ratio(cand, side)
        if cw <= best:
            row, rest, best = cand, rest[1:], cw
        else:
            break
    row_sum = sum(v for v, _ in row)
    if row_sum <= 0: return
    if w >= h:
        col_w = row_sum / h
        cy = y
        for v, p in row:
            ch = v / col_w if col_w > 0 else 0
            out.append(((x, cy, col_w, ch), p))
            cy += ch
        _treemap_squarify(rest, x + col_w, y, w - col_w, h, out)
    else:
        row_h = row_sum / w
        cx = x
        for v, p in row:
            cw = v / row_h if row_h > 0 else 0
            out.append(((cx, y, cw, row_h), p))
            cx += cw
        _treemap_squarify(rest, x, y + row_h, w, h - row_h, out)

def _build_cuisine_treemap_svg(cuisine_counts, width=720, height=420):
    # Filter to keys that have a real /cuisine/<key> page (CUISINE_LABEL is
    # the source of truth — banned slugs like 'cajun'/'american' linger in
    # legacy LLM cache rows but redirect to / via .htaccess, so they'd be
    # dead tiles).
    items = [(n, k) for k, n in cuisine_counts.items()
             if n > 0 and k in CUISINE_LABEL]
    items.sort(key=lambda x: -x[0])
    total = sum(n for n, _ in items)
    if not total: return ''
    scale = (width * height) / total
    scaled = [(n * scale, k) for n, k in items]
    rects = []
    _treemap_squarify(scaled, 0, 0, width, height, rects)
    parts = []
    for (rx, ry, rw, rh), key in rects:
        count = cuisine_counts.get(key, 0)
        label = CUISINE_LABEL.get(key, key.replace('_', ' ').title())
        pct = round(count / total * 100, 1)
        color = _flag_color(key) or '#7a746a'
        link = f'/cuisine/{_esc(key)}'
        # Format pct for display: show 1 decimal if <10%, integer otherwise
        pct_disp = f'{pct:.1f}%' if pct < 10 else f'{round(pct)}%'
        parts.append(
            f'<a href="{link}"><title>{_esc(label)}: {pct_disp}</title>'
            f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{rw:.2f}" height="{rh:.2f}" '
            f'fill="{color}" stroke="#faf7ee" stroke-width="1.5"/>'
        )
        # Label inside box if it fits. Heuristic: name shows if box >= 60x22,
        # count shows if also >= 40 tall.
        if rw >= 55 and rh >= 22:
            fs = max(10, min(16, int(min(rh, rw / max(1, len(label) * 0.55)) * 0.45)))
            max_chars = max(3, int(rw / (fs * 0.55)))
            disp = label if len(label) <= max_chars else label[:max_chars - 1] + '…'
            parts.append(
                f'<text x="{rx + 7:.2f}" y="{ry + fs + 5:.2f}" '
                f'font-family="-apple-system,Helvetica,Arial,sans-serif" '
                f'font-size="{fs}" font-weight="800" fill="#fff" '
                f'pointer-events="none" letter-spacing="-0.3">{_esc(disp)}</text>'
            )
            if rh >= 42:
                parts.append(
                    f'<text x="{rx + 7:.2f}" y="{ry + fs * 2 + 8:.2f}" '
                    f'font-family="ui-monospace,Menlo,Consolas,monospace" '
                    f'font-size="{max(9, fs - 3)}" font-weight="600" '
                    f'fill="rgba(255,255,255,0.88)" pointer-events="none">'
                    f'{pct_disp}</text>'
                )
        parts.append('</a>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Toronto cuisine landscape — all cuisines sized by 3-year licence count">'
        + ''.join(parts) + '</svg>'
    )

_long_treemap_svg = _build_cuisine_treemap_svg(_y3_cuisine_count)
_short_treemap_svg = _build_cuisine_treemap_svg(_short_cuisine_count)

# Build the tweet text now that _short_rows + _short_total exist. Uses
# the same 90-day window the on-page Last-3-months treemap renders, so
# the share copy mirrors what the visitor is looking at. Label is the
# explicit date range, not a single month, so the numbers don't read
# like one-month totals (the prior version said "May 2026: Indian 33"
# while 33 was actually a 6-month rolling sum — confusing).
# Tweet copy: placeholder; rebuilt later in the file after _lm_total +
# _y3_start_year are computed, so the swagger-voice version can use the
# same dynamic numbers as the lede without ordering errors.
_tweet_lines = ["Toronto's hottest new cuisines this quarter:"]
for _r in _short_rows[:5]:
    _tweet_lines.append(f"• {_r['label']}: {_r['count']} ({_r['pct']}%)")
_tweet_lines.append(f"\n→ Browse every new spot by cuisine + 'hood:\n{SITE_BASE}/trends/{_dispatch_today.year}-{_dispatch_today.month:02d}")
_tweet_lines.append("\n#TorontoEats #TorontoFoodie")
_tweet_intent = 'https://twitter.com/intent/tweet?text=' + quote_plus('\n'.join(_tweet_lines))

# Toronto CMA heritage population percentages (2021 Census, ethnic
# origin / visible minority — multiple-origin responses included, so
# sums > 100%). Used to compute a representation index per cuisine:
# openings % / population % = whether the cuisine is over- or
# under-served relative to its heritage community in Toronto.
# Source: Statistics Canada 2021 Census of Population, Toronto CMA
# (Code: 535). Cuisines without a clear heritage-pop bucket are
# omitted; methodology imperfections noted in the page footer.
CUISINE_POPULATION_PCT_TO_CMA = {
    'italian': 7.0, 'chinese': 11.6, 'indian': 7.5, 'pakistani': 1.8,
    'bangladeshi': 0.7, 'tamil': 2.4, 'sri_lankan': 2.4, 'filipino': 5.3,
    'vietnamese': 1.5, 'korean': 1.7, 'japanese': 0.5, 'jamaican': 2.8,
    'trinidadian': 1.2, 'guyanese': 1.5, 'caribbean': 3.0,
    'portuguese': 3.5, 'greek': 1.8, 'spanish': 0.8, 'mexican': 0.6,
    'colombian': 0.5, 'venezuelan': 0.4, 'peruvian': 0.3,
    'argentinian': 0.2, 'persian': 1.4, 'arab': 2.5, 'lebanese': 0.7,
    'turkish': 0.4, 'afghan': 0.5, 'middle_east': 3.0, 'ethiopian': 0.5,
    'eritrean': 0.4, 'somali': 0.5, 'nigerian': 0.8, 'ghanaian': 0.4,
    'french': 0.5, 'german': 1.2, 'polish': 2.8, 'ukrainian': 2.0,
    'russian': 1.2, 'jewish_deli': 3.0, 'thai': 0.3, 'tibetan': 0.2,
    'nepalese': 0.4, 'south_asian': 14.0, 'latin': 3.0,
}

# Compute representation rows for top cuisines that have a population estimate
_rep_rows = []
for r in _y3_rows:
    pop_pct = CUISINE_POPULATION_PCT_TO_CMA.get(r['key'])
    if pop_pct is None or pop_pct == 0: continue
    open_pct = r['pct']
    ratio = open_pct / pop_pct
    _rep_rows.append({
        'key': r['key'], 'label': r['label'],
        'open_pct': open_pct, 'pop_pct': pop_pct, 'ratio': ratio,
    })
_rep_top = sorted(_rep_rows, key=lambda r: -r['open_pct'])[:10]

# Build the representation chart HTML (flexbox rows, no SVG complexity)
def _rep_status_label(ratio):
    if ratio >= 1.5:  return ('OVER', '#3fb37f', f'{ratio:.1f}× over')
    if ratio >= 1.15: return ('OVER', '#3fb37f', f'{ratio:.1f}× over')
    if ratio <= 0.65: return ('UNDER', '#e84e3a', f'{ratio:.1f}× under')
    if ratio <= 0.85: return ('UNDER', '#e84e3a', f'{ratio:.2f}× under')
    return ('BALANCED', '#888', f'{ratio:.1f}× balanced')

_rep_max = max((max(r['open_pct'], r['pop_pct']) for r in _rep_top), default=1) or 1
_rep_html_rows = []
for r in _rep_top:
    color = PALETTE_HEX.get(r['key']) or cuisine_color(r['key'])
    bw_open = (r['open_pct'] / _rep_max) * 100
    bw_pop = (r['pop_pct'] / _rep_max) * 100
    _status, _status_color, _status_label = _rep_status_label(r['ratio'])
    _rep_html_rows.append(
        f'<div class="rep-row">'
        f'<a class="rep-cuisine" href="/cuisine/{_esc(r["key"])}">{_esc(r["label"])}</a>'
        f'<div class="rep-bars">'
        f'<div class="rep-bar rep-bar-open" style="width:{bw_open:.1f}%;background:{color}">'
        f'<span class="rep-bar-label">{r["open_pct"]:.1f}% openings</span></div>'
        f'<div class="rep-bar rep-bar-pop" style="width:{bw_pop:.1f}%">'
        f'<span class="rep-bar-label">{r["pop_pct"]:.1f}% Toronto pop</span></div>'
        f'</div>'
        f'<div class="rep-ratio" style="color:{_status_color}">{_status_label}</div>'
        f'</div>'
    )

_rep_section = (
    '<section class="trends-section trends-section-rep">'
    '<h2 class="trends-h2">Representation index <span class="trends-h2-sub">· openings vs heritage population</span></h2>'
    + '<div class="rep-chart">' + ''.join(_rep_html_rows) + '</div>'
    + '<p class="rep-note">For each cuisine: <b>colored bar</b> = share of Toronto restaurant openings (36 months). '
      '<b>Grey bar</b> = share of Toronto CMA heritage population (2021 Census). '
      'Ratio = openings% ÷ population%. <b>Over</b> = more restaurants per capita than the city average. '
      '<b>Under</b> = less. Cuisine ≠ ethnicity, generations matter, supply ≠ demand directly. '
      'Use as observation, not judgment. '
      '<a href="https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/page.cfm?Lang=E&DGUIDList=2021S0503535">StatsCan source</a>.</p>'
    + '</section>'
) if _rep_top else ''

# Wrestling-style event callouts (now that _long_top_6 + _short_rows
# + _y3_rows are all defined). Each event carries (tag, cuisine_key,
# cuisine_label, message_after_label) so the rendering can wrap the
# cuisine name in an anchor link to its /cuisine/<key> page.
_events = []
_y3_keys_top6 = {r['key'] for r in _long_top_6}
_y3_count_by_key = {y['key']: y['count'] for y in _y3_rows}
_drought_by_key = {}
for r in _trend_rows:
    if r['last_month'] >= 1 and all(r['by_m'].get(m, 0) == 0 for m in _recent_3):
        gap = 0
        for i in range(2, 12):
            m = _ym_back(_dispatch_today, i)
            if r['by_m'].get(m, 0) > 0:
                gap = i - 1
                break
            gap = i
        _drought_by_key[r['key']] = (r['label'], gap)

for r in _short_rows:
    if r['key'] not in _y3_keys_top6 and r['count'] >= 2:
        _events.append(('UPSET', r['key'], r['label'],
                        f"cracked the short-term top 6 with {r['count']} new registrations, despite missing the 3-year top 6"))
for key, (lbl, gap) in _drought_by_key.items():
    _events.append(('DROUGHT BROKEN', key, lbl, f"first new kitchen in {gap}+ months"))
for r in _trend_rows:
    if r['last_month'] >= 2 and r['avg'] > 0 and r['last_month'] >= r['avg'] * 2:
        _events.append(('HOT STREAK', r['key'], r['label'],
                        f"hit {r['last_month']} new registrations last month (vs {round(r['avg'], 1)}/mo average)"))
for r in _short_rows:
    if r['count'] >= 2:
        y3_count = _y3_count_by_key.get(r['key'], 0)
        if 0 < y3_count < 30:
            _events.append(('UNDERDOG MOVE', r['key'], r['label'],
                            f"got {r['count']} new registrations in 90 days vs only {y3_count} total in the past 3 years"))
for r in _short_rows:
    y3_count = _y3_count_by_key.get(r['key'], 0)
    if r['count'] >= 1 and y3_count <= 1:
        _events.append(('FIRST IN 3 YEARS', r['key'], r['label'],
                        f"just registered, vanishingly rare in Toronto's recent food history"))

# Dedup by cuisine key (one cuisine = one event max)
_seen = set()
_events_filtered = []
for tag, key, lbl, msg in _events:
    if key in _seen: continue
    _seen.add(key)
    _events_filtered.append((tag, key, lbl, msg))

if _events_filtered:
    _callouts_html = (
        '<section class="trends-section trends-section-news">'
        '<div class="trends-events">'
        f'<h3 class="trends-events-h">{_esc(_cal.month_name[_dispatch_today.month])} {_dispatch_today.year}</h3>'
        '<ul class="trends-events-list">'
        + ''.join(
            f'<li><span class="trends-events-tag">{_esc(tag)}</span> '
            f'<a class="trends-events-cuisine" href="/cuisine/{_esc(key)}">{_esc(lbl)}</a> '
            f'{_esc(msg)}.</li>'
            for tag, key, lbl, msg in _events_filtered[:6]
        )
        + '</ul></div>'
        '</section>'
    )

# Crown SVG: gold 5-point crown, used above both #1 and #2 in the
# hero VS card. Same crown both sides = equal footing.
_crown_svg = (
    '<svg class="trends-vs-medal trends-vs-crown" viewBox="0 0 48 38" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M4,32 L4,16 L13,22 L20,6 L24,20 L28,6 L35,22 L44,16 L44,32 Z" fill="#e6b800" stroke="#a8821f" stroke-width="1.5" stroke-linejoin="round"/>'
    '<circle cx="20" cy="6" r="2.8" fill="#e6b800" stroke="#a8821f" stroke-width="1"/>'
    '<circle cx="28" cy="6" r="2.8" fill="#e6b800" stroke="#a8821f" stroke-width="1"/>'
    '<circle cx="24" cy="20" r="2.4" fill="#c8201f"/>'
    '</svg>'
)

# Hero VS card: LAST MONTH's #1 vs #2 (the most-recent-completed-month
# headline). Same metric / same window for equal footing. Flags behind
# cuisine names at ~45% opacity. Single-month sample is noisy but the
# editorial purpose is "who's hot RIGHT NOW" — the noise IS the news.
_lm_ym = _ym_back(_dispatch_today, 1)  # most recently completed month
_lm_label = f'{_cal.month_name[int(_lm_ym[-2:])]} {_lm_ym[:4]}'
_lm_cuisine_count = _dd(int)
_lm_total = 0
for _e in seen_entries.values():
    _iso = _e.get('issuedDate') or ''
    if not _iso.startswith(_lm_ym): continue
    _cs = [c for c in (_e.get('cuisines') or ([_e.get('cuisine')] if _e.get('cuisine') else []))
           if c and c != 'unknown']
    if not _cs: continue
    _lm_total += 1
    for _c in _cs:
        _lm_cuisine_count[_c] += 1
_lm_top = sorted(
    [{'key': c, 'label': CUISINE_LABEL.get(c, c.replace('_', ' ').title()),
      'count': n, 'pct': round((n / _lm_total) * 100) if _lm_total else 0}
     for c, n in _lm_cuisine_count.items()],
    key=lambda r: -r['count']
)[:2]
# Single-month sample (_lm_top) was too volatile for the hero - flips
# on a 3-vs-2 swing. Use 3-year cumulative for the stable "who actually
# leads Toronto" answer. Last-month data still appears in dojo events.
_long_first = _long_top_6[0] if _long_top_6 and len(_long_top_6) >= 1 else None
_long_second = _long_top_6[1] if _long_top_6 and len(_long_top_6) >= 2 else None
if _long_first and _long_second:
    _first_color = _flag_color(_long_first['key'])
    _second_color = _flag_color(_long_second['key'])
    _first_flag = _flag_svg(_long_first['key'])
    _second_flag = _flag_svg(_long_second['key'])
    _first_link = f'/cuisine/{_esc(_long_first["key"])}'
    _second_link = f'/cuisine/{_esc(_long_second["key"])}'
    _flag_bg_first = (f'<span class="cuisine-flag-bg">{_first_flag}</span>'
                      if _first_flag else '')
    _flag_bg_second = (f'<span class="cuisine-flag-bg">{_second_flag}</span>'
                       if _second_flag else '')
    # Country-name table for the VS card — drops the nickname embellishments
    # (user feedback: "i just want Italy vs Japan"). Falls back to the cuisine
    # label for cuisines that don't map to a single country (Caribbean,
    # Middle Eastern, etc.).
    _vs_countries = {
        'italian':     'Italy',
        'japanese':    'Japan',
        'chinese':     'China',
        'indian':      'India',
        'mexican':     'Mexico',
        'middle_east': 'Middle East',
        'vietnamese':  'Vietnam',
        'korean':      'Korea',
        'thai':        'Thailand',
        'filipino':    'Philippines',
        'greek':       'Greece',
        'turkish':     'Türkiye',
        'lebanese':    'Lebanon',
        'persian':     'Iran',
        'french':      'France',
        'portuguese':  'Portugal',
        'polish':      'Poland',
        'spanish':     'Spain',
        'german':      'Germany',
        'brazilian':   'Brazil',
        'peruvian':    'Peru',
        'colombian':   'Colombia',
        'argentinian': 'Argentina',
        'venezuelan':  'Venezuela',
        'salvadoran':  'El Salvador',
        'ethiopian':   'Ethiopia',
        'eritrean':    'Eritrea',
        'nigerian':    'Nigeria',
        'ghanaian':    'Ghana',
        'jamaican':    'Jamaica',
        'afghan':      'Afghanistan',
        'pakistani':   'Pakistan',
        'bangladeshi': 'Bangladesh',
        'sri_lankan':  'Sri Lanka',
        'nepalese':    'Nepal',
        'indonesian':  'Indonesia',
    }
    # Per user feedback 2026-06-02: drop the country-name + ALL-CAPS
    # cuisine subtitle stack; just use the cuisine label as the big
    # colored fighter name. Cleaner — one bold word per fighter.
    _nick_first = _long_first['label']
    _nick_second = _long_second['label']
    _first_count = _long_first.get('count', 0)
    _second_count = _long_second.get('count', 0)
    _first_label_safe = _esc(_long_first['label'])
    _second_label_safe = _esc(_long_second['label'])
    _contrast_html = (
        '<div class="trends-vs-card">'
        '<div class="trends-vs-banner">MAIN EVENT · TORONTO CUISINE CHAMPIONSHIP</div>'
        '<div class="trends-vs-row">'
        # Fighter 1 (champion)
        f'<a class="trends-vs-fighter trends-vs-fighter-left" href="{_first_link}" '
        f'style="--fighter-color:{_first_color}">'
        f'<div class="trends-vs-belt">CHAMPION</div>'
        f'<div class="trends-vs-flag">{_first_flag or ""}</div>'
        f'<div class="trends-vs-nick">{_esc(_nick_first)}</div>'
        f'<div class="trends-vs-stats">'
        f'<span class="trends-vs-stat"><b>{round(_long_first["pct"])}%</b><em>share</em></span>'
        f'</div>'
        '</a>'
        # VS divider
        '<div class="trends-vs-divider"><span>VS</span></div>'
        # Fighter 2 (contender)
        f'<a class="trends-vs-fighter trends-vs-fighter-right" href="{_second_link}" '
        f'style="--fighter-color:{_second_color}">'
        f'<div class="trends-vs-belt trends-vs-belt-contender">CONTENDER</div>'
        f'<div class="trends-vs-flag">{_second_flag or ""}</div>'
        f'<div class="trends-vs-nick">{_esc(_nick_second)}</div>'
        f'<div class="trends-vs-stats">'
        f'<span class="trends-vs-stat"><b>{round(_long_second["pct"])}%</b><em>share</em></span>'
        f'</div>'
        '</a>'
        '</div>'
        f'<div class="trends-vs-tale">TALE OF THE TAPE · '
        f'{round(_long_first["pct"]) - round(_long_second["pct"])}-POINT LEAD '
        f'· SINCE {_dispatch_today.year - 3}</div>'
        '</div>'
    )
else:
    _contrast_html = ''
# Legacy variables - keep for tweet text below
_short_leader = _short_rows[0] if _short_rows else None
_long_leader = _long_first

_short_note = ''  # user feedback 2026-06-01: let the charts speak
_long_note = ''

# Editorial text takes - interpolate live data so the prose stays
# accurate as the leaderboard shifts month over month.
_take_first_label = _long_first['label'] if _long_first else 'Italian'
_take_second_label = _long_second['label'] if _long_second else 'Japanese'
_take_first_key = _long_first['key'] if _long_first else 'italian'
_take_second_key = _long_second['key'] if _long_second else 'japanese'
_take_first_pct = round(_long_first['pct']) if _long_first else 13
_take_second_pct = round(_long_second['pct']) if _long_second else 10
_short_top_label = _short_rows[0]['label'] if _short_rows else 'Vietnamese'
_short_top_key = _short_rows[0]['key'] if _short_rows else 'vietnamese'
_short_top_pct = _short_rows[0]['pct'] if _short_rows else 21
_y3_start_year = _dispatch_today.year - 3

# Tweet copy override: ported from the /trends lede swagger. Names blogTO +
# the durable long-tail diaspora cuisines so the tweet's editorial register
# matches what the visitor lands on. Replaces the earlier placeholder built
# at line ~3500 — placed here because _lm_total + _y3_start_year are
# computed above and weren't in scope at the original tweet-builder site.
_lm_prior_total_tweet = max(_y3_total - _lm_total, 0)
# Cache-bust the share URL with today's date so X (and other crawlers)
# treat it as a fresh URL on each daily inject, dodging stale-card-cache
# pain. Apache ignores the query string and serves the same /trends/2026-06
# page, so visitors see the right content; X's cardsbot re-scrapes
# because it sees a new URL.
from time import time as _epoch
_tweet_url = (f'{SITE_BASE}/trends/{_dispatch_today.year}-{_dispatch_today.month:02d}'
              f'?v={int(_epoch())}')
_tweet_lines = [
    f"Toronto's {_lm_total} newest restaurants this month: Uyghur kebabs in "
    f"Scarborough, Tamil dosa on Bloor, Salvadoran pupusas in Etobicoke.",
    f"\n{_tweet_url}",
    "\n#TorontoEats #TorontoFoodie",
]
_tweet_intent = 'https://twitter.com/intent/tweet?text=' + quote_plus('\n'.join(_tweet_lines))

_short_diff_phrase = ('outpacing the 3-year leader on momentum'
                      if _short_top_label != _take_first_label
                      else 'doubling down on its long-haul position')

# Trade-publication masthead stamp + industry-rag editorial voice.
# Targeting restaurant operators / industry analysts: less consumer-
# narrative, more market-intelligence register.
_issue_num = (_dispatch_today.year - 2025) * 12 + _dispatch_today.month
_masthead_html = (
    '<div class="trends-masthead">'
    '<a class="trends-mh-brand" href="/">NOWSERVING</a>'
    '<span class="trends-mh-sep">·</span>'
    '<span class="trends-mh-tag">TORONTO RESTAURANT INDUSTRY DATA</span>'
    '<span class="trends-mh-sep">·</span>'
    f'<span class="trends-mh-issue">VOL.1 NO.{_issue_num}</span>'
    '<span class="trends-mh-sep">·</span>'
    f'<span class="trends-mh-date">{_today_label.upper()}</span>'
    '<a class="trends-mh-cta" href="/">Browse the directory &rsaquo;</a>'
    '</div>'
)

# Lede - playful Toronto register, no diss. User feedback 2026-06-02:
# punching at blogTO from a 21-day-old domain reads wrong; switched to
# celebration of the spots themselves + neighborhood-coded specificity
# (Scarborough, Bloor, Etobicoke). Music-release verb ("dropped") +
# "new wave" framing for the youth register.
_lm_prior_total = max(_y3_total - _lm_total, 0)
_lede_html = (
    '<div class="trends-lede">'
    '<p class="trends-lede-p">'
    '<span class="trends-dropcap">T</span>'
    f'oronto dropped {_lm_total} new restaurants on the registry last month, plus '
    f'{_lm_prior_total:,} more since {_y3_start_year}. Uyghur kebabs in Scarborough, Tamil '
    'dosa on Bloor, Salvadoran pupusas in Etobicoke. The whole new wave, by cuisine and '
    '\'hood, updated daily. '
    '<a class="trends-lede-cta" href="/">Browse the full directory &rsaquo;</a>'
    '</p>'
    '</div>'
)

# Cuisine quick-chip row — diaspora-discovery shortcuts. Curated 8-cuisine
# set mixes current quarter leaders (Indian, Vietnamese, Filipino) with
# long-tail diaspora picks (Eritrean, Tamil, Salvadoran, Tibetan, Afghan).
# Lets a tweet-clicker test the "newest by cuisine" promise in one click,
# without scrolling past the data essay to find a cuisine they care about.
_chip_cuisines = [
    ('indian', 'Indian'),
    ('vietnamese', 'Vietnamese'),
    ('filipino', 'Filipino'),
    ('ethiopian', 'Ethiopian'),
    ('eritrean', 'Eritrean'),
    ('tamil', 'Tamil'),
    ('salvadoran', 'Salvadoran'),
    ('tibetan', 'Tibetan'),
]
_chip_html_parts = [
    '<div class="trends-chips">',
    '<div class="trends-chips-label">Jump to a cuisine &rsaquo;</div>',
    '<div class="trends-chips-row">',
]
for _ckey, _clabel in _chip_cuisines:
    _ccolor = _flag_color(_ckey) or '#7a746a'
    _chip_html_parts.append(
        f'<a class="trends-chip" href="/cuisine/{_esc(_ckey)}" '
        f'style="--chip-color:{_ccolor}">{_esc(_clabel)}</a>'
    )
_chip_html_parts.append('</div></div>')
_chips_html = ''.join(_chip_html_parts)

# Hero strip — the 4 newest registrations by issuedDate (post-swap, so
# date reflects "first known operating evidence" not just paperwork).
# Photo + name + cuisine + neighbourhood + days-since-registered badge.
# This is the literal "newest spots by cuisine" payoff promised in the
# tweet — visible above the fold, immediately clickable.
# Hero selection: diaspora-discovery weighted. Two-layer filter:
#   HARD_EXCLUDE — mainstream-Canadian cuisines that don't fit the
#     diaspora-discovery framing no matter how recent. Italian + French
#     consistently displace genuinely-novel entries; users have flagged
#     both as off-mission for the hero strip.
#   DISCOVERY_PENALTY — borderline-mainstream cuisines that get a 30-day
#     sort penalty (surface only if no fresher long-tail exists). Keeps
#     these visible when the diaspora pipeline is quiet, hides them when
#     it isn't.
# Indian / Tamil / Filipino / Vietnamese / Caribbean / etc. ride the
# normal recency sort — they're the discovery story we're trying to
# surface. 1-per-cuisine uniqueness cap ensures variety across the 6.
_HERO_HARD_EXCLUDE = {'italian', 'french'}
# Taiwanese / Korean kept OUT of penalty per user 2026-06-02: the live
# tweet using Star Glow Boba (Taiwanese) is getting clicks; don't
# disrupt a working post by demoting that cuisine right now.
_HERO_DISCOVERY_PENALTY = {'japanese', 'chinese', 'mexican', 'middle_east'}
_HERO_DISCOVERY_PENALTY_DAYS = 30
def _hero_rank(e):
    iso = e.get('issuedDate') or ''
    if not iso: return ''
    cuisine_keys = e.get('cuisines') or ([e.get('cuisine')] if e.get('cuisine') else [])
    if any(k in _HERO_DISCOVERY_PENALTY for k in cuisine_keys):
        try:
            from datetime import date as _hd, timedelta as _ht
            return (_hd.fromisoformat(iso) - _ht(days=_HERO_DISCOVERY_PENALTY_DAYS)).isoformat()
        except Exception:
            return iso
    return iso

def _hero_eligible(e):
    cuisine_keys = e.get('cuisines') or ([e.get('cuisine')] if e.get('cuisine') else [])
    return (e.get('slug')
            and (e.get('photo') or e.get('thumb'))
            and not any(k in _HERO_HARD_EXCLUDE for k in cuisine_keys))

_hero_pool = sorted(
    [_e for _e in (data.get('newOpenings') or {}).get('recent', []) if _hero_eligible(_e)],
    key=_hero_rank, reverse=True,
)
_seen_hero_cuisines = set()
_hero_recent = []
# Pull 7 instead of 6: index 0 becomes the magazine hero (big photo at
# top of page + OG card), and 1..6 fill the "Just registered" strip
# below. Without this we'd duplicate the featured spot in both places.
for _e in _hero_pool:
    _ck = _e.get('cuisine') or ''
    if _ck in _seen_hero_cuisines: continue
    _seen_hero_cuisines.add(_ck)
    _hero_recent.append(_e)
    if len(_hero_recent) >= 7: break
_hero_parts = ['<div class="trends-hero-strip">',
               '<div class="trends-hero-label">Just registered &rsaquo;</div>',
               '<div class="trends-hero-row">']
# Skip the featured magazine hero entry so it doesn't appear in the
# strip below its own big photo.
for _e in _hero_recent[1:]:
    _h_slug = _e.get('slug')
    _h_name = _esc(_e.get('operatingName') or '')
    _h_cuisine_key = _e.get('cuisine') or ''
    _h_cuisine_label = CUISINE_LABEL.get(_h_cuisine_key, _h_cuisine_key.replace('_',' ').title())
    _h_district = _esc(_e.get('district') or '')
    _h_thumb = _e.get('thumb') or _e.get('photo') or ''
    _h_days = _e.get('daysOpen') or 0
    if _h_days <= 1:
        _h_age = 'just registered'
    elif _h_days <= 30:
        _h_age = f'{_h_days}d ago'
    elif _h_days <= 60:
        _h_age = f'{_h_days // 7}w ago'
    else:
        _h_age = f'{_h_days // 30}mo ago'
    _hero_parts.append(
        f'<a class="trends-hero-card" href="/r/{_esc(_h_slug)}">'
        f'<div class="trends-hero-thumb" style="background-image:url(\'{_esc(_h_thumb)}\')"></div>'
        f'<div class="trends-hero-body">'
        f'<div class="trends-hero-age">{_esc(_h_age)}</div>'
        f'<div class="trends-hero-name">{_h_name}</div>'
        f'<div class="trends-hero-meta">{_esc(_h_cuisine_label)} &middot; {_h_district}</div>'
        f'</div></a>'
    )
_hero_parts.append('</div></div>')
_hero_html = ''.join(_hero_parts) if _hero_recent else ''

# Long-view editorial take - analyst voice with current-issue news anchors
_take_long = (
    '<div class="trends-take">'
    f'<p><b><a href="/cuisine/{_esc(_take_first_key)}">{_esc(_take_first_label)}</a></b> '
    f'still leads at {_take_first_pct}% of independent licences (chains excluded), but only '
    '7% of those land in Little Italy itself. Fusaro\'s shuttered after '
    '28 years on Spadina; Vivoli\'s 20-year run on College ended last year (Osteria Alba took '
    'the room). Mature operators still convert demand into storefronts — just rarely in the '
    'neighbourhood named for them.</p>'
    '</div>'
)

# --- Surger detection (3-month rank vs 3-year rank) ---
# Surfaces cuisines whose recent quarter-share clearly exceeds their
# 3-year share — a directional signal that something has changed on
# the operator-entry side (community capital, retail vacancy, owner
# diaspora cohort hitting opening age, etc.). Cosmetic only — small
# samples, so we phrase as "outpacing" not "overtaking".
# Full 3-year share-by-key (not just top 6) so surger comparison is honest
_long_pct_by_key = {
    _c: round((_n / _y3_total) * 100, 1) if _y3_total else 0
    for _c, _n in _y3_cuisine_count.items()
}
_surger = None
for _r in _short_rows[:5]:
    if _r['key'] == _short_top_key:
        continue  # don't re-name the cuisine we just called out as the leader
    _lp = _long_pct_by_key.get(_r['key'], 0)
    if _r['pct'] >= _lp + 3 and _r['count'] >= 3:
        _surger = (_r, _lp)
        break
_slipper = None
for _r in _long_top_6[:4]:
    _sp = next((s['pct'] for s in _short_rows if s['key'] == _r['key']), 0)
    if _r['pct'] >= _sp + 3:
        _slipper = (_r, _sp)
        break

if _surger:
    _surger_row, _surger_long_pct = _surger
    _surger_phrase = (
        f' <b><a href="/cuisine/{_esc(_surger_row["key"])}">{_esc(_surger_row["label"])}</a></b> '
        f'is outperforming — {_surger_row["pct"]}% vs a {round(_surger_long_pct)}% 3-year baseline.'
    )
else:
    _surger_phrase = ''

_slip_phrase = ''  # trimmed for length

# Short-view editorial take — below the pies. Velocity + current news anchors.
# Anchors verified against the Toronto City licence stream — only operators
# whose licence is in the 90-day window get named. Brampton/Mississauga
# expansions exist but live in those municipalities' separate streams.
_take_short = (
    '<div class="trends-take"><p>'
    f'<b><a href="/cuisine/{_esc(_short_top_key)}">{_esc(_short_top_label)}</a></b> '
    f'took the quarter at {_short_top_pct}% — heavily Scarborough-led, with new entries on '
    'Markham Rd, Pharmacy Ave, Kennedy Rd, and Sheppard E, plus downtown spots like '
    '<a href="/r/dakshin-flavours-indian-kitchen-bar-5">Dakshin Flavours</a> on Baldwin and '
    '<a href="/r/zafraan-indian-cuisine-downtown-671">Zafraan</a> on Queen W.'
    f'{_surger_phrase} Six of nine new Vietnamese licences in the quarter are dedicated '
    'banh mi shops — including <a href="/r/and-banh-mi-13">And Banh Mi</a> on Elm (selling out '
    'daily since its May open) and <a href="/r/coco-banh-mi-222">Coco Banh Mi</a> on Spadina. '
    'blogTO has called it Toronto\'s "summer of Saigon."'
    '</p></div>'
)

# Long-view editorial take — below the 3-year pies. Concentration + tail.
_long_top6_pct = sum(round(r['pct']) for r in _long_top_6[:6])
_long_top6_count = sum(r['count'] for r in _long_top_6[:6])
_long_tail_count = max(_y3_total - _long_top6_count, 0)
_long_tail_pct = round(100 - _long_top6_pct)
_long_sixth = _long_top_6[5] if len(_long_top_6) >= 6 else None
_long_sixth_phrase = (
    f'By position #6, the share has dropped to {round(_long_sixth["pct"])}% '
    f'(<a href="/cuisine/{_esc(_long_sixth["key"])}">{_esc(_long_sixth["label"])}</a>) — '
    if _long_sixth else ''
)
_take_3yr = (
    '<div class="trends-take">'
    f'<p>Six cuisines = {_long_top6_pct}% of {_y3_total:,} licences since {_y3_start_year}; '
    f'the remaining {_long_tail_pct}% spreads across ~60 smaller buckets — '
    '<a href="/cuisine/eritrean">Eritrean</a>, <a href="/cuisine/salvadoran">Salvadoran</a>, '
    '<a href="/cuisine/tibetan">Tibetan</a>, <a href="/cuisine/uyghur">Uyghur</a> kitchens '
    'opening one or two storefronts a year. Ottawa\'s '
    '2026 plan cuts new study permits roughly in half and caps PR at 380,000/yr through 2028, '
    'throttling the diaspora pipeline that feeds that tail. Dalhousie\'s Agri-Food Analytics '
    'Lab is forecasting 4,000 net Canadian restaurant closures in 2026 — the licence stream '
    'is one of the few places the new is still winning against what\'s being killed.</p>'
    '</div>'
)

# Closing column - analyst tone
_closing_html = (
    '<div class="trends-close">'
    f'<p>For operators tracking the competitive landscape, the consolidated dataset above '
    f'represents {_y3_total:,} restaurant licences issued over the trailing 36 months. The '
    f'live directory of currently-operating new entrants (verified open within the past 365 '
    f'days) is at <a href="/">nowservingto.com</a>. The cuisine-classified machine-readable '
    f'feed is at <a href="/data/corridors.json">/data/corridors.json</a>.</p>'
    '<p class="trends-close-method"><b>Sources:</b> City of Toronto Open Data (business licences '
    'via CKAN); Toronto Public Health DineSafe inspection records; Google Places API for '
    'operating-status verification; cuisine classification via Claude Haiku. Methodology and '
    f'verification gates documented at <a href="/press">/press</a>. Refresh cycle: daily, '
    f'~05:17 UTC. Last refresh: {_today_label}.</p>'
    '</div>'
)

# Magazine-style hero image — full-bleed photo of the featured spot
# above the masthead, GQ-feature style. Same featured pick the OG card
# uses, so visitor arriving from a tweet sees a continuous visual:
# tweet card photo → page hero photo.
def _mag_hero_age(days):
    if days is None or days <= 1: return 'TODAY'
    if days <= 30: return f'{days}D AGO'
    if days <= 60: return f'{days // 7}W AGO'
    return f'{days // 30}MO AGO'

_magazine_hero_html = ''
if _hero_recent:
    _feat = _hero_recent[0]
    _feat_slug = _feat.get('slug', '')
    # Branded typographic OG card replaces the Places photo (photos
    # retired site-wide 2026-06-03).
    _feat_photo = f'/og/{_feat_slug}.png' if _feat_slug else ''
    _feat_name = _feat.get('operatingName', '')
    _feat_cuisine_key = _feat.get('cuisine') or ''
    _feat_cuisine_label = CUISINE_LABEL.get(_feat_cuisine_key,
                                            _feat_cuisine_key.replace('_', ' ').title())
    _feat_district = _feat.get('district') or ''
    _feat_age = _mag_hero_age(_feat.get('daysOpen'))
    # Wrap the whole hero in an <a> so a click on the photo OR caption
    # takes the visitor to the actual listing — otherwise it reads as
    # bait-and-switch (big photo of a real spot, no way to act on it).
    _feat_link = f'/r/{_esc(_feat_slug)}' if _feat_slug else '/'
    _magazine_hero_html = (
        f'<a class="trends-mag-hero-link" href="{_feat_link}">'
        '<figure class="trends-mag-hero">'
        f'<img src="{_esc(_feat_photo)}" alt="{_esc(_feat_name)}" loading="lazy" />'
        '<figcaption class="trends-mag-hero-cap">'
        f'<span class="trends-mag-hero-eyebrow">JUST REGISTERED · {_esc(_feat_age)}</span>'
        f'<span class="trends-mag-hero-name">{_esc(_feat_name)}</span>'
        f'<span class="trends-mag-hero-meta">{_esc(_feat_cuisine_label)}'
        f'{" · " + _esc(_feat_district) if _feat_district else ""}</span>'
        '</figcaption></figure>'
        '</a>'
    )

_trends_body = (
    _magazine_hero_html
    + _masthead_html
    + _lede_html
    + _hero_html
    # The reigning crowns - hero
    + '<section class="trends-section trends-section-headline">'
    '<div class="trends-eyebrow">Industry pulse · top of the count</div>'
    f'<h2 class="trends-h2">By the numbers <span class="trends-h2-sub">· since {_dispatch_today.year - 3}</span></h2>'
    + _contrast_html
    + _take_long
    + '</section>'
    # Short-term section (current movement)
    + '<section class="trends-section trends-section-card">'
    '<div class="trends-eyebrow">Operator shifts · last quarter</div>'
    f'<h2 class="trends-h2">Last 3 months <span class="trends-h2-sub">· {_esc(_cal.month_name[int(_ym_back(_dispatch_today, 3)[-2:])][:3])}–{_esc(_cal.month_name[int(_lm_ym[-2:])][:3])} {_lm_ym[:4]}</span></h2>'
    + '<div class="trends-treemap-wrap">'
      '<div class="trends-treemap-eyebrow">All cuisines · sized by 90-day licence count</div>'
      f'<div class="trends-treemap">{_short_treemap_svg}</div>'
      '</div>'
    + _take_short
    + '</section>'
    # Long-term section (full leaderboard)
    + '<section class="trends-section trends-section-card">'
    '<div class="trends-eyebrow">Full landscape · 36-month cumulative</div>'
    f'<h2 class="trends-h2">Last 3 years <span class="trends-h2-sub">· since {_dispatch_today.year - 3}</span></h2>'
    + '<div class="trends-treemap-wrap">'
      '<div class="trends-treemap-eyebrow">All cuisines · sized by 3-year licence count</div>'
      f'<div class="trends-treemap">{_long_treemap_svg}</div>'
      '</div>'
    + _take_3yr
    + '</section>'
    # Supplemental news (dojo events) - tan background
    + f'{_callouts_html}'
    # Sources block — outbound citations for every external claim made in
    # the editorial takes above. Internal data (licence counts, treemap
    # percentages) draws on /press methodology; only third-party sources
    # need listing here. Keeps citations grouped instead of inline so the
    # takes stay readable.
    + '<div class="trends-sources">'
      '<div class="trends-sources-eyebrow">Sources</div>'
      '<ul class="trends-sources-list">'
      '<li><a href="https://www.blogto.com/eat_drink/2026/05/fusaros-toronto-closed/" '
      'target="_blank" rel="noopener">Fusaro\'s closes after 28 years on Spadina — blogTO</a></li>'
      '<li><a href="https://www.blogto.com/eat_drink/2025/07/vivoli-toronto-closed/" '
      'target="_blank" rel="noopener">Vivoli\'s 20-year run ends on College — blogTO</a></li>'
      '<li><a href="https://www.blogto.com/eat_drink/2025/07/toronto-chef-taking-over-italian-restaurant/" '
      'target="_blank" rel="noopener">Adam Pereira\'s Osteria Alba takes the Vivoli room — blogTO</a></li>'
      '<li><a href="https://www.blogto.com/eat_drink/2026/05/banh-mi-taking-over-toronto/" '
      'target="_blank" rel="noopener">"Banh mi is taking over Toronto" (And Banh Mi, Viet Bites, "summer of Saigon") — blogTO</a></li>'
      '<li><a href="https://www.canada.ca/en/immigration-refugees-citizenship/news/notices/2026-provincial-territorial-allocations-under-international-student-cap.html" '
      'target="_blank" rel="noopener">2026 international student cap allocations — IRCC (Canada.ca)</a></li>'
      '<li><a href="https://www.canada.ca/en/immigration-refugees-citizenship/corporate/mandate/corporate-initiatives/levels/supplementary-immigration-levels-2026-2028.html" '
      'target="_blank" rel="noopener">2026–2028 Immigration Levels Plan: PR capped at 380K through 2028 — IRCC (Canada.ca)</a></li>'
      '<li><a href="https://agrifoodanalyticslab.substack.com/p/canada-is-poised-to-lose-4000-restaurants" '
      'target="_blank" rel="noopener">"Canada Is Poised to Lose 4,000 Restaurants in 2026" — Dalhousie Agri-Food Analytics Lab</a></li>'
      '</ul>'
      '</div>'
    # Share CTA
    + '<p class="trends-share">'
    f'<a class="trends-tweet-btn" href="{_esc(_tweet_intent)}" target="_blank" rel="noopener">'
    'Share this on X &rsaquo;</a> '
    '<span class="trends-note">Auto-refreshes daily from City open data + DineSafe.</span>'
    '</p>'
)
# Render the standalone share card PNG (1200x675) so X / FB / iMessage
# show a rich card preview when the /trends URL is shared. Cached at
# /og/trends-<yyyy-mm>.png and pinned via og:image below. Card now uses
# the actual hero-strip photos (real restaurant thumbnails) instead of
# flag-coloured cuisine chips — user feedback: "fisher-price colours"
# on the chips read juvenile for a tweet preview.
_trends_card_dispatch_label = f"{_cal.month_name[_dispatch_today.month]} {_dispatch_today.year}"
_trends_card_filename = f"trends-{_dispatch_today.year}-{_dispatch_today.month:02d}.png"
_trends_card_path = Path(ROOT) / 'og' / _trends_card_filename
# Build hero-entry payload for the card (same 6 entries the page shows
# in the "Just registered" strip). Pull thumb paths from og/thumb/<slug>.webp.
def _hero_age(days):
    if days is None or days <= 1: return 'NEW'
    if days <= 30: return f'{days}D AGO'
    if days <= 60: return f'{days // 7}W AGO'
    return f'{days // 30}MO AGO'

_trends_card_hero = []
for _he in _hero_recent[:5]:  # 1 featured + 4 supporting
    _slug = _he.get('slug') or ''
    # Photo paths retired 2026-06-03 — card renderer falls back to
    # typographic treatment when these are empty.
    _ck = _he.get('cuisine') or ''
    _mh = MENU_HIGHLIGHTS_CACHE.get(_he.get('_cacheKey') or '') or {}
    _dishes = [d for d in (_mh.get('dishes') or []) if d][:3]
    _trends_card_hero.append({
        'thumb_path': '',
        'photo_path': '',
        'name': _he.get('operatingName') or '',
        'cuisine_label': CUISINE_LABEL.get(_ck, _ck.replace('_', ' ').title()),
        'district': _he.get('district') or '',
        'age_label': _hero_age(_he.get('daysOpen')),
        'dishes': _dishes,
    })
try:
    from og_card import render_trends_card_png
    render_trends_card_png(
        _trends_card_dispatch_label, _y3_total, _trends_card_hero,
        _trends_card_path,
    )
    # Cache-bust query string keyed on file mtime so X / FB / iMessage
    # re-scrape when the card content changes (otherwise their card cache
    # holds for ~7 days and shows the stale preview).
    _trends_card_mtime = int(_trends_card_path.stat().st_mtime)
    _trends_og_image = f'{SITE_BASE}/og/{_trends_card_filename}?v={_trends_card_mtime}'
except Exception as _e:
    print(f"  (trends card render skipped: {_e})")
    _trends_og_image = None

_trends_page = inject_into_html(_dispatch_template, static_block='', ld_payloads=[])
_trends_meta_subs = [
    (r'<title>[^<]*</title>', f'<title>{_esc(_trends_title)}</title>'),
    (r'(<meta name="description" content=")[^"]*(")', _esc(_trends_desc)),
    (r'(<meta property="og:title" content=")[^"]*(")', _esc(_trends_title)),
    (r'(<meta property="og:description" content=")[^"]*(")', _esc(_trends_desc)),
    (r'(<meta property="og:url" content=")[^"]*(")', _esc(_trends_canonical)),
    (r'(<meta name="twitter:title" content=")[^"]*(")', _esc(_trends_title)),
    (r'(<meta name="twitter:description" content=")[^"]*(")', _esc(_trends_desc)),
    (r'(<link rel="canonical" href=")[^"]*(")', _esc(_trends_canonical)),
]
if _trends_og_image:
    _trends_meta_subs += [
        (r'(<meta property="og:image" content=")[^"]*(")', _esc(_trends_og_image)),
        (r'(<meta name="twitter:image" content=")[^"]*(")', _esc(_trends_og_image)),
        (r'(<meta name="twitter:card" content=")[^"]*(")', 'summary_large_image'),
    ]
for _sel, _val in _trends_meta_subs:
    if _val.startswith('<title'):
        _trends_page = re.sub(_sel, _val, _trends_page, count=1)
    else:
        _trends_page = re.sub(_sel, lambda m, v=_val: m.group(1) + v + m.group(2),
                              _trends_page, count=1)
_trends_page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>(?:<div class="listing-lede">[\s\S]*?</div>)?',
                      lambda m: _trends_h1, _trends_page, count=1)
_trends_page = _trends_page.replace('<body>', '<body class="page-trends">', 1)
# Insert trends body BEFORE the open-feed div; CSS hides the feed on
# .page-trends so the chart fully occupies the content area. (Tried to
# replace the feed div via regex but the nested .open-row divs make
# matching the closing </div> brittle — sibling-insert + CSS hide is
# both simpler and more robust.)
_trends_page = re.sub(
    r'(<div class="open-feed")',
    _trends_body + '\n  \\1', _trends_page, count=1)
(Path(ROOT) / 'trends.html').write_text(_trends_page)
# Monthly snapshot at /trends/<yyyy-mm>.html. Overwrites within the
# current month (so visitors browsing /trends/2026-06 mid-June see
# data through whatever day inject last ran), then becomes effectively
# immutable on month rollover since the next cron writes a new
# yyyy-mm key. Mirrors the /dispatch/<yyyy-mm>.html pattern.
_trends_month_key = f'{_dispatch_today.year}-{_dispatch_today.month:02d}'
_trends_archive_dir = Path(ROOT) / 'trends'
_trends_archive_dir.mkdir(exist_ok=True)
# Rewrite canonical + share URLs inside the archived copy so a visitor
# arriving via the dated permalink doesn't get a canonical pointing at
# the rolling /trends (which would dilute SEO and make the X share
# button on the archive page link back to the rolling view).
_dated_canonical = f'{SITE_BASE}/trends/{_trends_month_key}'
_trends_archive_page = re.sub(
    r'(<link rel="canonical" href=")[^"]*(")',
    lambda m: m.group(1) + _esc(_dated_canonical) + m.group(2),
    _trends_page, count=1,
)
_trends_archive_page = re.sub(
    r'(<meta property="og:url" content=")[^"]*(")',
    lambda m: m.group(1) + _esc(_dated_canonical) + m.group(2),
    _trends_archive_page, count=1,
)
(_trends_archive_dir / f'{_trends_month_key}.html').write_text(_trends_archive_page)
print(f"  wrote /trends.html + /trends/{_trends_month_key}.html ({len(_trend_top)} cuisines, {len(_drought_broken)} drought-broken, {len(_spikes)} spikes)")

# ─────────────────────────────────────────────────────────────────────
# /press/data — press-grade data terminal (Reuters/Bloomberg aesthetic)
# Monospaced, source-attributed, embeddable. Designed for food editors,
# data journalists, and citation-grade artifact. Same data as /trends,
# different register: stark + dense + cite-friendly.
# ─────────────────────────────────────────────────────────────────────
_pro_top_n = 10
_pro_per_month = _dd(lambda: _dd(int))  # cuisine -> {ym: count}
with open(CSV_PATH, encoding='utf-8', errors='replace') as _f:
    for _row in csv.DictReader(_f):
        if (_row.get('Category') or '').strip() not in FOOD_CATS: continue
        if (_row.get('Cancel Date') or '').strip(): continue
        _iss = (_row.get('Issued') or '').split(' ')[0]
        _d = parse_d(_iss)
        if not _d or _d < _y3_cutoff_date: continue
        _ym = f'{_d.year}-{_d.month:02d}'
        _name = (_row.get('Operating Name') or '').strip()
        _addr1 = (_row.get('Licence Address Line 1') or '').strip()
        _addr3 = (_row.get('Licence Address Line 3') or '').strip()
        _addr = (_addr1 + ' ' + _addr3).strip() or '-'
        _ck = cache_key(_name, _addr)
        _llm = LLM_CACHE.get(_ck) or {}
        if _llm.get('status') != 'ok': continue
        _cs = [c for c in (_llm.get('cuisines') or [_llm.get('cuisine')]) if c and c != 'unknown']
        for _c in _cs:
            _pro_per_month[_c][_ym] += 1

_pro_top = [r['key'] for r in _y3_rows[:_pro_top_n]]
_pro_months_seq = [_ym_back(_dispatch_today, i) for i in range(36, 0, -1)]

# Multi-line SVG: 36 months on x, monthly count on y, one line per top cuisine
_pro_w, _pro_h = 720, 320
_pro_pl, _pro_pr, _pro_pt, _pro_pb = 40, 12, 16, 28
_pro_iw = _pro_w - _pro_pl - _pro_pr
_pro_ih = _pro_h - _pro_pt - _pro_pb
_pro_max = max((_pro_per_month[c].get(m, 0) for c in _pro_top for m in _pro_months_seq), default=1) or 1
_pro_x_step = _pro_iw / max(len(_pro_months_seq) - 1, 1)

_pro_lines_svg = []
for _c in _pro_top:
    _color = PALETTE_HEX.get(_c) or cuisine_color(_c)
    _pts = []
    for _i, _m in enumerate(_pro_months_seq):
        _v = _pro_per_month[_c].get(_m, 0)
        _x = _pro_pl + _i * _pro_x_step
        _y = _pro_pt + _pro_ih - (_v / _pro_max) * _pro_ih
        _pts.append(f'{_x:.1f},{_y:.1f}')
    _path_d = 'M' + ' L'.join(_pts)
    _pro_lines_svg.append(f'<path d="{_path_d}" stroke="{_color}" stroke-width="1.5" fill="none" opacity="0.85"/>')

_pro_y_ticks = []
_y_step = max(1, _pro_max // 4)
for _tv in range(0, _pro_max + 1, _y_step):
    _y = _pro_pt + _pro_ih - (_tv / _pro_max) * _pro_ih
    _pro_y_ticks.append(
        f'<line x1="{_pro_pl}" y1="{_y:.1f}" x2="{_pro_pl + _pro_iw}" y2="{_y:.1f}" stroke="#e8e8e6" stroke-width="0.5"/>'
        f'<text x="{_pro_pl - 6}" y="{_y + 3:.1f}" text-anchor="end" font-family="ui-monospace,SF Mono,Menlo,monospace" font-size="9.5" fill="#7a7a78">{_tv}</text>'
    )
_pro_x_labels = []
for _i, _m in enumerate(_pro_months_seq):
    if _m.endswith('-01') or _i == 0 or _i == len(_pro_months_seq) - 1:
        _x = _pro_pl + _i * _pro_x_step
        _pro_x_labels.append(
            f'<text x="{_x:.1f}" y="{_pro_h - 8}" text-anchor="middle" font-family="ui-monospace,SF Mono,Menlo,monospace" font-size="9.5" fill="#7a7a78">{_m}</text>'
        )
_pro_chart_svg = (
    f'<svg viewBox="0 0 {_pro_w} {_pro_h}" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="Toronto restaurant registrations by cuisine, 36-month time series" '
    f'style="width:100%;max-width:{_pro_w}px;height:auto;display:block;background:#fff">'
    + ''.join(_pro_y_ticks) + ''.join(_pro_lines_svg) + ''.join(_pro_x_labels)
    + '</svg>'
)

# Legend strip
_pro_legend = '<div class="pro-legend">' + ''.join(
    f'<span class="pro-legend-item"><span class="pro-legend-swatch" style="background:{PALETTE_HEX.get(_c) or cuisine_color(_c)}"></span>'
    f'<a href="/cuisine/{_esc(_c)}">{_esc(CUISINE_LABEL.get(_c, _c.replace("_"," ").title()))}</a></span>'
    for _c in _pro_top
) + '</div>'

# Dense data table
_pro_ranks_90 = {r['key']: i+1 for i, r in enumerate(_short_rows)}
_pro_ranks_36 = {r['key']: i+1 for i, r in enumerate(_y3_rows)}
_pro_table_rows = []
for _c in _pro_top:
    _label = CUISINE_LABEL.get(_c, _c.replace('_',' ').title())
    _scnt = next((r['count'] for r in _short_rows if r['key'] == _c), 0)
    _srnk = _pro_ranks_90.get(_c, '—')
    _lcnt = next((r['count'] for r in _y3_rows if r['key'] == _c), 0)
    _lrnk = _pro_ranks_36.get(_c, '—')
    _lpct = next((r['pct'] for r in _y3_rows if r['key'] == _c), 0)
    _color = PALETTE_HEX.get(_c) or cuisine_color(_c)
    _pro_table_rows.append(
        f'<tr><td><span class="pro-swatch" style="background:{_color}"></span>'
        f'<a href="/cuisine/{_esc(_c)}">{_esc(_label)}</a></td>'
        f'<td class="pro-num">{_scnt}</td>'
        f'<td class="pro-num pro-muted">#{_srnk}</td>'
        f'<td class="pro-num">{_lcnt}</td>'
        f'<td class="pro-num pro-muted">#{_lrnk}</td>'
        f'<td class="pro-num pro-muted">{_lpct}%</td></tr>'
    )
_pro_table = (
    '<table class="pro-table"><thead><tr>'
    '<th>CUISINE</th>'
    '<th class="pro-num">90D</th><th class="pro-num">RANK</th>'
    '<th class="pro-num">36MO</th><th class="pro-num">RANK</th>'
    '<th class="pro-num">SHARE</th>'
    '</tr></thead>'
    f'<tbody>{"".join(_pro_table_rows)}</tbody></table>'
)

# CSV export for press download
_csv_lines = ['cuisine,90d_count,90d_rank,36mo_count,36mo_rank,36mo_share_pct']
for _c in _pro_top:
    _label = CUISINE_LABEL.get(_c, _c.replace('_',' ').title())
    _scnt = next((r['count'] for r in _short_rows if r['key'] == _c), 0)
    _srnk = _pro_ranks_90.get(_c, '')
    _lcnt = next((r['count'] for r in _y3_rows if r['key'] == _c), 0)
    _lrnk = _pro_ranks_36.get(_c, '')
    _lpct = next((r['pct'] for r in _y3_rows if r['key'] == _c), 0)
    _csv_lines.append(f'"{_label}",{_scnt},{_srnk},{_lcnt},{_lrnk},{_lpct}')
(Path(ROOT) / 'data' / 'cuisines.csv').write_text('\n'.join(_csv_lines) + '\n')

# Header masthead + footer (methodology, citation, CSV, embed)
_iso_now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
_pro_header = (
    '<div class="pro-header"><div class="pro-header-row">'
    '<span class="pro-header-tag">CUISINE.VELOCITY</span>'
    f'<span class="pro-header-meta">UPD {_iso_now}</span>'
    '<span class="pro-header-meta">SRC: TORONTO MLS + DINESAFE</span>'
    f'<span class="pro-header-meta">N={_y3_total:,}</span>'
    '</div></div>'
)
_pro_embed = '<iframe src="https://nowservingto.com/press/data" width="720" height="800" frameborder="0" loading="lazy" title="NowServingTO Cuisine Velocity"></iframe>'
_pro_footer = (
    '<div class="pro-footer">'
    '<h3 class="pro-foot-h">METHODOLOGY</h3>'
    f'<p>Source: City of Toronto Open Data business licence registry (CKAN); Toronto Public Health DineSafe inspection records; Google Places API for verification. {_y3_total:,} restaurant licences issued in the past 36 months, classified by cuisine via Claude Haiku, gated against multi-licence renewals, pre-existing operators, OSM and Wikidata chain registries, and Toronto-Canadianized franchise concepts. Full methodology: <a href="/press">nowservingto.com/press</a>.</p>'
    '<h3 class="pro-foot-h">CITATION</h3>'
    f'<p>Source: NowServingTO, <a href="/press/data">nowservingto.com/press/data</a>, accessed {_dispatch_today.isoformat()}.</p>'
    '<h3 class="pro-foot-h">DOWNLOAD</h3>'
    '<p><a href="/data/cuisines.csv">/data/cuisines.csv</a> &middot; <a href="/data/corridors.json">/data/corridors.json</a> (full directory)</p>'
    '<h3 class="pro-foot-h">EMBED</h3>'
    f'<pre class="pro-embed">{_esc(_pro_embed)}</pre>'
    '</div>'
)
_pro_body = (
    _pro_header
    + '<section class="pro-section">'
    + '<h2 class="pro-h2">CUISINE VELOCITY &middot; 36-MONTH TIME SERIES</h2>'
    + f'<div class="pro-chart">{_pro_chart_svg}</div>'
    + _pro_legend
    + '</section>'
    + '<section class="pro-section">'
    + '<h2 class="pro-h2">STANDINGS &middot; 90D vs 36MO</h2>'
    + _pro_table
    + '</section>'
    + _pro_footer
)

_pro_title = 'Toronto Cuisine Velocity — Data Terminal | NowServingTO'
_pro_desc = f'Press-grade data terminal: Toronto restaurant registrations by cuisine, 36-month time series ({_y3_total:,} verified registrations). Methodology + CSV download + embed code.'
_pro_canonical = f'{SITE_BASE}/press/data'
_pro_page = inject_into_html(_dispatch_template, static_block='', ld_payloads=[])
for _sel, _val in [
    (r'<title>[^<]*</title>', f'<title>{_esc(_pro_title)}</title>'),
    (r'(<meta name="description" content=")[^"]*(")', _esc(_pro_desc)),
    (r'(<meta property="og:title" content=")[^"]*(")', _esc(_pro_title)),
    (r'(<meta property="og:description" content=")[^"]*(")', _esc(_pro_desc)),
    (r'(<meta property="og:url" content=")[^"]*(")', _esc(_pro_canonical)),
    (r'(<link rel="canonical" href=")[^"]*(")', _esc(_pro_canonical)),
]:
    if _val.startswith('<title'):
        _pro_page = re.sub(_sel, _val, _pro_page, count=1)
    else:
        _pro_page = re.sub(_sel, lambda m, v=_val: m.group(1) + v + m.group(2), _pro_page, count=1)
_pro_page = re.sub(r'<h1 class="sub">[\s\S]*?</h1>(?:<div class="listing-lede">[\s\S]*?</div>)?',
                   lambda m: '<h1 class="pro-h1">CUISINE.VELOCITY</h1>', _pro_page, count=1)
_pro_page = _pro_page.replace('<body>', '<body class="page-data">', 1)
_pro_page = re.sub(r'(<div class="open-feed")', _pro_body + '\n  \\1', _pro_page, count=1)

(Path(ROOT) / 'press').mkdir(exist_ok=True)
(Path(ROOT) / 'press' / 'data.html').write_text(_pro_page)
print(f"  wrote /press/data.html ({_y3_total:,} entries over 36 months, top {len(_pro_top)} cuisines, CSV exported)")

# Persist any photoRef values we backfilled into PLACES_CACHE so the next
# inject doesn't have to re-call place_details for the same entries.
try:
    with open(PLACES_CACHE_PATH, 'w') as f:
        json.dump(PLACES_CACHE, f, separators=(',', ':'))
except Exception as ex:
    print(f"  WARN: places_cache save failed: {ex}")

# Write sitemap.xml with today's lastmod + one URL per cuisine landing page so
# Google indexes "newest ethiopian toronto" etc. separately from the home page.
url_blocks = [
    f'  <url>\n    <loc>{SITE_BASE}/</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>',
    f'  <url>\n    <loc>{SITE_BASE}/press</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.6</priority>\n  </url>',
    f'  <url>\n    <loc>{SITE_BASE}/trends</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.7</priority>\n  </url>',
]
# Monthly dispatch archive pages - one per month, indexed for SEO
# ("newest toronto restaurants June 2026" type queries). Also surface
# /dispatch/latest as the canonical "current month" URL.
DISPATCH_DIR_PATH = Path(ROOT) / 'dispatch'
if DISPATCH_DIR_PATH.exists():
    for dfile in sorted(DISPATCH_DIR_PATH.glob('*.html')):
        dkey = dfile.stem
        url_blocks.append(
            f'  <url>\n    <loc>{SITE_BASE}/dispatch/{dkey}</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>'
        )

# Monthly trends archive — same pattern. Past months are immutable
# snapshots, current month updates daily.
TRENDS_DIR_PATH = Path(ROOT) / 'trends'
if TRENDS_DIR_PATH.exists():
    for tfile in sorted(TRENDS_DIR_PATH.glob('*.html')):
        tkey = tfile.stem
        url_blocks.append(
            f'  <url>\n    <loc>{SITE_BASE}/trends/{tkey}</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.6</priority>\n  </url>'
        )

# Diaspora-pitch wire pages - whatever build_wire_pages.py actually wrote
# is what we surface. Filesystem-driven so the two scripts can evolve
# independently.
WIRE_DIR_PATH = Path(ROOT) / 'wire'
if WIRE_DIR_PATH.exists():
    for wire_file in sorted(WIRE_DIR_PATH.glob('*.html')):
        wkey = wire_file.stem
        url_blocks.append(
            f'  <url>\n    <loc>{SITE_BASE}/wire/{wkey}</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>'
        )
for c in cuisines_out:
    # Sitemap every cuisine with at least 1 verified opening. Smaller cuisines
    # often have the BEST ranking opportunity ("newest Eritrean Toronto" has
    # almost no competing content), and excluding under-represented communities
    # would contradict the project ethos.
    if c.get('count365d', 0) < 1: continue
    url_blocks.append(
        f'  <url>\n    <loc>{SITE_BASE}/cuisine/{c["key"]}</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>'
    )
# Per-district landing pages - same priority as cuisines.
for label in by_district:
    if not by_district[label]: continue
    slug = _district_slug(label)
    url_blocks.append(
        f'  <url>\n    <loc>{SITE_BASE}/district/{slug}</loc>\n    <lastmod>{REFERENCE_DATE.isoformat()}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>'
    )
# Per-listing pages - every kept entry. Mid-tier priority (0.5) since each
# is thin-ish on its own, but Google needs to see them in the sitemap to
# discover them - they were completely absent before, which is why the
# GSC "Discovered - not indexed" count tracks the cuisine/district pages,
# not the 444 r/<slug> pages Google doesn't even know about.
# lastmod = each entry's actual issued date so Google sees stable URLs
# (revisit only when the listing's own data changes, not on every cron).
for entry in seen_entries.values():
    slug = entry.get('slug')
    if not slug: continue
    iss = entry.get('issuedDate', REFERENCE_DATE.isoformat())
    url_blocks.append(
        f'  <url>\n    <loc>{SITE_BASE}/r/{slug}</loc>\n    <lastmod>{iss}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.5</priority>\n  </url>'
    )
sitemap = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + '\n'.join(url_blocks) + '\n'
    '</urlset>\n'
)
with open(SITEMAP_PATH, 'w') as f: f.write(sitemap)
print(f"  wrote sitemap.xml ({len(url_blocks)} URLs)")

print(f"Injected newOpenings into {DATA_PATH}")
print(f"  {n_food_active_365:,} active food licences issued in last 365d")
print(f"  {n_tagged_365:,} cuisine-tagged ({data['newOpenings']['tagRate365d']}%)")
print(f"  {len(cuisines_out)} cuisines with at least 1 new opening")
print(f"  {n_tagged_30:,} tagged openings in last 30 days")
print()
print("Top cuisines by 12-month new-opening count:")
for c in cuisines_out[:12]:
    print(f"  {c['label']:20s} {c['count365d']:>4} new (last 30d: {c['count30d']})   newest: {c['newest']['operatingName'][:42]}")

# ---------------------------------------------------------------------------
# Cleanup pass - delete stale generated files for entries that no longer
# exist in the live data. Without this, every dropped restaurant + every
# emptied-out cuisine leaves an orphaned HTML file on disk serving 200 OK
# to Google, polluting the indexing report with "discovered but not
# indexed" URLs that point at content that doesn't reflect current state.
# ---------------------------------------------------------------------------
live_cuisines  = {c['key'] for c in cuisines_out}
live_districts = {_district_slug(d) for d in by_district if by_district[d]}
live_slugs     = {e.get('slug') for e in seen_entries.values() if e.get('slug')}

# Reserved og/ filename prefixes — page-level OG cards (trends, dispatch,
# press, etc.) that are NOT per-listing and must survive the listing-slug
# sweep below.
_OG_RESERVED_PREFIXES = ('trends-', 'dispatch-', 'press-')

def _cleanup(directory, live_keys, suffix='.html'):
    if not directory.exists(): return 0
    removed = 0
    for f in directory.iterdir():
        if not f.is_file() or not f.name.endswith(suffix): continue
        if suffix == '.png' and f.name.startswith(_OG_RESERVED_PREFIXES):
            continue
        key = f.name[:-len(suffix)]
        if key not in live_keys:
            try:
                f.unlink()
                removed += 1
            except Exception as ex:
                print(f"  WARN: failed to remove stale {f}: {ex}")
    return removed

n_cuisine_stale  = _cleanup(CUISINE_DIR,  live_cuisines)
n_district_stale = _cleanup(DISTRICT_DIR, live_districts)
n_listing_stale  = _cleanup(LISTING_DIR,  live_slugs)
# Same for the per-listing OG card PNGs + photo JPGs + thumb JPGs that
# track the listing lifecycle. (og/ also holds non-listing assets like
# /og.svg - only the <slug>.png pattern matters here.)
n_og_card_stale  = _cleanup(OG_DIR,           live_slugs, suffix='.png')
n_og_photo_stale = _cleanup(OG_DIR / 'photo', live_slugs, suffix='.jpg')
n_og_thumb_stale = _cleanup(OG_DIR / 'thumb', live_slugs, suffix='.webp')
# Transitional cleanup 2026-05-19: thumbnails switched from JPG → WebP.
# Sweep ALL leftover .jpg thumbs (regardless of slug match - they're no
# longer referenced by HTML; the new code only generates .webp).
_thumb_jpg_dir = OG_DIR / 'thumb'
if _thumb_jpg_dir.exists():
    for _f in _thumb_jpg_dir.iterdir():
        if _f.is_file() and _f.name.endswith('.jpg'):
            try: _f.unlink(); n_og_thumb_stale += 1
            except Exception: pass
print(f"  cleanup: removed {n_cuisine_stale} stale cuisine pages, "
      f"{n_district_stale} stale district pages, {n_listing_stale} stale listings, "
      f"{n_og_card_stale} cards, {n_og_photo_stale} photos, {n_og_thumb_stale} thumbs")

