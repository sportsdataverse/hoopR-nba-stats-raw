#!/usr/bin/env bash
# Backfill stats.nba.com raw JSON into nba_stats/json for a season range.
#
# RUN THIS YOURSELF in a terminal on a residential IP (stats.nba.com hangs on
# datacenter/cloud IPs; the proxy pool handles rotation but the box must not be
# cloud). Resumable: the read-through store skips games already on disk, so
# Ctrl-C + rerun is always safe and only fetches what's missing.
#
#   bash scripts/backfill_nba_stats_raw.sh            # default 1996:2026
#   bash scripts/backfill_nba_stats_raw.sh 2010:2026  # a sub-range
#   SCRAPE_WORKERS=4 bash scripts/backfill_nba_stats_raw.sh   # gentler pace
#
# Watch live from another terminal (Git Bash):
#   tail -f "$(ls -t logs/nba_stats_raw_backfill_*.log | head -1)"
# or PowerShell:
#   Get-Content -Path (Get-ChildItem logs\nba_stats_raw_backfill_*.log | Sort LastWriteTime -Desc | Select -First 1).FullName -Tail 5 -Wait
set -uo pipefail

SEASONS="${1:-1996:2026}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || { echo "FATAL: cannot cd to repo $REPO" >&2; exit 1; }

# Python runs on this repo's own venv (pyproject.toml pins sportsdataverse +
# curl_cffi). Override with NBA_VENV_PYTHON.
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PYBIN="$SDV_PY"

# Proxies are REQUIRED and live in ~/.Renviron (R loads it; Python does not).
# Export the three PROXY_* vars without echoing their values.
for RENV in "$HOME/.Renviron" "$HOME/Documents/.Renviron"; do
  [ -f "$RENV" ] || continue
  while IFS='=' read -r k v; do
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"; export "$k=$v"
  done < <(grep -E '^(PROXY_ENDPOINT|PROXY_KEY|PROXY_PKG)=' "$RENV")
done
if [ -z "${PROXY_ENDPOINT:-}" ] || [ -z "${PROXY_KEY:-}" ] || [ -z "${PROXY_PKG:-}" ]; then
  echo "FATAL: PROXY_ENDPOINT/PROXY_KEY/PROXY_PKG not found in ~/.Renviron" >&2; exit 3
fi

export PYTHONUNBUFFERED=1      # real-time log lines, no buffering lag
export PYTHONIOENCODING=utf-8  # cp1252 chokes on unicode in piped output
export SCRAPE_WORKERS="${SCRAPE_WORKERS:-6}"          # pace knob; raise only if the pool stays healthy
export PROXY_QUARANTINE_SECS="${PROXY_QUARANTINE_SECS:-600}"  # cooldown for a blocked proxy before retry
# Per-request deadline. Defaulted HERE rather than inherited: the transport's own
# fallback is 30s, and a 16-worker sweep at 30s produced ~3.7% timeout/err
# (concentrated in the slow endpoints -- boxscoresummaryv2, leaguedashptteamdefend).
# Those cost a whole extra pass to recover, so pay the wait up front.
export SDV_PY_NBA_STATS_TIMEOUT="${SDV_PY_NBA_STATS_TIMEOUT:-90}"

mkdir -p logs
LOG="logs/nba_stats_raw_backfill_$(date +%Y%m%d_%H%M%S).log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START seasons=$SEASONS workers=$SCRAPE_WORKERS log=$LOG" | tee -a "$LOG"
# Commit as the sweep runs. Nothing here used to commit at all, so a multi-hour
# backfill left every captured payload untracked -- a crashed box would have
# lost work that cost real requests against a shared stats-host budget.
#
# It watches THIS script's pid, which is also why the preflight-failure exit
# below needs no cleanup: when this shell goes, the loop's `kill -0` fails, it
# runs one final pass and exits on its own.
bash scripts/commit_loop.sh $$ >> "$LOG" 2>&1 &
COMMIT_LOOP_PID=$!

# --check first: sizes the sweep + verifies the proxy pool without fetching.
# Its status was previously discarded, so a run with no proxies sailed past the
# preflight into a sweep that could only hang. Note `set -e` would NOT catch
# either of these: both are piped into tee, so the shell sees tee's status --
# hence the explicit PIPESTATUS checks.
PYTHONIOENCODING=utf-8 "$PYBIN" python/scrape_raw_json.py --check "$SEASONS" 2>&1 | tee -a "$LOG"
check_rc=${PIPESTATUS[0]}
if [ "$check_rc" -ne 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] preflight failed (rc=$check_rc); not scraping" | tee -a "$LOG"
  echo "EXIT=$check_rc" | tee -a "$LOG"
  exit "$check_rc"
fi

"$PYBIN" python/scrape_raw_json.py "$SEASONS" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
# Stop the loop and flush whatever the last pass missed, so the final season is
# never stranded.
kill "$COMMIT_LOOP_PID" 2>/dev/null
wait "$COMMIT_LOOP_PID" 2>/dev/null
bash scripts/commit_raw_json.sh >> "$LOG" 2>&1 || echo "final commit pass failed" | tee -a "$LOG"
echo "EXIT=$rc" | tee -a "$LOG"   # grep-able completion marker
exit "$rc"
