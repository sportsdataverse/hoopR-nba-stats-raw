#!/usr/bin/env bash
#
# daily_refresh.sh
#
# Incremental daily refresh: sweep the CURRENT NBA season's new games into the
# raw store, then commit+push. Cron entry point. Idempotent — already-captured
# games are skipped, and the empty-{} guard (sportsdataverse-py#293) keeps
# dataless fetches from being persisted, so this can run every day cheaply.
#
# NBA seasons are labelled by END year (2025-26 => 2026). From October the
# current league year rolls to the next end-year; the rest of the year it is
# the just-finished season (a harmless near-no-op in the offseason).
#
# Runs the guard-fixed sportsdataverse via .venv/bin/python directly (NOT
# `uv run`, which would resync the venv to the lockfile).
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY=/mnt/sdv_repos/hoopR-nba-stats-data/python/.venv/bin/python
. "$HOME/.config/sdv/env" 2>/dev/null || true

m=$(date -u +%m); y=$(date -u +%Y)
season=$(( 10#$m >= 10 ? y + 1 : y ))
LOG="$REPO/logs/daily_refresh_$(date -u +%Y%m%d).log"

{
  echo "[$(date -u '+%F %T')Z] daily refresh start: NBA season=$season"
  cd "$REPO" || exit 1
  SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}" "$PY" scripts/scrape_raw_json.py "$season"
  bash scripts/commit_raw_json.sh
  echo "[$(date -u '+%F %T')Z] daily refresh done (rc=$?)"
} >> "$LOG" 2>&1
