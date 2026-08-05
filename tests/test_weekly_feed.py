"""Weekly topic feeds: per-topic RSS from picks + story, no network/LLM.

The feed body contract (user spec): description = our why-it-matters summary;
content = that summary, then a link to the topic background long read, then a
clickable preview snippet of the actual article.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import feedparser

from signalflow.weekly_feed import (
    build_site,
    build_topic_feed,
    load_snippet_map,
    pick_snippet,
    render_story_html,
    snippet_text,
    why_summary,
)

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _pick(
    url: str = "https://a.example/1",
    title: str = "Big AI capex story",
    reason: str = "Why it matters now",
    thesis: str = "Systemic thesis",
    event: str = "Observed event one",
    published: str = "2026-08-03T12:00:00+00:00",
    picked_at: str | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "published": published,
        "source": "Fake Feed",
        "domain": "a.example",
        "subarea": "Capex",
        "reason": reason,
        "thesis": thesis,
        "empirical_event": event,
        "picked_at": picked_at if picked_at is not None else (NOW - timedelta(hours=1)).isoformat(),
    }


def _story() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": "2026-08-03T00:00:00+00:00",
        "overview": "The big picture of compute buildout.\n\nSecond paragraph.",
        "angles": {
            "Capex": ["Hyperscaler capex outruns build capacity"],
            "Silicon": ["Packaging is the bottleneck"],
        },
        "open_questions": ["When does power become binding?"],
        "pending": [],
    }


def _build(tmp_path: Path, picks: list[dict[str, Any]], story: dict[str, Any] | None = None) -> Path:
    out = tmp_path / "topic.xml"
    build_topic_feed(
        slug="02-test",
        topic_name="Test Topic",
        picks=picks,
        story=story if story is not None else _story(),
        feed_url="https://signalflow.local/feeds/02-test.xml",
        story_url="https://signalflow.local/topics/02-test/",
        out_path=out,
        snippet_map={"https://a.example/1": "Snippet <b>text</b> of the article"},
    )
    return out


# --- description = why-it-matters summary ----------------------------------


def test_build_topic_feed_valid_rss_with_entries(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick(), _pick(url="https://a.example/2", title="Second story")])
    parsed = feedparser.parse(str(out))
    assert len(parsed.entries) == 2
    by_url = {e["id"]: e for e in parsed.entries}
    assert set(by_url) == {"https://a.example/1", "https://a.example/2"}
    assert by_url["https://a.example/1"].title == "Big AI capex story"
    assert any(link.href == "https://a.example/1" for link in by_url["https://a.example/1"].links)


def test_description_is_why_important_summary(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick(reason="This changes the capex calculus")])
    (entry,) = feedparser.parse(str(out)).entries
    assert entry.description == "This changes the capex calculus"


def test_description_falls_back_to_event_then_thesis(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick(reason="")])  # empty reason -> empirical_event
    (entry,) = feedparser.parse(str(out)).entries
    assert entry.description == "Observed event one"

    pick = _pick(reason="")
    pick["empirical_event"] = ""
    out2 = tmp_path / "t2.xml"
    build_topic_feed(
        slug="s",
        topic_name="T",
        picks=[pick],
        story=_story(),
        feed_url="https://x/feed.xml",
        story_url="https://x/story/",
        out_path=out2,
    )
    (entry2,) = feedparser.parse(str(out2)).entries
    assert entry2.description == "Systemic thesis"


def test_why_summary_first_non_empty() -> None:
    assert why_summary(_pick(reason="r", thesis="t", event="e")) == "r"
    p = _pick(reason="")
    assert why_summary(p) == "Observed event one"
    p["empirical_event"] = ""
    assert why_summary(p) == "Systemic thesis"
    p["thesis"] = ""
    assert why_summary(p) == ""


# --- body = summary + story link + clickable snippet -----------------------


def test_body_order_summary_story_link_then_snippet(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick()])
    (entry,) = feedparser.parse(str(out)).entries
    body = entry.content[0]["value"]
    assert "Why it matters now" in body  # the summary leads the body
    assert "https://signalflow.local/topics/02-test/" in body  # long-read link
    assert 'href="https://a.example/1"' in body  # snippet links to the article
    assert "Snippet" in body and "text of the article" in body  # snippet text present
    assert body.index("Why it matters now") < body.index("https://signalflow.local/topics/02-test/")
    assert body.index("https://signalflow.local/topics/02-test/") < body.index("https://a.example/1")


def test_body_snippet_comes_from_item_summary_via_map(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick()])
    (entry,) = feedparser.parse(str(out)).entries
    assert "Snippet" in entry.content[0]["value"]


# --- hygiene ---------------------------------------------------------------


def test_feed_escapes_markup_in_raw_xml(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick(title="<script>alert(1)</script>", reason="<b>bold</b>")])
    raw = out.read_text(encoding="utf-8")
    assert "<script>" not in raw  # never a raw tag
    assert "&lt;script&gt;" in raw
    assert "&lt;b&gt;bold&lt;/b&gt;" in raw  # description escaped too


def test_empty_picks_yields_valid_empty_feed(tmp_path: Path) -> None:
    out = _build(tmp_path, [])
    parsed = feedparser.parse(str(out))
    assert parsed.entries == []
    assert parsed["bozo"] == 0


def test_entry_pubdate_from_picked_at(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick()])
    (entry,) = feedparser.parse(str(out)).entries
    assert entry.published_parsed is not None


def test_no_temp_left_after_build(tmp_path: Path) -> None:
    out = _build(tmp_path, [_pick()])
    assert not out.with_suffix(".tmp").exists()


# --- snippet helpers -------------------------------------------------------


def test_snippet_text_strips_html_and_truncates() -> None:
    assert snippet_text("<p>Hello <b>world</b></p>") == "Hello world"
    long = "word " * 500
    s = snippet_text(long, limit=100)
    assert len(s) <= 100
    assert s.endswith("…")


def test_pick_snippet_uses_map_and_falls_back_to_title() -> None:
    p = _pick()
    assert pick_snippet(p, {"https://a.example/1": "<i>preview</i>"}) == "preview"
    assert pick_snippet(p, {}) == "Big AI capex story"  # no item summary cached


def test_load_snippet_map_latest_line_wins(tmp_path: Path) -> None:
    feeds = tmp_path / "feeds.jsonl"
    lines = [
        {"key": "root1", "items": [{"url": "https://a.example/1", "summary": "old"}]},
        {"key": "root1", "items": [{"url": "https://a.example/1", "summary": "new"}]},
        {"key": "root2", "items": [{"url": "https://b.example/2", "summary": "other"}]},
        {"key": "root3", "items": []},
    ]
    feeds.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    m = load_snippet_map(feeds)
    assert m["https://a.example/1"] == "new"
    assert m["https://b.example/2"] == "other"


def test_load_snippet_map_missing_file(tmp_path: Path) -> None:
    assert load_snippet_map(tmp_path / "nope.jsonl") == {}


def test_load_snippet_map_warns_on_corrupt_lines(tmp_path: Path, capsys) -> None:
    feeds = tmp_path / "feeds.jsonl"
    feeds.write_text('{"key": "a", "items": [{"url": "u", "summary": "s"}]}\nnot-json\n', encoding="utf-8")
    m = load_snippet_map(feeds)
    assert m["u"] == "s"  # good line still parsed
    assert "not-json" in capsys.readouterr().out  # corrupt line surfaced, not silent


# --- story page ------------------------------------------------------------


def test_render_story_html_contains_structure_and_escapes(tmp_path: Path) -> None:
    story = _story()
    story["angles"]["Capex"] = ["<script>angle</script>"]
    html = render_story_html(story, "Data Centers / AI / macro")
    assert "<h1>Data Centers / AI / macro</h1>" in html
    assert "The big picture of compute buildout" in html
    assert "Second paragraph." in html
    assert "Packaging is the bottleneck" in html  # untouched subarea renders
    assert "When does power become binding?" in html
    assert "<script>" not in html
    assert "&lt;script&gt;angle&lt;/script&gt;" in html


# --- site builder ----------------------------------------------------------


def _site_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    picks_dir = tmp_path / "picks"
    stories_dir = tmp_path / "stories"
    picks_dir.mkdir()
    stories_dir.mkdir()
    payload = {
        "generated_at": NOW.isoformat(),
        "topic": "Test Topic",
        "slug": "02-test",
        "picks": [_pick()],
    }
    (picks_dir / "02-test.json").write_text(json.dumps(payload), encoding="utf-8")
    (stories_dir / "02-test.json").write_text(json.dumps(_story()), encoding="utf-8")
    feeds = tmp_path / "feeds.jsonl"
    feeds.write_text(
        json.dumps({"key": "root", "items": [{"url": "https://a.example/1", "summary": "preview"}]}) + "\n",
        encoding="utf-8",
    )
    return picks_dir, stories_dir, feeds


def test_build_site_writes_feed_and_page(tmp_path: Path) -> None:
    picks_dir, stories_dir, feeds = _site_fixture(tmp_path)
    site = tmp_path / "site"
    built = build_site(
        picks_dir=picks_dir,
        stories_dir=stories_dir,
        feeds_path=feeds,
        site_dir=site,
        base_url="https://signalflow.local",
    )
    assert (site / "feeds" / "02-test.xml").exists()
    assert (site / "topics" / "02-test" / "index.html").exists()
    assert not (site / "topics" / "02-test" / "index.html.tmp").exists()  # atomic page write
    assert not (site / "feeds" / "02-test.xml.tmp").exists()
    parsed = feedparser.parse(str(site / "feeds" / "02-test.xml"))
    assert len(parsed.entries) == 1
    # the story page is the feed's alternate link target
    assert "https://signalflow.local/topics/02-test/" in (site / "feeds" / "02-test.xml").read_text(encoding="utf-8")
    assert built == [("02-test", 1)]


def test_build_site_skips_missing_story_or_empty_picks(tmp_path: Path, capsys) -> None:
    picks_dir, stories_dir, feeds = _site_fixture(tmp_path)  # 02-test has picks
    site = tmp_path / "site2"
    built = build_site(
        picks_dir=picks_dir,
        stories_dir=tmp_path / "stories2",  # no story for 02-test
        feeds_path=feeds,
        site_dir=site,
        base_url="https://signalflow.local",
    )
    assert built == []  # nothing buildable: story missing -> feed body would dangle
    assert site.exists()  # index page (fallback) is always rendered
    assert (site / "index.html").exists()
    out = capsys.readouterr().out
    assert "no story" in out  # picks WITHOUT a story is a state error — surfaced, not silent

    # empty picks are skipped silently (intentional — a quiet week is not an error)
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / "03-x.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), "topic": "X", "slug": "03-x", "picks": []}),
        encoding="utf-8",
    )
    site3 = tmp_path / "site3"
    build_site(
        picks_dir=orphan,
        stories_dir=tmp_path / "stories2",
        feeds_path=tmp_path / "no-feeds.jsonl",
        site_dir=site3,
        base_url="https://signalflow.local",
    )
    assert "no story" not in capsys.readouterr().out


def test_feed_orders_newest_pick_first(tmp_path: Path) -> None:
    """New articles appear ABOVE old ones: the accumulated picks file holds
    batch 1 (older) before batch 2 (newer), but the feed must render
    newest-first (by pick time, the entry pubDate)."""
    old = _pick(url="https://a.example/1", title="Old article", picked_at="2026-08-01T00:00:00+00:00")
    new = _pick(url="https://a.example/2", title="New article", picked_at="2026-08-05T00:00:00+00:00")
    out = _build(tmp_path, [old, new])  # merge_picks order: previous batch first
    parsed = feedparser.parse(str(out))
    assert [e.title for e in parsed.entries] == ["New article", "Old article"]


def test_index_shows_newest_pick_first(tmp_path: Path) -> None:
    """The front page card lists the topic's picks newest-first — the order
    merge_picks writes to the accumulated file (single ordering source)."""
    picks_dir, stories_dir, feeds = _site_fixture(tmp_path)
    picks_dir.joinpath("02-test.json").write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "topic": "Test Topic",
                "slug": "02-test",
                "picks": [
                    _pick(url="https://a.example/2", title="New article", picked_at="2026-08-05T00:00:00+00:00"),
                    _pick(url="https://a.example/1", title="Old article", picked_at="2026-08-01T00:00:00+00:00"),
                ],
            }
        ),
        encoding="utf-8",
    )
    site = tmp_path / "site"
    _ = build_site(
        picks_dir=picks_dir,
        stories_dir=stories_dir,
        feeds_path=feeds,
        site_dir=site,
        base_url="https://signalflow.local",
    )
    html = (site / "index.html").read_text(encoding="utf-8")
    assert html.index("New article") < html.index("Old article")


def test_render_index_shows_date_and_source(tmp_path: Path) -> None:
    """The landing page shows the published date and source attribution per pick."""
    picks_dir, stories_dir, feeds = _site_fixture(tmp_path)
    site = tmp_path / "site"
    _ = build_site(
        picks_dir=picks_dir,
        stories_dir=stories_dir,
        feeds_path=feeds,
        site_dir=site,
        base_url="https://signalflow.local",
    )
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "Aug 3, 2026" in html  # _pick's published date formatted
    assert "Fake Feed" in html  # source attribution
    assert "pick-source" in html
