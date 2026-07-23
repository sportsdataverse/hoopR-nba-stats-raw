#!/usr/bin/env python
"""Scrape stats.nba.com raw JSON into this repo's nba_stats/json tree.

THIS repo owns filling the WNBA raw store. Compile/build jobs elsewhere
(hoopR-nba-stats-data, sdv-py's nba possession engine) consume the tree as pure readers
(``SDV_PY_NBA_RAW_JSON_DIR`` + ``SDV_PY_NBA_RAW_JSON_READONLY=1``) and never
write it — the raw-vs-data separation of concerns, mirrored by wehoop-wnba-stats-raw.

Each season is swept in three passes:

1. **Season-level** endpoints (:mod:`season_capture`) into
   ``{endpoint}/{season}/{variant}.json``. Which endpoints, and the parameter
   matrix each gets, come from :mod:`endpoints` — derived from the endpoints' own
   signatures, so new upstream endpoints are captured without an edit here.
2. **Per-game** payloads for every game-keyed endpoint, through sdv-py's
   read-through store: ``{endpoint}/{season}/{game_id}.json`` (atomic tmp+rename).
3. **Per-period** boxscores (``boxscoretraditionalv3_period``) — the quarter-box
   lineup grounding. One payload per *game*, keyed by period, matching what the
   ``-data`` repos consume. Period counts are read off the play-by-play captured in
   pass 2, so overtime costs no extra request, and the request window uses
   :mod:`period_capture`'s NBA time math (delegated to sdv-py).

Game discovery reads the ``leaguegamelog`` payload pass 1 just persisted rather
than making its own call, so the index is fetched once per season/type.

Everything is league-agnostic apart from the ``LEAGUE`` block below: the same file
serves wehoop-wnba-stats-raw with those four constants changed.

**Proxies are required.** Un-proxied calls to stats.{nba,wnba}.com hang from a
datacenter IP rather than failing fast. ``proxy.load_proxies()`` reads
``PROXY_ENDPOINT`` / ``PROXY_KEY`` / ``PROXY_PKG`` from the process environment —
these live in ``~/.Renviron``, which R loads automatically but Python does not, so
export them before running (see ``--check`` below, which fails loudly on an empty
pool instead of hanging).

Seasons on the CLI are plain calendar years: ``2024`` or ``1997:2026``.
``--check`` sizes the sweep and verifies the proxy pool without fetching anything.

Run with the wehoop-wnba-stats-data venv (carries sportsdataverse+curl_cffi; this
repo deliberately has no Python project of its own):

    /mnt/sdv_repos/hoopR-nba-stats-data/python/.venv/bin/python \\
      scripts/scrape_raw_json.py 1997:2026
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ---- league binding: the only WNBA-specific block ---------------------------
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
            f"blocked={delta['blocked']} timeout/err={delta['transport_err']}] | "
            f"proxies {snap['healthy']}ok/{snap['degraded']}deg/{snap['quar']}quar of {pool_size}"
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


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    check_only = "--check" in argv
    argv = [a for a in argv if not a.startswith("--")]
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2

    # Explicit store args (not env mutation) so this writer is immune to ambient
    # config: store pins the tree to THIS checkout and readonly=False overrides
    # any leaked READONLY env var.
    store = os.environ.get(STORE_ENV) or str(REPO.joinpath(*STORE_SUBDIR))

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import importlib

    from endpoints import discover, plan_counts
    from period_capture import (
        QUARTER_BOX_RANGE_TYPE,
        period_start_range,
        periods_in_game,
        season_of,
    )
    from proxy import ProxyHealth, RoundRobin, classify, load_proxies
    from season_capture import capture_season, game_ids_from_gamelog, payload_path
    from sportsdataverse.nba.nba_possessions import _raw_store_path, _through_raw_store

    # The real curl_cffi transport lives in the shared stats runtime; wrap it so
    # every fetch's (proxy, status, latency, error) feeds ProxyHealth. League-
    # agnostic: prefer the league's runtime module, fall back to the NBA one.
    try:
        _rt = importlib.import_module(
            f"sportsdataverse.{LEAGUE_SLUG}.{STATS_PREFIX}_runtime"
        )
        _curl_transport = _rt._curl_transport
    except (ImportError, AttributeError):
        pass

    stats = importlib.import_module(f"sportsdataverse.{LEAGUE_SLUG}.{STATS_PREFIX}")
    game_endpoints, _season_endpoints = discover(stats, STATS_PREFIX)
    seasons = _parse_seasons(argv[0])

    pool = load_proxies()
    counts = plan_counts(stats, STATS_PREFIX, LEAGUE_ID)
    _log(f"{LEAGUE_SLUG.upper()} store: {store}")
    _log(
        f"{len(seasons)} seasons | {counts['game_endpoints']} game endpoints"
        f" | {counts['season_endpoints']} season endpoints"
        f" ({counts['season_calls_per_season']} calls/season) | workers={WORKERS}"
    )
    if not pool:
        _log(
            "ERROR: no proxies. Un-proxied stats.%s.com calls hang rather than fail;"
            " export PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG (they live in ~/.Renviron,"
            " which Python does not read)." % LEAGUE_SLUG
        )
        return 1
    _log(f"proxy pool: {len(pool)} entries")
    if check_only:
        _log("--check: sweep sized and proxy pool verified; fetching nothing")
        return 0

    health = ProxyHealth(
        quarantine_fails=int(os.environ.get("PROXY_QUARANTINE_FAILS", "5"))
    )
    rr = RoundRobin(pool, health=health)

    def _instrumented(url: str, params: dict, headers: dict, proxy_url) -> tuple:
        """Wrap the real curl_cffi transport to record per-fetch health, then
        return ``(status, text)`` unchanged so the store/parse path is identical."""
        t0 = time.monotonic()
        try:
            status, text = _curl_transport(url, params, headers, proxy_url)
        except Exception:
            health.record(proxy_url, "transport_err", (time.monotonic() - t0) * 1000)
            raise  # preserve the "timeout propagates" contract for the miss count
        health.record(
            proxy_url, classify(status, text, None), (time.monotonic() - t0) * 1000
        )
        return status, text

    def _season_fetch(endpoint: str, kwargs: dict) -> object:
        fn = getattr(stats, f"{STATS_PREFIX}_{endpoint}")
        return fn(
            return_parsed=False, proxy_url=rr.next(), transport=_instrumented, **kwargs
        )

    def _game_fetch(endpoint: str, gid: str) -> object:
        fn = getattr(stats, f"{STATS_PREFIX}_{endpoint}")
        return fn(
            game_id=gid,
            return_parsed=False,
            proxy_url=rr.next(),
            transport=_instrumented,
        )

    def _one(gid: str) -> tuple[int, int]:
        fetched = failed = 0
        pbp_payload = None
        for ep in game_endpoints:
            path = _raw_store_path(ep, gid, root=store)
            if path is not None and path.exists():
                if ep == "playbyplayv3":
                    try:
                        pbp_payload = json.loads(path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        pbp_payload = None
                continue
            try:
                got = _through_raw_store(
                    ep,
                    gid,
                    lambda e=ep, g=gid: _game_fetch(e, g),
                    store_dir=store,
                    readonly=False,
                )
                if ep == "playbyplayv3":
                    pbp_payload = got
                fetched += 1
            except Exception:  # noqa: BLE001 - a game-local failure must not kill the sweep
                failed += 1

        # Per-period boxscores, written as ONE payload per game keyed by period --
        # the shape the -data repos already consume. A file per period would mean
        # 4-6x the objects for no gain, and every reader would have to reassemble
        # them before use.
        #
        # The period count comes from the play-by-play above, so overtime is
        # discovered without a request and a fixed count cannot truncate an OT game.
        n_periods = periods_in_game(pbp_payload)
        ppath = _raw_store_path(PERIOD_ENDPOINT, gid, root=store)
        if n_periods and (ppath is None or not ppath.exists()):

            def _all_periods(g: str = gid, n: int = n_periods) -> dict:
                """Fetch every period for one game into a {period: payload} mapping.

                Written through the store as a single object, so a partially-fetched
                game leaves nothing behind: any period failing aborts the whole game
                rather than persisting a half-captured mapping that later looks
                complete.
                """
                season = season_of(g)
                out: dict[str, object] = {}
                for period in range(1, n + 1):
                    start_range, end_range = period_start_range(period, season)
                    out[str(period)] = getattr(
                        stats, f"{STATS_PREFIX}_boxscoretraditionalv3"
                    )(
                        game_id=g,
                        start_period=period,
                        end_period=period,
                        range_type=QUARTER_BOX_RANGE_TYPE,
                        start_range=start_range,
                        end_range=end_range,
                        return_parsed=False,
                        proxy_url=rr.next(),
                        transport=_instrumented,
                    )
                return out

            try:
                _through_raw_store(
                    PERIOD_ENDPOINT, gid, _all_periods, store_dir=store, readonly=False
                )
                fetched += 1
            except Exception:  # noqa: BLE001 - a period gap must not kill the game
                failed += 1
        return fetched, failed

    # Steady heartbeat + IP-health line every HEARTBEAT_SECS during the (otherwise
    # silent) per-game pass; a daemon thread so it can't block shutdown.
    progress = Progress()
    stop_hb = threading.Event()
    hb = threading.Thread(
        target=_heartbeat,
        args=(
            progress,
            health,
            stop_hb,
            float(os.environ.get("HEARTBEAT_SECS", "60")),
            len(pool),
        ),
        daemon=True,
    )
    hb.start()

    grand_fetched = grand_failed = 0
    for season in seasons:
        # Season-level first: cheap, and it persists leaguegamelog, which the
        # per-game pass then reads for its index instead of re-fetching it.
        s_written, s_skipped, s_failed = capture_season(
            season, store, _season_fetch, stats, STATS_PREFIX, LEAGUE_ID, _log
        )
        _log(
            f"season {season}: season-level | {s_written} written | {s_skipped} present | {s_failed} failed"
        )

        gids: set[str] = set()
        for stype in SEASON_TYPES:
            path = payload_path(store, "leaguegamelog", season, None)
            variant = stype.lower().replace(" ", "-")
            for candidate in (
                payload_path(store, "leaguegamelog", season, variant),
                path,
            ):
                if candidate.exists():
                    try:
                        gids.update(
                            game_ids_from_gamelog(
                                json.loads(candidate.read_text(encoding="utf-8"))
                            )
                        )
                    except (OSError, json.JSONDecodeError) as exc:
                        _log(f"season {season} {stype}: game-index read failed: {exc}")
                    break

        # A game is incomplete if any endpoint is missing OR its period boxscores
        # were never captured. Without the second half, games captured before an
        # endpoint was added would be skipped forever and a backfill would no-op.
        def _incomplete(g: str) -> bool:
            for ep in game_endpoints:
                p = _raw_store_path(ep, g, root=store)
                if p is not None and not p.exists():
                    return True
            periods = _raw_store_path(PERIOD_ENDPOINT, g, root=store)
            return periods is not None and not periods.exists()

        todo = [g for g in sorted(gids) if _incomplete(g)]
        _log(f"season {season}: {len(gids)} games indexed, {len(todo)} incomplete")
        progress.begin_season(season, len(todo))
        if not todo:
            continue
        fetched = failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool_exec:
            for fut in as_completed(pool_exec.submit(_one, g) for g in todo):
                f, x = fut.result()
                fetched += f
                failed += x
                progress.tick()
        grand_fetched += fetched
        grand_failed += failed
        snap = health.snapshot()
        c = snap["cat"]
        _log(
            f"season {season}: done | {fetched} payloads fetched | {failed} misses"
            f" | http[ok={c['ok']} blank={c['blank']} 404={c['notfound']}"
            f" blocked={c['blocked']} timeout/err={c['transport_err']}]"
            f" | proxies {snap['quar']} quarantined of {len(pool)}"
        )

    stop_hb.set()
    _log(
        f"sweep complete: {grand_fetched} payloads persisted, {grand_failed} misses"
        " (endpoint gaps are expected in early seasons)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
