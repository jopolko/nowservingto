# NowServingTO

**Toronto's newest registered restaurants, by cuisine.** A daily-fresh directory of restaurants newly licensed in the past 365 days, classified into 50+ cuisine buckets via Claude Haiku + web search, verified against Google Places, photo-curated by Haiku vision, and served as a static page.

Live at **https://nowservingto.com/**.

## What it does

Every morning the cron pulls the City of Toronto business-licence feed from CKAN, finds the food businesses registered in the last 365 days, asks Claude Haiku 4.5 to classify each by cuisine (using `web_search` to read actual menus, reviews, owner bios — not just the operating name), confirms each business is registered with Google Places, and serves a single-page directory plus per-cuisine, per-district, and per-listing pages. Links go to the restaurant's website when one exists; otherwise to its Google Maps profile.

The point: an **immigrant-first** discovery feed. The newest Ethiopian, Tamil, Bangladeshi, Persian, Filipino, Salvadoran, Jamaican, etc. spots get surfaced the day their licence is approved, with the dropdown surfacing the cuisine you're actually looking for — not "ethnic" lumped together.

## How it works

```
City of Toronto business-licences CSV (CKAN, refreshed daily)
  ↓ tools/cron_daily_openings.sh                     daily 5:17 UTC
  ↓ tools/llm_classify_batch.py                      Haiku name-only classifier (cold start only)
  ↓ tools/llm_verify_batch.py                        Haiku + web_search → cuisine + operating + website
  ↓ tools/llm_menu_highlights_batch.py               Haiku → dish names from each restaurant's site
  ↓ tools/llm_photo_classify_batch.py                Haiku vision → reject wrong-business photos
  ↓ tools/retry_denied_photos.py                     Street View fallback for rejected photos
  ↓ tools/retry_places_photos.py                     Places photos[1..N] fallback when Street View also fails
  ↓ tools/llm_evidence_rewrite_batch.py              Haiku → polished editorial blurb per listing
  ↓ tools/enrich_places.py                           Sunday weekly catch-all for new entries
  ↓ tools/check_link_health.py                       HEAD-probe every URL, drop 4xx/5xx
  ↓ tools/inject_openings.py                         apply gates, render every page, write sitemap
  ↓ tools/aggregate_usage.py                         per-call cost ledger → /usage
  ↓ tools/aggregate_bot_traffic.py                   parse Apache logs → bot dashboard on /usage
  ↓ tools/ping_indexnow.py                           submit sitemap to Bing/Yandex/Naver/Seznam
  ↓ data/corridors.json                              ~650 KB, daily-refreshed
  ↓ index.html + cuisine/* + district/* + r/*       vanilla JS, no build, no framework
```

No backend. No database. No framework. Apache serves static HTML files; the homepage fetches one JSON file for client-side filtering.

### Tagging hierarchy

1. **Haiku + web_search** (`web_verify_cache.json`). Claude reads menus, owner bios, blogTO articles, Instagram pages, and decides cuisine from the evidence. Strongest signal. Also returns the operating/closed/unclear verdict and the validator's best-website pick.
2. **Haiku name-only** (`llm_cuisine_cache.json`). Cheap fallback used when web_verify hasn't run yet on a brand-new entry.
3. Nothing else. The previous chain-denylist short-circuit and keyword-pattern fallback were removed on 2026-05-14 — the unified validator catches chains and institutional operators via the `validator_drop` flag.

### Coverage policy

- Only restaurants **registered with the City in the past 365 days** appear. Older licences fall out automatically.
- Only entries with a **Google Places match** appear (tightened 2026-05-27). Without a Places `place_id` we can't link visitors to a real Maps profile, and a row that doesn't go anywhere is worse than no row.
- Photos are filtered through a Haiku-vision classifier and auto-recovered via Street View or alternate Places photos when the first one is wrong (parking lot, bulletin board, gas station, etc.). 99%+ of listings carry a real storefront/interior photo.

### Self-healing

Each verification cached with `verified_at`. Tier-based re-check intervals:
- own website (.com/.ca): 180 days
- Instagram / Facebook / TikTok: 30 days
- blogTO / Yelp / Maps / TripAdvisor: 14 days
- no-link "yes" verdicts: 14 days
- `unclear`: 7 days
- `no` (confirmed closed): 60 days

As Google/Bing index new places, the next cron re-check picks up the better link and silently upgrades the entry.

### SEO + AI search

- **Sitemap** auto-rebuilt daily with `<lastmod>` updates
- **IndexNow** auto-pings Bing/Yandex/Naver/Seznam with every URL each cron run (Google doesn't participate, but ChatGPT Search + Perplexity both ride Bing's index)
- **JSON-LD** structured data on every page (`Restaurant`, `CollectionPage`, `BreadcrumbList`, `FAQPage`), including `sameAs` Wikidata links for each cuisine
- **`/llms.txt`** at the root as a content map for AI crawlers
- Bot dashboard on `/usage` shows live Googlebot / Bingbot / OAI-SearchBot / GPTBot / Perplexity hit counts

## Coverage

