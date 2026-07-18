#!/usr/bin/env bash
#
# supervise_sweep.sh
#
# Keep scripts/scrape_raw_json.py alive: relaunch on abnormal death, stop
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
# to this repo's compile sibling; override with SWEEP_PY for other pairs.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${SWEEP_PY:-/mnt/sdv_repos/hoopR-nba-stats-data/python/.venv/bin/python}"
SEASONS="${1:-1996:2025}"
MAX_RESTARTS="${MAX_RESTARTS:-6}"
WD="$REPO/logs/watchdog_$(date -u +%Y%m%d_%H%M%S).log"

log() { echo "[$(date -u '+%F %T')Z] $*" | tee -a "$WD"; }

log "supervisor start: seasons=$SEASONS max_restarts=$MAX_RESTARTS"
n=0
while :; do
  RUN="$REPO/logs/scrape_raw_json_$(date -u +%Y%m%d_%H%M%S).log"
  log "launch #$((n + 1)) -> $RUN"
  ( cd "$REPO" && . "$HOME/.config/sdv/env" 2>/dev/null; \
    PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 SCRAPE_WORKERS="${SCRAPE_WORKERS:-6}" \
      "$PY" scripts/scrape_raw_json.py "$SEASONS" >> "$RUN" 2>&1 )
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
