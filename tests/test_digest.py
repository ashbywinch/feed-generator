"""Digest: valid RSS, two bullets per entry, atomic replace, entry ids."""

from dataclasses import replace

import feedparser

from signalflow.digest import build_digest, publish
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


def test_digest_relative_path_branch(cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # out_path under cwd -> relative_to() succeeds
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert out.exists()


def test_publish_skipped_without_token(cfg, tmp_path, capsys):
    publish(cfg, tmp_path / "signalflow_digest.xml")
    assert "skipped (no DEPLOY_TOKEN)" in capsys.readouterr().out


def test_publish_token_branch(cfg, tmp_path, capsys):
    publish(replace(cfg, deploy_token="t-secret"), tmp_path / "signalflow_digest.xml")
    assert "not yet wired to Netlify site 't-secret'" in capsys.readouterr().out
