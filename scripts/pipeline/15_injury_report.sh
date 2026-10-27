#!/usr/bin/env bash
# Capture the official NBA injury report (league PDFs) into the raw store.
#
# Stage 15 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Source is ak-static.cms.nba.com (static S3 behind Akamai), NOT stats.nba.com:
# no proxy, no curl_cffi. Daily mode probes yesterday..today (ET); a slot already
# probed is never asked again, so re-runs only pick up newly published slots.
# The history backfill is scripts/backfill_injury_report.sh, run by hand -- it is
# deliberately NOT part of `run_pipeline.sh -m backfill` (~58k requests).
#
# Contract shared by every stage:
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="15_injury_report"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"

echo "[$STAGE] injury report: ${INJ_DATES:-yesterday..today (ET)}"
PYTHONUNBUFFERED=1 "$PY" python/nba_stats_04_injury_report.py ${INJ_DATES:-}
