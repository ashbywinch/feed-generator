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


def _plan(
    tmp_path: Path,
    topics: list[dict[str, Any]],
    loader: Any,
    legacy: dict[str, Any] | None = None,
    weekly_topics: list[str] | None = None,
):
    return wa.plan_runs(
        topics,
        discovery_dir=tmp_path / "discovery",
        picks_dir=tmp_path / "picks",
        legacy_picks_path=tmp_path / "weekly_picks.json" if legacy is not None else None,
        now=NOW,
        recency_days=7,
        load_list=loader,
        legacy_payload=legacy,
        weekly_topics=weekly_topics,
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
    assert [spec.slug for spec in plan.to_run] == ["02-stale", "03-no-list-topic"]
    stale, no_list = plan.to_run
    assert stale.topic is stale_topic
    assert stale.needs_sources is False
    assert stale.out.picks_path == tmp_path / "picks" / "02-stale.json"
    assert stale.out.legacy_picks_path is None  # multi-topic: never the single file
    # No discovery list: still queued — sources are generated before selection.
    assert no_list.topic is no_list_topic
    assert no_list.needs_sources is True
    assert no_list.slug == "03-no-list-topic"  # slug_for numbering matches persist()
    assert no_list.out.picks_path == tmp_path / "picks" / "03-no-list-topic.json"


def test_plan_runs_legacy_file_makes_topic_fresh(tmp_path: Path) -> None:
    topic = _topic("Topic A")
    (tmp_path / "picks").mkdir()
    legacy = _payload((NOW - timedelta(hours=1)).isoformat(), topic="Topic A")
    loader = _fake_loader({"Topic A": ({"topic": "Topic A"}, [{"name": "s"}], "00-topic-a")})
    plan = _plan(tmp_path, [topic], loader, legacy=legacy)
    assert plan.fresh == [("Topic A", "00-topic-a")]
    assert plan.to_run == []


# --- WEEKLY_TOPICS: run only tonight's rotation subset ----------------------


def test_plan_runs_filters_to_weekly_topics(tmp_path: Path) -> None:
    (tmp_path / "picks").mkdir()
    topics = [_topic("Alpha"), _topic("Bravo"), _topic("Charlie")]
    loader = _fake_loader(
        {
            "Alpha": ({"topic": "Alpha"}, [{"name": "s"}], "01-alpha"),
            "Bravo": ({"topic": "Bravo"}, [{"name": "s"}], "02-bravo"),
            "Charlie": ({"topic": "Charlie"}, [{"name": "s"}], "03-charlie"),
        }
    )
    plan = _plan(tmp_path, topics, loader, weekly_topics=["Alpha", "Charlie"])
    assert [s.slug for s in plan.to_run] == ["01-alpha", "03-charlie"]
    assert plan.fresh == []


def test_plan_runs_weekly_topics_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "picks").mkdir()
    loader = _fake_loader({"Alpha": ({"topic": "Alpha"}, [{"name": "s"}], "01-alpha")})
    plan = _plan(tmp_path, [_topic("Alpha")], loader, weekly_topics=["alpha"])
    assert [s.slug for s in plan.to_run] == ["01-alpha"]


def test_plan_runs_weekly_topics_empty_subset_runs_nothing(tmp_path: Path) -> None:
    (tmp_path / "picks").mkdir()
    loader = _fake_loader({"Alpha": ({"topic": "Alpha"}, [{"name": "s"}], "01-alpha")})
    plan = _plan(tmp_path, [_topic("Alpha")], loader, weekly_topics=[])
    assert plan.to_run == [] and plan.fresh == []


# --- execution --------------------------------------------------------------


def _recording_runner(results: list[tuple[str, str]], active: list[int], lock: threading.Lock, delay: float = 0.05):
    """Fake run_topic that records (slug, error) and tracks concurrent active."""

    def fake(topic, listing, sources, slug, out, *, limiter=None, **kwargs):
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
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(3)], fresh=[])
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
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(6)], fresh=[])
    results: list[tuple[str, str]] = []
    active: list[int] = [0]
    lock = threading.Lock()
    fake, peak = _recording_runner(results, active, lock)

    wa.run_all(plan, workers=3, run_topic_fn=fake)
    assert peak[0] == 3  # never more than WEEKLY_WORKERS topics at once
    assert len(results) == 6  # …and none were starved


