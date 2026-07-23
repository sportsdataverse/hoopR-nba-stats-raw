"""Season-level (non per-game) captures for the raw store.

``scrape_raw_json.py`` fills the per-game half of the store through sdv-py's
read-through cache, which keys on ``game_id``. Season-level endpoints are keyed on
*(season, parameters)* instead and cannot use that store, so they land here under

    {endpoint}/{season}/{variant}.json     (parameterized)
    {endpoint}/{season}.json               (no variants)

Which endpoints, and which parameter matrix each one gets, comes from
:mod:`endpoints` -- derived from the endpoints' own signatures rather than a
hand-maintained list, so a new upstream endpoint is captured without an edit here.

Writes are atomic (tmp + rename) and idempotent: an existing payload is skipped
without parsing, so a sweep is resumable after Ctrl-C.

Rate discipline: every fetch shares the ProxyBonanza rotation and the single
stats.{nba,wnba}.com budget with the per-game sweep. These are fetched
**sequentially** -- a few hundred calls per season against thousands of games --
so there is nothing to gain from parallelising them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from endpoints import discover, season_variants, slug

__all__ = [
    "capture_season",
    "game_ids_from_gamelog",
    "payload_path",
    "plan_season",
    "slug",
    "write_payload",
]


def payload_path(
    root: str | Path, endpoint: str, season: int, variant: str | None = None
) -> Path:
    """Where a season-level capture lives. ``variant=None`` means unparameterized."""
    base = Path(root) / endpoint
    return (
        base / str(season) / f"{variant}.json" if variant else base / f"{season}.json"
    )


def write_payload(path: Path, payload: Any) -> None:
    """Persist ``payload`` atomically, so a killed sweep never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.partial")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _ids_from(payload: Any, column: str) -> list[str]:
    """Distinct values of ``column`` across a resultSets payload."""
    if not isinstance(payload, dict):
        return []
    out: set[str] = set()
    for rs in payload.get("resultSets") or []:
        headers = [str(h).upper() for h in rs.get("headers") or []]
        if column not in headers:
            continue
        idx = headers.index(column)
        for row in rs.get("rowSet") or []:
            if row[idx] is not None:
                out.add(str(row[idx]))
    return sorted(out)


def game_ids_from_gamelog(payload: Any) -> list[str]:
    """Zero-padded game ids from a raw ``leaguegamelog`` payload.

    Lets the per-game sweep enumerate from the persisted capture instead of making
    its own call for the same thing.
    """
    return [g.zfill(10) for g in _ids_from(payload, "GAME_ID")]


def plan_season(
    season: int, module: Any, prefix: str, league_id: str
) -> Iterator[tuple[str, str | None, dict[str, Any]]]:
    """Yield ``(endpoint, variant, kwargs)`` for every season-level capture.

    ``commonteamroster`` is absent: it is team-keyed, so :func:`capture_season`
    schedules it separately once team ids are known.
    """
    _game, season_endpoints = discover(module, prefix)
    for endpoint in season_endpoints:
        fn = getattr(module, f"{prefix}_{endpoint}")
        for variant, kwargs in season_variants(fn, season, league_id):
            yield endpoint, variant, kwargs


def capture_season(
    season: int,
    root: str | Path,
    fetch: Callable[[str, dict[str, Any]], Any],
    module: Any,
    prefix: str,
    league_id: str,
    log: Callable[[str], None] = lambda _m: None,
) -> tuple[int, int, int]:
    """Fetch every season-level payload for ``season``. Returns (written, skipped, failed).

    ``fetch(endpoint, kwargs)`` performs one call and returns the raw payload; the
    caller supplies it so proxy rotation and transport stay in the scraper and this
    module stays offline-testable.
    """
    written = skipped = failed = 0
    team_source: Any = None

    def _is_team_source(endpoint: str, kwargs: dict[str, Any]) -> bool:
        """The one team-stats capture whose rows enumerate the league's teams.

        Matched on kwargs, not on the variant slug: the slug is composed from the
        axis order in ``endpoints._SWEEPS``, so reordering those axes would silently
        stop this from ever matching and no team rosters would be captured.
        """
        if endpoint != "leaguedashteamstats":
            return False
        return all(
            any(k.startswith(p) and v == want for k, v in kwargs.items())
            for p, want in (
                ("season_type", "Regular Season"),
                ("measure_type", "Base"),
                ("per_mode", "Totals"),
            )
        )

    for endpoint, variant, kwargs in plan_season(season, module, prefix, league_id):
        path = payload_path(root, endpoint, season, variant)
        is_team_source = _is_team_source(endpoint, kwargs)
        if path.exists():
            skipped += 1
            if is_team_source:
                try:
                    team_source = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    team_source = None
            continue
        try:
            payload = fetch(endpoint, kwargs)
        except Exception as exc:  # noqa: BLE001 - one endpoint gap must not kill the season
            log(f"season {season} {endpoint}[{variant}]: {exc}")
            failed += 1
            continue
        write_payload(path, payload)
        written += 1
        if is_team_source:
            team_source = payload

    # commonteamroster is per (season, team); team ids come from the team-stats
    # capture above rather than a second index call.
    if hasattr(module, f"{prefix}_commonteamroster"):
        for team_id in _ids_from(team_source, "TEAM_ID"):
            path = payload_path(root, "commonteamroster", season, team_id)
            if path.exists():
                skipped += 1
                continue
            try:
                payload = fetch(
                    "commonteamroster",
                    {"season": str(season), "team_id": team_id, "league_id": league_id},
                )
            except Exception as exc:  # noqa: BLE001
                log(f"season {season} commonteamroster[{team_id}]: {exc}")
                failed += 1
                continue
            write_payload(path, payload)
            written += 1

    return written, skipped, failed
