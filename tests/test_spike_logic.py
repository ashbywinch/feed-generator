"""Deterministic unit tests for spike-pipeline behaviors (no network/LLM).

The weekly-selection pipeline and its eval gates live in spikes/ (type/lint
gated, runnable via make spike-weekly / eval-story / eval-queries). These tests
pin the pure-logic behaviors — window slot reservation, malformed-LLM-output
handling, and the small-sample pass threshold — without calling any API.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
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


def test_load_verdicts_filters_by_slug(tmp_path: Any) -> None:
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
    got = ws.load_verdicts(story_version=1, slug="a", path=cache)
    assert set(got) == {"a|sub|https://x/1"}  # topic B's verdict must not leak in


def test_load_verdicts_filters_by_rev_and_story_version(tmp_path: Any) -> None:
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
    got = ws.load_verdicts(story_version=1, slug="a", path=cache)
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


def test_evaluate_source_handles_verdicts_null() -> None:
    """An LLM returning {"verdicts": null} (e.g. at token limits) must take the
    missing-verdict retry path, NOT raise TypeError and lose the whole source
    (r17 finding)."""

    class NullVerdictsLLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {"verdicts": None}  # malformed: null, not a list
            return {
                "verdicts": [
                    {"url": "https://x/1", "approved": False, "reason": "", "thesis": "", "empirical_event": ""}
                ]
            }

    class Limiter:
        def wait(self) -> None:
            pass

    source = {"name": "S", "subarea": "sub", "subareas": ["sub"]}
    topic = {"name": "T", "description": "d", "in": "i", "out": "o"}
    verdicts = ws.evaluate_source(
        source, [{"url": "https://x/1", "title": "T", "summary": "s"}], topic, NullVerdictsLLM(), Limiter(), ""
    )
    assert len(verdicts) == 1  # the retry produced the verdict; no crash, no source loss


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


# --- eval_story: pick-history read tolerates torn lines (r11) --------------


def test_eval_story_load_picked_urls_handles_torn_lines(tmp_path: Any) -> None:
    """A torn JSONL tail line must not crash the eval's pick-history read."""
    ev = _load_spike("eval_story")
    cache = tmp_path / "weekly_picks.jsonl"
    cache.write_text(
        json.dumps({"url": "https://x/ok", "title": "T"})
        + "\n"
        + '{"url": "torn", extra'  # invalid JSON tail line
        + "\n"
    )
    picked = ev.load_picked_urls(path=cache)
    assert "https://x/ok" in picked  # valid entry survives
    assert "torn" not in picked  # corrupt line skipped, no crash


# --- weekly_selection: zero_pick_sources excludes eval-failed sources (r11) --


def test_zero_pick_sources_excludes_eval_failed() -> None:
    """A source whose evaluation failed must NOT count as a valid zero-pick."""
    # Real sources shaped like the pipeline builds them
    ok_zero = {"name": "A", "items": [1], "picks": [], "eval_error": ""}  # genuine zero-pick
    eval_failed = {"name": "B", "items": [1], "picks": [], "eval_error": "router timeout"}  # not a zero-pick
    picked = {"name": "C", "items": [1], "picks": [1], "eval_error": ""}  # has picks
    sources = [ok_zero, eval_failed, picked]
    assert ws.count_zero_pick_sources(sources) == 1  # only the genuine zero-pick counts


# --- weekly_selection: first_seen survives re-fetch (r12) ------------------


def test_first_seen_preserved_across_refresh() -> None:
    """A re-fetched undated item keeps its ORIGINAL first_seen — not 'now'.

    Without this, a weekly run re-fetches (6h TTL), re-stamps first_seen as
    today, and stale undated articles never age out of the window.
    """
    old_first_seen = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    old_items = [{"url": "https://x/u", "title": "U", "published": None, "undated": True, "first_seen": old_first_seen}]
    new_items = [
        {
            "url": "https://x/u",
            "title": "U",
            "published": None,
            "undated": True,
            "first_seen": datetime.now(UTC).isoformat(),
        }
    ]
    merged = ws.preserve_first_seen(new_items, old_items)
    assert merged[0]["first_seen"] == old_first_seen  # original preserved, not re-stamped


