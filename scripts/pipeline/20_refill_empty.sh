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

# Resume is path.exists() -- presence, not content -- so a payload persisted
# empty blocks its own refetch forever. The write guard refuses empty payloads
# now, but files already on disk must be repaired. Deletions are tracked in git,
# so `git checkout -- nba_stats/` undoes a bad run.
echo "[$STAGE] empty-payload census + refill for $SEASONS"
"$PY" python/refill_empty.py --check "$SEASONS" || true
if [ "${REFILL_APPLY:-1}" = "1" ]; then
  "$PY" python/refill_empty.py "$SEASONS"
else
  echo "[$STAGE] REFILL_APPLY=0 -- census only, nothing refetched"
fi
