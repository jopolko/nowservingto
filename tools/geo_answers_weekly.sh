#!/usr/bin/env bash
# Weekly GEO-answers auto-post. Runs as user john from cron, on Josh's Claude
# Code credits (Opus). The harvester (Python, no model) finds the questions;
# headless Claude writes and publishes up to 3 genuinely-grounded answers into
# the live /var/www/html/geo-answers/index.html, then IndexNow pings the URL.
# No API key, no Haiku. See geo_answers_weekly.prompt.txt for the full task.
set -uo pipefail
export PATH="/home/john/.local/bin:$PATH"

TOOLS=/var/www/html/nowservingto/tools
PROMPT_FILE="$TOOLS/geo_answers_weekly.prompt.txt"
LOG_DIR="$TOOLS/logs"
LOG="$LOG_DIR/geo-answers-weekly-$(date +%Y%m%d).log"
mkdir -p "$LOG_DIR"
cd /var/www/html || exit 1

{
  echo "===== geo-answers weekly run $(date -u +%FT%TZ) ====="
  timeout 1800 claude -p "$(cat "$PROMPT_FILE")" --model claude-sonnet-4-6 --dangerously-skip-permissions
  echo "===== claude exit $? ====="
  # Direct IndexNow submit so Bing (and therefore ChatGPT/Copilot) re-crawl the
  # updated hub fast. Harmless if nothing changed this week.
  curl -s -X POST "https://api.indexnow.org/IndexNow" \
    -H "Content-Type: application/json" \
    -d '{"host":"joshuaopolko.com","key":"d7a5a9b4c10cd380e4004523688b3ae0","keyLocation":"https://joshuaopolko.com/d7a5a9b4c10cd380e4004523688b3ae0.txt","urlList":["https://joshuaopolko.com/geo-answers/"]}' \
    -o /dev/null -w "IndexNow submit: HTTP %{http_code}\n"
  echo "===== done $(date -u +%FT%TZ) ====="
} >> "$LOG" 2>&1
