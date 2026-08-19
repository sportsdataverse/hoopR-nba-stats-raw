#!/usr/bin/env bash
# The scrape itself. Resumable: on-disk payloads are skipped.
#
# Stage 10 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Contract shared by every stage:
#   * reads SEASONS (e.g. "2026" or "1996:2026") from the environment
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`,
#     which would resync the venv under a running multi-hour sweep
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="10_sweep"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
SEASONS="${SEASONS:-}"

: "${SEASONS:?[$STAGE] SEASONS is required}"

# Rate tuning is ENV-ONLY by convention -- never hardcode pace, so it can be
# re-tuned without a code change. Daily uses a gentler default than a backfill.
export SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}"
export SDV_PY_NBA_STATS_TIMEOUT="${SDV_PY_NBA_STATS_TIMEOUT:-90}"

echo "[$STAGE] sweeping $SEASONS (workers=$SCRAPE_WORKERS timeout=${SDV_PY_NBA_STATS_TIMEOUT}s)"
# Resume is presence-on-disk, so Ctrl-C + rerun is always safe.
PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 "$PY" python/scrape_raw_json.py "$SEASONS"
