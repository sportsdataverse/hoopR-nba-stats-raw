#!/usr/bin/env bash
#
# supervise_sweep.sh
#
# Keep python/nba_stats_01_raw_json_scrape.py alive: relaunch on abnormal death, stop
# cleanly once it prints "sweep complete", give up after MAX_RESTARTS so a
# real crash loop surfaces instead of spinning forever. The sweep is
# idempotent (on-disk payloads are skipped) so each restart resumes.
#
# Runs the sweep in the foreground of THIS shell so a silent process death is
# detected immediately (the failure mode that once left the sweep idle for an
# hour). Launch under tmux/nohup so it survives an SSH disconnect.
#
# Usage: tmux new-session -d -s sweepsup 'bash scripts/supervise_sweep.sh 1996:2025'
set -u

# PY: the venv carrying sportsdataverse (the raw store) + curl_cffi. Defaults
# to this repo's own .venv; SWEEP_PY still overrides for other pairs.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NBA_VENV_PYTHON="${SWEEP_PY:-${NBA_VENV_PYTHON:-}}"
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
# The resolver's last-resort ambient-python fallback is only safe with this
# check -- see sdv_preflight in scripts/_venv.sh.
sdv_preflight sportsdataverse.scrape.stats curl_cffi
SEASONS="${1:-1996:2025}"
MAX_RESTARTS="${MAX_RESTARTS:-6}"
WD="$REPO/logs/watchdog_$(date -u +%Y%m%d_%H%M%S).log"

log() { echo "[$(date -u '+%F %T')Z] $*" | tee -a "$WD"; }

log "supervisor start: seasons=$SEASONS max_restarts=$MAX_RESTARTS"
n=0
while :; do
  RUN="$REPO/logs/nba_stats_01_raw_json_scrape_$(date -u +%Y%m%d_%H%M%S).log"
  log "launch #$((n + 1)) -> $RUN"
  ( cd "$REPO" && . "$HOME/.config/sdv/env" 2>/dev/null; \
    PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 SCRAPE_WORKERS="${SCRAPE_WORKERS:-6}" \
      "$PY" python/nba_stats_01_raw_json_scrape.py "$SEASONS" >> "$RUN" 2>&1 )
  rc=$?
  if grep -q 'sweep complete' "$RUN"; then
    log "SWEEP COMPLETE (rc=$rc) — supervisor exiting"
    break
  fi
  n=$((n + 1))
  if [ "$n" -ge "$MAX_RESTARTS" ]; then
    log "GIVING UP after $n restarts (last rc=$rc) — needs investigation"
    break
  fi
  back=$((30 * n))
  log "sweep died rc=$rc without completing — restart $n/$MAX_RESTARTS after ${back}s backoff"
  sleep "$back"
done
log "supervisor exit"
