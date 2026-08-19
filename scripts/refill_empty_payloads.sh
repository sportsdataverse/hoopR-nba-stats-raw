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
#   bash scripts/refill_empty_payloads.sh                     # every empty found
#   bash scripts/refill_empty_payloads.sh --check             # census only, no network
#   bash scripts/refill_empty_payloads.sh 2015:2026           # season range
#   bash scripts/refill_empty_payloads.sh --endpoint matchupsrollup
#
# Watch it live from another terminal:
#   tail -f logs/refill_empty.log
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
# The resolver's last-resort ambient-python fallback is only safe with this
# check -- see sdv_preflight in scripts/_venv.sh.
sdv_preflight sportsdataverse.scrape.stats curl_cffi

LOG="$REPO/logs/refill_empty.log"
mkdir -p "$REPO/logs"

# There is deliberately no allow-list of "recoverable" endpoints here.
#
# An earlier revision carried one, built from a live probe that turned out to be
# invalid: it passed `measure_type_simple_detailed_defense`, which is not a
# parameter of the shot-locations wrappers, so it fell through to **kwargs and
# every "measure type" silently measured Base. That made five unsupported values
# look recoverable.
#
# The real causes were parameter bugs, now fixed in endpoints.py: measure types
# are narrowed to each parameter's own domain, and the season pin no longer
# misses `season_nullable`. So the sweep does not generate these requests at
# all any more, and this script simply refetches whatever `{}` files it finds --
# a list that is empty on a healthy tree. Keeping it list-free means it cannot
# go stale again, and it ports unchanged to wehoop-wnba-stats-raw, which has the
# same defects and 3,872 of these files.
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

# These payloads previously failed to capture. Give them well past the 30s
# default -- the sweep's own gamerotation guidance uses 60.
export SDV_PY_NBA_STATS_TIMEOUT="${SDV_PY_NBA_STATS_TIMEOUT:-90}"
echo "[$(date -u +%FT%TZ)] proxy config loaded; timeout=${SDV_PY_NBA_STATS_TIMEOUT}s" | tee -a "$LOG"

{
  echo "=========================================================="
  echo "[$(date -u +%FT%TZ)] refill START ${*:-}"
} >> "$LOG"

# Pass through any remaining args (a SEASON:RANGE, --endpoint X). Piped into
# tee, so the shell would otherwise see tee's status, not the refiller's.
"$SDV_PY" python/refill_empty.py "$@" 2>&1 | tee -a "$LOG"
status=${PIPESTATUS[0]}

echo "[$(date -u +%FT%TZ)] refill DONE EXIT=$status" | tee -a "$LOG"
echo "Re-run the census to confirm:  bash scripts/refill_empty_payloads.sh --check" | tee -a "$LOG"
exit "$status"
