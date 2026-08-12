"""Schedule master + coverage index for the stats.nba.com raw archive (spec §7).

The universe of games comes from the ``leaguegamelog`` payloads already in the
tree (the most complete per-season schedule source here — recorded as the
schedule source of this master). The ``has_<endpoint>`` capture flags come from
one ``os.scandir`` walk of the raw tree, never a per-game ``Path.exists()``:
the archive is ~490k files and per-game stat calls made the WBB step crawl.

Season and season_type are derived from each row's ``SEASON_ID`` (leading
digit = type, remainder = start year), never from the season directory label —
directory labels have historically mixed start-year and end-year conventions
between endpoint families, and rows are the only truth.

Game ids are pinned ``Utf8`` at the boundary: NBA ids are zero-padded
("0022300001") and an int cast destroys the "00" league prefix.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import polars as pl

#: Per-game raw files: "00" league prefix + 8 digits.
GAME_FILE_RE = re.compile(r"^(00\d{8})\.json$")

#: SEASON_ID leading digit -> season_type label.
SEASON_TYPES = {
    "1": "preseason",
    "2": "regular_season",
    "3": "all_star",
    "4": "playoffs",
    "5": "play_in",
    "6": "nba_cup",
}

#: The per-game family whose file stats become the master's scrape-state
#: columns (json_bytes / json_captured_at / scrape_status / last_scraped_at).
PRIMARY_FAMILY = "playbyplayv3"

#: An endpoint gets a ``has_*`` flag when at least this share of its files are
#: game-id-named. Variant endpoints (leaguegamelog, teamgamelogs' team-id
#: files, season aggregates) fall below it and go to the endpoint index only.
GAME_KEYED_SHARE = 0.95

#: Scrape-state + provenance columns the master adds on top of the universe.
SCRAPE_STATE_COLUMNS = (
    "json_bytes",
    "json_captured_at",
    "last_scraped_at",
    "scrape_status",
)

_UNIVERSE_SCHEMA = {
    "game_id": pl.Utf8,
    "season": pl.Utf8,
    "season_type": pl.Utf8,
    "game_date": pl.Date,
    "home_team_id": pl.Int64,
    "home_team_abbreviation": pl.Utf8,
    "away_team_id": pl.Int64,
    "away_team_abbreviation": pl.Utf8,
}


def _span(start_year: int) -> str:
    """1999 -> "1999-00", 2023 -> "2023-24" (the stats-API span convention)."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def load_universe(json_root: str | Path) -> pl.DataFrame:
    """One row per game from every team-level ``leaguegamelog`` payload."""
    games: dict[str, dict] = {}
    lgl = Path(json_root) / "leaguegamelog"
    for season_dir in sorted(lgl.iterdir()) if lgl.is_dir() else []:
        if not season_dir.is_dir():
            continue
        for path in sorted(season_dir.glob("*.json")):
            if path.stem.endswith("_p"):
                continue  # player-level variant; team rows already cover every game
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                print(f"::warning ::unreadable leaguegamelog payload {path}")
                continue
            for result_set in payload.get("resultSets") or []:
                idx = {h: i for i, h in enumerate(result_set.get("headers") or [])}
                need = ("SEASON_ID", "GAME_ID", "GAME_DATE", "MATCHUP", "TEAM_ID")
                if any(k not in idx for k in need):
                    continue
                for row in result_set.get("rowSet") or []:
                    sid = str(row[idx["SEASON_ID"]])
                    gid = str(row[idx["GAME_ID"]])
                    rec = games.setdefault(
                        gid,
                        {
                            "game_id": gid,
                            "season": _span(int(sid[1:])),
                            "season_type": SEASON_TYPES.get(sid[0], sid[0]),
                            "game_date": row[idx["GAME_DATE"]],
                        },
                    )
                    matchup = row[idx["MATCHUP"]] or ""
                    side = "home" if " vs" in matchup else ("away" if "@" in matchup else None)
                    if side is not None:
                        rec[f"{side}_team_id"] = int(row[idx["TEAM_ID"]])
                        abbr = idx.get("TEAM_ABBREVIATION")
                        if abbr is not None:
                            rec[f"{side}_team_abbreviation"] = row[abbr]
    frame = pl.DataFrame(
        list(games.values()) or None,
        schema={**_UNIVERSE_SCHEMA, "game_date": pl.Utf8},
    )
    return frame.with_columns(pl.col("game_date").str.to_date("%Y-%m-%d", strict=False)).sort(
        "season", "game_id"
    )


