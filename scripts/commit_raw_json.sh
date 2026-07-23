#!/usr/bin/env bash
#
# commit_raw_json.sh
#
# Commit + push captured stats.nba.com raw JSON in per-season batches.
#
# The JSON tree is populated by sportsdataverse-py's read-through raw store
# (env SDV_PY_NBA_RAW_JSON_DIR pointing at nba_stats/json in this checkout), in
# two shapes:
#   nba_stats/json/{endpoint}/{season}/{game_id}.json   per-game and per-variant
#   nba_stats/json/{endpoint}/{season}.json             one payload per season
# The second shape is easy to miss: league-level endpoints (commonallplayers,
# drafthistory, playerindex, ...) write a flat file, so a season-directory-only
# scan never sees them and they stay untracked forever without ever erroring.
# Both shapes are discovered and staged below.
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

seasons=$(
  {
    find nba_stats/json -mindepth 2 -maxdepth 2 -type d -printf '%f\n'
    find nba_stats/json -mindepth 2 -maxdepth 2 -type f -name '*.json' -printf '%f\n' | sed 's/\.json$//'
  } 2>/dev/null | grep -E '^[0-9]{4}$' | sort -u
)
[ -z "$seasons" ] && { echo "no captured seasons under nba_stats/json — nothing to do"; exit 0; }

for season in $seasons; do
  git add -- nba_stats/json/*/"$season" nba_stats/json/*/"$season".json 2>/dev/null || true
  if git diff --cached --quiet; then
    continue
  fi
  n=$(git diff --cached --name-only | wc -l)
  git commit -m "NBA Stats Update (Start: $season End: $season)"
  git push origin main
  echo "[$(date -u '+%F %TZ')] pushed season $season ($n files)"
done
