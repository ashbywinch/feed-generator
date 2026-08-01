"""Repeatable source-list generator: mechanical gates + rendering (unit).

The agent tool-loop itself needs router + Exa keys; it is exercised by the
manual `make topic-sources` run, not the unit suite.
"""

from datetime import date, timedelta
from typing import Any

from signalflow.source_lists import (
    _parse_json,
    exclude_domains,
    gate_collision,
    gate_crawlability,
    gate_dns,
    gate_schema,
    normalize_domain,
    render_markdown,
    slug_for,
)


def _listing(**over: Any) -> dict[str, Any]:
    listing: dict[str, Any] = {
        "topic": "T",
        "subareas": [
            {
                "name": "Markets",
                "sources": [
                    {"name": "A", "domain": "https://www.example.com/feed", "type": "trade press"},
                    {"name": "B", "domain": "other.org", "type": "blog"},
                ],
            },
        ],
        "queries": ["q1"],
    }
    listing.update(over)
    return listing


def test_normalize_domain_strips_scheme_www_slash() -> None:
    assert normalize_domain("https://WWW.Example.COM/feed") == "example.com"
    assert normalize_domain("example.com") == "example.com"


def test_schema_gate_flags_missing_domain_and_queries() -> None:
    bad = _listing()
    bad["subareas"][0]["sources"][0]["domain"] = ""  # type: ignore[index]
    bad["queries"] = []
    findings = gate_schema(bad)
    assert any(f["severity"] == "blocker" for f in findings)  # missing domain
    assert any(f["issue"].startswith("no queries") for f in findings)
    assert gate_schema(_listing()) == []


def test_dns_gate_uses_injected_resolver_and_normalizes() -> None:
    def resolver(host: str) -> bool:
        return host != "other.org"

    findings = gate_dns(_listing(), resolver=resolver)
    assert len(findings) == 1
    assert findings[0]["severity"] == "blocker"
    assert "other.org" in findings[0]["issue"]


def test_dns_gate_flags_exact_duplicate_domain() -> None:
    listing = _listing()
    listing["subareas"].append(  # type: ignore[arg-type]
        {"name": "Storage", "sources": [{"name": "C", "domain": "example.com", "type": "blog"}]}
    )
    findings = gate_dns(listing, resolver=lambda h: True)
    assert any(f["area"] == "duplicates" and f["severity"] == "minor" for f in findings)


def test_collision_gate_blacklists_subscribed_domain() -> None:
    listing = _listing()
    listing["subareas"][0]["sources"][1]["domain"] = "carbonbrief.org"  # type: ignore[index]
    findings = gate_collision(listing, known_domains={"carbonbrief.org"})
    assert len(findings) == 1
    assert findings[0]["severity"] == "blocker"


def test_exclude_domains_resolves_topic_source_names() -> None:
    feeds = [
        {"title": "Solar Power Portal", "url": "https://www.solarpowerportal.co.uk/feed"},
        {"title": "Random Blog", "url": "https://blog.example.com/rss"},
    ]
    topic = {"sources": ["Solar Power Portal", "Other"]}
    assert exclude_domains(feeds, topic) == ["solarpowerportal.co.uk"]


def test_slug_for_orders_by_topics_index() -> None:
    topics = [{"name": "Grid & Net Zero economics"}, {"name": "Data Centers / AI / macro"}]
    assert slug_for("Data Centers / AI / macro", topics) == "02-data-centers-ai-macro"
    assert slug_for("Grid & Net Zero economics", topics) == "01-grid-net-zero-economics"


def test_parse_json_falls_back_to_braces() -> None:
    assert _parse_json('prefix {"a": 1} suffix') == {"a": 1}


def test_apply_revision_remove_replace_add() -> None:
    from signalflow.source_lists import _apply_revision

    listing = {
        "topic": "T",
        "subareas": [
            {"name": "Markets", "sources": [{"name": "A", "domain": "a.com", "type": "blog"}]},
            {"name": "Storage", "sources": [{"name": "B", "domain": "b.com", "type": "blog"}]},
        ],
    }
    delta = {
        "remove": ["a.com"],
        "replace": {"b.com": {"name": "B2", "domain": "b.com", "type": "trade press"}},
        "add": {"Markets": [{"name": "C", "domain": "c.com", "type": "blog"}]},
    }
    out = _apply_revision(listing, delta)
    markets = out["subareas"][0]["sources"]
    storage = out["subareas"][1]["sources"]
    assert [s["domain"] for s in markets] == ["c.com"]  # a.com removed, C added
    assert storage == [{"name": "B2", "domain": "b.com", "type": "trade press"}]  # replaced in place


def test_apply_revision_creates_missing_subarea() -> None:
    from signalflow.source_lists import _apply_revision

    listing = {"topic": "T", "subareas": []}
    out = _apply_revision(listing, {"add": {"New": [{"name": "X", "domain": "x.com", "type": "blog"}]}})
    assert out["subareas"][0]["name"] == "New"
    assert out["subareas"][0]["sources"][0]["domain"] == "x.com"


def test_parse_json_invalid_braces_raises_agent_error() -> None:
    import pytest

    from signalflow.source_lists import AgentError

    with pytest.raises(AgentError):
        _parse_json("I think {this is not json}")


