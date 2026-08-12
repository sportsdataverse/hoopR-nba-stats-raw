#!/usr/bin/env bash
#
# commit_loop.sh — keep the captured store committed while a sweep runs.
#
# scrape_raw_json.py only writes files; nothing commits them. On a multi-hour
# backfill that leaves gigabytes of captured payloads sitting untracked, so a
# crashed box or a full disk loses work that cost real requests against a shared
# stats-host budget.
#
# commit_raw_json.sh is idempotent and commits one season at a time, so running it
# on a timer produces exactly one commit per season as each finishes.
#
#   bash scripts/commit_loop.sh <watch_pid>   # until that process exits
#   INTERVAL=120 bash scripts/commit_loop.sh <watch_pid>
#
# <watch_pid> is the process to follow -- normally the launcher's own $$, since
# run_backfill.sh knows exactly when its sweep ends. Without it the loop falls
# back to `pgrep -f scrape_raw_json`, which does NOT work under Git Bash on
# Windows: pgrep cannot see native python.exe command lines, so it reported
# "not running" mid-sweep and the loop exited after a single pass. Pass the pid.
#
# Safe alongside the scraper: payloads are written atomically (tmp + rename) and
# *.json.tmp is gitignored, so a commit can never catch a half-written file.
#
# Exits once the sweep is no longer running AND a final pass finds nothing new,
# so it cleans up after itself rather than looping forever.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
INTERVAL="${INTERVAL:-300}"
LOG="${REPO}/logs/commit_loop.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date -u '+%F %TZ')] $*" >> "$LOG"; }

WATCH_PID="${1:-}"

# Watching an explicit pid keeps this portable: `kill -0` works anywhere, while
# scanning for the python process does not (see the note above).
_sweep_running() {
    if [ -n "$WATCH_PID" ]; then
        kill -0 "$WATCH_PID" 2>/dev/null
        return $?
    fi
    pgrep -f "scrape_raw[_]json" > /dev/null 2>&1
}

log "commit loop started (interval ${INTERVAL}s, watching ${WATCH_PID:-<pgrep>})"
while true; do
    bash scripts/commit_raw_json.sh >> "$LOG" 2>&1 || log "commit pass failed (will retry)"

    if ! _sweep_running; then
        # One more pass after the sweep ends, so the final season is never stranded.
        sleep 10
        bash scripts/commit_raw_json.sh >> "$LOG" 2>&1 || log "final commit pass failed"
        log "sweep no longer running — commit loop exiting"
        exit 0
    fi
    sleep "$INTERVAL"
done
