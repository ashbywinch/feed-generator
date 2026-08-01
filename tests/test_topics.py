"""Curated topic set: load/render invariants (FR-2 seed source)."""

from __future__ import annotations

from signalflow.topics import DOCS_PATH, load_topics, render_markdown


def test_load_topics_shape() -> None:
    topics = load_topics()
    assert len(topics) == 13
    for t in topics:
        assert t["name"] and t["in"] and t["out"]
        assert isinstance(t.get("sources", []), list)


def test_render_matches_committed_doc() -> None:
    assert render_markdown(load_topics()) == DOCS_PATH.read_text(encoding="utf-8")


def test_write_doc_roundtrip(tmp_path, monkeypatch) -> None:
    from signalflow import topics as topics_mod

    target = tmp_path / "topics.md"
    monkeypatch.setattr(topics_mod, "DOCS_PATH", target)
    p = topics_mod.write_doc(load_topics())
    assert p == target
    assert p.read_text(encoding="utf-8").startswith("# SignalFlow — Curated Topic Set")
