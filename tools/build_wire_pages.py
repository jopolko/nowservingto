#!/usr/bin/env python3
"""
Generate diaspora-pitch wire pages: wire/<cuisine>.html

One page per target cuisine (Filipino, Jamaican, Vietnamese). Each page
is a self-contained editorial brief built around the visual DNA of the
target audience's home publications - sans-serif, photo-led, card-grid,
restrained accent color. Audited against Spot.ph, Lifestyle.INQ,
Saigoneer, VnExpress, Jamaica Observer, and Jamaicans.com.

Design rules:
- Hero is a real restaurant photograph (og/photo/<slug>.jpg), not a stat
  dashboard. Maps are excluded - audit consensus said map-as-hero
  reads as un-serious.
- One accent color per cuisine (matches the on-site pill color). White
  background, near-black type, dek in muted gray.
- Headline grammar tuned per audience: Filipino gets LIST: prefix
  (Spot.ph-native), Jamaican gets aspirational "Toronto's newest..."
  recognition framing (Jamaicans.com-native), Vietnamese gets quiet
  declarative framing (Saigoneer-native, no hype).
- Census anchors are 2021 absolute Toronto CMA figures only. 2016 -> 2021
  comparisons would be misleading because StatCan changed the
  ethnic-origin coding methodology between cycles.
- No JS. No external chart library. Inline SVG only where needed.

Reads data/corridors.json. Writes wire/<key>.html. Safe to run from cron.
"""
import json, sys
from pathlib import Path
from datetime import date, datetime, timedelta
from collections import Counter
from html import escape as _esc

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / 'data' / 'corridors.json'
WIRE_DIR = ROOT / 'wire'
PHOTO_DIR = ROOT / 'og' / 'photo'

# Photo denylist: union of the manual list (photo_denylist.json) and any
# slugs the Haiku vision classifier flagged as not-restaurant. The wire
# picker bypasses entry.photo/thumb fields (it reads PHOTO_DIR directly),
# so we honor the denylist here too - otherwise a banned hair-salon /
# gas-station / paint-section photo could become the wire-page hero.
_DENY_PATH = ROOT / 'tools' / 'cache' / 'photo_denylist.json'
_CLS_PATH  = ROOT / 'tools' / 'cache' / 'photo_classification.json'
try:
    _PHOTO_DENY = set(json.load(open(_DENY_PATH)).get('slugs') or [])
except FileNotFoundError:
    _PHOTO_DENY = set()
try:
    _cls = json.load(open(_CLS_PATH))
    for _slug, _v in _cls.items():
        if _v.get('status') == 'ok' and _v.get('is_restaurant_or_food') is False:
            _PHOTO_DENY.add(_slug)
except FileNotFoundError:
    pass

# Diaspora pitch targets. Each gets its own accent + headline grammar
# tuned to its home-publication aesthetic. Census numbers are 2021
# absolute Toronto CMA totals (StatCan SIP, DGUID 2021S0503535) -
# do NOT add 2016 deltas; methodology change makes the comparison fake.
# Each target ships with a `headline` (durable - no live counts baked
# in, so it doesn't go stale between updates) and a `field_note_tmpl`
# (HTML, formatted with {n_total}, {n_30d}, {label}, {s30} where
# s30 = 's' if n_30d != 1 else '' - English plural-agreement helper).
# GA4 + Microsoft Clarity lazy-load snippet — kept as a module constant
# so the f-string wire template can splice it in without escaping every
# JS brace as `{{` / `}}`. Same load-on-first-interaction pattern as
# index.html to keep Lighthouse TBT clean.
GA_SNIPPET = """<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  (function() {
    var loaded = false;
    var load = function() {
      if (loaded) return; loaded = true;
      ['scroll','pointerdown','keydown','touchstart','visibilitychange']
        .forEach(function(ev){ window.removeEventListener(ev, load, true); });
      var s = document.createElement('script');
      s.async = true;
      s.src = 'https://www.googletagmanager.com/gtag/js?id=G-CBQJHD3G7P';
      document.head.appendChild(s);
      gtag('js', new Date());
      gtag('config', 'G-CBQJHD3G7P');
      (function(c,l,a,r,i,t,y){
        c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
        t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
        y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
      })(window, document, "clarity", "script", "x10kln08ch");
    };
    ['scroll','pointerdown','keydown','touchstart','visibilitychange']
      .forEach(function(ev){ window.addEventListener(ev, load, {once: true, passive: true, capture: true}); });
    setTimeout(load, 10000);
  })();
</script>"""