def test_run_all_workers_one_serializes(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")
    plan = wa.Plan(to_run=[_run_spec(f"0{i}", out) for i in range(2)], fresh=[])
    results: list[tuple[str, str]] = []
    active: list[int] = [0]
    lock = threading.Lock()
    fake, peak = _recording_runner(results, active, lock)

    wa.run_all(plan, workers=1, run_topic_fn=fake)
    assert peak[0] == 1  # serialized: no overlap


def test_run_all_failure_isolated(tmp_path: Path) -> None:
    out = ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")

    def flaky(topic, listing, sources, slug, out, *, limiter=None, **kwargs):
        if slug == "01":
            raise RuntimeError("router exploded")
        return {"picked": 2, "slug": slug}

    plan = wa.Plan(to_run=[_run_spec("00", out), _run_spec("01", out), _run_spec("02", out)], fresh=[])
    out_results = wa.run_all(plan, workers=3, run_topic_fn=flaky)

    by_slug = {r.slug: r for r in out_results}
    assert by_slug["00"].ok and by_slug["02"].ok
    assert by_slug["01"].ok is False
    assert "router exploded" in by_slug["01"].error
    assert by_slug["01"].picked == 0


def test_run_all_empty_plan_no_calls(tmp_path: Path) -> None:
    plan = wa.Plan(to_run=[], fresh=[])
    called: list[str] = []

    def fake(topic, listing, sources, slug, out, *, limiter=None, **kwargs):
        called.append(slug)
        return {"picked": 0, "slug": slug}

    assert wa.run_all(plan, workers=3, run_topic_fn=fake) == []
    assert called == []


def test_ensure_per_topic_picks_materializes_legacy_with_slug(tmp_path: Path) -> None:
    """A topic fresh via the legacy single-file gets a per-topic picks file, so
    the feed builder (and the next freshness check) sees it without a re-run."""
    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    legacy = tmp_path / "weekly_picks.json"
    legacy.write_text(
        json.dumps(_payload((NOW - timedelta(hours=1)).isoformat(), topic="Topic A")),  # no slug field (pre-runner)
        encoding="utf-8",
    )
    assert wa.ensure_per_topic_picks("Topic A", "00-topic-a", picks_dir, legacy) is True
    written = json.loads((picks_dir / "00-topic-a.json").read_text(encoding="utf-8"))
    assert written["slug"] == "00-topic-a"
    assert written["topic"] == "Topic A"
    assert len(written["picks"]) == 2


def test_ensure_per_topic_picks_skips_when_already_present(tmp_path: Path) -> None:
    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    (picks_dir / "00-topic-a.json").write_text(json.dumps({"slug": "00-topic-a", "picks": []}), encoding="utf-8")
    legacy = tmp_path / "weekly_picks.json"
    legacy.write_text(json.dumps(_payload(NOW.isoformat(), topic="Topic A")), encoding="utf-8")
    assert wa.ensure_per_topic_picks("Topic A", "00-topic-a", picks_dir, legacy) is False
    assert json.loads((picks_dir / "00-topic-a.json").read_text(encoding="utf-8"))["picks"] == []  # untouched


def test_ensure_per_topic_picks_ignores_other_topics_legacy(tmp_path: Path) -> None:
    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    legacy = tmp_path / "weekly_picks.json"
    legacy.write_text(json.dumps(_payload(NOW.isoformat(), topic="Topic B")), encoding="utf-8")
    assert wa.ensure_per_topic_picks("Topic A", "00-topic-a", picks_dir, legacy) is False
    assert not (picks_dir / "00-topic-a.json").exists()


# --- source generation for topics without discovery lists -------------------


def _out(tmp_path: Path) -> Any:
    return ws.TopicOut(picks_path=tmp_path / "p.json", report_path=tmp_path / "r.md", story_md_path=tmp_path / "s.md")


def test_run_all_generates_sources_before_selecting(tmp_path: Path) -> None:
    """A topic without a discovery list gets sources generated, then the fresh
    listing (reloaded from disk) is selected — in order, in the same worker."""
    calls: list[str] = []
    topic = _topic("No List Topic")

    def fake_generate(t: dict[str, Any], **kwargs) -> tuple[bool, int]:
        calls.append(f"generate:{t['name']}")
        return True, 3  # approved after 3 iterations

    def fake_load(topic_name: str, discovery_dir: Path | None = None) -> tuple[Any, list[Any], str]:
        if topic_name == "No List Topic":
            return {"topic": topic_name, "subareas": []}, [{"name": "s"}], "03-no-list-topic"
        return None, [], ""

    def fake_run(t, listing, sources, slug, out, *, limiter=None, **kwargs):
        calls.append(f"select:{slug}:{bool(listing)}:{len(sources)}")
        return {"picked": 4, "slug": slug}

    plan = wa.Plan(
        to_run=[
            wa.RunSpec(
                topic=topic,
                slug="03-no-list-topic",
                listing={},
                sources=[],
                out=_out(tmp_path),
                needs_sources=True,
            )
        ],
        fresh=[],
    )
    results = wa.run_all(plan, workers=1, run_topic_fn=fake_run, generate_fn=fake_generate, load_list_fn=fake_load)

    (result,) = results
    assert result.ok and result.generated_sources is True and result.sources_approved is True
    assert result.picked == 4
    # generation ran, THEN selection with the RELOADED (non-empty) listing
    assert calls == ["generate:No List Topic", "select:03-no-list-topic:True:1"]


def test_run_all_generation_failure_isolated(tmp_path: Path) -> None:
    """One topic's source generation failing must not kill the batch."""
    good = _topic("Good Topic")
    bad = _topic("Bad Topic")

    def fake_generate(t: dict[str, Any], **kwargs) -> tuple[bool, int]:
        if t["name"] == "Bad Topic":
            raise RuntimeError("EXA_API_KEY missing")
        return True, 1

    def fake_run(t, listing, sources, slug, out, *, limiter=None, **kwargs):
        return {"picked": 2, "slug": slug}

    def fake_load(topic_name: str, discovery_dir: Path | None = None) -> tuple[Any, list[Any], str]:
        return {"topic": topic_name}, [{"name": "s"}], "x"

    plan = wa.Plan(
        to_run=[
            wa.RunSpec(topic=bad, slug="01-bad", listing={}, sources=[], out=_out(tmp_path), needs_sources=True),
            wa.RunSpec(topic=good, slug="02-good", listing={}, sources=[], out=_out(tmp_path), needs_sources=True),
        ],
        fresh=[],
    )
    results = {
        r.slug: r
        for r in wa.run_all(plan, workers=2, run_topic_fn=fake_run, generate_fn=fake_generate, load_list_fn=fake_load)
    }

    assert results["01-bad"].ok is False and "EXA_API_KEY" in results["01-bad"].error
    assert results["02-good"].ok is True and results["02-good"].picked == 2


def test_run_all_generation_without_usable_list_fails(tmp_path: Path) -> None:
    """Generation 'succeeds' but no list appears on disk -> the topic fails,
    it must not select against an empty listing."""

    def fake_generate(t: dict[str, Any], **kwargs) -> tuple[bool, int]:
        return False, 6  # never approved

    ran: list[str] = []

    def fake_run(t, listing, sources, slug, out, *, limiter=None, **kwargs):
        ran.append(slug)
        return {"picked": 0, "slug": slug}

    def fake_load(topic_name: str, discovery_dir: Path | None = None) -> tuple[Any, list[Any], str]:
        return None, [], ""  # nothing persisted

    plan = wa.Plan(
        to_run=[
            wa.RunSpec(
                topic=_topic("X"),
                slug="03-x",
                listing={},
                sources=[],
                out=_out(tmp_path),
                needs_sources=True,
            )
        ],
        fresh=[],
    )
    (result,) = wa.run_all(plan, workers=1, run_topic_fn=fake_run, generate_fn=fake_generate, load_list_fn=fake_load)

    assert result.ok is False
    assert "no usable list" in result.error
    assert ran == []  # selection never ran against an empty listing


def test_run_all_retries_generation_once_then_selects(tmp_path: Path) -> None:
    """A stochastic generation failure (router error, non-JSON prose) gets ONE
    immediate retry; on success the topic proceeds to selection normally."""
    attempts: list[str] = []
    ran: list[str] = []

    def flaky_generate(t: dict[str, Any], **kwargs) -> tuple[bool, int]:
        attempts.append(t["name"])
        if len(attempts) == 1:
            raise RuntimeError("router 400: label empty or too long")  # transient
        return True, 2

    def fake_run(t, listing, sources, slug, out, *, limiter=None, **kwargs):
        ran.append(slug)
        return {"picked": 3, "slug": slug}

    def fake_load(topic_name: str, discovery_dir: Path | None = None) -> tuple[Any, list[Any], str]:
        return {"topic": topic_name}, [{"name": "s"}], "03-x"

    plan = wa.Plan(
        to_run=[
            wa.RunSpec(
                topic=_topic("X"),
                slug="03-x",
                listing={},
                sources=[],
                out=_out(tmp_path),
                needs_sources=True,
            )
        ],
        fresh=[],
    )
    (result,) = wa.run_all(plan, workers=1, run_topic_fn=fake_run, generate_fn=flaky_generate, load_list_fn=fake_load)

    assert len(attempts) == 2  # exactly one retry
    assert result.ok and result.generated_sources and result.picked == 3
    assert ran == ["03-x"]


def test_run_all_generation_fails_after_retry(tmp_path: Path) -> None:
    """A persistently failing generation is NOT retried forever: two attempts
    total, then the topic fails and the batch continues."""
    attempts: list[str] = []

    def always_fail(t: dict[str, Any], **kwargs) -> tuple[bool, int]:
        attempts.append(t["name"])
        raise RuntimeError("EXA_API_KEY missing")

    plan = wa.Plan(
        to_run=[
            wa.RunSpec(
                topic=_topic("X"),
                slug="03-x",
                listing={},
                sources=[],
                out=_out(tmp_path),
                needs_sources=True,
            )
        ],
        fresh=[],
    )
    (result,) = wa.run_all(plan, workers=1, run_topic_fn=lambda *a, **k: None, generate_fn=always_fail)

    assert len(attempts) == 2  # bounded retry, not a loop
    assert result.ok is False
    assert "EXA_API_KEY" in result.error


def test_run_all_redacts_keys_from_error_and_traceback(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """Exception messages can embed API keys (the codebase's LLM._redact exists
    because of it) — both the RunResult error and the logged traceback must be
    redacted, not just the traceback."""

    def boom(t, listing, sources, slug, out, *, limiter=None, **kwargs):
        raise RuntimeError("router rejected sekrit-key-abc")

    monkeypatch.setattr(wa, "LLM_KEY", "sekrit-key-abc")
    plan = wa.Plan(
        to_run=[wa.RunSpec(topic=_topic("X"), slug="03-x", listing={}, sources=[], out=_out(tmp_path))],
        fresh=[],
    )
    (result,) = wa.run_all(plan, workers=1, run_topic_fn=boom)

    assert "sekrit-key-abc" not in result.error
    assert "sekrit-key-abc" not in capsys.readouterr().out  # logged traceback redacted too


def test_require_opml_if_generating(tmp_path: Path) -> None:
    """Source-list generation parses feedly.opml for the exclusion set — a
    missing OPML must abort once as a setup error, not fail N topics inside
    workers (FR-1 fail-fast)."""
    gen = wa.Plan(
        to_run=[
            wa.RunSpec(
                topic=_topic("X"),
                slug="03-x",
                listing={},
                sources=[],
                out=_out(tmp_path),
                needs_sources=True,
            )
        ],
        fresh=[],
    )
    no_gen = wa.Plan(
        to_run=[wa.RunSpec(topic=_topic("Y"), slug="01-y", listing={}, sources=[], out=_out(tmp_path))],
        fresh=[],
    )
    opml = tmp_path / "feedly.opml"
    msg = wa.require_opml_if_generating(gen, opml)
    assert msg is not None and "feedly.opml" in msg
    opml.write_text("<?xml version='1.0'?><opml/>", encoding="utf-8")
    assert wa.require_opml_if_generating(gen, opml) is None
    assert wa.require_opml_if_generating(no_gen, tmp_path / "missing.opml") is None  # no generation: no need
