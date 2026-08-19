#!/usr/bin/env bash
# Rebuild the schedule master + coverage index LAST, so it sees the sweep.
#
# Stage 30 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Contract shared by every stage:
#   * reads SEASONS (e.g. "2026" or "1996:2026") from the environment
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`,
#     which would resync the venv under a running multi-hour sweep
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="30_schedule_master"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
SEASONS="${SEASONS:-}"

# Runs after the sweep on purpose: the master's per-game boolean flags are a
# claim about what is on disk, and building it first would record the previous
# run's coverage. Treated as non-fatal by the orchestrator -- a master failure
# must not keep the day's captured payloads from being committed.
echo "[$STAGE] rebuilding schedule master + coverage index"
"$PY" python/nba_stats_99_schedule_master_creation.py
