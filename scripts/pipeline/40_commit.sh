#!/usr/bin/env bash
# Commit + push captured payloads, one commit per season.
#
# Stage 40 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Contract shared by every stage:
#   * reads SEASONS (e.g. "2026" or "1996:2026") from the environment
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`,
#     which would resync the venv under a running multi-hour sweep
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="40_commit"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
SEASONS="${SEASONS:-}"

# The commit subject "NBA Stats Update (Start: YYYY End: YYYY)" is load-bearing
# verbatim -- downstream tooling parses the years out of it.
echo "[$STAGE] committing captured payloads"
bash scripts/commit_raw_json.sh
rc=$?

# The master artifacts live beside the json tree and commit_raw_json.sh
# deliberately does not stage them -- commit them separately, only when changed.
git add -- nba_stats/nba_stats_schedule_master.parquet \
           nba_stats/nba_stats_schedule_coverage.parquet \
           nba_stats/nba_stats_endpoint_coverage.parquet 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -m "chore(schedule): refresh schedule master + coverage index" >/dev/null
  if ! git push origin HEAD >/dev/null 2>&1; then
    git fetch --quiet origin main || true
    git rebase --merge origin/main >/dev/null 2>&1 && git push origin HEAD >/dev/null 2>&1 \
      || { echo "[$STAGE] ::error ::master push failed -- the coverage index on origin is stale"; rc=1; }
  fi
fi
exit "$rc"
