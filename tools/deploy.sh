#!/usr/bin/env bash
#
# deploy.sh — push hand-authored SOURCE files from dev (WSL) to prod (VPS).
#
# Why this exists: prod is a scp/cp-deploy target, NOT a git-pull target. Its
# web root is a mutating artifact directory — the nightly cron regenerates
# ~7,000 files (sitemap, cuisine/, r/, og/, the index.html feed block, etc.).
# Git-tracking that on prod is pointless; instead we keep dev↔GitHub as the
# source of truth and push only the files a human actually edits.
#
# This script deploys the SOURCE set and deliberately EXCLUDES:
#   - generated pages   : cuisine/ district/ neighborhood/ r/ og/ wire/
#                         dispatch/ trends/ all.html answers.html trends.html
#                         press/data.html sitemap.xml data/corridors.json
#                         (the cron rebuilds these from the source below)
#   - prod-authoritative: tools/cache/  (LLM/Places caches live on prod;
#                         pushing dev copies would clobber production blurbs)
#   - runtime junk      : tools/logs/  *.lock  __pycache__/
#   - requirements.txt  : NOT in the synced file set at all. If you change
#                         it (e.g. pinning a new dependency), scp it to prod
#                         by hand and reinstall into .venv there, or the venv
#                         will silently drift from what git tracks. Bit us on
#                         2026-08-20 (anthropic SDK): the pkg was installed
#                         ad hoc on prod, never pinned, then vanished with no
#                         log trail, breaking LLM-dependent inject steps for
#                         ~a month before anyone noticed.
#
# Usage:
#   tools/deploy.sh              # sync source; nightly cron rebuilds artifacts
#   tools/deploy.sh --rebuild    # sync, then run inject + IndexNow on prod now
#   tools/deploy.sh --dry-run    # show what would transfer, change nothing
#
# Notes:
#   - Pushing index.html / llms.txt reverts the cron-injected feed/date until
#     the next cron tick. Use --rebuild if you need the change live immediately.
#   - Host alias `nowservingto` must be in ~/.ssh/config (it is — see CLAUDE.md).
#   - After scp'ing requirements.txt to prod, run on the VPS:
#       .venv/bin/python -m pip install -r requirements.txt
#     to actually apply it (scp alone doesn't touch the installed packages).

set -euo pipefail

HOST="nowservingto"
DEST_PATH="/var/www/html/nowservingto"
DEST="${HOST}:${DEST_PATH}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REBUILD=0
RSYNC_FLAGS=(-az --human-readable)
for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    --dry-run) RSYNC_FLAGS+=(--dry-run --verbose) ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# Single source files that live at the web root.
ROOT_FILES=(
  index.html .htaccess robots.txt llms.txt embed.js
  geocode-proxy.php here-transit-proxy.php
  press.html usage.html contribute.html game.html
  favicon.svg og.svg x-banner.svg
  manifest-game.json sw-game.js
)

# Source directories synced wholesale (no --delete, so prod-only files survive).
# tools/ carries excludes for cache/logs/bytecode.
echo "→ deploying source to ${DEST}"

rsync "${RSYNC_FLAGS[@]}" \
  --exclude='cache/' --exclude='logs/' --exclude='__pycache__/' \
  --exclude='.*.lock' --exclude='*.pyc' \
  tools/ "${DEST}/tools/"

rsync "${RSYNC_FLAGS[@]}" js/app.js "${DEST}/js/app.js"

for d in fonts icons pwa-icons; do
  [ -d "$d" ] && rsync "${RSYNC_FLAGS[@]}" "$d/" "${DEST}/$d/"
done

rsync "${RSYNC_FLAGS[@]}" "${ROOT_FILES[@]}" "${DEST}/"

echo "✓ source synced"

if [ "$REBUILD" -eq 1 ]; then
  echo "→ rebuilding artifacts on prod (inject + IndexNow)"
  ssh "$HOST" "cd ${DEST_PATH} \
    && set -a && source /var/secrets/nowservingto.env 2>/dev/null && set +a \
    && PY=\$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3) \
    && \"\$PY\" tools/inject_openings.py 2>&1 | grep -iE 'wrote sitemap|error|traceback' \
    && \"\$PY\" -u tools/ping_indexnow.py 2>&1 | grep -iE 'submitting|HTTP'"
  echo "✓ prod rebuilt"
else
  echo "  (artifacts will refresh on tonight's cron; use --rebuild to do it now)"
fi
