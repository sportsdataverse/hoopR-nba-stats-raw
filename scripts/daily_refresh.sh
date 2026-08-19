#!/usr/bin/env bash
# Legacy entry point -- kept so the droplet cron line keeps working.
#
# The implementation moved to the numbered stages under scripts/pipeline/,
# sequenced by scripts/run_pipeline.sh. See RUNBOOK.md. This shim exists only to
# avoid breaking the cron entry and muscle memory; put new work in a stage.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$REPO/scripts/run_pipeline.sh" -m daily "$@"
