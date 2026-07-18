#!/usr/bin/env bash
#
# commit_raw_json.sh
#
# Commit + push captured stats.nba.com raw JSON in per-season batches.
#
# The JSON tree is populated by sportsdataverse-py's read-through raw store
# (env SDV_PY_NBA_RAW_JSON_DIR pointing at nba_stats/json in this checkout):
#   nba_stats/json/{endpoint}/{season}/{game_id}.json
#
# Safe to re-run any time (cron or manual): only seasons with new/changed
# files produce a commit, one commit per season so no single push carries
# more than ~1-2 GB. *.json.tmp files are atomic-write leftovers and are
# gitignored — never commit them.
#
# The commit subject format "NBA Stats Update (Start: YYYY End: YYYY)" is
# load-bearing (verbatim per this repo's contributor docs): downstream
# tooling parses the years out of it. Disk dirs AND labels both use the NBA
# stats pipeline's END-year convention (1995-96 season => 1996), so the
# label is the directory name verbatim.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

seasons=$(find nba_stats/json -mindepth 2 -maxdepth 2 -type d -printf '%f\n' 2>/dev/null | sort -u)
[ -z "$seasons" ] && { echo "no captured seasons under nba_stats/json — nothing to do"; exit 0; }

for season in $seasons; do
  git add -- nba_stats/json/*/"$season" 2>/dev/null || true
  if git diff --cached --quiet; then
    continue
  fi
  n=$(git diff --cached --name-only | wc -l)
  git commit -m "NBA Stats Update (Start: $season End: $season)"
  git push origin main
  echo "[$(date -u '+%F %TZ')] pushed season $season ($n files)"
done
