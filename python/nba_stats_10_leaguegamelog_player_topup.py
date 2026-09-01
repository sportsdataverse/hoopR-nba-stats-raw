#!/usr/bin/env python
"""Capture the PLAYER variant of ``leaguegamelog`` for every season.

The main sweep captures ``leaguegamelog`` only at the wrapper's default
``player_or_team_abbreviation="T"`` -- team rows, which carry no ``PLAYER_ID``.
That serves game discovery fine (it needs only game ids), but the downstream
``nba_box_logs`` builder wants **player** game logs too, and no committed capture
could satisfy it, so that one call kept falling through to the live API and
pinned the whole impact build to a proxied host.

This is the ~62-call top-up that closes it: 31 seasons x 2 season types.

**Naming is deliberately additive.** The existing team captures stay at
``leaguegamelog/{season}/{season_type}.json`` -- renaming them would break the
consumers already reading that path (offline season discovery in sdv-py's
``_season_game_index``, and the ``-data`` producer's store mapping). The player
variant lands beside them as ``{season_type}_p.json``.

Resumable: an existing capture is skipped without a request, so a killed run can
be re-run. Writes are atomic (tmp + rename) via ``season_capture.write_payload``.

    python scripts/nba_stats_10_leaguegamelog_player_topup.py            # 1996:2026
    python scripts/nba_stats_10_leaguegamelog_player_topup.py 2020:2026  # a sub-range

Proxies are REQUIRED (stats.nba.com hangs on datacenter IPs and is slow to
non-residential ones); export PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG first --
they live in ~/.Renviron, which R reads automatically but Python does not.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEASON_TYPES = ("Regular Season", "Playoffs")
LEAGUE_ID = "00"


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from nba_stats_raw_scrape.season_capture import payload_path, write_payload
    from sportsdataverse.nba.nba_schedule import year_to_season
    from sportsdataverse.nba.nba_stats import nba_stats_leaguegamelog
    from sportsdataverse.scrape.stats.proxy import ProxyHealth, RoundRobin, load_proxies
    from sportsdataverse.scrape.stats.session_transport import SessionTransport

    spec = argv[0] if argv else "1996:2026"
    lo, _, hi = spec.partition(":")
    seasons = range(int(lo), int(hi or lo) + 1)
    store = REPO / "nba_stats" / "json"

    pool = load_proxies()
    if not pool:
        _log(
            "ERROR: no proxies. Un-proxied stats.nba.com calls hang rather than fail;"
            " export PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG (they live in ~/.Renviron,"
            " which Python does not read)."
        )
        return 1
    _log(f"proxy pool: {len(pool)} entries | store: {store}")

    health = ProxyHealth(error_log=str(REPO / "logs" / "topup_errors.jsonl"))
    transport = SessionTransport(RoundRobin(pool, health=health), health)

    written = skipped = failed = 0
    for season in seasons:
        for stype in SEASON_TYPES:
            variant = f"{stype.lower().replace(' ', '-')}_p"
            path = payload_path(store, "leaguegamelog", season, variant)
            if path.exists():
                skipped += 1
                continue
            try:
                payload = nba_stats_leaguegamelog(
                    # The store's SEASON-LEVEL half is keyed by START year (dir
                    # 2023 holds 2023-24) -- unlike the per-game half, which is
                    # keyed by END year. Match the sibling team capture that
                    # already lives in this directory, or the two are a season
                    # apart and every downstream join silently finds nothing.
                    season=year_to_season(season),
                    season_type_all_star=stype,
                    player_or_team_abbreviation="P",
                    league_id=LEAGUE_ID,
                    return_parsed=False,
                    transport=transport,
                )
            except Exception as exc:  # noqa: BLE001 - one gap must not kill the sweep
                _log(f"season {season} {stype}: FAILED {exc}")
                failed += 1
                continue
            rows = len(((payload.get("resultSets") or [{}])[0]).get("rowSet") or [])
            if not rows:
                # An empty envelope is a real answer for a season the endpoint has
                # no player rows for; persisting it would look identical to a real
                # capture and never be retried. Leave it absent instead.
                _log(f"season {season} {stype}: empty, not persisted")
                skipped += 1
                continue
            write_payload(path, payload)
            written += 1
            _log(f"season {season} {stype}: {rows} rows -> {path.name}")

    _log(f"top-up complete: {written} written | {skipped} present/empty | {failed} failed")
    for ep, errs, ec in health.endpoint_summary():
        _log(f"  {ep}: {errs} faults {ec}")
    health.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
