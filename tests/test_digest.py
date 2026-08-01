"""Digest: valid RSS, two bullets per entry, atomic replace, entry ids."""

import feedparser

from signalflow.digest import build_digest
from signalflow.models import Analysis, ApprovedEvent, Candidate


def _events():
    def ev(url: str, topic: str, title: str, event: str, thesis: str) -> ApprovedEvent:
        cand = Candidate(title=title, summary="s", url=url, source_tier="search", topic=topic)
        analysis = Analysis(approved=True, topic=topic, empirical_event=event, core_thesis=thesis)
        return ApprovedEvent(candidate=cand, analysis=analysis)

    return [
        ev("https://a.example/1", "Energy", "Big thing", "Grid milestone reached", "Thesis one"),
        ev("https://a.example/2", "Maritime", "Other thing", "Port shift observed", "Thesis two"),
    ]


def test_digest_is_valid_rss_with_two_bullets(cfg, tmp_path):
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert out.exists()
    parsed = feedparser.parse(str(out))
    assert len(parsed.entries) == 2
    energy = next(e for e in parsed.entries if e.title.startswith("[Energy]"))  # order not guaranteed
    desc = energy.description
    assert "Grid milestone reached" in desc  # observed event bullet
    assert "Thesis one" in desc  # systemic thesis bullet
    assert any(link.href == "https://a.example/1" for link in energy.links)


def test_digest_atomic_no_temp_left(cfg, tmp_path):
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert not (tmp_path / "signalflow_digest.xml.tmp").exists()