def test_first_seen_new_item_keeps_fetch_time() -> None:
    """A genuinely new undated item (not in old cache) keeps its fetch stamp."""
    old_items = [
        {
            "url": "https://x/other",
            "title": "O",
            "published": None,
            "undated": True,
            "first_seen": "2026-01-01T00:00:00+00:00",
        }
    ]
    fetch_time = (datetime.now(UTC)).isoformat()
    new_items = [{"url": "https://x/u", "title": "U", "published": None, "undated": True, "first_seen": fetch_time}]
    merged = ws.preserve_first_seen(new_items, old_items)
    assert merged[0]["first_seen"] == fetch_time  # new item: fetch time is correct


def test_zero_pick_source_names_excludes_eval_failed() -> None:
    """Console zero-picks list must not count eval failures as valid zero-picks."""
    ws = _load_spike("weekly_selection")
    ok_zero = {"name": "A", "items": [1], "picks": [], "eval_error": ""}
    failed = {"name": "B", "items": [1], "picks": [], "eval_error": "router timeout"}
    picked = {"name": "C", "items": [1], "picks": [1]}
    assert ws.zero_pick_source_names([ok_zero, failed, picked]) == ["A"]


# --- weekly_selection: zero-parse on first fetch is a bot-wall, not empty (r13) ---


def test_zero_parse_suspicious_on_first_fetch_when_not_a_feed() -> None:
    """A first-fetch 200 that parses to zero entries is a bot-wall/redirect —
    unless the payload is a REAL feed with no entries yet (feed version set).
    Previously the zero-parse guard only fired when items were cached before,
    so a first-fetch bot-wall was stored as a clean empty feed and read as a
    genuine 'nothing worth surfacing' outcome.
    """
    ws = _load_spike("weekly_selection")
    # HTML bot-wall/redirect on first fetch: no feed version -> suspicious
    assert ws.is_zero_parse_suspicious({"items": [], "feed_version": ""}, had_items=False) is True
    # Genuinely empty feed (real markup, zero entries) -> NOT suspicious
    assert ws.is_zero_parse_suspicious({"items": [], "feed_version": "rss20"}, had_items=False) is False
    # Previously-cached feed goes quiet -> suspicious regardless of markup
    assert ws.is_zero_parse_suspicious({"items": [], "feed_version": "rss20"}, had_items=True) is True
    # Real items or a fetch error -> not a zero-parse case
    assert ws.is_zero_parse_suspicious({"items": [1]}, had_items=False) is False
    assert ws.is_zero_parse_suspicious({"error": "boom", "items": []}, had_items=False) is False


# --- weekly_selection: shared feeds keyed on FULL subarea set (r14) --------


def test_subarea_key_stable_under_reorder() -> None:
    """A feed listed under several subareas must key on the full SORTED set.

    Previously the verdict cache key used only the FIRST subarea, so
    reordering subareas in the discovery JSON re-keyed every cached verdict
    and the whole week re-judged. Sorted set: order-independent.
    """
    ws = _load_spike("weekly_selection")
    a = {"crawl_root": "https://x/feed", "subarea": "B", "subareas": ["B", "A"]}
    b = {"crawl_root": "https://x/feed", "subarea": "A", "subareas": ["A", "B"]}  # reordered
    assert ws.subarea_key(a) == ws.subarea_key(b)
    assert ws.subarea_key(a) == "A|B"


def test_verdict_key_uses_full_subarea_set() -> None:
    """Verdict cache key = slug|sorted subareas|url — reorder-proof."""
    ws = _load_spike("weekly_selection")
    s1 = {
        "crawl_root": "https://x/feed",
        "subarea": "Long-duration storage",
        "subareas": ["Grid-scale batteries & storage", "Long-duration storage"],
    }
    s2 = {
        "crawl_root": "https://x/feed",
        "subarea": "Long-duration storage",
        "subareas": ["Long-duration storage", "Grid-scale batteries & storage"],
    }
    assert ws.verdict_key("slug", s1, "https://x/a") == ws.verdict_key("slug", s2, "https://x/a")
    # single-subarea source keeps its old-shaped key
    s3 = {"crawl_root": "https://y/feed", "subarea": "A", "subareas": ["A"]}
    assert ws.verdict_key("slug", s3, "u") == "slug|A|u"


