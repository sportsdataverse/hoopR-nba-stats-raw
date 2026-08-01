"""Declarative capture registry for the stats.{nba,wnba}.com surface.

One module drives both leagues and both raw repos; only ``league_id`` differs.

Rather than hand-maintaining ~90 endpoint entries and their parameter matrices,
the matrix for each endpoint is **derived from its own signature**: an endpoint
that accepts a ``season_type*`` parameter gets swept over season types, one that
accepts ``measure_type*`` over measure types, and so on. A new endpoint appearing
upstream is therefore captured at the right granularity with no edit here, and an
endpoint that drops a parameter stops being swept over it instead of 400-ing.

Granularity choices, made for reuse rather than for any one current consumer:

* **Game endpoints** are captured whole-game, one payload per game per endpoint.
  Anything narrower (period, range) is a strict subset that can be re-requested,
  and the per-period capture already exists separately for lineup grounding.
* **Season endpoints** are captured at ``Totals`` *and* ``PerGame``. Totals is the
  information-dense form -- PerGame, Per36 and Per100 are all derivable from it --
  but the currently published datasets are PerGame, and deriving them would
  introduce rounding differences against what consumers already read. Season-level
  calls are cheap enough (tens per season, against thousands per season of games)
  that capturing both removes the question entirely.
* Every call pins ``season`` and ``league_id`` explicitly rather than relying on
  upstream defaults, which are undocumented and free to drift.

Capturing a superset is deliberate: a payload already on disk costs nothing to
reshape later, while a payload never captured means re-sweeping a decade.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any, Callable

LEAGUE_NBA = "00"
LEAGUE_WNBA = "10"

SEASON_TYPES = ("Regular Season", "Playoffs")
MEASURE_TYPES = ("Base", "Advanced", "Misc", "Scoring", "Usage", "Defense", "Opponent")
PER_MODES = ("Totals", "PerGame")

#: Lineups are five-player units; the endpoint also accepts 2-4 but the published
#: datasets are 5-man and the smaller units are a much larger combinatorial space.
LINEUP_GROUP_QUANTITY = 5

#: Parameter-name prefix -> the values to sweep it over. Prefix-matched because the
#: same concept is spelled differently per endpoint (``season_type_all_star``,
#: ``season_type_playoffs``, ``season_type_nullable``).
_SWEEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("season_type", SEASON_TYPES),
    ("measure_type", MEASURE_TYPES),
    ("per_mode", PER_MODES),
)

#: Parameters pinned to a single value when the endpoint accepts them.
_PINS: tuple[tuple[str, Any], ...] = (("group_quantity", LINEUP_GROUP_QUANTITY),)


def _params(fn: Callable[..., Any]) -> set[str]:
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def _match(params: set[str], prefix: str) -> str | None:
    """The endpoint's own spelling of a swept parameter, if it accepts one."""
    for name in sorted(params):
        if name.startswith(prefix):
            return name
    return None


def slug(value: Any) -> str:
    """Filename-safe parameter value (``Regular Season`` -> ``regular-season``)."""
    return str(value).lower().replace(" ", "-").replace("_", "-")


def discover(module: Any, prefix: str) -> tuple[list[str], list[str]]:
    """``(game_endpoints, season_endpoints)`` exposed by a league's stats module.

    Team- and player-keyed endpoints are excluded: they are addressed by an id this
    sweep does not enumerate, and are a separate (much larger) capture decision.
    """
    game: list[str] = []
    season: list[str] = []
    for name in sorted(dir(module)):
        if not name.startswith(f"{prefix}_"):
            continue
        fn = getattr(module, name)
        if not callable(fn):
            continue
        params = _params(fn)
        if not params:
            continue
        short = name[len(prefix) + 1 :]
        if "game_id" in params:
            game.append(short)
        elif "team_id" in params or "player_id" in params:
            continue
        else:
            season.append(short)
    return game, season


def season_variants(
    fn: Callable[..., Any], season: int, league_id: str
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Yield ``(variant_slug, kwargs)`` for every capture of one season endpoint.

    The slug is built only from the parameters this endpoint actually sweeps, so
    an endpoint gaining an unrelated parameter later cannot rename existing
    captures, and two endpoints never collide on a filename.
    """
    params = _params(fn)
    base: dict[str, Any] = {}
    if "season" in params:
        base["season"] = str(season)
    if "league_id" in params:
        base["league_id"] = league_id
    for pin, value in _PINS:
        name = _match(params, pin)
        if name:
            base[name] = value

    # Expand the cartesian product of whichever sweeps this endpoint supports.
    axes: list[tuple[str, tuple[str, ...]]] = []
    for prefix, values in _SWEEPS:
        name = _match(params, prefix)
        if name:
            axes.append((name, values))

    if not axes:
        yield None, base
        return

    def walk(
        i: int, acc: dict[str, Any], parts: list[str]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        if i == len(axes):
            yield "_".join(parts), {**base, **acc}
            return
        name, values = axes[i]
        for value in values:
            yield from walk(i + 1, {**acc, name: value}, [*parts, slug(value)])

    yield from walk(0, {}, [])


def plan_counts(
    module: Any, prefix: str, league_id: str, season: int = 2025
) -> dict[str, int]:
    """Per-season call counts, for sizing a sweep before running one."""
    game, season_eps = discover(module, prefix)
    n_season = sum(
        len(list(season_variants(getattr(module, f"{prefix}_{ep}"), season, league_id)))
        for ep in season_eps
    )
    return {
        "game_endpoints": len(game),
        "season_endpoints": len(season_eps),
        "season_calls_per_season": n_season,
    }