- ~430 listings at any time (rolling 365-day window of newly licensed restaurants in Toronto)
- 47 active cuisine buckets, 6 district buckets
- 99%+ photo coverage; rest render text-only

Cuisines split out where meaningfully different from their parent region. Examples (full list in `tools/cuisines.py`): Afghan, Argentinian, Armenian, Bangladeshi, Brazilian, Caribbean, Chinese, Colombian, Eritrean, Ethiopian, Filipino, French, Ghanaian, Greek, Guyanese, Haitian, Indian, Indonesian, Italian, Jamaican, Japanese, Jewish deli, Korean, Latin American, Lebanese, Mexican, Middle Eastern, Nepalese, Nigerian, Pakistani, Persian, Peruvian, Polish, Portuguese, Salvadoran, Senegalese, Somali, South Asian, Spanish, Sri Lankan, Tamil, Thai, Tibetan, Trinidadian, Turkish, Venezuelan, Vietnamese.

## Setup

```bash
# clone
git clone https://github.com/jopolko/nowservingto.git
cd nowservingto

# venv + deps
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt

# put credentials at /var/secrets/nowservingto.env (chmod 600)
# required: ANTHROPIC_API_KEY=sk-ant-...
# required: GOOGLE_API_KEY (Places + Street View)
# optional: GITHUB_TOKEN (for repo automation)

# run once manually to verify
tools/cron_daily_openings.sh

# install daily cron (1:17 AM Toronto)
crontab -e
# add:
#   17 5 * * * /path/to/nowservingto/tools/cron_daily_openings.sh
```

The cache files under `tools/cache/*.json` are committed, so a fresh clone has a year of verified entries to start with. Only the daily delta hits the APIs.

## Layout

```
nowservingto/
├── index.html                              # homepage; reads data/corridors.json
├── llms.txt                                # content map for AI crawlers
├── sitemap.xml                             # auto-regenerated
├── data/corridors.json                     # daily-refreshed wire file
├── cuisine/<key>.html                      # per-cuisine landing pages (47)
├── district/<slug>.html                    # per-district landing pages (6)
├── r/<slug>.html                           # per-restaurant listing pages (~430)
├── wire/<key>.html                         # editorial briefs per cuisine
├── og/{,photo/,thumb/}<slug>.{png,jpg,webp}  # OG cards + Places photos + thumbs
├── tools/
│   ├── cron_daily_openings.sh              # the cron entry point
│   ├── inject_openings.py                  # main ETL: gates, renders, writes sitemap
│   ├── cuisines.py                         # canonical cuisine taxonomy (single source of truth)
│   ├── llm_classify*.py                    # name-only Haiku cuisine classifier
│   ├── llm_verify*.py                      # Haiku + web_search verifier
│   ├── llm_menu_highlights_batch.py        # dish-name extraction from restaurant sites
│   ├── llm_evidence_rewrite_batch.py       # validator notes → editorial prose
│   ├── llm_photo_classify_batch.py         # Haiku vision: is this photo of a restaurant?
│   ├── retry_denied_photos.py              # Street View fallback for rejected photos
│   ├── retry_places_photos.py              # Places multi-photo fallback
│   ├── enrich_places.py                    # Google Places enrichment (with fuzzy address fallback)
│   ├── check_link_health.py                # HEAD-probe + 14-day re-check ladder
│   ├── ping_indexnow.py                    # submit URLs to Bing/Yandex/Naver/Seznam
│   ├── aggregate_usage.py                  # per-call API spend ledger → /usage
│   ├── aggregate_bot_traffic.py            # Apache log → bot dashboard on /usage
│   ├── gsc_priority_urls.py                # generate freshness-first reindex list
│   ├── fetch_cuisine_wikidata.py           # SPARQL → Wikidata QIDs for JSON-LD sameAs
│   ├── deploy_to_vps.sh                    # rsync deploy
│   └── cache/                              # JSON caches (committed; cold-start data)
└── legacy/                                 # archived BloomTO and DemoCalcTO codebases
```

## What it's not

- Not a Yelp clone. No user-submitted reviews, no claim flow. The source of truth is the City's licence feed.
- Not a curated editorial list like blogTO. Entries come from licence data + AI classification, not editorial taste.
- Not a complete restaurant directory. Only places licensed in the last 365 days.
- Not a historical record. As licences age past 365 days they fall out.

## Status

- 2026-05-28 — Places-required gate, fuzzy address fallback, photo recovery pipeline, hybrid `/r/` cards, sitewide editorial lede
- 2026-05-27 — IndexNow auto-submission, bot-traffic dashboard, llms.txt
- 2026-05-13 — pivoted from "cultural corridor displacement map" to "now open by cuisine"
- BloomTO (multiplex parcel filtering) archived under `legacy/bloomto-tooling/`
- DemoCalcTO archived under `legacy/democalcto/`

## License

Code: MIT (`LICENSE`). Data: from the [City of Toronto Open Data Portal](https://open.toronto.ca/dataset/municipal-licensing-and-standards-business-licences-and-permits/) under its Open Data Licence. Cuisine classifications are generated by AI and may be wrong — flag issues via [GitHub issues](https://github.com/jopolko/nowservingto/issues).
