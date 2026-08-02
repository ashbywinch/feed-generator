"""Deterministic unit tests for spike-pipeline behaviors (no network/LLM).

The weekly-selection pipeline and its eval gates live in spikes/ (type/lint
gated, runnable via make spike-weekly / eval-story / eval-queries). These tests
pin the pure-logic behaviors — window slot reservation, malformed-LLM-output
handling, and the small-sample pass threshold — without calling any API.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_spike(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "spikes" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spike {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ws = _load_spike("weekly_selection")


# --- weekly_selection: parse_bool strictness (round-1 fix) ------------------


def test_parse_bool_is_strict() -> None:
    """bool("false") was True — a model emitting the string 'false' must reject."""
    assert ws.parse_bool(True) is True
    assert ws.parse_bool("true") is True
    assert ws.parse_bool("yes") is True
    assert ws.parse_bool("1") is True
    assert ws.parse_bool(False) is False
    assert ws.parse_bool("false") is False  # the round-1 bug
    assert ws.parse_bool("no") is False
    assert ws.parse_bool("0") is False
    assert ws.parse_bool("") is False
    assert ws.parse_bool(None) is False
    assert ws.parse_bool(1) is False  # JSON booleans are bool, not int


# --- weekly_selection: verdict cache is namespaced by topic slug (r4) -------


def test_load_verdicts_filters_by_slug(tmp_path: Any, monkeypatch: Any) -> None:
    """Same URL judged under topic A must not replay under topic B."""
    cache = tmp_path / "weekly_verdicts.jsonl"
    cache.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "key": "a|sub|https://x/1",
                        "slug": "a",
                        "rev": ws.PROMPT_REV,
                        "story_ver": 1,
                        "url": "https://x/1",
                    }
                ),
                json.dumps(
                    {
                        "key": "b|sub|https://x/1",
                        "slug": "b",
                        "rev": ws.PROMPT_REV,
                        "story_ver": 1,
                        "url": "https://x/1",
                    }
                ),
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(ws, "VERDICTS_PATH", cache)
    got = ws.load_verdicts(story_version=1, slug="a")
    assert set(got) == {"a|sub|https://x/1"}  # topic B's verdict must not leak in


def test_load_verdicts_filters_by_rev_and_story_version(tmp_path: Any, monkeypatch: Any) -> None:
    """Stale prompt-rev and stale story-version verdicts are never reused."""
    cache = tmp_path / "weekly_verdicts.jsonl"
    cache.write_text(
        "\n".join(
            [
                json.dumps({"key": "a|s|u", "slug": "a", "rev": ws.PROMPT_REV, "story_ver": 1, "url": "u"}),
                json.dumps(
                    {"key": "a|s|u2", "slug": "a", "rev": ws.PROMPT_REV - 1, "story_ver": 1, "url": "u2"}
                ),  # stale rev
                json.dumps(
                    {"key": "a|s|u3", "slug": "a", "rev": ws.PROMPT_REV, "story_ver": 0, "url": "u3"}
                ),  # stale story
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(ws, "VERDICTS_PATH", cache)
    got = ws.load_verdicts(story_version=1, slug="a")
    assert set(got) == {"a|s|u"}  # only the current-rev + current-story verdict survives


# --- weekly_selection: fold_story guards malformed output (r6) --------------


def test_fold_story_handles_non_dict_output() -> None:
    """Non-dict LLM output must return False (pending kept), not crash."""

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            return "not a dict"

    class Limiter:
        def wait(self) -> None:
            pass

    story = {
        "version": 1,
        "updated_at": "",
        "overview": "o",
        "angles": {"s": ["a"]},
        "open_questions": ["q"],
        "pending": [],
    }
    ok = ws.fold_story(
        story,
        [{"url": "https://x/1", "title": "T", "subarea": "s"}],
        {"name": "T", "in": "i", "out": "o"},
        BoomLLM(),
        Limiter(),
    )
    assert ok is False  # caller keeps pending for retry
    assert story["version"] == 1  # unchanged


def test_fold_story_handles_router_exception() -> None:
    """A router error must return False (pending kept), not crash the run."""

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            raise RuntimeError("router timeout")

    class Limiter:
        def wait(self) -> None:
            pass

    story = {
        "version": 1,
        "updated_at": "",
        "overview": "o",
        "angles": {"s": ["a"]},
        "open_questions": ["q"],
        "pending": [],
    }
    ok = ws.fold_story(
        story,
        [{"url": "https://x/1", "title": "T", "subarea": "s"}],
        {"name": "T", "in": "i", "out": "o"},
        BoomLLM(),
        Limiter(),
    )
    assert ok is False
    assert story["version"] == 1


# --- weekly_selection: approved verdicts missing empirical_event demote (r3/r4) --


def test_evaluate_source_demotes_approved_without_empirical_event() -> None:
    """An approved pick with an empty Observed Event must not reach the digest."""

    class StubLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {
                    "verdicts": [
                        {"url": "https://x/1", "approved": True, "reason": "", "thesis": "t", "empirical_event": ""}
                    ]
                }
            # retry (missing-verdict path won't fire; event-retry fires and returns the event)
            return {
                "verdicts": [
                    {
                        "url": "https://x/1",
                        "approved": True,
                        "reason": "",
                        "thesis": "t",
                        "empirical_event": "the event",
                    }
                ]
            }

    class Limiter:
        def wait(self) -> None:
            pass

    source = {"name": "S", "subarea": "sub", "subareas": ["sub"]}
    topic = {"name": "T", "description": "d", "in": "i", "out": "o"}
    llm = StubLLM()
    verdicts = ws.evaluate_source(
        source, [{"url": "https://x/1", "title": "T", "summary": "s"}], topic, llm, Limiter(), ""
    )
    assert verdicts[0]["approved"] is True
    assert verdicts[0]["empirical_event"] == "the event"  # retried sentence filled in


def test_evaluate_source_still_missing_event_demotes() -> None:
    """If the retry also omits empirical_event, the pick is rejected."""

    class StubLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {
                "verdicts": [
                    {"url": "https://x/1", "approved": True, "reason": "", "thesis": "t", "empirical_event": ""}
                ]
            }

    class Limiter:
        def wait(self) -> None:
            pass

    source = {"name": "S", "subarea": "sub", "subareas": ["sub"]}
    topic = {"name": "T", "description": "d", "in": "i", "out": "o"}
    llm = StubLLM()
    verdicts = ws.evaluate_source(
        source, [{"url": "https://x/1", "title": "T", "summary": "s"}], topic, llm, Limiter(), ""
    )
    assert verdicts[0]["approved"] is False  # demoted: a digest bullet must not be empty


# --- weekly_selection: report renders eval_error distinctly (r4) -----------


def test_render_report_surfaces_eval_error() -> None:
    """An evaluation failure must not be conflated with a valid zero-pick source."""
    summary = {
        "topic": "T",
        "generated_at": "2026-08-02",
        "recency_days": 7,
        "sources_total": 1,
        "sources_ok": 0,
        "sources_failed": 0,
        "cache_reuse": 0,
        "items_window": 5,
        "items_undated": 0,
        "items_new": 5,
        "items_cached": 0,
        "picked": 0,
        "zero_pick_sources": 0,
        "story_version": 1,
        "story_updated": "2026-08-02",
    }
    sections = [
        {
            "source": "S",
            "domain": "x.com",
            "subarea": "sub",
            "fetch_error": "",
            "eval_error": "router timeout",
            "stale": False,
            "n_items": 5,
            "n_picked": 0,
            "picks": [],
        }
    ]
    report = ws.render_report(summary, sections)
    assert "evaluation failed" in report
    assert "router timeout" in report
    assert "0 picked — nothing worth surfacing" not in report  # distinct branch


# --- weekly_selection: undated items get reserved cap slots -----------------


def test_window_reserves_slots_for_undated_items() -> None:
    """Undated items sort last and would be cut by the cap; slots are reserved."""
    cap = 30
    items = [
        {
            "url": f"https://x.example/{i:03d}",
            "title": f"A{i:03d}",
            "published": f"2026-07-{1 + i % 28:02d}T00:00:00+00:00",
            "undated": False,
        }
        for i in range(1, cap + 10)  # more dated items than the cap
    ] + [
        {"url": f"https://x.example/undated-{i}", "title": f"U{i}", "published": None, "undated": True}
        for i in range(1, 6)
    ]
    out = ws.window_items(items, cap)
    assert len(out) == cap
    reserved = min(5, max(1, cap // 5))
    assert sum(1 for it in out if it.get("undated")) == reserved  # all reserved slots taken
    assert all(str(it.get("title")).startswith("U") for it in out if it.get("undated"))


# --- eval_queries: token derivation + geo anchors (r7/r8) -------------------


def test_subarea_tokens_singular_plural_variants() -> None:
    eq = _load_spike("eval_queries")
    # "batteries" must match a query containing "battery" (and vice versa)
    tokens = eq.subarea_tokens("Grid-scale batteries & storage")
    assert "battery" in tokens and "batteries" in tokens
    # acronyms keep their exact spelling
    tokens = eq.subarea_tokens("Storage beyond lithium-ion (CAES, thermal, gravity, flow)")
    assert "caes" in tokens


def test_geo_anchors_catch_uk_variants() -> None:
    eq = _load_spike("eval_queries")
    assert eq.GEO_ANCHORS.search("UK CfD allocation round") is not None
    assert eq.GEO_ANCHORS.search("U.K. CfD allocation round") is not None  # was dead-code (r8)
    assert eq.GEO_ANCHORS.search("GB grid connection queues") is not None
    assert eq.GEO_ANCHORS.search("grid connection queues") is None  # global: not flagged


def test_coverage_check_requires_token_match() -> None:
    eq = _load_spike("eval_queries")
    queries = ["grid-scale battery storage revenue streams"]
    assert eq.coverage_check(queries, ["Grid-scale batteries & storage"]) == []
    assert eq.coverage_check(queries, ["Offshore wind"]) == ["Offshore wind"]


def test_llm_check_judgment_count_mismatch_fails_all() -> None:
    eq = _load_spike("eval_queries")

    class PartialLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {
                "judgments": [{"global": True, "mechanism_first": True, "in_scope": True, "distinct": True}]
            }  # 1 of 2

    class Limiter:
        def wait(self) -> None:
            pass

    failures = eq.llm_check(["q1", "q2"], {"name": "T", "in": "i", "out": "o"}, PartialLLM(), Limiter())
    assert len(failures) == 2  # a partial judgment set must fail every query (r1/r8)


# --- eval_queries: malformed LLM output must FAIL the gate, not crash -------


def test_llm_check_handles_non_dict_output() -> None:
    eq = _load_spike("eval_queries")

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            return None  # malformed: not a dict

    class Limiter:
        def wait(self) -> None:
            pass

    failures = eq.llm_check(["q1", "q2"], {"name": "T", "in": "i", "out": "o"}, BoomLLM(), Limiter())
    assert len(failures) == 2  # every query fails with a controlled verdict


def test_llm_check_handles_router_exception() -> None:
    eq = _load_spike("eval_queries")

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            raise RuntimeError("router timeout")

    class Limiter:
        def wait(self) -> None:
            pass

    failures = eq.llm_check(["q1"], {"name": "T", "in": "i", "out": "o"}, BoomLLM(), Limiter())
    assert len(failures) == 1
    assert "LLM call failed" in failures[0]


# --- eval_story: contextualize handles malformed/erroring LLM output --------


def test_contextualize_handles_non_dict_output() -> None:
    ev = _load_spike("eval_story")

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            return "not a dict"

    class Limiter:
        def wait(self) -> None:
            pass

    r = ev.contextualize(
        {"url": "https://x.example/1", "title": "T", "summary": "S", "source": "src"},
        "story text",
        "Topic",
        BoomLLM(),
        Limiter(),
    )
    assert r["sufficient"] is False
    assert r["missing"]  # a reason is recorded


def test_contextualize_handles_router_exception() -> None:
    ev = _load_spike("eval_story")

    class BoomLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> Any:
            raise RuntimeError("router timeout")

    class Limiter:
        def wait(self) -> None:
            pass

    r = ev.contextualize(
        {"url": "https://x.example/1", "title": "T", "summary": "S", "source": "src"},
        "story text",
        "Topic",
        BoomLLM(),
        Limiter(),
    )
    assert r["sufficient"] is False
    assert "LLM call failed" in r["missing"]


# --- eval_story: small samples must not tighten the pass bar to 100% --------


def test_small_sample_pass_tolerance() -> None:
    ev = _load_spike("eval_story")
    # With only 2 held-out articles (fixtures-only run), 0.75 * 2 rounds to 2/2 —
    # one insufficient must not fail the whole gate.
    assert ev.contextualization_passes(sufficient=1, total=2, pass_frac=ev.PASS_FRAC) is True
    assert ev.contextualization_passes(sufficient=2, total=2, pass_frac=ev.PASS_FRAC) is True


def test_full_sample_still_requires_ratio() -> None:
    ev = _load_spike("eval_story")
    # With a normal-size sample the ratio applies: 3/4 = 0.75 passes, 2/4 fails.
    assert ev.contextualization_passes(sufficient=3, total=4, pass_frac=ev.PASS_FRAC) is True
    assert ev.contextualization_passes(sufficient=2, total=4, pass_frac=ev.PASS_FRAC) is False
    assert ev.contextualization_passes(sufficient=0, total=0, pass_frac=ev.PASS_FRAC) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
