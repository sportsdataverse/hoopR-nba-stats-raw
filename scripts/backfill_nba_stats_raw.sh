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

# Python runs on the sibling data-repo venv (carries sportsdataverse + curl_cffi;
# this repo has no Python project of its own). Override with NBA_VENV_PYTHON.
DEFAULT_VENV="$REPO/../hoopR-nba-stats-data/python/.venv/Scripts/python.exe"   # Windows
[ -x "$DEFAULT_VENV" ] || DEFAULT_VENV="$REPO/../hoopR-nba-stats-data/python/.venv/bin/python"  # POSIX
PYBIN="${NBA_VENV_PYTHON:-$DEFAULT_VENV}"
if [ ! -x "$PYBIN" ]; then
  echo "FATAL: venv python not found at $PYBIN (set NBA_VENV_PYTHON)" >&2; exit 2
fi

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
export SCRAPE_WORKERS="${SCRAPE_WORKERS:-8}"          # pace knob; lower if the pool gets throttled
export PROXY_QUARANTINE_SECS="${PROXY_QUARANTINE_SECS:-600}"  # cooldown for a blocked proxy before retry

mkdir -p logs
LOG="logs/nba_stats_raw_backfill_$(date +%Y%m%d_%H%M%S).log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START seasons=$SEASONS workers=$SCRAPE_WORKERS log=$LOG" | tee -a "$LOG"
# --check first: sizes the sweep + verifies the proxy pool without fetching.
PYTHONIOENCODING=utf-8 "$PYBIN" scripts/scrape_raw_json.py --check "$SEASONS" 2>&1 | tee -a "$LOG"
"$PYBIN" scripts/scrape_raw_json.py "$SEASONS" 2>&1 | tee -a "$LOG"
echo "EXIT=${PIPESTATUS[0]}" | tee -a "$LOG"   # grep-able completion marker
