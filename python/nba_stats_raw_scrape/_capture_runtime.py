"""Shared capture runtime for the numbered stats.nba.com capture stages.

Every capture stage needs the same plumbing: the league binding, per-endpoint
season floors, the proxy pool and its sticky ``curl_cffi`` transport, the
progress heartbeat, and the end-of-run health breakdown. That plumbing lives
here ONCE.

This is an import seam, not a stage — it has no ``main()`` and captures
nothing. The stages that use it are independently runnable and resume from
what is on disk, so a failure in one does not strand the others:

    nba_stats_01_season_endpoints.py   season-level payloads (persists leaguegamelog)
    nba_stats_02_game_endpoints.py     per-game whole-game payloads
    nba_stats_03_period_boxscores.py   per-period boxscores

They are ordered by DATA dependency, through the store rather than through
memory: stage 01 persists ``leaguegamelog``, which 02 and 03 read back for
their game universe. That indirection is exactly what lets each be re-run,
resumed, or skipped on its own.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---- league binding: the only NBA-specific block ----------------------------
LEAGUE_SLUG = "nba"
LEAGUE_ID = "00"
STATS_PREFIX = "nba_stats"
STORE_ENV = "SDV_PY_NBA_RAW_JSON_DIR"
STORE_SUBDIR = ("nba_stats", "json")
# -----------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SEASON_TYPES = ("Regular Season", "Playoffs")


WORKERS = int(os.environ.get("SCRAPE_WORKERS", "6"))
PERIOD_ENDPOINT = "boxscoretraditionalv3_period"
# Per-endpoint season floor (start-year): below it the endpoint has no data and
# either 500s or returns an empty envelope, so we skip the wasted call. Floors are
# measured (store scan + live probe), not guessed. Game-keyed endpoints are dropped
# in _endpoints_for; season-level ones via capture_season(skip_endpoints=...).
#
# NOT skipped (verified they DO carry old-season data): leaguedashteamshotlocations
# / leaguedashplayershotlocations (basic shot-zone variants populate back to 1996);
# leaguedashteamstats (its Base variant is the team-id source for commonteamroster).
_PT = int(os.environ.get("PT_MIN_SEASON", "2013"))  # SportVU player tracking: 2013-14+


def _parked(endpoint: str) -> int:
    """Floor for a PARKED endpoint: above any real season, so it is skipped.

    Read from ``<ENDPOINT>_MIN_SEASON`` so every parked endpoint is
    independently re-enablable. A shared variable would be a trap: one
    ``DRAFTCOMBINE_MIN_SEASON`` would un-park all five draftcombine endpoints
    at once, so a fixed-parameter run for one of them would silently resume
    hammering the other four with parameters that are still wrong.
    """
    return int(os.environ.get(f"{endpoint.upper()}_MIN_SEASON", "9999"))


ENDPOINT_MIN_SEASON = {
    # --- game-keyed (probed floors) ---
    # gamerotation is PARKED (floor above any real season = skipped outright). It
    # holds real data from 2015-16 on (empty resultSets earlier), but it's a slow
    # endpoint that times out on most attempts under the main sweep's concurrency,
    # so it drags every 2016+ season for a low capture rate. Capture it later with a
    # dedicated low-concurrency pass — everything else is already on disk, so it
    # skips-as-present and only gamerotation is fetched:
    #   GAMEROTATION_MIN_SEASON=2016 SCRAPE_WORKERS=3 SDV_PY_NBA_STATS_TIMEOUT=60 \
    #     bash scripts/backfill_nba_stats_raw.sh 2016:2026
    "gamerotation": _parked("gamerotation"),
    # Rows-measured floors (archive scan 2026-08-02): both lineup dashboards
    # answer with a valid zero-row envelope for every season before 2007-08.
    "leaguedashlineups": 2007,
    "leaguelineupviz": 2007,
    "boxscorematchupsv3": 2017,  # probed: empty <=2016, populates 2017-18
    "boxscoredefensivev2": 2017,  # probed: empty <=2016, populates 2017-18
    # --- PARKED: needs an input the season sweep cannot build.
    # Same sentinel mechanism as gamerotation above: a floor over any real
    # season, overridable so a fixed-parameter pass can re-enable one.
    #
    #   playercompare   VERIFIED FUNCTIONAL (calm probe 2026-08-02:
    #                   PlayerIDList=2544 vs 201142, 2023-24 -> OverallCompare
    #                   + Individual rows). It is ENTITY-keyed like
    #                   shotchartlineupdetail: without real player-id lists the
    #                   28 variants/season all time out, which is what dragged
    #                   the 2026-08-01 sweep (seasons 2014/2015 took 9m18s /
    #                   7m51s). Un-parking is a per-entity capture design, not
    #                   a parameter fix.
    #
    # Deliberately NOT parked:
    #   leaguedashptteamdefend  floor is simply the shared _PT one -- calm
    #                   probes (2026-08-02) return 30 rows at 2013-14, 2015-16
    #                   and 2016-17; the earlier "fails across the tracking
    #                   era" was throttle noise, not a data boundary.
    #   teamgamelogs    fully solved by the span season string (2,460 rows
    #                   measured); its Usage variant returns {} even with valid
    #                   params (both leagues), so ENDPOINT_MEASURE_TYPES in
    #                   endpoints.py excludes Usage for it (and now carries the
    #                   probed Four Factors + Opponent team measures instead).
    #   draftcombine*   UN-PARKED 2026-08-02. The park rationale ("value shape
    #                   still wrong") was a misdiagnosis: calm probes return
    #                   full tables with the exact bare-year `season_year` the
    #                   sweep builds (77 rows, 2019, all four per-year
    #                   endpoints). draftcombinestats was different -- its
    #                   season param is spelled `season_all_time`, which
    #                   _SEASON_PARAMS never matched, so it was swept with NO
    #                   season at all; endpoints.py now matches + spans it.
    #                   Floor 2000 is measured (valid zero-row envelopes
    #                   1996-99, 65 rows in 2000).
    "playercompare": _parked("playercompare"),
    "draftcombinestats": 2000,
    "draftcombinedrillresults": 2000,
    "draftcombineplayeranthro": 2000,
    "draftcombinespotshooting": 2000,
    "draftcombinenonstationaryshooting": 2000,
    # --- season-level: player-tracking (SportVU) ---
    "leaguedashptstats": _PT,
    "leaguedashptdefend": _PT,
    "leaguedashplayerptshot": _PT,
    "leaguedashoppptshot": _PT,
    "leaguedashteamptshot": _PT,
    "leaguedashptteamdefend": _PT,
    # --- season-level: matchup data (2017-18+, same era as boxscorematchups) ---
    "matchupsrollup": 2017,
    "leagueseasonmatchups": 2017,
    # --- season-level: Synergy play-types (2015-16+) ---
    "synergyplaytypes": 2015,
    # --- season-level: game-log v-endpoints (tracking-era, empty pre-2014) ---
    # playercompare is NOT listed here: it is parked above. A second entry for
    # it would silently win (later key wins in a dict literal) and un-park it.
    "playergamelogs": 2014,
    "teamgamelogs": 2014,
}
# NOTE: a duplicated key in the literal above is INVISIBLE at runtime -- the
# later one silently wins, which is exactly how the parked playercompare floor
# got overridden by a stale 2014 entry. It cannot be caught by inspecting the
# built dict (the duplicate is already gone), so
# tests/test_endpoint_floor.py::test_no_duplicate_endpoint_keys parses the AST.


#: Season CEILINGS -- an endpoint that stops publishing entirely after the
#: listed season. Only consulted by _skip_endpoint. Currently EMPTY: the
#: draftcombine* 2019 ceilings recorded here until 2026-08-02 were false --
#: calm probes return 74/83/83 rows for 2021/2022/2024 (the "NOTHING after
#: 2019" reading came from the era when draftcombinestats was swept with no
#: season param at all). A ceiling belongs here only when a calm probe of
#: later seasons keeps answering a VALID ZERO-ROW envelope, never from
#: absence-of-capture alone.
ENDPOINT_MAX_SEASON: dict[str, int] = {}


def _skip_endpoint(endpoint: str, season: int) -> bool:
    """True when `endpoint` has no data for `season`, so the call is skipped.

    Single owner of the floor comparison. Both call sites -- the per-game
    `_endpoints_for` and the season-level `skip_season_eps` -- previously
    inlined it, in INVERTED forms (`yr >= floor` to keep vs `season < mn` to
    skip). Two hand-maintained copies of one boundary is how the shot-locations
    over-skip (4ec4c143a4) happened. An endpoint absent from the table has no
    floor and is never skipped.
    """
    if season < ENDPOINT_MIN_SEASON.get(endpoint, 0):
        return True
    return season > ENDPOINT_MAX_SEASON.get(endpoint, 9999)


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


class Progress:
    """Shared per-game progress, updated by the main consume loop and read by the
    heartbeat thread. games_done is per-season so the rate/ETA reflect now, not
    the whole run."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.season: object = None
        self.games_done = 0
        self.games_total = 0
        self.season_start = time.monotonic()

    def begin_season(self, season: object, total: int) -> None:
        with self.lock:
            self.season = season
            self.games_done = 0
            self.games_total = total
            self.season_start = time.monotonic()

    def tick(self) -> None:
        with self.lock:
            self.games_done += 1

    def snapshot(self) -> tuple:
        with self.lock:
            return self.season, self.games_done, self.games_total, self.season_start