def test_gates_tolerate_malformed_shapes() -> None:
    listing = {"topic": "T", "queries": ["q"], "subareas": None}
    assert gate_schema(listing)  # schema flags it
    assert gate_dns(listing) == []  # dependent gates must not crash
    assert gate_collision(listing, known_domains=set()) == []
    assert gate_crawlability(listing, fetcher=lambda url: _FakeResp(url=url)) == []

    listing = {"topic": "T", "queries": ["q"], "subareas": [{"name": "S", "sources": [42]}]}
    assert gate_dns(listing) == []
    assert gate_crawlability(listing, fetcher=lambda url: _FakeResp(url=url)) == []


def test_render_markdown_contains_sections() -> None:
    record = {
        "topic": "T",
        "status": "approved",
        "iterations": 2,
        "approved_at": "2026-08-01",
        "subareas": [
            {
                "name": "Markets",
                "coverage": "prices",
                "sources": [
                    {"name": "A", "domain": "example.com", "type": "blog", "confidence": "high", "why": "prices"}
                ],
            }
        ],
        "registries": ["ofgem.gov.uk", {"name": "OpenAlex", "domain": "api.openalex.org", "why": "lit data"}],
        "queries": ["q1"],
        "news_vs_analysis": "analysis",
        "notes": "n",
        "review_record": {"findings": [{"severity": "minor", "area": "x", "issue": "y"}]},
    }
    md = render_markdown(record)
    assert "## Subareas" in md and "## Registries" in md and "## Queries" in md
    assert "[minor] x: y" in md
    assert "- ofgem.gov.uk" in md
    assert "**OpenAlex** (`api.openalex.org`) — lit data" in md


# -- crawlability gate -------------------------------------------------------


class _FakeResp:
    def __init__(self, url: str, content_type: str = "", text: str = "", status: int = 200) -> None:
        self.status_code = status
        self.url = url
        self.headers = {"content-type": content_type}
        self.text = text


def _feed_html(when: str) -> str:
    return f"<rss><channel><lastBuildDate>{when}</lastBuildDate></channel></rss>"


def _when(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _crawl_listing(domain: str = "example.com", crawl_root: str = "") -> dict[str, Any]:
    return {
        "topic": "T",
        "subareas": [
            {
                "name": "S",
                "sources": [{"name": "X", "domain": domain, "type": "blog", "crawl_root": crawl_root}],
            }
        ],
        "queries": ["q"],
    }


def test_crawlability_accepts_working_feed() -> None:
    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(url=url, content_type="application/rss+xml", text=_feed_html(_when(5)))

    assert gate_crawlability(_crawl_listing(), fetcher=fetcher) == []


def test_crawlability_cross_host_crawl_root_is_not_redirect() -> None:
    # crawl_root intentionally on a feed host (feeds.reuters.com-style): must pass,
    # not trip the "domain repurposed" finding.
    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(url=url, content_type="application/rss+xml", text=_feed_html(_when(5)))

    listing = _crawl_listing(crawl_root="https://feeds.example.net/feed")
    assert gate_crawlability(listing, fetcher=fetcher) == []


def test_crawlability_redirect_to_working_target_swaps_domain() -> None:
    def fetcher(url: str) -> _FakeResp:
        if "newexample.com" in url:
            return _FakeResp(url=url, content_type="application/rss+xml", text=_feed_html(_when(5)))
        return _FakeResp(
            url="https://newexample.com/feed", content_type="application/rss+xml", text=_feed_html(_when(5))
        )

    listing = _crawl_listing()
    assert gate_crawlability(listing, fetcher=fetcher) == []
    src = listing["subareas"][0]["sources"][0]
    assert src["domain"] == "newexample.com"  # mechanically corrected, no LLM round-trip


def test_crawlability_redirect_to_dead_target_removes_source() -> None:
    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(
            url="https://dead.example.net/", content_type="text/html", text="<html><body>gone</body></html>"
        )

    listing = _crawl_listing()
    assert gate_crawlability(listing, fetcher=fetcher) == []  # handled mechanically, never bounced
    assert listing["subareas"][0]["sources"] == []  # dead-redirect source dropped


def test_crawlability_bot_block_is_blocker() -> None:
    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(url=url, status=403)

    findings = gate_crawlability(_crawl_listing(), fetcher=fetcher)
    assert len(findings) == 1
    assert findings[0]["severity"] == "blocker"


def test_crawlability_stale_feed_is_major() -> None:
    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(url=url, content_type="application/rss+xml", text=_feed_html(_when(200)))

    findings = gate_crawlability(_crawl_listing(), fetcher=fetcher)
    assert len(findings) == 1
    assert findings[0]["severity"] == "major"
    assert "stale" in findings[0]["issue"]


def test_crawlability_corrects_wrong_crawl_root() -> None:
    def fetcher(url: str) -> _FakeResp:
        if url.endswith("/feed"):
            return _FakeResp(url=url, content_type="application/rss+xml", text=_feed_html(_when(5)))
        return _FakeResp(url=url, status=404)

    listing = _crawl_listing(crawl_root="https://example.com/rss")
    assert gate_crawlability(listing, fetcher=fetcher) == []
    assert listing["subareas"][0]["sources"][0]["crawl_root"] == "https://example.com/feed"


def test_crawlability_homepage_feed_link_sets_crawl_root() -> None:
    html = '<html><head><link rel="alternate" type="application/rss+xml" href="/en/rss/"></head></html>'

    def fetcher(url: str) -> _FakeResp:
        return _FakeResp(url="https://example.com/", content_type="text/html", text=html)

    listing = _crawl_listing()
    assert gate_crawlability(listing, fetcher=fetcher) == []
    assert listing["subareas"][0]["sources"][0]["crawl_root"] == "https://example.com/en/rss/"
