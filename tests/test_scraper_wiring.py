"""Contract tests for the objects `scrape_raw_json.main()` wires together.

These exist because a module swap left an incompatible consumer behind and
nothing caught it until a live backfill crashed two seasons in:

    AttributeError: 'ProxyHealth' object has no attribute 'pool_size'

`proxy.ProxyHealth` (time-based quarantine, JSONL error log) replaced the older
`observability.ProxyHealth` (consecutive-failure counter), but
`observability.Degradation` still consumed the old attribute. Everything
imported fine and 68 unit tests passed -- the mismatch only surfaced on the
first call, inside a loop that runs after a season's games are fetched.

`main()` is hard to unit test (it needs a proxy pool and the network), so these
assert the API SURFACE instead: every attribute the scraper reads off these
objects must actually exist on them.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from sportsdataverse.scrape.stats.proxy import ProxyHealth, RoundRobin

SCRAPER = Path(__file__).resolve().parent.parent / "python" / "scrape_raw_json.py"
SOURCE = SCRAPER.read_text(encoding="utf-8")


def _attrs_used(source: str, receiver: str) -> set[str]:
    """Attribute names read off `receiver` anywhere in `source`."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == receiver
        ):
            found.add(node.attr)
    return found


def test_every_proxyhealth_attribute_the_scraper_uses_exists() -> None:
    used = _attrs_used(SOURCE, "health")
    assert used, "expected the scraper to use the health object"
    missing = sorted(a for a in used if not hasattr(ProxyHealth, a))
    assert not missing, f"scrape_raw_json calls health.{missing} which ProxyHealth lacks"


def test_every_roundrobin_attribute_the_scraper_uses_exists() -> None:
    used = _attrs_used(SOURCE, "rr")
    missing = sorted(a for a in used if not hasattr(RoundRobin, a))
    assert not missing, f"scrape_raw_json calls rr.{missing} which RoundRobin lacks"


def test_snapshot_exposes_the_keys_the_scraper_reads() -> None:
    """The scraper indexes snapshot() by literal key; a rename would KeyError
    at runtime rather than at import."""
    snap = ProxyHealth(error_log=None).snapshot()
    for key in ("cat", "quar", "worst"):
        assert key in snap, f"snapshot() must expose {key!r}"
    for cat in ("ok", "blank", "notfound", "blocked", "server_err", "transport_err"):
        assert cat in snap["cat"], f"snapshot()['cat'] must expose {cat!r}"


def test_the_retired_degradation_consumer_is_gone() -> None:
    """observability.Degradation is coupled to the OLD ProxyHealth (pool_size).
    The NBA sibling dropped the shared observability import entirely (its own
    inline heartbeat plays the same role), so this only fires for a twin that
    DOES import observability -- only that shape can reintroduce the crash."""
    imported = re.findall(r"from \S*observability import ([^\n]+)", SOURCE)
    assert not any("Degradation" in line for line in imported), (
        "Degradation consumes the retired ProxyHealth API -- use health.snapshot() instead"
    )


@pytest.mark.parametrize("name", ["record", "snapshot", "endpoint_summary", "close"])
def test_proxyhealth_core_methods_are_callable(name: str) -> None:
    assert callable(getattr(ProxyHealth, name))
