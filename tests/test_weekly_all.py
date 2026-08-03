"""Multi-topic weekly runner: freshness planning + bounded concurrency.

Deterministic, no network, no LLM: the real pipeline body (fetch/eval) is
replaced by fakes; what is tested is the runner's own logic — which topics
count as stale, how plans map to per-topic outputs, and that at most
`workers` topics run at once with failures isolated.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
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


# weekly_selection FIRST: weekly_all imports it, so both tests must share the
# same module instance (monkeypatches would otherwise target a dead twin).
ws = _load_spike("weekly_selection")
wa = _load_spike("weekly_all")


def _payload(generated_at: str, topic: str = "Topic A", n_picks: int = 2) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "topic": topic,
        "slug": "00-topic-a",
        "picks": [{"url": f"https://a.example/{i}", "title": f"t{i}"} for i in range(n_picks)],
    }


def _topic(name: str) -> dict[str, Any]:
    return {"name": name, "description": "d", "in": "i", "out": "o", "sources": []}


NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


# --- freshness --------------------------------------------------------------


def test_is_topic_fresh_when_per_topic_picks_recent() -> None:
    per_topic = _payload((NOW - timedelta(hours=1)).isoformat())
    assert wa.is_topic_fresh("Topic A", per_topic, None, NOW, recency_days=7) is True


def test_is_topic_fresh_stale_when_older_than_window() -> None:
    per_topic = _payload((NOW - timedelta(days=8)).isoformat())
    assert wa.is_topic_fresh("Topic A", per_topic, None, NOW, recency_days=7) is False


def test_is_topic_fresh_boundary_is_stale() -> None:
    # Exactly RECENCY_DAYS old is NOT fresh (strictly inside the window counts).
    per_topic = _payload((NOW - timedelta(days=7)).isoformat())
    assert wa.is_topic_fresh("Topic A", per_topic, None, NOW, recency_days=7) is False


def test_is_topic_fresh_missing_payloads_stale() -> None:
    assert wa.is_topic_fresh("Topic A", None, None, NOW, recency_days=7) is False


def test_is_topic_fresh_legacy_fallback_matching_topic() -> None:
    # No per-topic file yet (pre-runner state): the legacy single-file counts
    # ONLY if its topic field matches this topic.
    legacy = _payload((NOW - timedelta(hours=2)).isoformat(), topic="Topic A")
    assert wa.is_topic_fresh("Topic A", None, legacy, NOW, recency_days=7) is True


def test_is_topic_fresh_legacy_other_topic_does_not_count() -> None:
    legacy = _payload((NOW - timedelta(hours=2)).isoformat(), topic="Topic B")
    assert wa.is_topic_fresh("Topic A", None, legacy, NOW, recency_days=7) is False


def test_is_topic_fresh_per_topic_wins_over_legacy() -> None:
    # A fresh per-topic file is fresh even if the legacy file is another topic's.
    per_topic = _payload((NOW - timedelta(hours=1)).isoformat())
    legacy = _payload((NOW - timedelta(hours=2)).isoformat(), topic="Topic B")
    assert wa.is_topic_fresh("Topic A", per_topic, legacy, NOW, recency_days=7) is True


def test_is_topic_fresh_naive_timestamp_treated_utc() -> None:
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    per_topic = _payload(naive.isoformat())
    assert wa.is_topic_fresh("Topic A", per_topic, None, NOW, recency_days=7) is True


def test_is_topic_fresh_malformed_timestamp_stale() -> None:
    per_topic = _payload("not-a-date")
    assert wa.is_topic_fresh("Topic A", per_topic, None, NOW, recency_days=7) is False


# --- planning ---------------------------------------------------------------


def _fake_loader(by_name: dict[str, tuple[Any, list[Any], str]]):
    """Loader returning canned (listing, sources, slug) per topic name."""

    def load(topic_name: str, discovery_dir: Path | None = None) -> tuple[Any, list[Any], str]:
        return by_name.get(topic_name, (None, [], ""))  # unknown -> no source list

    return load


def _plan(tmp_path: Path, topics: list[dict[str, Any]], loader: Any, legacy: dict[str, Any] | None = None):
    return wa.plan_runs(
        topics,
        discovery_dir=tmp_path / "discovery",
        picks_dir=tmp_path / "picks",
        legacy_picks_path=tmp_path / "weekly_picks.json" if legacy is not None else None,
        now=NOW,
        recency_days=7,
        load_list=loader,
        legacy_payload=legacy,
    )


def test_plan_runs_classifies_fresh_stale_and_no_list(tmp_path: Path) -> None:
    fresh_topic = _topic("Fresh Topic")
    stale_topic = _topic("Stale Topic")
    no_list_topic = _topic("No List Topic")
    (tmp_path / "picks").mkdir()
    (tmp_path / "picks" / "01-fresh.json").write_text(
        json.dumps(_payload((NOW - timedelta(hours=1)).isoformat())), encoding="utf-8"
    )
    loader = _fake_loader(
        {
            "Fresh Topic": ({"topic": "Fresh Topic"}, [{"name": "s"}], "01-fresh"),
            "Stale Topic": ({"topic": "Stale Topic"}, [{"name": "s"}], "02-stale"),
            # "No List Topic" absent -> loader returns (None, [], "")
        }
    )
    plan = _plan(tmp_path, [fresh_topic, stale_topic, no_list_topic], loader)

    assert plan.fresh == [("Fresh Topic", "01-fresh")]
    assert plan.no_list == ["No List Topic"]
    assert [spec.slug for spec in plan.to_run] == ["02-stale"]
    spec = plan.to_run[0]
    assert spec.topic is stale_topic
    assert spec.out.picks_path == tmp_path / "picks" / "02-stale.json"
    assert spec.out.legacy_picks_path is None  # multi-topic: never the single file


def test_plan_runs_legacy_file_makes_topic_fresh(tmp_path: Path) -> None:
    topic = _topic("Topic A")
    (tmp_path / "picks").mkdir()
    legacy = _payload((NOW - timedelta(hours=1)).isoformat(), topic="Topic A")
    loader = _fake_loader({"Topic A": ({"topic": "Topic A"}, [{"name": "s"}], "00-topic-a")})
    plan = _plan(tmp_path, [topic], loader, legacy=legacy)
    assert plan.fresh == [("Topic A", "00-topic-a")]
    assert plan.to_run == []


# --- execution --------------------------------------------------------------


def _recording_runner(results: list[tuple[str, str]], active: list[int], lock: threading.Lock, delay: float = 0.05):
    """Fake run_topic that records (slug, error) and tracks concurrent active."""

    def fake(topic, listing, sources, slug, out, *, limiter=None):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(delay)
            results.append((slug, ""))
            return {"picked": 1, "slug": slug}
        finally:
            with lock:
                active[0] -= 1

    peak = [0]
    return fake, peak


def _run_spec(slug: str, out: Any) -> Any:
    return wa.RunSpec(topic=_topic(slug), slug=slug, listing={"topic": slug}, sources=[], out=out)


def test_run_all_runs_every_stale_topic(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(3)], fresh=[], no_list=[])
    results: list[tuple[str, str]] = []
    active: list[int] = [0]
    lock = threading.Lock()
    fake, _peak = _recording_runner(results, active, lock)

    out_results = wa.run_all(plan, workers=3, run_topic_fn=fake)

    assert sorted(r.slug for r in out_results) == ["00", "01", "02"]
    assert all(r.ok for r in out_results)
    assert sorted(results) == [("00", ""), ("01", ""), ("02", "")]


def test_run_all_caps_concurrency_at_workers(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(6)], fresh=[], no_list=[])
    results: list[tuple[str, str]] = []
    active: list[int] = [0]
    lock = threading.Lock()
    fake, peak = _recording_runner(results, active, lock)

    wa.run_all(plan, workers=3, run_topic_fn=fake)
    assert peak[0] == 3  # never more than WEEKLY_WORKERS topics at once
    assert len(results) == 6  # …and none were starved


def test_run_all_workers_one_serializes(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(2)], fresh=[], no_list=[])
    results: list[tuple[str, str]] = []
    active: list[int] = [0]
    lock = threading.Lock()
    fake, peak = _recording_runner(results, active, lock)

    wa.run_all(plan, workers=1, run_topic_fn=fake)
    assert peak[0] == 1  # serialized: no overlap


def test_run_all_failure_isolated(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")

    def flaky(topic, listing, sources, slug, out, *, limiter=None):
        if slug == "01":
            raise RuntimeError("router exploded")
        return {"picked": 2, "slug": slug}

    plan = wa.Plan(to_run=[_run_spec("00", out), _run_spec("01", out), _run_spec("02", out)], fresh=[], no_list=[])
    out_results = wa.run_all(plan, workers=3, run_topic_fn=flaky)

    by_slug = {r.slug: r for r in out_results}
    assert by_slug["00"].ok and by_slug["02"].ok
    assert by_slug["01"].ok is False
    assert "router exploded" in by_slug["01"].error
    assert by_slug["01"].picked == 0


def test_run_all_empty_plan_no_calls(tmp_path: Path) -> None:
    plan = wa.Plan(to_run=[], fresh=[], no_list=[])
    called: list[str] = []

    def fake(topic, listing, sources, slug, out, *, limiter=None):
        called.append(slug)
        return {"picked": 0, "slug": slug}

    assert wa.run_all(plan, workers=3, run_topic_fn=fake) == []
    assert called == []
