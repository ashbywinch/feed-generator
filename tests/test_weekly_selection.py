"""Weekly selection: per-topic picks accumulate across runs (additive feeds).

Contract (user spec): running the selection a second time on a topic must keep
the first batch of items in the feed alongside the second batch — the feed
grows, it never gets replaced. The accumulation is `merge_picks`, a pure
helper (no I/O): previous batch preserved in order, new batch appended,
deduped by URL.
"""

from __future__ import annotations

import importlib.util
import json
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


def _pick(url: str, title: str, picked_at: str = "2026-08-03T00:00:00+00:00") -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "source": "Fake Feed",
        "domain": "a.example",
        "subarea": "Capex",
        "reason": "why relevant",
        "thesis": "thesis",
        "empirical_event": "event",
        "picked_at": picked_at,
    }


def test_merge_picks_orders_newest_batch_first() -> None:
    """The accumulated list is newest-first: a second run's picks appear ABOVE
    the first run's (new articles surface at the top of the feed + front page)."""
    batch1 = [
        _pick("https://a/1", "First batch story", picked_at="2026-08-03T00:00:00+00:00"),
        _pick("https://a/2", "Another first batch", picked_at="2026-08-03T00:00:00+00:00"),
    ]
    batch2 = [_pick("https://b/1", "Second batch story", picked_at="2026-08-05T00:00:00+00:00")]
    merged = ws.merge_picks(batch1, batch2)
    assert [p["url"] for p in merged] == ["https://b/1", "https://a/1", "https://a/2"]  # newest first
    assert merged[0]["title"] == "Second batch story"
    assert {p["title"] for p in merged} == {
        "First batch story",
        "Another first batch",
        "Second batch story",
    }  # nothing dropped


def test_merge_picks_dedups_by_url_newer_wins() -> None:
    """A URL in both batches appears once — the newer pick (first in the
    newest-first order) wins."""
    batch1 = [_pick("https://a/1", "Original title", picked_at="2026-08-03T00:00:00+00:00")]
    batch2 = [
        _pick("https://a/1", "Re-picked title", picked_at="2026-08-05T00:00:00+00:00"),
        _pick("https://b/2", "Brand new", picked_at="2026-08-05T00:00:00+00:00"),
    ]
    merged = ws.merge_picks(batch1, batch2)
    assert [p["url"] for p in merged] == ["https://a/1", "https://b/2"]
    assert merged[0]["title"] == "Re-picked title"  # newer pick wins


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


# --- run_topic with an injected fake LLM (llm_factory seam) ------------------


class _FakeLLM:
    """chat_json returns canned responses in call order — no network, no keys."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat_json(self, prompt: str, max_tokens: int | None = None) -> dict[str, Any]:
        self.calls += 1
        assert self._responses, f"unexpected LLM call: {prompt[:80]}"
        return self._responses.pop(0)


class _NoopLimiter:
    def wait(self) -> None:
        pass


def _topic(name: str = "Test Topic") -> dict[str, Any]:
    return {"name": name, "description": "d", "in": "i", "out": "o", "sources": []}


def _story() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": "2026-08-03T00:00:00+00:00",
        "overview": "o",
        "angles": {"Capex": ["background"]},
        "open_questions": [],
        "pending": [],
    }


def _source(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "Fake Feed",
        "domain": "a.example",
        "crawl_root": "https://a.example/feed",
        "subarea": "Capex",
        "items": items,
        "cached": {"items": items, "fetched_at": "2026-08-05T00:00:00+00:00"},
    }


def _item(url: str, title: str) -> dict[str, Any]:
    return {"url": url, "title": title, "summary": "s", "published": "2026-08-05T00:00:00+00:00", "undated": False}


def _verdicts(*urls: str) -> dict[str, Any]:
    return {
        "verdicts": [{"url": u, "approved": True, "reason": "why", "thesis": "t", "empirical_event": "e"} for u in urls]
    }


def test_run_topic_second_run_accumulates_picks_with_fake_llm(tmp_path: Path) -> None:
    """Real run_topic + fake LLM (llm_factory seam): running twice on the same
    topic keeps batch 1 in the picks file alongside batch 2 — additive feeds,
    no network."""
    out = ws.TopicOut(
        picks_path=tmp_path / "picks.json",
        report_path=tmp_path / "report.md",
        story_md_path=tmp_path / "story.md",
    )
    batches = iter(
        [
            _source([_item("https://a/1", "First batch story")]),
            _source([_item("https://b/1", "Second batch story")]),
        ]
    )
    llm = _FakeLLM([_verdicts("https://a/1"), _verdicts("https://b/1")])

    def fake_fetch(source):
        batch = next(batches)
        source.clear()
        source.update(batch)  # real fetch_feed mutates in place — the sources list holds the same object
        return source

    for _ in range(2):
        ws.run_topic(
            _topic(),
            {"subareas": []},
            [_source([])],  # real items come from the fake fetch_feed_fn
            slug="02-test",
            out=out,
            limiter=_NoopLimiter(),
            feeds_path=tmp_path / "feeds.jsonl",
            verdicts_path=tmp_path / "verdicts.jsonl",
            picks_history_path=tmp_path / "history.jsonl",
            load_feeds_fn=lambda: {},
            load_verdicts_fn=lambda *a, **k: {},
            load_picked_urls_fn=lambda: set(),
            load_story_fn=lambda slug: _story(),  # pre-seeded: no story-seed LLM call
            save_story_fn=lambda slug, story: None,
            fold_story_fn=lambda *a, **k: False,
            fetch_feed_fn=fake_fetch,
            llm_factory=lambda cfg: llm,
        )

    payload = json.loads(out.picks_path.read_text(encoding="utf-8"))
    assert [p["title"] for p in payload["picks"]] == ["Second batch story", "First batch story"]  # newest first
    assert llm.calls == 2  # exactly one evaluation per run — the seam kept the network out
