#!/usr/bin/env bash
# One orchestrator for the NBA stats raw pipeline.
#
# The stages under scripts/pipeline/ are the ONLY implementation. A daily
# refresh and a cold backfill are the same stages with different env and a
# different stage list -- deliberately not two parallel scripts, which is how
# `daily_refresh.sh` and the backfill driver drifted apart in the first place
# (one grew a census gate and a commit loop, the other grew the schedule-master
# rebuild; neither had the other's).
#
#   bash scripts/run_pipeline.sh                       # daily, current season
#   bash scripts/run_pipeline.sh -m backfill           # cold backfill, 1996:current
#   bash scripts/run_pipeline.sh -m backfill -s 2015:2020
#   bash scripts/run_pipeline.sh -m repair -s 2019
#   bash scripts/run_pipeline.sh -k 10,40 -s 2026      # only these stages
#   DRY_RUN=1 bash scripts/run_pipeline.sh -m backfill # print the plan, run nothing
#
# Watch a run:  tail -f logs/pipeline_<mode>_<stamp>.log
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

MODE="daily"; SEASONS=""; ONLY=""
while getopts m:s:k:h flag; do
  case "$flag" in
    m) MODE=$OPTARG;;
    s) SEASONS=$OPTARG;;
    k) ONLY=$OPTARG;;
    h) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0;;
    *) echo "usage: $0 [-m daily|backfill|repair] [-s SEASONS] [-k 10,40]" >&2; exit 2;;
  esac
done

# Season = END year (1995-96 => 1996; 2026 => 2025-26). October rolls forward,
# so the current season is not the calendar year for three months of it.
current_season() {
  local m y
  m=$(date -u +%m); y=$(date -u +%Y)
  if [ "$((10#$m))" -ge 10 ]; then echo "$((y + 1))"; else echo "$y"; fi
}

case "$MODE" in
  daily)
    SEASONS="${SEASONS:-$(current_season)}"
    STAGES="${ONLY:-10,11,12,30,40}"
    export SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}"
    ;;
  backfill)
    SEASONS="${SEASONS:-1996:$(current_season)}"
    # 00 gates on a census before spending a single request; 50 refreshes the
    # release tarballs, which only a backfill has a reason to do.
    STAGES="${ONLY:-00,10,11,12,20,30,40,50}"
    export SCRAPE_WORKERS="${SCRAPE_WORKERS:-6}"
    ;;
  repair)
    SEASONS="${SEASONS:-$(current_season)}"
    STAGES="${ONLY:-20,30,40}"
    ;;
  *) echo "unknown mode '$MODE' (expected daily|backfill|repair)" >&2; exit 2;;
esac
export SEASONS

mkdir -p logs
LOG="logs/pipeline_${MODE}_$(date -u +%Y%m%d_%H%M%S).log"

# Stage 30 is advisory: the schedule master is a claim ABOUT the payloads, so a
# failure there must not stop stage 40 from committing the payloads themselves.
NON_FATAL="30"

{
  echo "[run] mode=$MODE seasons=$SEASONS stages=$STAGES"
  echo "[run] log=$LOG"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "[run] DRY_RUN=1 -- plan only:"
    IFS=',' read -ra want <<< "$STAGES"
    for n in "${want[@]}"; do
      f=$(ls "scripts/pipeline/${n}_"*.sh 2>/dev/null | head -1)
      echo "  would run: ${f:-<no stage $n>}"
    done
    exit 0
  fi

  RC=0
  IFS=',' read -ra want <<< "$STAGES"
  for n in "${want[@]}"; do
    f=$(ls "scripts/pipeline/${n}_"*.sh 2>/dev/null | head -1)
    if [ -z "$f" ]; then
      echo "[run] ::error ::no stage numbered $n under scripts/pipeline/"; RC=1; continue
    fi
    echo "[run] ---- $(basename "$f") ----"
    bash "$f"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      case ",$NON_FATAL," in
        *",$n,"*) echo "[run] $(basename "$f") failed (rc=$rc) -- advisory, continuing";;
        *) echo "[run] ::error ::$(basename "$f") failed (rc=$rc) -- stopping the chain"
           RC=$rc; break;;
      esac
    fi
  done
  echo "[run] EXIT=$RC"
  exit "$RC"
} 2>&1 | tee -a "$LOG"
exit "${PIPESTATUS[0]}"
