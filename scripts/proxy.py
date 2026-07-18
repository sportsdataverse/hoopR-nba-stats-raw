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
import urllib.error
import urllib.request
from typing import Any, Optional


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
        {"ip": pack["ip"], "port": pack["port_http"], "login": login, "password": password}
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

    def __init__(self, proxies: list[dict[str, Any]]):
        self._proxies = list(proxies)
        self._order = list(range(len(self._proxies)))
        random.shuffle(self._order)
        self._pos = 0

    def next(self) -> Optional[str]:
        """Return the next proxy URL in rotation, or ``None`` if the pool is empty.

        Returns:
            A ``http://{login}:{password}@{ip}:{port}`` URL, or ``None``.
        """
        if not self._proxies:
            return None
        p = self._proxies[self._order[self._pos % len(self._order)]]
        self._pos += 1
        return f"http://{p['login']}:{p['password']}@{p['ip']}:{p['port']}"


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
