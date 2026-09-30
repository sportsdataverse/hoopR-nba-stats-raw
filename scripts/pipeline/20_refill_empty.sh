#!/usr/bin/env bash
# Repair payloads persisted as empty before the write guard existed.
#
# Stage 20 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Contract shared by every stage:
#   * reads SEASONS (e.g. "2026" or "1996:2026") from the environment
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`,
#     which would resync the venv under a running multi-hour sweep
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="20_refill_empty"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
SEASONS="${SEASONS:-}"

: "${SEASONS:?[$STAGE] SEASONS is required}"

# SEASONS are END years (2026 = 2025-26). The refill walks the SEASON-LEVEL
# store, whose dirs are still keyed by the START year, so shift the spec by one.
case "$SEASONS" in
  *:*) STORE_SEASONS="$(( ${SEASONS%%:*} - 1 )):$(( ${SEASONS##*:} - 1 ))" ;;
  *)   STORE_SEASONS="$(( SEASONS - 1 ))" ;;
esac

# Resume is path.exists() -- presence, not content -- so a payload persisted
# empty blocks its own refetch forever. The write guard refuses empty payloads
# now, but files already on disk must be repaired. Deletions are tracked in git,
# so `git checkout -- nba_stats/` undoes a bad run.
echo "[$STAGE] empty-payload census + refill for END $SEASONS (store dirs $STORE_SEASONS)"
"$PY" python/nba_stats_20_refill_empty.py --check "$STORE_SEASONS" || true
if [ "${REFILL_APPLY:-1}" = "1" ]; then
  "$PY" python/nba_stats_20_refill_empty.py "$STORE_SEASONS"
else
  echo "[$STAGE] REFILL_APPLY=0 -- census only, nothing refetched"
fi