def walk_raw_tree(
    json_root: str | Path,
) -> tuple[dict[str, set[str]], dict[str, tuple[int, float]], pl.DataFrame]:
    """One scandir sweep: per-endpoint game-id sets, primary-family file stats,
    and the per-(endpoint, season) file index.

    Returns:
        ``(endpoint_gids, primary_stats, endpoint_index)`` where
        ``endpoint_gids`` maps only the game-keyed endpoints (>=95% game-id
        files) to their id sets, ``primary_stats`` maps game_id ->
        ``(bytes, mtime)`` for :data:`PRIMARY_FAMILY`, and ``endpoint_index``
        has one row per (endpoint, season) for every endpoint, game-keyed or
        not — the variant/season-aggregate endpoints live only here.
    """
    endpoint_gids: dict[str, set[str]] = {}
    totals: dict[str, tuple[int, int]] = {}
    primary_stats: dict[str, tuple[int, float]] = {}
    index_rows: list[tuple[str, str, int, int, float]] = []

    root = Path(json_root)
    with os.scandir(root) as it:
        endpoints = sorted(e.name for e in it if e.is_dir())
    for endpoint in endpoints:
        gids: set[str] = set()
        n_total = n_game = 0
        with os.scandir(root / endpoint) as it:
            entries = list(it)
        for entry in sorted(entries, key=lambda e: e.name):
            if entry.is_file() and entry.name.endswith(".json"):
                # Flat per-season payload (drafthistory/2026.json shape).
                stat = entry.stat()
                index_rows.append((endpoint, entry.name[:-5], 1, 0, stat.st_mtime))
                n_total += 1
                continue
            if not entry.is_dir():
                continue
            n_files = n_game_files = 0
            newest = 0.0
            with os.scandir(entry.path) as files:
                for file in files:
                    if not file.name.endswith(".json"):
                        continue
                    n_files += 1
                    stat = file.stat()
                    newest = max(newest, stat.st_mtime)
                    match = GAME_FILE_RE.match(file.name)
                    if match is not None:
                        n_game_files += 1
                        gids.add(match.group(1))
                        if endpoint == PRIMARY_FAMILY:
                            primary_stats[match.group(1)] = (stat.st_size, stat.st_mtime)
            index_rows.append((endpoint, entry.name, n_files, n_game_files, newest))
            n_total += n_files
            n_game += n_game_files
        totals[endpoint] = (n_total, n_game)
        if n_total and n_game / n_total >= GAME_KEYED_SHARE:
            endpoint_gids[endpoint] = gids

    endpoint_index = (
        pl.DataFrame(
            index_rows or None,
            schema={
                "endpoint": pl.Utf8,
                "season": pl.Utf8,
                "n_files": pl.Int64,
                "n_game_files": pl.Int64,
                "newest_mtime": pl.Float64,
            },
            orient="row",
        )
        .with_columns(
            (pl.col("newest_mtime") * 1_000_000)
            .cast(pl.Int64)
            .pipe(lambda e: pl.from_epoch(e, time_unit="us"))
            .alias("newest_captured_at")
        )
        .drop("newest_mtime")
        .sort("endpoint", "season")
    )
    return endpoint_gids, primary_stats, endpoint_index


def build_master(
    universe: pl.DataFrame,
    endpoint_gids: dict[str, set[str]],
    primary_stats: dict[str, tuple[int, float]],
) -> pl.DataFrame:
    """Universe + ``has_*`` flags + scrape state, pinned column order."""
    master = universe
    for endpoint in sorted(endpoint_gids):
        member = sorted(endpoint_gids[endpoint])
        master = master.with_columns(pl.col("game_id").is_in(member).alias(f"has_{endpoint}"))

    stats = (
        pl.DataFrame(
            {
                "game_id": pl.Series(list(primary_stats), dtype=pl.Utf8),
                "json_bytes": pl.Series([b for b, _ in primary_stats.values()], dtype=pl.Int64),
                "_mtime": pl.Series([m for _, m in primary_stats.values()], dtype=pl.Float64),
            }
        )
        .with_columns(
            (pl.col("_mtime") * 1_000_000)
            .cast(pl.Int64)
            .pipe(lambda e: pl.from_epoch(e, time_unit="us"))
            .alias("json_captured_at")
        )
        .drop("_mtime")
    )

    master = master.join(stats, on="game_id", how="left").with_columns(
        pl.when(pl.col("json_bytes").is_null())
        .then(pl.lit("missing"))
        # The empty-{} guard upstream should keep these out, but a 2-byte
        # payload in the tree is a failed capture, not a capture.
        .when(pl.col("json_bytes") <= 2)
        .then(pl.lit("error"))
        .otherwise(pl.lit("ok"))
        .alias("scrape_status"),
        # ponytail: mtime is the only timestamp the tree carries, so captured-at
        # and last-scraped-at coincide; a scrape ledger would split them.
        pl.col("json_captured_at").alias("last_scraped_at"),
    )
    return master.select(sorted(master.columns)).sort("season", "game_id")


def build_coverage(master: pl.DataFrame) -> pl.DataFrame:
    """One row per (season, season_type): counts, date range, capture rates."""
    has_cols = sorted(c for c in master.columns if c.startswith("has_"))
    aggs = [
        pl.len().alias("n_games"),
        pl.col("game_date").min().alias("first_date"),
        pl.col("game_date").max().alias("last_date"),
        (pl.col("scrape_status") == "ok").mean().alias("pct_captured"),
        *[pl.col(c).mean().alias(f"pct_{c}") for c in has_cols],
    ]
    return (
        master.group_by(["season", "season_type"], maintain_order=True)
        .agg(aggs)
        .sort("season", "season_type")
    )


def reconcile(universe: pl.DataFrame, endpoint_gids: dict[str, set[str]]) -> pl.DataFrame:
    """Per-endpoint file-count vs flag-count reconciliation (the WBB gate).

    ``n_orphans`` = files whose game id the schedule universe does not know;
    a non-zero count means the leaguegamelog capture is behind the tree.
    """
    known = set(universe["game_id"].to_list())
    rows = [
        (ep, len(gids), len(gids & known), len(gids - known))
        for ep, gids in sorted(endpoint_gids.items())
    ]
    return pl.DataFrame(
        rows or None,
        schema={
            "endpoint": pl.Utf8,
            "n_files": pl.Int64,
            "n_flagged": pl.Int64,
            "n_orphans": pl.Int64,
        },
        orient="row",
    )
