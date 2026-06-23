#!/usr/bin/env bash
#
# Daily cron: refresh the "Now open" feed.
#
#   1. Pull fresh Toronto Open Data business licences CSV
#   2. Inject openings (uses LLM + Places caches; cuisine + websites where cached)
#   3. Classify any NEW openings not yet in LLM cache (Anthropic Batch API)
#   4. Re-inject so newly-tagged businesses surface
#   5. Look up websites for newly cuisine-tagged businesses (Haiku + web_search)
#   6. Re-inject one more time to merge in any new website data
#   7. Optionally rsync data/corridors.json to prod
#
# Safe for cron:
#   - flock against concurrent runs
#   - rotates its own logs to tools/logs/openings-*.log
#   - exits non-zero on hard failure so cron MAILTO catches it
#   - per-step failure is logged but doesn't abort downstream steps where possible
#
# Optional env (override at the cron line):
#   ROOTED_DIR    repo root (default: derived from this script)
#   WEB_ROOT      local prod dir for `cp` deploy (e.g. /var/www/html/nowservingto)
#   SKIP_LLM      "1" to skip the Haiku classification step
#   SKIP_WEBSITES "1" to skip the web_search website-lookup step
#
# Suggested cron line (every morning 5:17 AM Toronto):
#   17 5 * * *  WEB_ROOT=/var/www/html/nowservingto /var/www/html/nowservingto/tools/cron_daily_openings.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
ROOTED_DIR="${ROOTED_DIR:-$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)}"
LOG_DIR="$ROOTED_DIR/tools/logs"
LOG_FILE="$LOG_DIR/openings-$(date +%Y%m%d).log"
LOCK_FILE="$ROOTED_DIR/tools/.openings.lock"

mkdir -p "$LOG_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -Is)] another openings refresh is in progress; exiting" >> "$LOG_FILE"
    exit 0
fi

log() { echo "[$(date -Is)] $*" | tee -a "$LOG_FILE"; }

log "==== daily openings refresh start ===="

cd "$ROOTED_DIR"