def test_subarea_label_includes_all_subareas() -> None:
    """A pick from a feed covering two subareas is attributed to BOTH."""
    ws = _load_spike("weekly_selection")
    s = {
        "crawl_root": "https://x/feed",
        "subarea": "Long-duration storage",
        "subareas": ["Grid-scale batteries & storage", "Long-duration storage"],
    }
    label = ws.subarea_label(s)
    assert "Grid-scale batteries & storage" in label
    assert "Long-duration storage" in label
    # single-subarea source: label is just that subarea
    s2 = {"crawl_root": "https://y/feed", "subarea": "A", "subareas": ["A"]}
    assert ws.subarea_label(s2) == "A"


# --- weekly_selection: tracker params normalized so one article = one url (r15) ---


def test_normalize_url_strips_tracker_families() -> None:
    """Feeds appending fbclid/gclid/ref/cmp variants must normalize to ONE url
    or the article re-enters the window, re-judges, and can be picked twice."""
    ws = _load_spike("weekly_selection")
    base = "https://example.com/story/42"
    assert ws.normalize_url(base) == base
    for q in (
        "?utm_source=x&utm_medium=y",
        "?fbclid=abc",
        "?gclid=xyz",
        "?ref=newsletter",
        "?cmp=week-3",
        "?mc_cid=1&mc_eid=2",
        "?utm_source=x&fbclid=abc&ref=r",
    ):
        assert ws.normalize_url(base + q) == base, q
    # meaningful params are KEPT
    assert ws.normalize_url(base + "?page=2") == base + "?page=2"


# --- weekly_selection: shared feeds keyed on FULL subarea set (r14) --------


def test_shared_feed_subareas_deduplicated_on_merge(tmp_path: Any) -> None:
    """A crawl_root repeated WITHIN the same subarea must not append the
    subarea twice: ['A','A'] would turn the verdict key from A into A|A and
    silently re-key every cached verdict (r15 suggestion)."""
    ws = _load_spike("weekly_selection")
    listing = {
        "topic": "T",
        "subareas": [
            {"name": "A", "sources": [{"crawl_root": "https://x/feed"}]},
            {"name": "A", "sources": [{"crawl_root": "https://x/feed"}]},  # same subarea, again
            {"name": "B", "sources": [{"crawl_root": "https://x/feed"}]},
        ],
    }
    (tmp_path / "t.json").write_text(json.dumps(listing), encoding="utf-8")
    _, sources, _ = ws.load_source_list("T", discovery_dir=tmp_path)
    assert len(sources) == 1
    assert sources[0]["subareas"] == ["A", "B"]  # no "A" duplication
    assert ws.subarea_key(sources[0]) == "A|B"  # stable key


# --- eval_story: malformed section must FAIL the gate, not be skipped (r15) -


def test_mechanical_check_fails_malformed_section() -> None:
    """A subarea section whose value is not a list is corrupt story JSON — the
    gate must record a failure, not silently skip it (r15 suggestion)."""
    ev = _load_spike("eval_story")
    story = {
        "overview": "x" * 60,
        "angles": {"Good": ["fine sentence here."], "Bad": "not a list"},
        "open_questions": [],
    }
    failures = ev.mechanical_check(story)
    assert any("Bad" in f and "malformed" in f for f in failures)


