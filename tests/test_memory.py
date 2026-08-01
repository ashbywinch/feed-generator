"""Semantic memory: idempotent inserts, cosine dedup, retention pruning."""

from typing import Any

from signalflow.memory import Memory


def _memory(tmp_path, **cfg_over):
    cfg = _cfg(**cfg_over)
    return Memory(cfg, tmp_path / "test.db"), cfg


def _cfg(**over):
    from signalflow.config import Config

    base: dict[str, Any] = dict(
        llm_key="k",
        llm_base="https://r/v1",
        llm_model="m",
        embed_model="gemini-embedding-001",
        google_key="g",
        exa_key="",
    )
    base.update(over)
    return Config(**base)


def test_save_is_url_idempotent(tmp_path):
    mem, _ = _memory(tmp_path)
    assert mem.save_event("u1", "t", "s1", "topic", [1.0, 0.0])
    assert not mem.save_event("u1", "t2", "s2", "topic", [0.0, 1.0])  # URL UNIQUE
    assert mem.has_url("u1")
    assert not mem.has_url("u2")


def test_best_similar_cosine(tmp_path):
    mem, _ = _memory(tmp_path)
    mem.save_event("u1", "t", "past event", "topic", [1.0, 0.0])
    result = mem.best_similar([0.9, 0.1], 0.5)
    assert result is not None
    sim, past = result
    assert past == "past event"
    assert sim > 0.9  # cos([1,0],[0.9,0.1]) = 0.994
    assert mem.best_similar([0.0, 1.0], 0.5) is None  # orthogonal


def test_prune_respects_retention(tmp_path):
    mem, _ = _memory(tmp_path, retention_days=30)
    mem.save_event("old", "t", "s", "topic", [1.0, 0.0])
    mem.save_event("new", "t", "s", "topic", [1.0, 0.0])
    mem._conn.execute("UPDATE seen_events SET timestamp = '2000-01-01 00:00:00' WHERE url = 'old'")
    mem._conn.commit()
    assert mem.prune() == 1
    assert not mem.has_url("old")
    assert mem.has_url("new")


def test_seed_topics_upsert(tmp_path):
    mem, _ = _memory(tmp_path)
    assignment = {"topics": {"Energy": {"n_feeds": 3, "gap": False, "strategy": {"queries": ["q"]}}}}
    assert mem.seed_topics(assignment) >= 1
    topics = mem.topics()
    assert topics[0]["name"] == "Energy"
    assert topics[0]["feed_count"] == 3
    assert topics[0]["strategy"]["queries"] == ["q"]
    # upsert changes strategy, does not duplicate
    assignment["topics"]["Energy"]["strategy"] = {"queries": ["q2"]}
    mem.seed_topics(assignment)
    assert len(mem.topics()) == 1
    assert mem.topics()[0]["strategy"]["queries"] == ["q2"]