# venv detection
if [[ -x ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    log "ERROR: no python available"; exit 1
fi
log "python=$PYTHON"

# Step 0a: refresh the OSM chain set if older than 7 days (or missing). This is
# one of the two authoritative sources for auto-chain detection (along with
# Wikidata, refreshed in 0b). Free (no API key), ~6s for the Overpass query.
OSM_CACHE="$ROOTED_DIR/tools/cache/osm_chain_set.json"
if [[ ! -s "$OSM_CACHE" ]] || [[ $(find "$OSM_CACHE" -mtime +7 2>/dev/null | wc -l) -gt 0 ]]; then
    log "→ build_osm_chain_set.py (refresh authoritative chain list from OSM)"
    "$PYTHON" -u tools/build_osm_chain_set.py >> "$LOG_FILE" 2>&1 \
        || log "WARN: OSM chain refresh failed (non-fatal — using cached set)"
fi

# Step 0b: refresh the Wikidata chain set if older than 7 days. Catches every
# named restaurant chain globally — including ones with a single Toronto
# location that OSM's Toronto-bbox query misses (Pokeworks, Marugame Udon,
# Molly Tea were burning ~$1-2/day in Places lookups before this was wired in).
# Free, no API key, one SPARQL query.
WIKI_CACHE="$ROOTED_DIR/tools/cache/wikidata_chain_set.json"
if [[ ! -s "$WIKI_CACHE" ]] || [[ $(find "$WIKI_CACHE" -mtime +7 2>/dev/null | wc -l) -gt 0 ]]; then
    log "→ build_wikidata_chain_set.py (refresh authoritative chain list from Wikidata)"
    "$PYTHON" -u tools/build_wikidata_chain_set.py >> "$LOG_FILE" 2>&1 \
        || log "WARN: Wikidata chain refresh failed (non-fatal — using cached set)"
fi

# Step 1: fresh CSV pull from CKAN
log "→ pulling fresh business-licences CSV"
START=$SECONDS
CSV_URL="https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/municipal-licensing-and-standards-business-licences-and-permits/resource/54bddc5e-92d9-4102-89c1-43e82f8f4d2d/download/business-licences-data.csv"
if ! curl -sSf --max-time 120 -o /tmp/business_licences_alt.csv "$CSV_URL"; then
    log "ERROR: CSV download failed"; exit 1
fi
ROWS=$(wc -l < /tmp/business_licences_alt.csv)
log "  fetched $ROWS rows in $((SECONDS - START))s"
if [[ "$ROWS" -lt 100000 ]]; then
    log "ERROR: CSV looks truncated (rows=$ROWS); aborting"; exit 1
fi

# Step 1b: refresh DineSafe inspection lookup. Toronto Public Health
# publishes inspection records daily on CKAN. Used by inject_openings'
# pre-existing-restaurant gate (Phase B): if DineSafe inspected this
# address+name >180d before the licence-issued date, the licence event
# is a re-licensing of a long-operating place, not a new opening, and
# the entry is suppressed. Also powers the licence→DineSafe-earliest
# date swap (use the inspection date as 'registered' when it's later).
# Non-fatal: if the fetch fails, inject falls back to whatever lookup
# is on disk; gate just gets staler but doesn't break.
log "→ fetch_dinesafe.py (Toronto Public Health inspection lookup)"
if ! "$PYTHON" -u tools/fetch_dinesafe.py >> "$LOG_FILE" 2>&1; then
    log "WARN: DineSafe fetch failed (non-fatal — gate will use cached lookup)"
fi

# Step 2: initial inject (uses existing caches)
log "→ inject_openings.py (initial pass)"
if ! "$PYTHON" tools/inject_openings.py >> "$LOG_FILE" 2>&1; then
    log "ERROR: initial inject failed"; exit 1
fi

# Step 3: cuisine classification via Anthropic Message Batches (async, 50% off).
# Walks the CSV, picks up new entries + previous errors, submits one batch, polls
# until done. Exits cleanly with no spend if nothing is missing.
if [[ "${SKIP_LLM:-0}" != "1" ]]; then
    log "→ llm_classify_batch.py (batch / async / Haiku — 50% off)"
    if ! "$PYTHON" -u tools/llm_classify_batch.py >> "$LOG_FILE" 2>&1; then
        log "WARN: batch classification failed (non-fatal, will keep existing tags)"
    fi
    log "→ inject_openings.py (post-classification)"
    "$PYTHON" tools/inject_openings.py >> "$LOG_FILE" 2>&1 || log "WARN: re-inject failed"
else
    log "  SKIP_LLM=1 — skipping classification"
fi

# Step 4: web_search verification via Message Batches (operating? website? cuisine?).
# Walks the CSV, picks up entries needing first-time or tier-stale re-verification,
# submits one batch, polls until done.
if [[ "${SKIP_WEBSITES:-0}" != "1" ]]; then
    log "→ llm_verify_batch.py (batch / async / Haiku + web_search — 50% off)"
    if ! "$PYTHON" -u tools/llm_verify_batch.py >> "$LOG_FILE" 2>&1; then
        log "WARN: batch web verification failed (non-fatal)"
    fi
fi

# Step 4b: menu-signal extraction. Two-tier Haiku pass over every entry
# with a website + cached page text — extracts specific dish names
# (tier 1, "Try the mandi, shawarma, kibbeh") AND falls back to verbatim
# menu categories (tier 2, "Menu features biryanis, curries, kebabs")
# when no dishes can be pulled. Cached per cache_key, refreshed every 90
# days so the cache picks up new dishes/sections as restaurants update
# their websites. Steady-state daily cost: ~$0.001 (only new openings);
# quarterly refresh: ~$0.30 (~287 entries) once every 90 days.
# Safe to skip (non-fatal) — listing pages just render without the tile.
log "→ llm_menu_highlights_batch.py (dish + category extraction, 90-day refresh)"
if ! "$PYTHON" -u tools/llm_menu_highlights_batch.py --max-age-days 90 >> "$LOG_FILE" 2>&1; then
    log "WARN: menu-highlights batch failed (non-fatal — menu tile will skip)"
fi

# Step 4c / 4c+ DISABLED 2026-06-03 — photos retired site-wide. The
# Haiku-vision classifier, Street View fallback, and Places multi-photo
# walker were all in service of getting a *correct* photo on each row.
# With no photos rendered anywhere, there is nothing to classify or
# recover. Scripts kept in the repo for one-off historical debugging
# but no longer fire on cron.
log "  step 4c (llm_photo_classify_batch)  DISABLED — site is text-only"
log "  step 4c+ (retry_denied_photos)      DISABLED — site is text-only"
log "  step 4c+ (retry_places_photos)      DISABLED — site is text-only"

# Step 4d: (moved) Editorial-blurb generation now runs ONCE, after the final
# inject (Step 6.2), so it sees the complete admitted set. It used to run here
# too — but llm_evidence_rewrite_batch reads corridors.json, and at this point
# same-day entries haven't cleared the gate yet, so this pass only ever rewrote
# yesterday's entries (already cached) while today's stayed blurb-less until a
# second "catch-up" run. That double-ran Haiku for no benefit; removed.

# Step 5: probe every cached restaurant website for HTTP errors so we don't show
# dead links. $0 cost, ~20s for full sweep. Each URL re-probed every 14 days.
log "→ check_link_health.py (HEAD-probe cached websites)"
if ! "$PYTHON" -u tools/check_link_health.py >> "$LOG_FILE" 2>&1; then
    log "WARN: link health check failed (non-fatal)"
fi

# Step 5a: ask Google Places about every operating-but-uncategorized entry we
# haven't queried yet (no website OR a social website). Places frequently knows
# the real restaurant URL even when our verifier only found the IG account, so
# this populates places_cache for the downstream cuisine-recovery step to use.
# Order matters: this must run BEFORE llm_recover_cuisine so Places' website
# data is available. ~$0.017 × daily-delta = pennies.
log "→ places_enrich_socials.py (upgrade social-link entries via Places)"
if ! "$PYTHON" -u tools/places_enrich_socials.py >> "$LOG_FILE" 2>&1; then
    log "WARN: social-link Places enrichment failed (non-fatal)"
fi
log "→ places_recover_cuisine.py (Places lookup for entries with no/social website)"
if ! "$PYTHON" -u tools/places_recover_cuisine.py >> "$LOG_FILE" 2>&1; then
    log "WARN: Places coverage expansion failed (non-fatal)"
fi

# Step 5a3: catch-all Places enrichment — for every kept entry that none of
# the targeted recovery scripts above queried (e.g. entry already has cuisine
# from web_verify AND its website isn't social, so neither places_recover
# nor places_enrich_socials triggers). Without this, entries like JARDIN
# NOIR (yorkdale.com URL + cuisine=french from web_verify) never get
# Places-queried → no photoRef → no row thumbnail. Idempotent: skips
# entries already in places_cache. Pre-2026-05-20 ran daily; now SUNDAY-
# ONLY because targeted scripts (places_enrich_socials + places_recover)
# pick up most cases within hours, and a 6-day delay for the catch-all
# sweep is acceptable trade for ~$2-4/week saved.
if [[ "$(date -u +%u)" == "7" ]]; then
    log "→ enrich_places.py (catch-all: Sunday weekly sweep)"
    if ! "$PYTHON" -u tools/enrich_places.py >> "$LOG_FILE" 2>&1; then
        log "WARN: enrich_places catch-all failed (non-fatal)"
    fi
else
    log "  enrich_places.py catch-all — skipped (runs Sundays only)"
fi

# Step 5b: cuisine-recovery pass — for entries still without a cuisine, fetch
# the best available website (Places' own-site preferred over verify-cache's
# social URL; social used only as last resort) and classify via Haiku.
# Order: Places-first → verify non-social → social fallback (immigrant-run
# spots that live entirely on IG). ~$0.001 per recovery × ~10/day delta.
log "→ llm_recover_cuisine.py (Places-first website fetch + reclassify)"
if ! "$PYTHON" -u tools/llm_recover_cuisine.py >> "$LOG_FILE" 2>&1; then
    log "WARN: cuisine recovery failed (non-fatal — entries stay uncategorized)"
fi

# Step 5c: Layer 4 — for entries where the website fetch failed (SPA shells,
# Cloudflare-blocked, PDF-only menus), use Haiku + web_search via the Message
# Batches API to classify from Google's already-rendered/indexed view of the
# site. Batch is 50% off ($5/1K web_search vs $10/1K sync) AND has much higher
# per-org rate limits — sync would hit web_search throttling after ~80 calls.
# Uses GHDB-style operators (filetype:pdf, site:blogto.com, intitle:menu,
# quoted exact names, -aggregator exclusions) on the second search call.
# Cost: ~$0.01/attempt × daily delta. The sync variant (llm_search_recover_cuisine.py)
# is kept in the repo for manual / debugging use but not invoked by cron.
log "→ llm_search_recover_batch.py (Haiku web_search recovery — Layer 4, batch / 50% off)"
if ! "$PYTHON" -u tools/llm_search_recover_batch.py >> "$LOG_FILE" 2>&1; then
    log "WARN: batched search-based cuisine recovery failed (non-fatal)"
fi

# Step 5d: unified validator — jina-renders each entry's candidate URL,
# feeds rendered page text + licence row + Places match + reviews into Haiku,
# and gets a single verdict (is_same_business / is_restaurant / cuisines /
# best_website / evidence). Catches multi-location chains, dead websites,
# aggregator wrappers, wrong-business Places matches. Skips entries
# validated in the last 24h, so per-day cost stays small (~$0.10-$0.30
# typical daily delta; ~$2 for a full --force re-validate).
log "→ validate_entries_batch.py (jina + Haiku unified judgment)"
if ! "$PYTHON" -u tools/validate_entries_batch.py >> "$LOG_FILE" 2>&1; then
    log "WARN: validator failed (non-fatal — entries keep prior verdict)"
fi

# Step 5e: geocode addresses for entries missing lat/lng (powers the map view).
# Uses free Nominatim @ 1 req/sec; the daily delta is ~5-15 addresses so this
# adds ~10-20s per cron. Skips any address already geocoded.
log "→ geocode_addresses.py (Nominatim — free, 1 req/sec)"
if ! "$PYTHON" -u tools/geocode_addresses.py >> "$LOG_FILE" 2>&1; then
    log "WARN: geocoding failed (non-fatal — map will still work for already-geocoded entries)"
fi

# Step 6: final inject — merges verification + health-check results into corridors.json
log "→ inject_openings.py (final, post-verify + post-health-check)"
"$PYTHON" tools/inject_openings.py >> "$LOG_FILE" 2>&1 || log "WARN: final inject failed"

# Step 6.2: editorial blurbs — the SINGLE evidence-rewrite pass. It runs here,
# after the final inject, on purpose: llm_evidence_rewrite_batch reads
# corridors.json, so an entry must be admitted (in the wire) before it can get a
# blurb. By this point every spot that cleared the gate today is admitted with
# its web_verify evidence, so this one pass covers the complete set — no lag, no
# second "catch-up" run, and Haiku is paid once. The re-inject below bakes the
# new blurbs into corridors.json + /r/ pages. Incremental (cached per _cacheKey)
# → ~1-3 Haiku calls/day. inject's field-synthesized _fallback_blurb is the
# safety net for any entry whose evidence is too thin to write from.
log "→ llm_evidence_rewrite_batch.py (Haiku: editorial blurbs for the admitted set)"
"$PYTHON" -u tools/llm_evidence_rewrite_batch.py >> "$LOG_FILE" 2>&1 || log "WARN: evidence-rewrite failed (non-fatal — new spots fall back to synthesized blurb)"
log "→ inject_openings.py (bake blurbs into corridors.json + /r/ pages)"
"$PYTHON" tools/inject_openings.py >> "$LOG_FILE" 2>&1 || log "WARN: blurb re-inject failed (non-fatal)"

# Step 6.25: regenerate the diaspora pitch wire pages (/wire/filipino,
# /wire/jamaican, /wire/vietnamese) from the freshly-injected corridors.json.
# Self-contained editorial briefs aimed at homeland food editors - charts
# stay current without manual rebuilding.
log "→ build_wire_pages.py (live diaspora pitch wires)"
"$PYTHON" tools/build_wire_pages.py >> "$LOG_FILE" 2>&1 || log "WARN: wire-pages build failed (non-fatal)"

# Step 7: post the freshest unposted entry to @nowservingto on X.
#
# DISABLED 2026-05-19 — @nowservingto is shadow-banned; daily auto-posts
# reinforce the bot classification. Pausing to let the account go dormant
# for ~30 days. If shadow-ban doesn't lift, plan is to delete the account
# and recreate as personal. To re-enable: uncomment the block below.
#
# if [[ -n "$(grep '^X_API_KEY=' /var/secrets/nowservingto.env 2>/dev/null)" ]]; then
#     log "→ x_post_new_openings.py (1 tweet)"
#     "$PYTHON" tools/x_post_new_openings.py --max 1 --since-days 30 >> "$LOG_FILE" 2>&1 \
#         || log "WARN: x post failed (non-fatal)"
# else
#     log "  X_API_KEY not in /var/secrets/nowservingto.env — skipping X post"
# fi
log "  step 7 (x_post) DISABLED — account dormant for shadow-ban recovery"

# Step 6.5: aggregate the per-call usage ledger into data/usage.json so
# the /usage page reflects today's spend. Cheap (just reads a JSONL file).
log "→ aggregate_usage.py"
"$PYTHON" -u tools/aggregate_usage.py >> "$LOG_FILE" 2>&1 || log "WARN: usage aggregate failed (non-fatal)"

# Crawl-log rollup: parse Apache access logs for search-engine and AI-bot
# hits. Powers the "Crawlers" section on /usage. Cron user (john) must
# be in the `adm` group to read /var/log/apache2/*; if not, the script
# writes a friendly stub with the one-time sudo command to fix it.
log "→ aggregate_bot_traffic.py"
"$PYTHON" -u tools/aggregate_bot_traffic.py >> "$LOG_FILE" 2>&1 || log "WARN: bot-traffic aggregate failed (non-fatal)"

# Step 5: sanity-check + deploy
DATA="$ROOTED_DIR/data/corridors.json"
if [[ ! -s "$DATA" ]]; then
    log "ERROR: $DATA missing or empty"; exit 1
fi
if ! "$PYTHON" -c "import json,sys; json.load(open(sys.argv[1]))" "$DATA" >> "$LOG_FILE" 2>&1; then
    log "ERROR: $DATA failed JSON parse"; exit 1
fi
TAGGED=$("$PYTHON" -c "import json; d=json.load(open('$DATA')); print(d['newOpenings']['totalTagged365d'])")
log "  corridors.json OK · $TAGGED tagged 12mo openings"

if [[ -n "${WEB_ROOT:-}" ]]; then
    if [[ ! -d "$WEB_ROOT" ]]; then
        log "ERROR: WEB_ROOT=$WEB_ROOT does not exist"; exit 1
    fi
    DEST_DATA="$WEB_ROOT/data"
    mkdir -p "$DEST_DATA"
    TMP="$DEST_DATA/corridors.json.tmp.$$"
    cp -f "$DATA" "$TMP"
    chmod 644 "$TMP"
    mv -f "$TMP" "$DEST_DATA/corridors.json"
    log "  deployed corridors.json → $DEST_DATA"
fi

# Step 7.5: ping IndexNow with today's URL set. Bing, Yandex, Naver,
# Seznam re-crawl on receipt. Google doesn't participate, but ChatGPT
# Search + Perplexity ride Bing's index, so this is the cheapest way
# to push freshness to AI search. Idempotent and free; runs every day
# regardless of whether anything actually changed (IndexNow handles
# the "no-op" case server-side).
log "→ ping_indexnow.py (Bing/Yandex/etc. re-crawl notification)"
"$PYTHON" -u tools/ping_indexnow.py >> "$LOG_FILE" 2>&1 || log "WARN: IndexNow ping failed (non-fatal)"

# Step 8: fire per-cuisine + per-district real-time email alerts for any
# brand-new entries that hit corridors.json today. Runs AFTER deploy so
# subscribers only ever get notified about listings already live on prod.
# Mail hops through local Postfix (DKIM-signed by OpenDKIM) — see
# deploy/mail-setup.md. First run snapshots the existing 365d backlog so
# nobody gets blasted with a year of openings.
log "→ send_alerts.py (real-time per-cuisine + per-district email alerts)"
"$PYTHON" -u tools/send_alerts.py >> "$LOG_FILE" 2>&1 || log "WARN: send_alerts failed (non-fatal)"

# Rotate logs (keep 30 days)
find "$LOG_DIR" -name 'openings-*.log' -mtime +30 -delete 2>/dev/null || true

log "==== daily openings refresh done ===="
exit 0
