#!/usr/bin/env bash
# Backfill the official NBA injury report archive (2018-12-17 onward) -- run by hand.
#
#   bash scripts/backfill_injury_report.sh 2018-12-17:2026-06-30
#   tail -f logs/injury_report_backfill.log            # watch (another terminal)
#
# ~58k slot probes in all (3/day to 2021-10-14, hourly to 2025-12-21, every 15 min
# after). Resumable: every probed slot (hit or miss) is recorded per date, so Ctrl-C
# and re-run picks up where it stopped. Pace with INJ_RATE_DELAY (seconds between
# requests, default 0.5). Commit the store afterwards with stage 40.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
. "$REPO/scripts/_venv.sh"
RANGE="${1:-2018-12-17:$(date +%Y-%m-%d)}"
mkdir -p logs
LOG="logs/injury_report_backfill.log"
{
  echo "[backfill] $(date -u +%FT%TZ) range=$RANGE delay=${INJ_RATE_DELAY:-0.5}"
  PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 "$SDV_PY" python/nba_stats_04_injury_report.py "$RANGE"
  rc=$?
  echo "EXIT=$rc"
  exit "$rc"
} >> "$LOG" 2>&1
rc=$?
tail -n 3 "$LOG"
exit "$rc"
