"""Weekly selection: per-topic picks accumulate across runs (additive feeds).

Contract (user spec): running the selection a second time on a topic must keep
the first batch of items in the feed alongside the second batch — the feed
grows, it never gets replaced. The accumulation is `merge_picks`, a pure
helper (no I/O): previous batch preserved in order, new batch appended,
deduped by URL.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_spike(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "spikes" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spike {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses + cross-spike imports need registration
    spec.loader.exec_module(mod)
    return mod


ws = _load_spike("weekly_selection")


def _pick(url: str, title: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "source": "Fake Feed",
        "domain": "a.example",
        "subarea": "Capex",
        "reason": "why relevant",
        "thesis": "thesis",
        "empirical_event": "event",
        "picked_at": "2026-08-03T00:00:00+00:00",
    }


def test_merge_picks_keeps_first_batch_when_second_batch_added() -> None:
    """A second run's picks extend the feed — the first batch is preserved."""
    batch1 = [_pick("https://a/1", "First batch story"), _pick("https://a/2", "Another first batch")]
    batch2 = [_pick("https://b/1", "Second batch story")]
    merged = ws.merge_picks(batch1, batch2)
    assert [p["url"] for p in merged] == ["https://a/1", "https://a/2", "https://b/1"]
    assert merged[0]["title"] == "First batch story"  # first batch intact, in order


def test_merge_picks_dedups_by_url_keeping_first() -> None:
    """A URL appearing in both batches is kept once — the earlier pick wins."""
    batch1 = [_pick("https://a/1", "Original title")]
    batch2 = [_pick("https://a/1", "Re-picked title"), _pick("https://b/2", "Brand new")]
    merged = ws.merge_picks(batch1, batch2)
    assert [p["url"] for p in merged] == ["https://a/1", "https://b/2"]
    assert merged[0]["title"] == "Original title"


def test_merge_picks_first_run_no_previous() -> None:
    batch = [_pick("https://a/1", "Only story")]
    assert ws.merge_picks([], batch) == batch
    assert ws.merge_picks(None, batch) == batch


def test_merge_picks_second_run_zero_new_keeps_feed() -> None:
    """A second run that picks nothing new must NOT blank the feed."""
    batch1 = [_pick("https://a/1", "Only story")]
    assert ws.merge_picks(batch1, []) == batch1


def test_merge_picks_does_not_mutate_inputs() -> None:
    batch1 = [_pick("https://a/1", "One")]
    batch2 = [_pick("https://b/1", "Two")]
    _ = ws.merge_picks(batch1, batch2)
    assert [p["url"] for p in batch1] == ["https://a/1"]
    assert [p["url"] for p in batch2] == ["https://b/1"]