def _heartbeat(
    progress: Progress, health, stop_evt: threading.Event, secs: float, pool_size: int
) -> None:
    """Emit a steady progress + IP-health line every ``secs`` and WARN when the
    proxy pool degrades. Windowed on the delta since the last beat so the
    error-rate reflects the recent window, not the cumulative run."""
    last = {}
    while not stop_evt.wait(secs):
        season, done, total, t0 = progress.snapshot()
        if not total:
            continue
        elapsed = max(time.monotonic() - t0, 1e-6)
        rate = done / elapsed
        remaining = max(total - done, 0)
        eta_min = (remaining / rate / 60) if rate > 0 else float("inf")
        snap = health.snapshot()
        c = snap["cat"]
        delta = {k: c.get(k, 0) - last.get(k, 0) for k in c}
        last = dict(c)
        eta_s = "?" if eta_min == float("inf") else f"{eta_min:.0f}m"
        _log(
            f"season {season}: {done}/{total} games | {rate:.1f}/s | ETA {eta_s} | "
            f"win[ok={delta['ok']} blank={delta['blank']} 404={delta['notfound']} "
            f"blocked={delta['blocked']} 5xx={delta['server_err']} timeout/err={delta['transport_err']}] | "
            f"proxies {snap['healthy']}ok/{snap['degraded']}deg/{snap['quar']}quar of {pool_size} | "
            f"top-err: {health.top_error_endpoints(3)}"
        )
        # Degradation WARN — driven by proxy-fault signals (timeouts + blocks +
        # quarantines), NOT 404s (those are expected-absent old-season endpoints).
        win_total = sum(delta.values())
        win_fault = delta["transport_err"] + delta["blocked"]
        if snap["quar"] >= max(3, pool_size // 5) or (
            win_total > 50 and win_fault / win_total > 0.35
        ):
            worst = ", ".join(f"{k}:{n}" for k, n in snap["worst"]) or "n/a"
            _log(
                f"WARN: proxy pool degrading — {snap['quar']}/{pool_size} quarantined, "
                f"{win_fault}/{win_total} recent faults; worst: {worst}"
            )


