#!/usr/bin/env bash
# Legacy entry point -- kept so existing invocations keep working.
#
# The implementation moved to the numbered stages under scripts/pipeline/,
# sequenced by scripts/run_pipeline.sh. See RUNBOOK.md. A backfill is now the
# same stages as a daily run with different env, not a parallel script.
#
# Usage kept compatible: an optional LO:HI positional.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -gt 0 ] && [ -n "${1:-}" ]; then
  exec bash "$REPO/scripts/run_pipeline.sh" -m backfill -s "$1"
fi
exec bash "$REPO/scripts/run_pipeline.sh" -m backfill
