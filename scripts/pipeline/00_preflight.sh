#!/usr/bin/env bash
# Verify the environment can actually run a sweep, spending no requests.
#
# Stage 00 of the NBA stats raw pipeline. Every stage is independently
# runnable and idempotent -- run it directly, or let scripts/run_pipeline.sh
# sequence it. See RUNBOOK.md for the stage table.
#
# Contract shared by every stage:
#   * reads SEASONS (e.g. "2026" or "1996:2026") from the environment
#   * resolves its interpreter through scripts/_venv.sh -- never `uv run`,
#     which would resync the venv under a running multi-hour sweep
#   * exits non-zero on failure so the orchestrator can stop the chain
set -uo pipefail

STAGE="00_preflight"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
SEASONS="${SEASONS:-}"

# The census is the cheap gate: it sizes the sweep and verifies the proxy pool
# WITHOUT fetching. stats.nba.com HANGS rather than erroring on a datacenter
# IP, so a run that skips this discovers the problem as an unexplained stall
# hours later.
sdv_preflight sportsdataverse.scrape.stats curl_cffi

# Proxy creds live in ~/.Renviron (R reads it at startup; Python does not).
# shellcheck disable=SC1090
. "$HOME/.Renviron" 2>/dev/null || true
. "$HOME/.config/sdv/env" 2>/dev/null || true
export PROXY_ENDPOINT PROXY_KEY PROXY_PKG

if [ -z "${PROXY_ENDPOINT:-}" ]; then
  echo "[$STAGE] FATAL: PROXY_ENDPOINT unset -- a direct-IP sweep will hang, not error." >&2
  exit 2
fi

: "${SEASONS:?[$STAGE] SEASONS is required (e.g. 2026 or 1996:2026)}"
echo "[$STAGE] census for $SEASONS (no requests spent)"
PYTHONIOENCODING=utf-8 "$PY" python/nba_stats_01_raw_json_scrape.py --check "$SEASONS"