def _parse_seasons(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = spec.split(":", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


# ---- shared setup, previously inline in the monolith's main() ---------------


def resolve_store() -> str:
    """Pin the store to THIS checkout.

    Explicit rather than env mutation, so a stage is immune to ambient config:
    a leaked ``*_READONLY`` would otherwise silently turn a capture stage into
    a no-op that still exits 0.
    """
    return os.environ.get(STORE_ENV) or str(REPO.joinpath(*STORE_SUBDIR))


def load_stats_module():
    """The league's sdv-py stats module, plus its discovered endpoint split."""
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nba_stats_raw_scrape.endpoints import discover

    stats = importlib.import_module(f"sportsdataverse.{LEAGUE_SLUG}.{STATS_PREFIX}")
    game_endpoints, season_endpoints = discover(stats, STATS_PREFIX)
    return stats, game_endpoints, season_endpoints


def open_transport():
    """Proxy pool -> health -> round robin -> sticky session transport.

    Returns ``(transport, health, pool)``, or ``(None, None, [])`` when no
    proxies are configured. Every capture stage must treat the empty pool as
    fatal: un-proxied stats.{nba,wnba}.com calls HANG rather than fail, so a
    stage that proceeded would look busy forever instead of erroring.
    """
    from sportsdataverse.scrape.stats.proxy import ProxyHealth, RoundRobin, load_proxies
    from sportsdataverse.scrape.stats.session_transport import SessionTransport

    pool = load_proxies()
    if not pool:
        return None, None, []
    health = ProxyHealth(
        quarantine_fails=int(os.environ.get("PROXY_QUARANTINE_FAILS", "5")),
        quarantine_secs=float(os.environ.get("PROXY_QUARANTINE_SECS", "120")),
        error_log=os.environ.get("STATS_ERROR_LOG", "logs/errors.jsonl"),
    )
    return SessionTransport(RoundRobin(pool, health=health), health), health, pool


def no_proxy_error() -> int:
    _log(
        "ERROR: no proxies. Un-proxied stats.%s.com calls hang rather than fail;"
        " export PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG (they live in ~/.Renviron,"
        " which Python does not read)." % LEAGUE_SLUG
    )
    return 1


def start_heartbeat(progress: "Progress", health, n_proxies: int):
    """Daemon heartbeat thread; returns ``(thread, stop_event)``."""
    stop = threading.Event()
    t = threading.Thread(
        target=_heartbeat,
        args=(progress, health, stop, float(os.environ.get("HEARTBEAT_SECS", "60")), n_proxies),
        daemon=True,
    )
    t.start()
    return t, stop


def summarize_health(health) -> None:
    """Full by-endpoint fault breakdown, so 'which requests errored and why' is
    answerable without opening the JSONL."""
    for ep, errs, ec in health.endpoint_summary():
        _log(
            f"endpoint {ep}: {errs} faults | ok={ec['ok']} 404={ec['notfound']}"
            f" blocked={ec['blocked']} 5xx={ec['server_err']} blank={ec['blank']}"
            f" timeout/err={ec['transport_err']}"
        )
    health.close()


def game_ids_for_season(store: str, season: int) -> set[str]:
    """The season's game universe, read from the ``leaguegamelog`` payloads
    stage 01 persisted.

    Reading from disk rather than re-fetching is what makes 02 and 03
    independently runnable: the index is already paid for.
    """
    from nba_stats_raw_scrape.season_capture import game_ids_from_gamelog, payload_path

    gids: set[str] = set()
    for stype in SEASON_TYPES:
        flat = payload_path(store, "leaguegamelog", season, None)
        variant = stype.lower().replace(" ", "-")
        for candidate in (payload_path(store, "leaguegamelog", season, variant), flat):
            if candidate.exists():
                try:
                    gids.update(
                        game_ids_from_gamelog(json.loads(candidate.read_text(encoding="utf-8")))
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    _log(f"season {season} {stype}: game-index read failed: {exc}")
                break
    return gids


def targeted_ids(ids_file: str) -> dict[int, list[str]]:
    """Parse a ``--game-ids=<file>`` list into ``{season: [game_id, ...]}``.

    leaguegamelog indexes regular season + playoffs only, so preseason,
    All-Star, play-in and Cup-final games are unreachable by the season sweep
    however often it is rerun -- they have to be named.
    """
    from nba_stats_raw_scrape.period_capture import season_of

    out: dict[int, list[str]] = {}
    for line in Path(ids_file).read_text(encoding="utf-8").splitlines():
        gid = line.strip()
        if gid:
            out.setdefault(season_of(gid), []).append(gid)
    return out


def parse_common(argv: list[str], doc: str):
    """Shared CLI shape for every capture stage: ``[--check] [--game-ids=F] LO:HI``.

    Returns ``(seasons, targeted, check_only)`` or ``None`` on a usage error.
    """
    check_only = "--check" in argv
    ids_file = next((a.split("=", 1)[1] for a in argv if a.startswith("--game-ids=")), None)
    positional = [a for a in argv if not a.startswith("--")]
    if not positional and ids_file is None:
        print(doc, file=sys.stderr)
        return None
    targeted: dict[int, list[str]] = {}
    if ids_file is not None:
        targeted = targeted_ids(ids_file)
        # An empty / all-blank file otherwise reaches the summary log with no
        # seasons and dies on seasons[0] -- an IndexError traceback in place of
        # the usage error this actually is.
        if not targeted:
            print(f"no game ids in {ids_file}", file=sys.stderr)
            return None
    seasons = sorted(targeted) if ids_file is not None else _parse_seasons(positional[0])
    return seasons, targeted, check_only