def test_held_out_sample_window_matches_recency() -> None:
    """The held-out sampler must window on RECENCY_DAYS, not a hardcoded 7,
    or the eval can pass on a window that no longer matches production
    selection when RECENCY_DAYS is changed (r16 finding). The window is an
    injectable param (DI over patching, r20)."""
    ev = _load_spike("eval_story")
    cutoff = datetime.now(UTC) - timedelta(days=14)
    feeds = {
        "a": {
            "source": "test-source-a",
            "items": [
                # 10 days old: inside a 14-day window, outside a 7-day one
                {
                    "url": "https://x/band",
                    "title": "Band",
                    "summary": "s",
                    "published": (cutoff + timedelta(days=4)).isoformat(),
                },
                {
                    "url": "https://x/out",
                    "title": "Out",
                    "summary": "s",
                    "published": (cutoff - timedelta(days=30)).isoformat(),
                },
            ],
        }
    }
    got = ev.held_out_articles(feeds, set(), {"pending": []}, recency_days=14)
    urls = [i["url"] for i in got]
    assert "https://x/band" in urls  # within the CONFIGURED window (14d), not a hardcoded 7d
    assert "https://x/out" not in urls  # outside it — must be excluded


def test_held_out_sample_handles_naive_timestamps() -> None:
    """A legacy cache line with a NAIVE published timestamp must not crash the
    eval with naive-vs-aware TypeError — same _aware treatment the weekly
    pipeline applies (r17 finding)."""
    ev = _load_spike("eval_story")
    cutoff = datetime.now(UTC) - timedelta(days=ev.RECENCY_DAYS)
    feeds = {
        "a": {
            "source": "test-source-naive",
            "items": [
                {
                    "url": "https://x/naive",
                    "title": "Naive",
                    "summary": "s",
                    "published": (cutoff + timedelta(days=1)).isoformat().replace("+00:00", ""),
                }
            ],
        }
    }
    got = ev.held_out_articles(feeds, set(), {"pending": []})
    assert any(i["url"] == "https://x/naive" for i in got)  # included, no crash


def test_held_out_sample_windows_undated_by_first_seen() -> None:
    """Undated items must window on first_seen, exactly like the weekly
    pipeline — a stale undated article must not be held out as fresh (r18
    suggestion)."""
    ev = _load_spike("eval_story")
    cutoff = datetime.now(UTC) - timedelta(days=ev.RECENCY_DAYS)
    feeds = {
        "a": {
            "source": "test-source-fresh",
            "items": [
                {
                    "url": "https://x/undated-fresh",
                    "title": "UF",
                    "summary": "s",
                    "published": None,
                    "undated": True,
                    "first_seen": (cutoff + timedelta(days=1)).isoformat(),
                },
            ],
        },
        "b": {
            "source": "test-source-stale",
            "items": [
                {
                    "url": "https://x/undated-stale",
                    "title": "US",
                    "summary": "s",
                    "published": None,
                    "undated": True,
                    "first_seen": (cutoff - timedelta(days=30)).isoformat(),
                },
            ],
        },
    }
    got = ev.held_out_articles(feeds, set(), {"pending": []})
    urls = [i["url"] for i in got]
    assert "https://x/undated-fresh" in urls
    assert "https://x/undated-stale" not in urls  # first seen before window -> excluded


def test_evaluate_source_retry_handles_verdicts_null(capsys: Any) -> None:
    """The retry path must survive {\"verdicts\": null} — the first-call guard
    was fixed, so the retry loop must not iterate None and print 'retry
    failed' for a malformed-but-recoverable model reply (r18 suggestion)."""

    class NullRetryLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {"verdicts": None}  # null on BOTH calls — the retry-loop case

    class Limiter:
        def wait(self) -> None:
            pass

    source = {"name": "S", "subarea": "sub", "subareas": ["sub"]}
    topic = {"name": "T", "description": "d", "in": "i", "out": "o"}
    verdicts = ws.evaluate_source(
        source, [{"url": "https://x/1", "title": "T", "summary": "s"}], topic, NullRetryLLM(), Limiter(), ""
    )
    assert len(verdicts) == 1  # item still yields a (rejected) verdict
    assert "retry failed" not in capsys.readouterr().out  # null handled, not an exception


