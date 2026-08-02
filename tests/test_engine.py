"""FR-8 orchestration: run() sequences the stages in order and stays idempotent."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from signalflow import engine as engine_mod
from signalflow.engine import Engine


class FakeMemory:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._topics: list[dict[str, Any]] = []
        self._blacklist: set[str] = set()

    def topics(self) -> list[dict[str, Any]]:
        return self._topics

    def seed_topics(self, assignment: dict[str, Any]) -> int:
        return len(assignment["topics"])

    def clear_topics(self) -> None:
        self._topics = []

    def set_topics(self, topics: list[dict[str, Any]]) -> None:
        self._topics = topics

    def save_blacklist(self, domains: set[str]) -> int:
        self._blacklist = set(domains)
        return len(domains)

    def blacklist(self) -> set[str]:
        return self._blacklist

    def prune(self) -> int:
        return 2

    def has_url(self, url: str) -> bool:
        return False


class FakeDiscovery:
    def __init__(self, cfg: Any) -> None:
        pass

    def discover(self, topics: list[dict[str, Any]]) -> list[Any]:
        return []


class FakePipeline:
    def __init__(self, cfg: Any, known_domains: set[str], memory: Any, llm: Any, embedder: Any) -> None:
        pass

    def process(self, candidates: list[Any]) -> list[Any]:
        return []


def _engine(
    cfg: Any,
    memory_cls: type = FakeMemory,
    discovery_cls: type = FakeDiscovery,
    pipeline_cls: type = FakePipeline,
    parse_opml: Any = None,
    load_topics: Any = None,
    build_digest: Any = None,
    publish: Any = None,
) -> Engine:
    """Construct an Engine with injected fakes — constructor DI, never
    monkeypatched module globals (coding-standards: DI over patching)."""
    return Engine(
        cfg=cfg,
        memory=memory_cls(cfg, Path("/tmp/test.db")),
        llm=SimpleNamespace(chat_json=lambda prompt, **kw: {"ok": True}),
        embedder=SimpleNamespace(embed=lambda texts: [[0.1] for _ in texts]),
        parse_opml_fn=parse_opml or (lambda path: ({"sub.com"}, [])),
        load_topics_fn=load_topics or (lambda: []),
        discovery_cls=discovery_cls,
        pipeline_cls=pipeline_cls,
        build_digest_fn=build_digest or (lambda cfg, events, path: None),
        publish_fn=publish or (lambda cfg, path: None),
    )


def test_run_sequences_stages_and_publishes(cfg: Any) -> None:
    order: list[str] = []

    class D(FakeDiscovery):
        def discover(self, topics: list[dict[str, Any]]) -> list[Any]:
            order.append("discover")
            return [{"title": "c"}]

    class P(FakePipeline):
        def process(self, candidates: list[Any]) -> list[Any]:
            order.append("dedup")
            return [object()]  # one event -> digest + publish path

    engine = _engine(
        cfg,
        discovery_cls=D,
        pipeline_cls=P,
        build_digest=lambda cfg, events, path: order.append("digest"),
        publish=lambda cfg, path: order.append("publish"),
    )
    cast(Any, engine._memory).save_blacklist({"sub.com"})
    cast(Any, engine._memory).set_topics(
        [{"name": "T", "status": "adequate", "feed_count": 3, "strategy": {"queries": ["q"]}}]
    )
    assert engine.run() == 0
    assert order == ["discover", "dedup", "digest", "publish"]


def test_run_no_events_keeps_previous_digest(cfg: Any) -> None:
    called: list[str] = []
    engine = _engine(
        cfg,
        build_digest=lambda *a: called.append("build"),
        publish=lambda *a: called.append("publish"),
    )
    cast(Any, engine._memory).save_blacklist({"sub.com"})
    cast(Any, engine._memory).set_topics([{"name": "T"}])
    assert engine.run() == 0
    assert called == []  # no events: previous digest is kept, nothing published


def test_run_fails_fast_without_setup(cfg: Any) -> None:
    """FR-8 recurring run never re-derives: no stored blacklist -> abort, no OPML."""

    def _no_opml(path: Any) -> Any:
        raise AssertionError("run() must not parse OPML")

    engine = _engine(cfg, memory_cls=FakeMemory)
    engine._parse_opml = _no_opml
    assert engine.run() == 1  # no blacklist stored
    cast(Any, engine._memory).save_blacklist({"sub.com"})
    assert engine.run() == 1  # still no topics stored


def test_setup_fails_fast_on_empty_opml(cfg: Any) -> None:
    """FR-1/FR-2 setup: zero domains parsed -> abort, never persist empty blacklist."""
    seen: dict[str, Any] = {}

    def _parse(path: Any) -> Any:
        return set(), []

    class M(FakeMemory):
        def save_blacklist(self, domains: set[str]) -> int:
            seen["called"] = True
            return 0

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse)
    assert engine.setup() == 1
    assert "called" not in seen  # blacklist must not be persisted


def test_setup_fails_fast_when_seed_produces_zero_topics(cfg: Any) -> None:
    """FR-1/FR-2 setup: a zero topics seed must not leave a blacklist behind.

    Blacklist is persisted and verified FIRST (r13 fix), then topics are
    seeded; a zero-seed rolls the blacklist back so setup leaves NO partial
    state (previously topics were seeded before the blacklist was verified,
    so a failed blacklist write left topics persisted despite the refusal).
    """
    saved: list[set[str]] = []

    def _parse(path: Any) -> Any:
        return {"sub.com"}, []

    class M(FakeMemory):
        def seed_topics(self, assignment: dict[str, Any]) -> int:
            return 0

        def save_blacklist(self, domains: set[str]) -> int:
            saved.append(set(domains))
            self._blacklist = set(domains)  # mirror the real write for the verify step
            return len(domains)

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse)
    assert engine.setup() == 1
    assert saved == [{"sub.com"}, set()]  # blacklist written, then rolled back to empty
    assert engine._memory.blacklist() == set()  # no partial blacklist left behind


def test_setup_does_not_seed_topics_when_blacklist_write_fails(cfg: Any) -> None:
    """FR-1/FR-2 setup (r13): when the blacklist write does not stick, topics
    must NOT have been seeded — setup is atomic, no partial state."""
    seen: dict[str, Any] = {}

    def _parse(path: Any) -> Any:
        return {"sub.com"}, []

    class M(FakeMemory):
        def save_blacklist(self, domains: set[str]) -> int:
            seen["blacklist"] = True
            return len(domains)  # reports success but does NOT persist (no self._blacklist update)

        def seed_topics(self, assignment: dict[str, Any]) -> int:
            seen["seeded"] = True
            return 1

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse)
    assert engine.setup() == 1
    assert seen.get("blacklist") is True  # write was attempted
    assert "seeded" not in seen  # topics NOT seeded after a failed blacklist write


def test_setup_fails_fast_when_blacklist_write_incomplete(cfg: Any) -> None:
    """FR-1/FR-2 setup: a blacklist write that doesn't stick must not complete setup.

    The previous blacklist is restored so the failed write never destroys the
    last-good exclusion set (r15 suggestion: the zero-seed branch rolls back,
    the incomplete-write branch must too).
    """
    saved: list[set[str]] = []

    def _parse(path: Any) -> Any:
        return {"sub.com"}, []

    class M(FakeMemory):
        _write_sticks: bool = True

        def blacklist(self) -> set[str]:
            return self._blacklist

        def save_blacklist(self, domains: set[str]) -> int:
            saved.append(set(domains))
            if self._write_sticks:
                self._blacklist = set(domains)
                return len(domains)
            return 0  # write does NOT stick (no self._blacklist update)

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse)
    cast(Any, engine._memory)._blacklist = {"old.com"}  # last-good set
    cast(Any, engine._memory)._write_sticks = False
    assert engine.setup() == 1
    assert saved[0] == {"sub.com"}  # attempted write
    assert saved[1] == {"old.com"}  # previous restored
    assert engine._memory.blacklist() == {"old.com"}  # last-good set survives


def test_setup_fails_fast_on_shrunk_blacklist(cfg: Any) -> None:
    """FR-1/FR-2 setup: a >50% drop vs stored blacklist looks like a truncated export."""
    seen: dict[str, Any] = {}

    def _parse(path: Any) -> Any:
        return {"only.com"}, []

    class M(FakeMemory):
        def blacklist(self) -> set[str]:
            return {"a.com", "b.com", "c.com"}  # stored: 3; new parse: 1

        def save_blacklist(self, domains: set[str]) -> int:
            seen["called"] = True
            return 0

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse)
    assert engine.setup() == 1
    assert "called" not in seen


def test_setup_rolls_back_blacklist_when_seed_raises(cfg: Any) -> None:
    """A topics-seed that RAISES must roll the blacklist back, same as a
    zero-seed — a partial setup must never survive either failure (r16
    suggestion)."""
    saved: list[set[str]] = []

    def _parse(path: Any) -> Any:
        return {"sub.com"}, []

    class M(FakeMemory):
        def seed_topics(self, assignment: dict[str, Any]) -> int:
            raise RuntimeError("topics file corrupt")

        def save_blacklist(self, domains: set[str]) -> int:
            saved.append(set(domains))
            self._blacklist = set(domains)
            return len(domains)

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse, load_topics=engine_mod.load_topics)
    assert engine.setup() == 1
    assert saved == [{"sub.com"}, set()]  # written, then rolled back to empty
    assert engine._memory.blacklist() == set()


def test_setup_shrink_guard_uses_config_ratio(cfg: Any) -> None:
    """FR-1/FR-2 setup: the shrink threshold comes from Config, not a hardcoded 0.5."""
    seen: dict[str, Any] = {}

    def _parse(path: Any) -> Any:
        return {"a.com", "b.com"}, []

    class M(FakeMemory):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._blacklist = {"a.com", "b.com", "c.com", "d.com", "e.com"}  # stored: 5; new: 2

        def save_blacklist(self, domains: set[str]) -> int:
            seen["called"] = True
            self._blacklist = set(domains)
            return len(domains)

    # ratio 0.5: 2 < 2.5 -> guard trips; ratio 0.25: 2 >= 1.25 -> passes
    loose = cfg.__class__(
        llm_key=cfg.llm_key,
        llm_base=cfg.llm_base,
        llm_model=cfg.llm_model,
        embed_model=cfg.embed_model,
        google_key=cfg.google_key,
        exa_key=cfg.exa_key,
        min_blacklist_ratio=0.25,
    )
    engine = _engine(loose, memory_cls=M, parse_opml=_parse, load_topics=engine_mod.load_topics)
    assert engine.setup() == 0  # loose ratio lets the shrink through
    assert seen["called"] is True


def test_setup_persists_blacklist_and_topics(cfg: Any) -> None:
    """FR-1/FR-2 setup: OPML parsed once, blacklist + topics persisted."""
    seen: dict[str, Any] = {}

    def _parse(path: Any) -> Any:
        return {"sub.com"}, [{"folder": "F", "title": "T", "url": "https://sub.com/f"}]

    class M(FakeMemory):
        def save_blacklist(self, domains: set[str]) -> int:
            seen["blacklist"] = domains
            self._blacklist = set(domains)  # mirror the real write for the verify step
            return len(domains)

        def seed_topics(self, assignment: dict[str, Any]) -> int:
            seen["seeded"] = True
            return len(assignment["topics"])

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse, load_topics=engine_mod.load_topics)
    assert engine.setup() == 0
    assert seen["blacklist"] == {"sub.com"}
    assert seen["seeded"] is True


def test_setup_force_bypasses_shrink_guard(cfg: Any) -> None:
    """FR-1/FR-2 setup: --force persists a deliberate large unsubscribe."""

    def _parse(path: Any) -> Any:
        return {"only.com"}, []

    class M(FakeMemory):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._blacklist = {"a.com", "b.com", "c.com"}  # previously stored set

        def save_blacklist(self, domains: set[str]) -> int:
            self._blacklist = set(domains)
            return len(domains)

    engine = _engine(cfg, memory_cls=M, parse_opml=_parse, load_topics=engine_mod.load_topics)
    assert engine.setup(force=True) == 0
    assert engine._memory.blacklist() == {"only.com"}


def test_seed_from_curated_marks_gaps(cfg: Any) -> None:
    seen: dict[str, Any] = {}

    class M(FakeMemory):
        def seed_topics(self, assignment: dict[str, Any]) -> int:
            seen["assignment"] = assignment
            return len(assignment["topics"])

    engine = _engine(cfg, memory_cls=M, load_topics=engine_mod.load_topics)
    assert engine._seed_from_curated() == 13
    topics = seen["assignment"]["topics"]
    assert topics["Agriculture"]["gap"] is True  # 1 source < MIN_FEEDS_PER_TOPIC
    assert topics["Leadership / Management"]["gap"] is False  # 8 sources


def test_reseed_clears_then_seeds(cfg: Any) -> None:
    engine = _engine(cfg, load_topics=engine_mod.load_topics)
    assert engine.reseed_topics() == 13


def test_smoke_offline(cfg: Any) -> None:
    class FakeLLM:
        def __init__(self, cfg: Any) -> None:
            pass

        def chat_json(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
            return {"ok": True}

    class FakeEmbedder:
        def __init__(self, cfg: Any) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2] for _ in texts]

    engine = Engine(
        cfg=cfg,
        memory=FakeMemory(cfg, Path("/tmp/test.db")),
        llm=FakeLLM(cfg),
        embedder=FakeEmbedder(cfg),
        parse_opml_fn=lambda path: ({"sub.com"}, [{"folder": "F", "title": "T", "url": "https://sub.com/f"}]),
        load_topics_fn=lambda: [],
        discovery_cls=FakeDiscovery,
        pipeline_cls=FakePipeline,
    )
    assert engine.smoke() == 0


def test_show_topics(cfg: Any) -> None:
    engine = _engine(cfg)
    cast(Any, engine._memory).set_topics(
        [{"name": "T", "status": "adequate", "feed_count": 3, "strategy": {"registries": ["ukri gtr"]}}]
    )
    assert engine.show_topics() == 0


class FakeEngine:
    def __init__(self) -> None:
        pass

    def run(self) -> int:
        return 0

    def smoke(self) -> int:
        return 0

    def show_topics(self) -> int:
        return 0

    def reseed_topics(self) -> int:
        return 0

    class _Mem:
        def prune(self) -> int:
            return 3

    _memory = _Mem()


def test_main_sources_dispatches_without_engine(monkeypatch: Any) -> None:
    fake = SimpleNamespace(main=lambda args: 7)
    monkeypatch.setitem(sys.modules, "signalflow.source_lists", fake)
    assert engine_mod.main(["sources", "Grid & Net Zero economics"]) == 7


def test_main_command_dispatch(monkeypatch: Any, cfg: Any) -> None:
    monkeypatch.setattr(engine_mod, "Engine", FakeEngine)
    monkeypatch.setattr(engine_mod, "write_doc", lambda topics: "docs/topics.md")
    assert engine_mod.main([]) == 0  # default: run
    assert engine_mod.main(["run"]) == 0
    assert engine_mod.main(["smoke"]) == 0
    assert engine_mod.main(["topics"]) == 0
    assert engine_mod.main(["topics-doc"]) == 0
    assert engine_mod.main(["reseed"]) == 0
    assert engine_mod.main(["prune"]) == 0
    assert engine_mod.main(["bogus"]) == 2
