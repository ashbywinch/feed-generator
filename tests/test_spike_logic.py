"""Deterministic unit tests for spike-pipeline behaviors (no network/LLM).

The weekly-selection pipeline and its eval gates live in spikes/ (type/lint
gated, runnable via make spike-weekly / eval-story / eval-queries). These tests
pin the pure-logic behaviors — window slot reservation, malformed-LLM-output
handling, and the small-sample pass threshold — without calling any API.
"""

from __future__ import annotations

import importlib.util
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