def test_geo_anchors_catch_uk_mechanisms() -> None:
    """CfD/RAB are UK-specific contract/funding instruments — a query naming
    them is jurisdiction-anchored and must fail the mechanical gate (r17
    finding: the regenerated set shipped 'CfD auction results' queries that
    only the LLM gate caught)."""
    eq = _load_spike("eval_queries")
    assert eq.GEO_ANCHORS.search("CfD auction results renewable energy policy") is not None
    assert eq.GEO_ANCHORS.search("nuclear new-build economics RAB CfD SMR") is not None
    assert eq.GEO_ANCHORS.search("floating offshore wind auction results") is None  # generic: fine


# --- weekly_selection: undated items age out of the window (r10) -----------


def test_undated_items_age_out_via_first_seen() -> None:
    """An undated item first seen before the window must not be a candidate."""
    cutoff = datetime.now(UTC) - timedelta(days=ws.RECENCY_DAYS)
    old = {
        "url": "https://x/old",
        "title": "Old",
        "published": None,
        "undated": True,
        "first_seen": (cutoff - timedelta(days=1)).isoformat(),
    }
    fresh = {
        "url": "https://x/fresh",
        "title": "Fresh",
        "published": None,
        "undated": True,
        "first_seen": (cutoff + timedelta(days=1)).isoformat(),
    }
    dated_old = {
        "url": "https://x/d",
        "title": "D",
        "published": (cutoff - timedelta(days=1)).isoformat(),
        "undated": False,
    }
    assert ws.is_item_in_window(old, cutoff) is False  # undated, seen before window
    assert ws.is_item_in_window(fresh, cutoff) is True  # undated, seen within window
    assert ws.is_item_in_window(dated_old, cutoff) is False  # dated, published before window


def test_undated_without_first_seen_is_kept_once() -> None:
    """Legacy cached items without first_seen stay candidates (migration safety)."""
    cutoff = datetime.now(UTC) - timedelta(days=ws.RECENCY_DAYS)
    legacy = {"url": "https://x/legacy", "title": "L", "published": None, "undated": True}
    assert ws.is_item_in_window(legacy, cutoff) is True


def test_naive_cached_timestamps_handled_safely() -> None:
    """Legacy caches may hold NAIVE timestamps; comparing naive vs aware cutoff
    raises TypeError — the window check must assume UTC (r15 suggestion)."""
    cutoff = datetime.now(UTC) - timedelta(days=ws.RECENCY_DAYS)
    naive_old = {
        "url": "https://x/n1",
        "title": "N",
        "published": None,
        "undated": True,
        "first_seen": (cutoff - timedelta(days=2)).isoformat().replace("+00:00", ""),
    }
    naive_fresh = {
        "url": "https://x/n2",
        "title": "N2",
        "published": None,
        "undated": True,
        "first_seen": (cutoff + timedelta(days=2)).isoformat().replace("+00:00", ""),
    }
    assert ws.is_item_in_window(naive_old, cutoff) is False  # naive, seen before window
    assert ws.is_item_in_window(naive_fresh, cutoff) is True  # naive, within window


def test_parse_feed_date_guards_malformed_tuples() -> None:
    """A malformed/partial feedparser date tuple must yield None, not raise —
    one bad entry must not abort the entire source fetch (r17 suggestion)."""
    good = (2026, 8, 2, 10, 30, 0, 0, 0, 0)
    bad_zero = (0, 0, 0, 0, 0, 0, 0, 0, 0)  # feedparser's all-missing sentinel
    bad_month = (2026, 13, 40, 99, 99, 99, 0, 0, 0)  # out-of-range
    assert ws.parse_feed_date(good) == datetime(2026, 8, 2, 10, 30, tzinfo=UTC)
    assert ws.parse_feed_date(bad_zero) is None
    assert ws.parse_feed_date(bad_month) is None


def test_render_story_text_guards_non_dict_angles() -> None:
    """A corrupt story with non-dict angles must render without AttributeError —
    mechanical_check already flags it; the render must fail cleanly (r20)."""
    ev = _load_spike("eval_story")
    story = {"overview": "x" * 60, "angles": ["not", "a", "dict"], "open_questions": []}
    text = ev.render_story_text(story, "T")  # must not raise
    assert "Area Story" in text  # rendered without the corrupt angles section


