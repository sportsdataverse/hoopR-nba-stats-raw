"""One-shot migration for the 2026-08-02 season-format + sub-dimension fixes.

Why deletion is REQUIRED and not cleanup: resume is ``path.exists()``. The
bare-year sweeps persisted VALID zero-row envelopes for the season-format
endpoints (they are real envelopes, so the write guard rightly kept them), and
those files now block the fixed sweep from ever refetching -- presence-skip
treats them as done. Removing them is what makes the recovered data reachable.

Three actions, all narrow:

1. DELETE season-level captures with zero rows for the season-format-affected
   endpoints (leagueleaders, teamgamelogs, and the five PT dashboards). Every
   zero-row file there is a bare-year artifact; the span-format sweep refetches
   them with real parameters. Files WITH rows are untouched.
2. DELETE all scoreboardv3 season files -- the endpoint is date-keyed and every
   per-season file is the wrapper's fixed default date (junk by construction).
   scoreboardv3 is now excluded from discovery entirely.
3. RENAME synergyplaytypes captures to carry their true slice tokens: the old
   ``{season_type}_{per_mode}.json`` files are real Isolation/Offensive data
   (129 rows each) whose name no longer says so now that play_type and
   type_grouping are swept axes. New name:
   ``{season_type}_isolation_offensive_{per_mode}.json``.

Row counting is resultSets-family only; every affected endpoint is classic-
envelope. Run from the repo root; prints a full accounting; idempotent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "nba_stats" / "json"

SEASON_FORMAT_ENDPOINTS = (
    "leagueleaders",
    "teamgamelogs",
    "leaguedashptstats",
    "leaguedashptdefend",
    "leaguedashteamptshot",
    "leaguedashplayerptshot",
    "leaguedashoppptshot",
)


def rows_of(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    rs = payload.get("resultSets") if "resultSets" in payload else payload.get("resultSet")
    tables = rs if isinstance(rs, list) else [rs] if isinstance(rs, dict) else []
    return sum(len(t.get("rowSet") or []) for t in tables if isinstance(t, dict))


def main() -> int:
    deleted = kept = renamed = 0

    for ep in SEASON_FORMAT_ENDPOINTS:
        d = ROOT / ep
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.json")):
            n = rows_of(f)
            if n == 0:
                f.unlink()
                deleted += 1
            else:
                kept += 1
        print(f"{ep}: zero-row deleted so far={deleted}, with-rows kept={kept}")

    sb = ROOT / "scoreboardv3"
    if sb.exists():
        junk = list(sb.rglob("*.json"))
        for f in junk:
            f.unlink()
        deleted += len(junk)
        print(f"scoreboardv3: {len(junk)} date-keyed junk files deleted")

    syn = ROOT / "synergyplaytypes"
    if syn.exists():
        for f in sorted(syn.rglob("*.json")):
            stem = f.stem
            if "isolation" in stem:  # already migrated
                continue
            parts = stem.rsplit("_", 1)  # {season_type}, {per_mode}
            if len(parts) != 2:
                continue
            target = f.with_name(f"{parts[0]}_isolation_offensive_{parts[1]}.json")
            f.rename(target)
            renamed += 1
        print(f"synergyplaytypes: {renamed} renamed to explicit slice names")

    print(f"TOTAL: deleted={deleted} kept={kept} renamed={renamed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
