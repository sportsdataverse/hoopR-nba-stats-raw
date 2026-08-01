#!/usr/bin/env bash
#
# refill_empty_payloads.sh
#
# Refetch the season-level payloads that were persisted as empty `{}`.
#
# Background: season_capture.write_payload had no guard and resume is
# path.exists() -- presence, not content -- so a failed fetch that returned `{}`
# was written to disk and never retried. 3,347 files reached that state here
# (3,872 in wehoop-wnba-stats-raw). The guard now refuses to persist a
# contentless payload, but cannot undo files already on disk; this refills them.
#
# RUN THIS DIRECTLY IN YOUR OWN TERMINAL, not through an agent, and only from a
# RESIDENTIAL IP: stats.nba.com hangs (does not error) on datacenter IPs.
#
#   bash scripts/refill_empty_payloads.sh                 # recoverable endpoints
#   bash scripts/refill_empty_payloads.sh --all           # every empty, incl. unproven
#   bash scripts/refill_empty_payloads.sh --check         # census only, no network
#
# Watch it live from another terminal:
#   tail -f logs/refill_empty.log
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"

LOG="$REPO/logs/refill_empty.log"
mkdir -p "$REPO/logs"

# Endpoints a live probe confirmed DO return real data when refetched, so their
# `{}` files are recoverable:
#   leaguedash{player,team}shotlocations  all 7 measure types -> 30 rows
#   leaguedashptteamdefend                30 rows
#   matchupsrollup                        2,283 rows
# Left out of the default run because a live probe got `{}` or a zero-row
# envelope for them too -- they need a parameter fix first, not a refetch:
#   playercompare (needs player-id lists), playergamelogs / teamgamelogs
#   (zero-row envelope), draftcombine* (param shape), leaguedashteamstats
#   MeasureType=Usage (genuinely unsupported: 1 of 7 variants, in both leagues).
RECOVERABLE=(
  leaguedashplayershotlocations
  leaguedashteamshotlocations
  leaguedashptteamdefend
  matchupsrollup
  leaguedashplayerclutch
  shotchartleaguewide
)

export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

# The census reads only the local tree, so it runs before the proxy gate.
if [ "${1:-}" = "--check" ]; then
  "$SDV_PY" python/refill_empty.py --check
  exit $?
fi

# Proxies are REQUIRED for this refill. The credentials live in ~/.Renviron,
# which only R reads at startup -- Python and bash do not see them -- so they are
# sourced here at call time rather than hardcoded anywhere. Values are never
# echoed; only the variable names and the resulting pool size are logged.
for rc in "$HOME/.Renviron" "$HOME/Documents/.Renviron"; do
  [ -f "$rc" ] || continue
  for var in PROXY_ENDPOINT PROXY_KEY PROXY_PKG; do
    if [ -z "${!var:-}" ]; then
      val="$(sed -n "s/^${var}[[:space:]]*=[[:space:]]*//p" "$rc" | head -1 | tr -d '"'"'"'\r')"
      [ -n "$val" ] && export "$var=$val"
    fi
  done
done

missing=""
for var in PROXY_ENDPOINT PROXY_KEY PROXY_PKG; do
  [ -z "${!var:-}" ] && missing="$missing $var"
done
if [ -n "$missing" ]; then
  echo "FATAL: proxy config missing:$missing" >&2
  echo "       expected in ~/.Renviron (R-only) or the environment." >&2
  exit 3
fi

# These payloads previously failed to capture; a too-short deadline is the most
# likely reason (the shot-locations variants are the big ones). Give them well
# past the 30s default -- the sweep's own gamerotation guidance uses 60.
export SDV_PY_NBA_STATS_TIMEOUT="${SDV_PY_NBA_STATS_TIMEOUT:-90}"
echo "[$(date -u +%FT%TZ)] proxy config loaded; timeout=${SDV_PY_NBA_STATS_TIMEOUT}s" | tee -a "$LOG"

{
  echo "=========================================================="
  echo "[$(date -u +%FT%TZ)] refill START (${1:-recoverable-only})"
} >> "$LOG"

if [ "${1:-}" = "--all" ]; then
  "$SDV_PY" python/refill_empty.py 2>&1 | tee -a "$LOG"
  status=${PIPESTATUS[0]}
else
  status=0
  for ep in "${RECOVERABLE[@]}"; do
    echo "[$(date -u +%FT%TZ)] --- $ep ---" | tee -a "$LOG"
    "$SDV_PY" python/refill_empty.py --endpoint "$ep" 2>&1 | tee -a "$LOG"
    rc=${PIPESTATUS[0]}
    [ "$rc" -ne 0 ] && status=$rc
  done
fi

echo "[$(date -u +%FT%TZ)] refill DONE EXIT=$status" | tee -a "$LOG"
echo "Re-run the census to confirm:  bash scripts/refill_empty_payloads.sh --check" | tee -a "$LOG"
exit "$status"