def test_load_source_list_warns_on_corrupt_discovery_json(tmp_path: Any, capsys: Any) -> None:
    """An unparseable discovery JSON must be surfaced (WARNING), not silently
    skipped as if the file were absent (r20 finding — never swallow errors)."""
    ws = _load_spike("weekly_selection")
    (tmp_path / "bad.json").write_text("{not valid json", encoding="utf-8")
    listing, sources, slug = ws.load_source_list("T", discovery_dir=tmp_path)
    assert listing is None  # no parseable listing for T
    captured = capsys.readouterr().out.lower()
    assert "bad.json" in captured and ("skip" in captured or "warn" in captured or "unparseable" in captured)


def test_load_jsonl_skips_keyless_lines(tmp_path: Any) -> None:
    """A JSON-valid line without the key field (foreign/partial entry) must be
    skipped with the corrupt count, not abort the run with KeyError (r20)."""
    cache = tmp_path / "weekly_feeds.jsonl"
    cache.write_text(
        json.dumps({"key": "ok", "items": []})
        + "\n"
        + json.dumps({"url": "no-key-field"})  # valid JSON, not a cache record
        + "\n"
    )
    got = ws.load_feeds(path=cache)
    assert set(got) == {"ok"}


def test_render_story_markdown_skips_malformed_angles() -> None:
    """Corrupt (non-list) subarea sections must not crash the markdown render —
    the mechanical gate already flags them (r15 suggestion)."""
    story = {"overview": "x" * 60, "angles": {"Good": ["fine sentence."], "Bad": "not a list"}, "open_questions": []}
    md = ws.render_story_markdown(story, "T")
    assert "fine sentence." in md
    assert "## Bad" not in md  # corrupt section's header must not be rendered
    assert "not a list" not in md  # nor its (string) body


# --- weekly_selection: retry prompt carries story context (r10) -------------


def test_retry_prompt_includes_story_slice() -> None:
    """Retried verdicts must be judged with the same story context as the main call."""
    prompts: list[str] = []

    class CapturingLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            prompts.append(prompt)
            if len(prompts) == 1:
                return {"verdicts": []}  # omit everything -> retry path
            return {
                "verdicts": [
                    {"url": "https://x/1", "approved": False, "reason": "r", "thesis": "", "empirical_event": ""}
                ]
            }

    class Limiter:
        def wait(self) -> None:
            pass

    source = {"name": "S", "subarea": "sub", "subareas": ["sub"], "why": "why this source"}
    topic = {"name": "T", "description": "d", "in": "i", "out": "o"}
    ws.evaluate_source(
        source,
        [{"url": "https://x/1", "title": "T", "summary": "s"}],
        topic,
        CapturingLLM(),
        Limiter(),
        "STORY SLICE TEXT",
    )
    assert len(prompts) >= 2
    assert "STORY SLICE TEXT" in prompts[1]  # retry prompt must carry the story slice


# --- weekly_selection: story_slice missing subarea is detected (r10) --------


def test_story_slice_returns_empty_and_reports_missing_subarea() -> None:
    """A subarea absent from the story's angles must not silently pass as context."""
    story = {"angles": {"exact-name": ["a"]}, "open_questions": ["q"]}
    # The listing may use "Grid-scale batteries & storage" while the story has
    # "Grid-scale storage": a key mismatch must be detectable, not silent.
    missing = ws.story_slice(story, "Grid-scale batteries & storage")
    assert missing == ""  # no angles found
    # After the fix: the run should log/report the miss rather than proceed silently.
    assert ws.story_slice(story, "exact-name") != ""


# --- eval_queries: mechanical gate bounds never deadlock generation (r13) ---


def test_query_bounds_small_topic_no_lower_bound_deadlock() -> None:
    """A topic with fewer subareas than MIN_QUERIES must be able to pass.

    The prompt mandates EXACTLY one query per subarea; a 3-subarea topic can
    therefore only produce 3 queries, but the gate demanded MIN_QUERIES=5 —
    refresh could never persist. Bounds must track the real subarea count.
    """
    eq = _load_spike("eval_queries")
    subareas = ["A", "B", "C"]
    lo, hi = eq.query_bounds(subareas)
    assert lo <= 3 <= hi  # exactly one query per subarea fits the bounds


