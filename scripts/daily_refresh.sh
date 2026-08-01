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
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
. "$HOME/.config/sdv/env" 2>/dev/null || true

m=$(date -u +%m); y=$(date -u +%Y)
season=$(( 10#$m >= 10 ? y + 1 : y ))
LOG="$REPO/logs/daily_refresh_$(date -u +%Y%m%d).log"

{
  echo "[$(date -u '+%F %T')Z] daily refresh start: NBA season=$season"
  cd "$REPO" || exit 1
  SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}" "$PY" python/scrape_raw_json.py "$season"
  scrape_rc=$?
  # The commit used to run unconditionally, so a failed sweep still published a
  # partial season -- and the `rc=$?` below reported the COMMIT's status, which
  # made the failure invisible in the log too.
  if [ "$scrape_rc" -ne 0 ]; then
    echo "[$(date -u '+%F %T')Z] scrape failed (rc=$scrape_rc); not committing"
    exit "$scrape_rc"
  fi
  bash scripts/commit_raw_json.sh
  commit_rc=$?
  echo "[$(date -u '+%F %T')Z] daily refresh done (scrape=$scrape_rc commit=$commit_rc)"
  exit "$commit_rc"
} >> "$LOG" 2>&1
