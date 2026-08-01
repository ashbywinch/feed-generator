"""Repeatable source-list generator: mechanical gates + rendering (unit).

The agent tool-loop itself needs router + Exa keys; it is exercised by the
manual `make topic-sources` run, not the unit suite.
"""

from typing import Any

from signalflow.source_lists import (
    _parse_json,
    exclude_domains,
    gate_collision,
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
        "registries": ["ofgem.gov.uk"],
        "queries": ["q1"],
        "news_vs_analysis": "analysis",
        "notes": "n",
        "review_record": {"findings": [{"severity": "minor", "area": "x", "issue": "y"}]},
    }
    md = render_markdown(record)
    assert "## Subareas" in md and "## Registries" in md and "## Queries" in md
    assert "[minor] x: y" in md