def test_query_bounds_tolerates_extra_queries() -> None:
    """The prompt allows 'strong subareas may get two'; the gate must accept
    a small number of extra queries beyond one-per-subarea (r13)."""
    eq = _load_spike("eval_queries")
    subareas = ["A", "B", "C", "D", "E", "F", "G", "H"]
    lo, hi = eq.query_bounds(subareas)
    assert lo <= 8 <= hi  # one per subarea fits
    # two queries for one strong subarea (9 total) also fits
    assert lo <= 9 <= hi


def test_mechanical_check_uses_query_bounds() -> None:
    """mechanical_check accepts the bounds query_bounds computes — the gate
    and the generator agree on what a valid set looks like (r13)."""
    eq = _load_spike("eval_queries")
    subareas = ["A", "B", "C"]
    lo, hi = eq.query_bounds(subareas)
    failures = eq.mechanical_check(["q1 a", "q2 b", "q3 c"], lo, hi)
    assert failures == []


# --- eval_queries: strict bool parsing of LLM judgments (r10) ---------------


def test_llm_check_rejects_false_string_judgments() -> None:
    eq = _load_spike("eval_queries")

    class FalseStringLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {"judgments": [{"global": "false", "mechanism_first": True, "in_scope": True, "distinct": True}]}

    class Limiter:
        def wait(self) -> None:
            pass

    failures = eq.llm_check(["q1"], {"name": "T", "in": "i", "out": "o"}, FalseStringLLM(), Limiter())
    assert any("not global" in f for f in failures)  # string "false" must fail, not pass


# --- eval_story: malformed angles must fail cleanly, not crash (r10) --------


def test_mechanical_check_handles_non_dict_angles() -> None:
    ev = _load_spike("eval_story")
    # angles as a list (corrupt story) must produce a failure, not AttributeError
    failures = ev.mechanical_check({"overview": "x" * 60, "angles": ["not", "a", "dict"], "open_questions": []})
    assert any("subarea" in f.lower() or "angles" in f.lower() for f in failures)


# --- weekly_selection: corrupt cache lines are logged, not silently dropped (r10) --


def test_load_jsonl_reports_corrupt_lines(tmp_path: Any, capsys: Any) -> None:
    """A torn JSONL tail line must be skipped AND surfaced, not silently swallowed."""
    cache = tmp_path / "weekly_feeds.jsonl"
    cache.write_text(
        json.dumps({"key": "ok", "items": []})
        + "\n"
        + '{"key": "torn", extra'  # invalid JSON: torn tail line
        + "\n"
    )
    got = ws.load_feeds(path=cache)
    assert set(got) == {"ok"}  # valid entry survives
    captured = capsys.readouterr().out.lower()
    assert "torn" in captured or "skipped" in captured or "corrupt" in captured


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


def test_llm_check_handles_non_list_judgments() -> None:
    """{\"judgments\": <non-list>} must fail every query cleanly, not crash
    the gate with len() TypeError (r19 finding)."""
    eq = _load_spike("eval_queries")

    class BadJudgmentsLLM:
        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {"judgments": 3}  # malformed: not a list

    class Limiter:
        def wait(self) -> None:
            pass

    failures = eq.llm_check(["q1", "q2"], {"name": "T", "in": "i", "out": "o"}, BadJudgmentsLLM(), Limiter())
    assert len(failures) == 2  # each query flagged as unjudged, no crash


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


def test_single_article_never_passes_via_tolerance() -> None:
    ev = _load_spike("eval_story")
    # total == 1 with zero sufficient must FAIL (was: 0 >= 0 via total-1 passed).
    assert ev.contextualization_passes(sufficient=0, total=1, pass_frac=ev.PASS_FRAC) is False
    assert ev.contextualization_passes(sufficient=1, total=1, pass_frac=ev.PASS_FRAC) is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
