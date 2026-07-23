"""Round-robin ProxyBonanza proxy pool for the shared stats.nba.com request budget.

Port of the R side's ``R/utils.R::get_proxy_ips`` / ``next_proxy``. Credentials
(``PROXY_ENDPOINT`` / ``PROXY_KEY`` / ``PROXY_PKG``) are read from the process
environment at call time -- never hardcoded, never logged in cleartext (use
:func:`redact` before putting a proxy URL in a log line or error message).
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional


def classify(status: Optional[int], text: str, error: Optional[str]) -> str:
    """Bucket a fetch outcome for health/observability.

    - ``transport_err``: the request raised (timeout / connection / proxy dead).
    - ``blocked``: HTTP 403 / 429 / 5xx — the site pushed back (throttle / IP block).
    - ``notfound``: HTTP 400 / 404 — endpoint genuinely absent (expected for old
      seasons; benign, NOT a proxy-health signal).
    - ``blank``: HTTP 200 with an empty body (mild throttle signal).
    - ``ok``: HTTP 200 with a body.

    ``transport_err`` and ``blocked`` are the quarantine-worthy signals (the proxy
    or the IP is the problem); ``notfound`` never counts against a proxy.
    """
    if error is not None:
        return "transport_err"
    if status == 200:
        return "ok" if (text or "").strip() else "blank"
    if status in (400, 404):
        return "notfound"
    return "blocked"


_QUARANTINE_CATS = ("transport_err", "blocked", "blank")


class ProxyHealth:
    """Thread-safe per-proxy + global fetch-outcome registry.

    Drives three things: per-proxy quarantine (consecutive bad outcomes), the
    heartbeat's health summary, and the degradation WARN. Keyed by the redacted
    ``host:port`` so credentials never enter the counters or a log line.
    """

    def __init__(self, quarantine_fails: int = 5, quarantine_secs: float = 120.0):
        self._lock = threading.Lock()
        self._per: dict[str, dict[str, Any]] = {}
        self.quarantine_fails = quarantine_fails
        # Quarantine is a COOLDOWN, not a death sentence: a proxy that trips the
        # consecutive-fault threshold is benched for quarantine_secs then retried,
        # so a transient block storm can't sideline good IPs forever.
        self.quarantine_secs = quarantine_secs
        self.cat: dict[str, int] = {
            k: 0 for k in ("ok", "blank", "notfound", "blocked", "transport_err")
        }

    def record(
        self, proxy_url: Optional[str], category: str, latency_ms: float = 0.0
    ) -> None:
        key = redact(proxy_url) if proxy_url else "direct"
        with self._lock:
            self.cat[category] = self.cat.get(category, 0) + 1
            d = self._per.setdefault(
                key,
                {
                    "req": 0,
                    "consec_err": 0,
                    "quar_until": 0.0,
                    "lat_ms": 0.0,
                    "ok": 0,
                    "blank": 0,
                    "notfound": 0,
                    "blocked": 0,
                    "transport_err": 0,
                },
            )
            d["req"] += 1
            d[category] = d.get(category, 0) + 1
            d["lat_ms"] = latency_ms
            if category in _QUARANTINE_CATS:
                d["consec_err"] += 1
                if (
                    d["consec_err"] >= self.quarantine_fails
                ):  # (re-)bench for a cooldown
                    d["quar_until"] = time.monotonic() + self.quarantine_secs
            else:  # a good outcome fully rehabilitates the proxy
                d["consec_err"] = 0
                d["quar_until"] = 0.0

    def is_quarantined(self, proxy_url: Optional[str]) -> bool:
        key = redact(proxy_url) if proxy_url else "direct"
        with self._lock:
            d = self._per.get(key)
            return bool(d and d["quar_until"] > time.monotonic())

    def reset_quarantine(self) -> None:
        with self._lock:
            for d in self._per.values():
                d["consec_err"] = 0
                d["quar_until"] = 0.0

    def snapshot(self) -> dict:
        with self._lock:
            healthy = degraded = quar = 0
            worst = []
            now = time.monotonic()
            for k, d in self._per.items():
                if d["quar_until"] > now:
                    quar += 1
                    worst.append((k, d["consec_err"]))
                elif d["consec_err"] >= 2:
                    degraded += 1
                    worst.append((k, d["consec_err"]))
                else:
                    healthy += 1
            worst.sort(key=lambda x: -x[1])
            return {
                "cat": dict(self.cat),
                "healthy": healthy,
                "degraded": degraded,
                "quar": quar,
                "used": len(self._per),
                "worst": worst[:3],
            }


def load_proxies() -> list[dict[str, Any]]:
    """Fetch the configured ProxyBonanza proxy list.

    Reads ``PROXY_ENDPOINT`` / ``PROXY_KEY`` / ``PROXY_PKG`` from the process
    environment at call time. GETs ``{PROXY_ENDPOINT}/{PROXY_PKG}.json`` with
    an ``Authorization: {PROXY_KEY}`` header, mirroring the R
    ``get_proxy_ips()`` response shape (``data.login`` / ``data.password`` /
    ``data.ippacks[].ip`` / ``data.ippacks[].port_http``, broadcast into one
    dict per IP pack). Never raises: returns ``[]`` if any of the three env
    vars is unset, the request fails, or the payload doesn't match the
    expected shape.

    Returns:
        A list of dicts with ``ip`` / ``port`` / ``login`` / ``password``
        keys (consumable by :class:`RoundRobin`), or ``[]`` when
        unconfigured / unreachable.
    """
    endpoint = os.environ.get("PROXY_ENDPOINT")
    key = os.environ.get("PROXY_KEY")
    pkg = os.environ.get("PROXY_PKG")
    if not endpoint or not key or not pkg:
        return []

    url = f"{endpoint.rstrip('/')}/{pkg}.json"
    req = urllib.request.Request(url, headers={"Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https proxy-vendor endpoint
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return []

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    ippacks = data.get("ippacks")
    if not isinstance(ippacks, list):
        return []
    login = data.get("login")
    password = data.get("password")
    return [
        {
            "ip": pack["ip"],
            "port": pack["port_http"],
            "login": login,
            "password": password,
        }
        for pack in ippacks
        if isinstance(pack, dict) and pack.get("ip") and pack.get("port_http")
    ]


class RoundRobin:
    """Random-start round-robin proxy rotation.

    Mirrors ``next_proxy()``: shuffles a fixed visiting order once (spreads
    load evenly across IPs instead of ``select_proxy()``'s sampling with
    replacement) and walks it forever.

    Args:
        proxies: List of proxy dicts (``ip`` / ``port`` / ``login`` /
            ``password``), e.g. from :func:`load_proxies`.
    """

    def __init__(
        self, proxies: list[dict[str, Any]], health: "Optional[ProxyHealth]" = None
    ):
        self._proxies = list(proxies)
        self._order = list(range(len(self._proxies)))
        random.shuffle(self._order)
        self._pos = 0
        self._health = health
        self._lock = threading.Lock()  # 14 workers call next() concurrently

    def _url_at(self, idx: int) -> str:
        p = self._proxies[self._order[idx % len(self._order)]]
        return f"http://{p['login']}:{p['password']}@{p['ip']}:{p['port']}"

    def next(self) -> Optional[str]:
        """Return the next non-quarantined proxy URL, or ``None`` if the pool is empty.

        Skips proxies the health tracker has quarantined (too many consecutive
        timeouts / blocks). If every proxy is quarantined, clears the quarantine
        and hands one back anyway rather than stalling the sweep.
        """
        if not self._proxies:
            return None
        with self._lock:
            n = len(self._order)
            for _ in range(n):
                url = self._url_at(self._pos)
                self._pos += 1
                if self._health is None or not self._health.is_quarantined(url):
                    return url
            # whole pool quarantined — reset and fall back so work never stalls
            if self._health is not None:
                self._health.reset_quarantine()
            url = self._url_at(self._pos)
            self._pos += 1
            return url


def redact(url: str) -> str:
    """Strip ``login:password@`` userinfo from a proxy URL for safe logging.

    Args:
        url: A proxy URL, e.g. ``"http://user:pass@1.2.3.4:8000"``.

    Returns:
        The URL with credentials removed (``"scheme://host:port"``). Returns
        the input unchanged if there is no ``@`` to strip.
    """
    scheme_sep = url.find("://")
    if scheme_sep == -1 or "@" not in url:
        return url
    scheme = url[: scheme_sep + 3]
    rest = url[scheme_sep + 3 :]
    _, _, hostport = rest.partition("@")
    return f"{scheme}{hostport}"