# The field note is the editorial paragraph anchoring the data in
# Toronto-diaspora-geography human context; each is hand-written in
# the register of the cuisine's homeland press.
TARGETS = [
    {
        'key': 'filipino',   'label': 'Filipino',
        'color': '#e08226',  'color_dark': '#a85d12',
        'country': 'the Philippines',
        'eyebrow': 'LIST',
        'headline': "Toronto's newest Filipino kitchens",
        'field_note_tmpl': (
            "The diaspora is building. <b>{n_30d}</b> new Filipino "
            "kitchen{s30} registered in the past 30 days. <b>{n_total}</b> "
            "in the past year. Each one is a lease signed, a kitchen "
            "built, a family name committed to, logged the night "
            "each got its City licence so Manila sees the Toronto "
            "chapter before anyone else does."
        ),
    },
    {
        'key': 'jamaican',   'label': 'Jamaican',
        'color': '#1a8a5a',  'color_dark': '#0e5c3a',
        'country': 'Jamaica',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's newest Jamaican kitchens",
        'field_note_tmpl': (
            "Eglinton West has anchored Toronto&apos;s Jamaican food "
            "culture for two generations. But the <b>{n_total}</b> "
            "kitchens below cluster across Scarborough, the western "
            "401 corridor, and Etobicoke as much as the original Little "
            "Jamaica - with <b>{n_30d}</b> of them registered in "
            "just the past 30 days."
        ),
    },
    {
        'key': 'vietnamese', 'label': 'Vietnamese',
        'color': '#4a8b8b',  'color_dark': '#2a5e5e',
        'country': 'Vietnam',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Vietnamese kitchens, by the week",
        'field_note_tmpl': (
            "Spadina&apos;s original Chinatown pho wave is no longer "
            "where the new ones land. The <b>{n_total}</b> Vietnamese "
            "kitchens below opened across Bloor East and Scarborough "
            "in the past year, with <b>{n_30d}</b> registered in just "
            "the last 30 days."
        ),
    },
    {
        'key': 'indian',     'label': 'Indian',
        'color': '#e88e2c',  'color_dark': '#b06820',
        'country': 'India',
        'eyebrow': 'TIMES OF TORONTO',
        'headline': "Toronto's newest Indian kitchens, region by region",
        'field_note_tmpl': (
            "Indian isn&apos;t a monolith and the licence registry "
            "knows it. The <b>{n_total}</b> kitchens below span "
            "Hyderabadi biryani houses on Davenport, Punjabi dhabas "
            "in Scarborough, Tamil-South Indian dosa counters on Kennedy, "
            "and the Indo-Chinese hybrid spots Toronto invented twice "
            "over - with <b>{n_30d}</b> of them registered in just "
            "the past 30 days. Brampton and Mississauga get the press; "
            "the registry shows the city proper is keeping pace."
        ),
    },
    {
        'key': 'chinese',    'label': 'Chinese',
        'color': '#b13e6a',  'color_dark': '#82294a',
        'country': 'China',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Chinese kitchens, regional and rising",
        'field_note_tmpl': (
            "The Spadina-Dundas Cantonese era anchors a generation; the "
            "<b>{n_total}</b> kitchens below tell the next chapter. "
            "Sichuan hot-pot, Yunnan rice-noodle, Shanghainese xiao long "
            "bao, Hakka, even Uyghur polov - the regional map of "
            "China keeps unfolding across Markham, Steeles East, North "
            "York, and back into downtown. <b>{n_30d}</b> registered in "
            "just the past 30 days."
        ),
    },
    {
        'key': 'italian',    'label': 'Italian',
        'color': '#c83624',  'color_dark': '#8e2218',
        'country': 'Italy',
        'eyebrow': 'REGISTRO TORONTO',
        'headline': "Toronto's newest Italian kitchens",
        'field_note_tmpl': (
            "Little Italy on College, Corso Italia on St Clair West, "
            "Woodbridge for the second generation - and now a "
            "return downtown for the third. The <b>{n_total}</b> Italian "
            "kitchens licensed by the City of Toronto in the past 12 "
            "months sit across all four chapters at once: red-sauce "
            "trattorias, Neapolitan pizzerias, Roman-style by-the-slice, "
            "fresh-pasta counters, gelato. <b>{n_30d}</b> of them in "
            "just the past 30 days."
        ),
    },
    {
        'key': 'mexican',    'label': 'Mexican',
        'color': '#d63d2a',  'color_dark': '#a02a1d',
        'country': 'Mexico',
        'eyebrow': 'TORONTO, EN EL REGISTRO',
        'headline': "Toronto's newest Mexican kitchens",
        'field_note_tmpl': (
            "A decade ago Toronto had a handful of taquerias. The "
            "<b>{n_total}</b> kitchens below - <b>{n_30d}</b> "
            "registered in just the past 30 days - show the wave: "
            "birria-and-consom&eacute; counters along Bloor West and "
            "Danforth, regional-specific spots from Jalisco, Puebla, "
            "Oaxaca, CDMX, and Yucatec specialists you couldn&apos;t "
            "find here at all five years ago. The City of Toronto&apos;s "
            "nightly licence registry is where the wave shows first."
        ),
    },
    {
        'key': 'korean',     'label': 'Korean',
        'color': '#6b2456',  'color_dark': '#4a1838',
        'country': 'Korea',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Korean kitchens, K-town and beyond",
        'field_note_tmpl': (
            "Bloor-Christie is the original Koreatown; the Yonge "
            "corridor north of Finch is the second. The <b>{n_total}</b> "
            "Korean kitchens registered in the past 12 months sit across "
            "both anchors and the downtown spillover - gimbap "
            "counters, Korean fried chicken, soju-and-tteokbokki "
            "late-night spots, KBBQ houses. <b>{n_30d}</b> of them in "
            "just the past 30 days."
        ),
    },
    {
        'key': 'tamil',      'label': 'Tamil',
        'color': '#8a5d20',  'color_dark': '#5a3d10',
        'country': 'Sri Lanka and Tamil Nadu',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Tamil kitchens, Scarborough's everyday wave",
        'field_note_tmpl': (
            "Scarborough holds one of the densest concentrations of "
            "Tamil-owned food businesses anywhere outside South Asia. "
            "The <b>{n_total}</b> Tamil kitchens below sit on Markham "
            "Rd, Brimley, McNicoll, Eglinton East - kothu roti "
            "stalls, idiyappam-and-curry counters, Jaffna-style "
            "mutton specialists, dosa kitchens. <b>{n_30d}</b> "
            "registered in just the past 30 days."
        ),
    },
    # ─── Tier 2 hand-authored: ≥10 entries ───────────────────────────────
    {
        'key': 'japanese',   'label': 'Japanese',
        'color': '#2f3aa3',  'color_dark': '#1c2470',
        'country': 'Japan',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Japanese kitchens, counter by counter",
        'field_note_tmpl': (
            "Toronto&apos;s Japanese kitchens cluster across three "
            "anchors - the Yonge corridor from Eglinton north to "
            "Sheppard, Markham&apos;s Pacific Mall belt, and the "
            "Bay-Yonge downtown core. The <b>{n_total}</b> registered in "
            "the past 12 months sit across all three: omakase counters, "
            "izakaya, ramen-yas, conveyor sushi, and bento takeouts. "
            "<b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'thai',       'label': 'Thai',
        'color': '#7a8a3a',  'color_dark': '#4f5a22',
        'country': 'Thailand',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Thai kitchens, regional and unhidden",
        'field_note_tmpl': (
            "Toronto&apos;s Thai scene has stopped pretending pad thai "
            "is the whole menu. The <b>{n_total}</b> kitchens below "
            "include som tum specialists, Isaan-northeastern grills, "
            "boat-noodle counters, and curry-paste-from-scratch "
            "spots across Spadina, College, Bloor East, and Yonge "
            "- with <b>{n_30d}</b> registered in just the past "
            "30 days."
        ),
    },
    {
        'key': 'turkish',    'label': 'Turkish',
        'color': '#a8662a',  'color_dark': '#6e3f15',
        'country': 'T&uuml;rkiye',
        'eyebrow': 'TORONTO&apos;NUN KAYDI',
        'headline': "Toronto's Turkish kitchens, lahmacun to s&uuml;tla&ccedil;",
        'field_note_tmpl': (
            "Toronto&apos;s Turkish kitchens anchor along Yonge north "
            "of Sheppard, with a second cluster on Eglinton West and "
            "scattered shops downtown. The <b>{n_total}</b> licensed "
            "in the past year include lahmacun bakeries, kebab houses, "
            "simit cafes, and the first wave of Anatolian-regional "
            "specialists Toronto has seen outside Mississauga. "
            "<b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'french',     'label': 'French',
        'color': '#5a3a7a',  'color_dark': '#3a2552',
        'country': 'France',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's French kitchens, bistro and patisserie",
        'field_note_tmpl': (
            "Toronto&apos;s French kitchens sit across Yorkville, "
            "King West, Ossington, and the Yonge-Eglinton corridor. "
            "The <b>{n_total}</b> registered in the past year include "
            "neighborhood bistros, p&acirc;tisseries, wine bars, and "
            "a small but growing wave of Lyonnais-style bouchons. "
            "<b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'lebanese',   'label': 'Lebanese',
        'color': '#c89538',  'color_dark': '#8a6420',
        'country': 'Lebanon',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Lebanese kitchens, shawarma to knafeh",
        'field_note_tmpl': (
            "Lebanese cooking is one of Toronto&apos;s deepest "
            "diaspora cuisines - the <b>{n_total}</b> kitchens "
            "below stretch from Yonge-Sheppard shawarma counters and "
            "North York mezza houses to Etobicoke bakeries turning "
            "out fresh man&apos;oushe and knafeh. <b>{n_30d}</b> "
            "registered in the past 30 days."
        ),
    },
    {
        'key': 'middle_east','label': 'Middle Eastern',
        'color': '#b87a25',  'color_dark': '#7a4f12',
        'country': 'the Levant and beyond',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Middle Eastern kitchens, by the registry",
        'field_note_tmpl': (
            "Toronto&apos;s broader Middle Eastern scene - "
            "Mediterranean grills, mixed-Levantine spots, shawarma "
            "counters that don&apos;t fit a single national label "
            "- counts <b>{n_total}</b> kitchens in the past "
            "12 months, with <b>{n_30d}</b> registered in the past 30 "
            "days. The City&apos;s registry doesn&apos;t enforce "
            "national borders; neither do these menus."
        ),
    },
    # ─── Tier 3 hand-authored: 5-9 entries ───────────────────────────────
    {
        'key': 'nigerian',   'label': 'Nigerian',
        'color': '#4a7a30',  'color_dark': '#2e5018',
        'country': 'Nigeria',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Nigerian kitchens, jollof to suya",
        'field_note_tmpl': (
            "Toronto&apos;s Nigerian food scene has crossed from "
            "home-kitchen catering into the licence registry: "
            "<b>{n_total}</b> kitchens in the past 12 months, "
            "jollof-rice specialists and suya grills, anchored along "
            "Eglinton West, with overflow into Etobicoke and the 401 "
            "corridor toward Brampton. <b>{n_30d}</b> in the past 30 "
            "days."
        ),
    },
    {
        'key': 'pakistani',  'label': 'Pakistani',
        'color': '#a06030',  'color_dark': '#6a3e18',
        'country': 'Pakistan',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Pakistani kitchens, biryani and karahi",
        'field_note_tmpl': (
            "Pakistani cooking has its own current in Toronto, "
            "separate from the umbrella Indian-restaurant scene. The "
            "<b>{n_total}</b> kitchens below specialize in karahi, "
            "nihari, biryani, and Lahori grill, anchored across "
            "Scarborough, Mississauga&apos;s spillover into Etobicoke, "
            "and the Don Mills corridor. <b>{n_30d}</b> in the past "
            "30 days."
        ),
    },
    {
        'key': 'caribbean',  'label': 'Caribbean',
        'color': '#1a8a5a',  'color_dark': '#0e5c3a',
        'country': 'the Caribbean',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Caribbean kitchens, beyond the islands",
        'field_note_tmpl': (
            "Toronto&apos;s broader Caribbean scene - spots "
            "that don&apos;t fit a single island, roti shops with "
            "Trinidadian-Guyanese hybrid menus, jerk-and-curry "
            "counters - counts <b>{n_total}</b> kitchens "
            "registered in the past 12 months, anchored on Eglinton "
            "West and Scarborough. <b>{n_30d}</b> in the past 30 days. "
            "For island-specific cuts, see Jamaican, Trinidadian, "
            "Guyanese, and Haitian briefs separately."
        ),
    },
    {
        'key': 'portuguese', 'label': 'Portuguese',
        'color': '#9b2538',  'color_dark': '#651620',
        'country': 'Portugal',
        'eyebrow': 'REGISTO TORONTO',
        'headline': "Toronto's Portuguese kitchens, the Dundas West cradle",
        'field_note_tmpl': (
            "Little Portugal - Dundas West, Ossington, "
            "Davenport - remains the cradle. The <b>{n_total}</b> "
            "Portuguese kitchens registered in the past 12 months sit "
            "across the original blocks plus a recent expansion north "
            "into Bloordale: pastel de nata bakeries, churrasco "
            "houses, bifana counters, and a quiet wave of Aoreanu "
            "regional specialists. <b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'persian',    'label': 'Persian',
        'color': '#8a4a25',  'color_dark': '#5a2f14',
        'country': 'Iran',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Persian kitchens, Yonge-Finch and beyond",
        'field_note_tmpl': (
            "Yonge between Finch and Steeles is Toronto&apos;s Persian "
            "heartland, with overflow into Richmond Hill and a downtown "
            "presence. The <b>{n_total}</b> kitchens below cover the "
            "full Persian table - kabab houses with charcoal "
            "kubideh, full-menu spots serving ghormeh sabzi and tahdig, "
            "tea-houses, sweet shops. <b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'greek',      'label': 'Greek',
        'color': '#1f7a6a',  'color_dark': '#0f4e44',
        'country': 'Greece',
        'eyebrow': 'TORONTO &Sigma;&Eta;&Mu;&Epsilon;&Iota;&Omega;&Mu;&Alpha;',
        'headline': "Toronto's Greek kitchens, Greektown and after",
        'field_note_tmpl': (
            "The Danforth between Pape and Logan still carries the "
            "Greektown name. But the <b>{n_total}</b> Greek kitchens "
            "registered in the past 12 months stretch well beyond "
            "- souvlaki counters in midtown, modern Greek bistros "
            "downtown, and the next generation of tavernas opening east "
            "of Coxwell. <b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'sri_lankan', 'label': 'Sri Lankan',
        'color': '#a9882c',  'color_dark': '#6f5614',
        'country': 'Sri Lanka',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Sri Lankan kitchens, Sinhala and Tamil",
        'field_note_tmpl': (
            "Sri Lankan cooking in Toronto threads through Scarborough "
            "alongside the Tamil scene but carries its own register: "
            "hoppers, lamprais, lunu miris, and the Sinhala-distinct "
            "side of the table. The <b>{n_total}</b> kitchens licensed "
            "in the past 12 months sit across Markham Rd, Eglinton East, "
            "and the Lawrence-Kennedy belt. <b>{n_30d}</b> in the past "
            "30 days."
        ),
    },
    {
        'key': 'ethiopian',  'label': 'Ethiopian',
        'color': '#a0522d',  'color_dark': '#6a341a',
        'country': 'Ethiopia',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Ethiopian kitchens, Little Ethiopia and east",
        'field_note_tmpl': (
            "The Danforth east of Greenwood holds Toronto&apos;s "
            "Little Ethiopia - the densest Ethiopian-Eritrean "
            "restaurant cluster anywhere in Canada. The <b>{n_total}</b> "
            "kitchens registered in the past 12 months sit across that "
            "anchor plus a Bloor West node and downtown spillover: "
            "injera houses, tibs grills, kitfo and doro wat "
            "specialists. <b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'bangladeshi','label': 'Bangladeshi',
        'color': '#b88820',  'color_dark': '#7a5810',
        'country': 'Bangladesh',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Bangladeshi kitchens, Danforth east",
        'field_note_tmpl': (
            "Bangladeshi cooking has its own cluster in Toronto - "
            "Danforth East between Victoria Park and Warden, with "
            "overflow into Scarborough proper. The <b>{n_total}</b> "
            "kitchens below serve bhuna khichuri, kacchi biryani, "
            "pitha sweets, and the everyday rice-and-curry menus that "
            "anchor a specific generation of immigrant cooking. "
            "<b>{n_30d}</b> in the past 30 days."
        ),
    },
    {
        'key': 'colombian',  'label': 'Colombian',
        'color': '#cc6248',  'color_dark': '#8a3f2c',
        'country': 'Colombia',
        'eyebrow': 'TORONTO, EN EL REGISTRO',
        'headline': "Toronto's Colombian kitchens, arepas and beyond",
        'field_note_tmpl': (
            "Colombian cooking has moved past the home-kitchen "
            "stage in Toronto. The <b>{n_total}</b> kitchens licensed "
            "in the past 12 months serve arepas con todo, bandeja "
            "paisa, empanadas, and the Caribbean-coast and "
            "Andean-region specialists Toronto didn&apos;t have a "
            "decade ago. <b>{n_30d}</b> in the past 30 days."
        ),
    },
    # ─── Tier 4 generic: 3-4 entries (auto-templated field note) ─────────
    {
        'key': 'afghan',     'label': 'Afghan',
        'color': '#7a5d3a',  'color_dark': '#4f3c24',
        'country': 'Afghanistan',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Afghan kitchens, kabuli and kebab",
    },
    {
        'key': 'trinidadian','label': 'Trinidadian',
        'color': '#2a9560',  'color_dark': '#16613c',
        'country': 'Trinidad and Tobago',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Trinidadian kitchens, roti and doubles",
    },
    {
        'key': 'nepalese',   'label': 'Nepalese',
        'color': '#5ea92c',  'color_dark': '#3d7016',
        'country': 'Nepal',
        'eyebrow': 'TORONTO REGISTER',
        'headline': "Toronto's Nepalese kitchens, momos and thakali",
    },
]


def _has_photo(slug):
    """Real Places photo exists locally for this slug AND is not denylisted
    by the manual list or the Haiku vision classifier verdict."""
    if not slug: return False
    if slug in _PHOTO_DENY: return False
    return (PHOTO_DIR / f'{slug}.jpg').exists() or (PHOTO_DIR / f'{slug}.png').exists()


def _photo_url(slug):
    """Return URL path to the largest available photo for slug. Falls
    back to thumb if no full photo. Returns None if neither exists."""
    if not slug: return None
    for ext in ('jpg', 'png'):
        if (PHOTO_DIR / f'{slug}.{ext}').exists():
            return f'/og/photo/{slug}.{ext}'
    thumb = ROOT / 'og' / 'thumb' / f'{slug}.webp'
    if thumb.exists():
        return f'/og/thumb/{slug}.webp'
    return None


def _photo_size(slug):
    """File size in bytes of the slug's photo, or 0 if missing."""
    if not slug: return 0
    for ext in ('jpg', 'png'):
        p = PHOTO_DIR / f'{slug}.{ext}'
        if p.exists():
            try: return p.stat().st_size
            except OSError: return 0
    return 0


def _image_wh(path):
    """Return (width, height) for a JPEG or PNG by reading the header.
    Stdlib-only (no Pillow); works in the prod venv where Pillow
    isn't installed. Handles JPEGs misnamed as .png / PNGs misnamed
    as .jpg (some Places photo downloads land cross-named). Returns
    None if unreadable or an unsupported format."""
    try:
        with open(path, 'rb') as f:
            head = f.read(8)
            # PNG: signature \x89PNG\r\n\x1a\n, IHDR at offset 16 (w,h u32 BE)
            if head.startswith(b'\x89PNG\r\n\x1a\n'):
                f.read(8)  # IHDR chunk length(4) + type(4)
                w = int.from_bytes(f.read(4), 'big')
                h = int.from_bytes(f.read(4), 'big')
                return w, h
            # JPEG: SOI marker FFD8, walk segments to SOFn for dimensions
            if head[:2] == b'\xff\xd8':
                f.seek(2)
                while True:
                    b = f.read(2)
                    if len(b) < 2 or b[0] != 0xff: return None
                    marker = b[1]
                    if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
                        f.read(3)  # length(2) + precision(1)
                        h = int.from_bytes(f.read(2), 'big')
                        w = int.from_bytes(f.read(2), 'big')
                        return w, h
                    length = int.from_bytes(f.read(2), 'big')
                    if length < 2: return None
                    f.seek(length - 2, 1)
            return None
    except (OSError, ValueError):
        return None


def _photo_aspect(slug):
    """Width/height ratio of the slug's photo, or 0 if unreadable.
    >1.0 = landscape, ~1.0 = square, <1.0 = portrait. Hero banners
    use background-size:cover at min-height 64vh - landscape photos
    (ratio ≥ 1.5) crop cleanly; square/portrait crops awkwardly."""
    if not slug: return 0
    for ext in ('jpg', 'png'):
        p = PHOTO_DIR / f'{slug}.{ext}'
        if p.exists():
            wh = _image_wh(p)
            if wh and wh[1]:
                return wh[0] / wh[1]
    return 0


# Photo-quality threshold for hero selection. Google Places "Premium"
# photos are typically 300-800 KB at 1600+ wide; Street View fallbacks
# land around 80-120 KB at 640x640; low-res storefronts under ~200 KB.
# We require ≥250 KB AND ≥1200 wide AND landscape ≥1.5 for the hero -
# anything below the bar falls through to the gradient .hero-flat
# fallback, which carries the headline over a bold accent-color wash.
# This is the photo-magazine pattern: don't crop a portrait to a 16:9
# banner; publish the typography moment instead.
HERO_QUALITY_MIN_BYTES = 250_000
HERO_MIN_WIDTH         = 1200


def _pick_hero(matches, override_slug=None):
    """Pick the best available hero photo. If TARGETS sets `hero_slug`,
    honor it (manual escape hatch). Otherwise walk in recency order
    across passes of relaxing standards. Most cuisines should land a
    photo in pass 1 or 2; only cuisines with truly bad photo cohorts
    fall through to the gradient block.

      Pass 1: BANNER-GRADE      landscape ≥1.5 + ≥1200 wide + ≥250 KB
      Pass 2: ACCEPTABLE         landscape ≥1.3 (4:3) + ≥800 wide + ≥150 KB
      Pass 3: ANY REAL RESTAURANT-PASSING photo (skip portraits ≤0.85
              because those crop visibly badly into the wide banner,
              but accept anything else)
      Pass 4: (None, None) → caller renders the gradient .hero-flat
    """
    if override_slug:
        for e in matches:
            if e.get('slug') == override_slug and _has_photo(override_slug):
                return e, _photo_url(override_slug)

    def width_of(slug):
        for ext in ('jpg', 'png'):
            p = PHOTO_DIR / f'{slug}.{ext}'
            if p.exists():
                wh = _image_wh(p)
                return wh[0] if wh else 0
        return 0

    # Pass 1: banner-grade
    for e in matches:
        slug = e.get('slug', '')
        if not _has_photo(slug): continue
        if _photo_size(slug) < 250_000: continue
        if _photo_aspect(slug) < 1.5: continue
        if width_of(slug) < 1200: continue
        return e, _photo_url(slug)
    # Pass 2: acceptable (4:3 landscape)
    for e in matches:
        slug = e.get('slug', '')
        if not _has_photo(slug): continue
        if _photo_size(slug) < 150_000: continue
        if _photo_aspect(slug) < 1.30: continue
        if width_of(slug) < 800: continue
        return e, _photo_url(slug)
    # Pass 3: anything not visibly portrait
    for e in matches:
        slug = e.get('slug', '')
        if not _has_photo(slug): continue
        aspect = _photo_aspect(slug)
        if aspect and aspect < 0.85: continue   # skip true portraits
        return e, _photo_url(slug)
    return None, None


def _when_label(days):
    if days is None: return ''
    if days <= 1: return 'TODAY'
    if days <= 7: return f'{days}D AGO'
    if days <= 60: return f'{days}D AGO'
    if days <= 365: return f'{round(days/30)}MO AGO'
    return f'{days/365:.1f}Y AGO'


def build_district_bars(district_counts, color):
    """CSS-only horizontal bar chart. Returns inner HTML to drop into
    a parent with class district-bars."""
    if not district_counts: return ''
    items = sorted(district_counts.items(), key=lambda x: -x[1])
    max_c = items[0][1]
    rows = []
    for d, c in items:
        pct = (c / max_c) * 100
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-label">{_esc(d)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="bar-count">{c}</div>'
            f'</div>'
        )
    return '\n'.join(rows)


def build_card_grid(matches, color, limit=12):
    """Restaurant card grid. Each card: 1:1 photo + bold name +
    neighborhood + recency tag. Matches Spot.ph / Jamaicans.com /
    Saigoneer card patterns."""
    cards = []
    for e in matches[:limit]:
        slug = e.get('slug', '')
        name = _esc(e.get('operatingName') or 'Unknown')
        addr = _esc(e.get('address') or '')
        district = _esc(e.get('district') or '')
        days = e.get('daysOpen', 999)
        when = _when_label(days)
        link = e.get('mapsUrl') or e.get('website') or (f'/r/{slug}' if slug else '#')
        # Photo slot retired site-wide 2026-06-03; cards are text-only.
        district_pill = f' <span class="card-district">{district}</span>' if district else ''
        cards.append(
            f'<article class="card">'
            f'<div class="card-body">'
            f'<div class="card-when" style="color:{color}">{when}</div>'
            f'<h3 class="card-name"><a href="{_esc(link)}" rel="noopener">{name}</a></h3>'
            f'<div class="card-meta">{addr}{district_pill}</div>'
            f'</div>'
            f'</article>'
        )
    return '\n'.join(cards)


def build_wire_page(target, entries):
    matches = [e for e in entries
               if target['key'] in (e.get('cuisines') or [e.get('cuisine', '')])]
    matches = sorted(matches, key=lambda e: e.get('daysOpen', 99999))

    n_total = len(matches)
    n_7d  = sum(1 for e in matches if e.get('daysOpen', 99999) <= 7)
    n_30d = sum(1 for e in matches if e.get('daysOpen', 99999) <= 30)
    n_90d = sum(1 for e in matches if e.get('daysOpen', 99999) <= 90)
    by_district = Counter(e.get('district') or 'Unknown' for e in matches)
    n_districts = len(by_district)

    # Dynamic pulse eyebrow: shows the smallest active time window so the
    # page leads with the freshest signal. "1 NEW · THIS WEEK" >
    # "3 NEW · THIS MONTH" > "12 NEW · THIS YEAR" - the more recent the
    # window, the more dopamine.
    if n_7d > 0:
        pulse_n, pulse_window = n_7d, 'THIS WEEK'
    elif n_30d > 0:
        pulse_n, pulse_window = n_30d, 'THIS MONTH'
    elif n_90d > 0:
        pulse_n, pulse_window = n_90d, 'THIS QUARTER'
    else:
        pulse_n, pulse_window = n_total, 'PAST 12 MONTHS'

    # Hero picker retired (no photos to pick from) — flat color hero only.
    hero_entry, hero_photo = None, None

    color = target['color']
    color_dark = target['color_dark']
    label = target['label']
    country = target['country']

    # Stat strip cells. Hide windows where the count is zero - "0 in past
    # 30 days" reads as a dead column to a diaspora editor scanning for
    # momentum. Labels are "Past N days/months" (replaces "This Week /
    # Month / Quarter" - "quarter" is finance jargon, not editorial).
    # Column count is set via inline CSS vars so the gap-as-divider
    # styling renders cleanly for any 1-4 cell layout.
    _stat_cells = [
        (n_7d,   'Past 7 days'),
        (n_30d,  'Past 30 days'),
        (n_90d,  'Past 3 months'),
        (n_total,'Past 12 months'),
    ]
    _visible = [(n, lbl) for n, lbl in _stat_cells if n > 0]
    if not _visible:
        _visible = [(n_total, 'Past 12 months')]  # always show at least one
    _cols_desktop = len(_visible)
    _cols_mobile  = 2 if _cols_desktop >= 3 else _cols_desktop
    stats_html = (
        f'  <div class="stats" style="--cols-desktop: {_cols_desktop}; --cols-mobile: {_cols_mobile}">\n'
        + '\n'.join(
            f'    <div class="stat">\n'
            f'      <div class="stat-num">{n}</div>\n'
            f'      <div class="stat-label">{lbl}</div>\n'
            f'    </div>'
            for n, lbl in _visible)
        + '\n  </div>'
    )

    # "This Week in Toronto" is the column name across all three cuisines.
    # Ties cadence to the rhythm a homeland-media editor cares about: what
    # hit Toronto's licensing feed this week, ready to publish back home
    # this week. Also matches Toronto Caribbean diaspora print rhythm
    # (Share, Pride News, Caribbean Camera all weekly), Inquirer Sunday
    # food editions, and VnExpress weekly digests.
    eyebrow = 'THIS WEEK IN TORONTO'

    # Headline pulled from target config - durable (no live counts baked
    # in, so it doesn't go stale between updates). The eyebrow + stats
    # strip carry the live-this-week energy instead.
    headline = target.get('headline') or f"Toronto's newest {label} kitchens"

    # Dek leads with this-week count if there's activity, else cascades
    # to whichever window first has movement. Editors see the pulse first.
    if n_7d > 0:
        dek = f"{n_7d} licensed this week. {n_total} in the past year. From the City of Toronto’s nightly registry."
    elif n_30d > 0:
        dek = f"{n_30d} licensed this month. {n_total} in the past year. From the City of Toronto’s nightly registry."
    else:
        dek = f"{n_total} registered in the past year. From the City of Toronto’s nightly registry."
    today = date.today()
    updated_str = today.isoformat()
    updated_human = today.strftime('%B %-d, %Y')

    # Hero — photo backdrop retired 2026-06-03 with the rest of the photo
    # pipeline. All wire pages now use the flat cuisine-color gradient hero
    # (was previously the no-photo fallback path).
    hero_html = (
        f'<div class="hero hero-flat" style="background: linear-gradient(135deg, {color} 0%, {color_dark} 100%);">'
        f'<div class="hero-inner">'
        f'<div class="hero-eyebrow" style="color:rgba(255,255,255,0.9)">{eyebrow}</div>'
        f'<h1 class="hero-headline">{_esc(headline)}</h1>'
        f'<p class="hero-dek">{_esc(dek)}</p>'
        f'</div>'
        f'</div>'
    )

    card_grid = build_card_grid(matches, color)
    district_bars = build_district_bars(by_district, color)

    title = f"This Week in Toronto · Newest {label} kitchens"
    meta_desc = (
        f"{n_7d} licensed this week, {n_total} in the past year. "
        f"Every {label} restaurant the City of Toronto has licensed, "
        f"tracked nightly. Updated {updated_human}."
    )

    # Per-cuisine field note - hand-written in TARGETS as a template
    # string with named placeholders. Formats {n_total}, {n_30d}, {label},
    # and {s30} (plural-agreement helper: 's' when n_30d != 1).
    tmpl = target.get('field_note_tmpl') or (
        "<b>{n_total}</b> {label} kitchens licensed by the City of "
        "Toronto in the past 12 months, with <b>{n_30d}</b> in the past "
        "30 days. Tracked nightly from the municipal registry."
    )
    field_note = tmpl.format(
        n_total=n_total, n_30d=n_30d, label=label,
        s30='s' if n_30d != 1 else '',
    )

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(meta_desc)}">
<meta name="theme-color" content="{color}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(meta_desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://nowservingto.com/wire/{target['key']}">
{f'<meta property="og:image" content="https://nowservingto.com{hero_photo}">' if hero_photo and hero_photo.startswith('/') else ''}
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://nowservingto.com/wire/{target['key']}">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article","@id":"https://nowservingto.com/wire/{target['key']}#article","headline":{json.dumps(headline)},"description":{json.dumps(meta_desc)},"datePublished":{json.dumps(updated_str)},"dateModified":{json.dumps(updated_str)},"url":"https://nowservingto.com/wire/{target['key']}","mainEntityOfPage":{{"@id":"https://nowservingto.com/wire/{target['key']}"}},"author":{{"@id":"https://nowservingto.com/#organization"}},"publisher":{{"@id":"https://nowservingto.com/#organization"}},"about":{{"@type":"Thing","name":{json.dumps(label + " cuisine")}}}}}</script>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Home","item":"https://nowservingto.com/"}},{{"@type":"ListItem","position":2,"name":{json.dumps(label + " wire")},"item":"https://nowservingto.com/wire/{target['key']}"}}]}}</script>
<style>
  :root {{
    --ink: #131516; --ink2: #46494c; --muted: #74787c; --paper: #ffffff;
    --bg: #fafafa; --line: #ebecef; --accent: {color}; --accent-dark: {color_dark};
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink); font-family: var(--sans); -webkit-font-smoothing: antialiased; line-height: 1.5; }}
  a {{ color: inherit; }}

  /* HERO: full-bleed photo with dark gradient bottom + overlaid type */
  .hero {{ position: relative; width: 100%; min-height: 64vh; max-height: 720px; background-size: cover; background-position: center 35%; background-color: #1a1a1a; display: flex; align-items: flex-end; }}
  .hero-flat {{ min-height: 50vh; }}
  .hero-inner {{ width: 100%; max-width: 1080px; margin: 0 auto; padding: 60px 32px; color: #fff; position: relative; z-index: 2; }}
  .hero-eyebrow {{ font: 800 12px/1 var(--sans); letter-spacing: 0.2em; text-transform: uppercase; margin-bottom: 14px; }}
  .hero-headline {{ font: 800 clamp(34px, 5vw, 56px)/1.08 var(--sans); margin: 0; letter-spacing: -0.025em; }}
  .hero-dek {{ font: 400 clamp(15px, 1.7vw, 17px)/1.5 var(--sans); margin: 18px 0 0; color: rgba(255,255,255,0.88); }}
  /* .hero-credit retired with photo hero — 2026-06-03 */

  /* MAIN WRAPPER */
  main {{ max-width: 1080px; margin: 0 auto; padding: 0 32px; }}
  @media (max-width: 640px) {{ main {{ padding: 0 18px; }} .hero-inner {{ padding: 44px 18px; }} }}

  /* STAT STRIP: photo-magazine style. Cell count is dynamic (zero-count
     windows are omitted), so cells are separated by gap-as-divider
     rather than positional border rules - any count from 1-4 renders
     cleanly. Column count comes from --cols-desktop / --cols-mobile
     inline CSS vars set when the strip is built. */
  .stats {{ display: grid; grid-template-columns: repeat(var(--cols-desktop, 4), 1fr); gap: 1px; background: var(--line); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin: 48px 0 40px; }}
  .stat {{ background: var(--paper); padding: 22px 18px; }}
  .stat-num {{ font: 800 clamp(28px, 4vw, 40px)/1 var(--sans); color: var(--accent); letter-spacing: -0.02em; }}
  .stat-label {{ font: 600 10.5px/1.3 var(--sans); color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-top: 8px; }}
  @media (max-width: 640px) {{
    .stats {{ grid-template-columns: repeat(var(--cols-mobile, 2), 1fr); }}
  }}

  /* FIELD NOTE: short editorial paragraph anchoring the data in human context */
  .field-note {{ font: 400 17px/1.6 var(--sans); color: var(--ink2); margin: 0 0 60px; padding: 0 0 0 18px; border-left: 3px solid var(--accent); }}
  .field-note b {{ color: var(--ink); font-weight: 700; }}

  /* SECTION HEADERS */
  section {{ margin: 56px 0; }}
  section > h2 {{ font: 800 24px/1.2 var(--sans); margin: 0 0 6px; letter-spacing: -0.015em; }}
  section > .h2-dek {{ font: 400 14.5px/1.5 var(--sans); color: var(--muted); margin-bottom: 28px; }}

  /* CARD GRID */
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .card {{ background: var(--paper); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; transition: transform 0.18s, box-shadow 0.18s; }}
  .card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.08); }}
  /* .card-photo / .card-photo-empty retired with photo pipeline — 2026-06-03 */
  .card-body {{ padding: 16px 18px 18px; }}
  .card-when {{ font: 800 11px/1 var(--sans); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }}
  .card-name {{ font: 700 17px/1.25 var(--sans); margin: 0 0 6px; letter-spacing: -0.005em; }}
  .card-name a {{ text-decoration: none; border-bottom: 1px solid transparent; transition: border-color 0.12s; }}
  .card-name a:hover {{ border-bottom-color: var(--accent); }}
  .card-meta {{ font: 400 13px/1.45 var(--sans); color: var(--ink2); }}
  .card-district {{ display: inline-block; margin-left: 4px; padding: 2px 7px; background: var(--bg); border-radius: 99px; font: 600 11px/1.4 var(--sans); color: var(--muted); }}

  /* DISTRICT BAR CHART */
  .district-bars {{ display: flex; flex-direction: column; gap: 14px; }}
  .bar-row {{ display: grid; grid-template-columns: 160px 1fr 40px; align-items: center; gap: 14px; }}
  .bar-label {{ font: 700 12.5px/1 var(--sans); letter-spacing: 0.05em; text-transform: uppercase; color: var(--ink); }}
  .bar-track {{ height: 14px; background: var(--bg); border-radius: 7px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 7px; }}
  .bar-count {{ font: 700 18px/1 var(--sans); color: var(--ink); text-align: right; }}
  @media (max-width: 540px) {{ .bar-row {{ grid-template-columns: 110px 1fr 32px; gap: 10px; }} .bar-label {{ font-size: 11px; }} }}

  /* FOOTER */
  .foot {{ margin: 70px 0 50px; padding-top: 30px; border-top: 1px solid var(--line); font: 400 13.5px/1.55 var(--sans); color: var(--muted); }}
  .foot a {{ color: var(--ink2); text-decoration: underline; }}
  .foot p + p {{ margin-top: 14px; }}
  .foot .cta {{ display: inline-block; margin-top: 18px; padding: 12px 22px; background: var(--ink); color: #fff; text-decoration: none; font: 700 14px/1 var(--sans); border-radius: 8px; letter-spacing: 0.005em; }}
  .foot .cta:hover {{ background: var(--accent); }}

  /* META BAR (small top utility bar with site brand) */
  .topbar {{ position: absolute; top: 0; left: 0; right: 0; padding: 18px 32px; z-index: 3; display: flex; justify-content: space-between; align-items: center; }}
  .topbar .brand {{ font: 800 17px/1 var(--sans); letter-spacing: -0.01em; color: #fff; text-decoration: none; }}
  .topbar .updated {{ font: 600 11px/1 var(--sans); letter-spacing: 0.12em; text-transform: uppercase; color: rgba(255,255,255,0.85); }}
  .topbar .updated b {{ color: #fff; font-weight: 800; }}
  @media (max-width: 640px) {{ .topbar {{ padding: 14px 18px; }} .topbar .brand {{ font-size: 15px; }} }}
</style>
{GA_SNIPPET}
</head>
<body>

{hero_html.replace('<div class="hero', '<div class="topbar"><a class="brand" href="/">NowServingTO</a><span class="updated"><b>This Week in Toronto</b> · ' + updated_human + '</span></div><div class="hero', 1)}

<main>

{stats_html}

  <p class="field-note">{field_note}</p>

  <section>
    <h2>The {min(n_total, 12)} most recently licensed</h2>
    <div class="h2-dek">Click any card to open the restaurant&apos;s Google Maps profile. Cards link out to live listings.</div>
    <div class="grid">
      {card_grid}
    </div>
  </section>

  <section>
    <h2>Where they&apos;re opening</h2>
    <div class="h2-dek">All {n_total} kitchens, by Toronto district. Concentration tells you where the {label} community&apos;s commercial footprint is densest right now.</div>
    <div class="district-bars">
      {district_bars}
    </div>
  </section>

  <footer class="foot">
    <p><b style="color:var(--ink)">About <em style="font-style:italic">This Week in Toronto</em>.</b> A weekly dispatch tracking every restaurant the City of Toronto licenses. Cuisine is verified against Google Places, owner websites, and food-press coverage. Every restaurant above appears on the live site at <a href="https://nowservingto.com/cuisine/{target['key']}">nowservingto.com/cuisine/{target['key']}</a>.</p>
    <p>Editorial use: lift the numbers, screenshot the cards, link the brief. If you&apos;d like the wire delivered weekly to your inbox - or want a custom cut for {country} - drop a line via the site footer.</p>
    <a href="https://nowservingto.com/cuisine/{target['key']}" class="cta">Browse the live {label} feed &rarr;</a>
  </footer>

</main>

</body></html>
'''


def main():
    if not DATA_PATH.exists():
        print(f'build_wire_pages: {DATA_PATH} missing - run inject_openings.py first', file=sys.stderr)
        return 1
    data = json.loads(DATA_PATH.read_text())
    entries = data.get('newOpenings', {}).get('recent', [])
    WIRE_DIR.mkdir(exist_ok=True)
    for t in TARGETS:
        page = build_wire_page(t, entries)
        path = WIRE_DIR / f"{t['key']}.html"
        path.write_text(page)
        n_match = sum(1 for e in entries if t['key'] in (e.get('cuisines') or [e.get('cuisine','')]))
        print(f"  wrote {path}  ({n_match} entries)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
