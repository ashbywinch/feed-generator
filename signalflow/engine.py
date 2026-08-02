"""FR-8: recurring engine orchestration + CLI.

Setup (one-and-done, FR-1/FR-2): `python -m signalflow setup` parses the OPML
and persists the exclusion set + curated topics. Re-run setup only when the
user adds/removes a topic.

Recurring run (default daily; weekly if yield thin): `python -m signalflow run`
executes the STORED strategies — discover (registries + Exa per topic strategy)
+ feed selection (FR-9) -> dedup (4 layers) -> store -> digest -> publish ->
prune. It never re-derives topics or re-parses the OPML. Idempotent by
construction: dedup L2 + URL-unique inserts mean a re-run emits no duplicates.
"""

from __future__ import annotations

import sys
from typing import Any

from .config import Config
from .dedup import DedupPipeline
from .digest import build_digest, publish
from .discovery import Discovery
from .embed import Embedder
from .env import PROJECT_ROOT, load_env
from .llm import LLM
from .memory import Memory
from .opml import parse_opml
from .topics import load_topics, write_doc

DIGEST_PATH = PROJECT_ROOT / "signalflow_digest.xml"
DB_PATH = PROJECT_ROOT / "history_memory.db"
ASSIGNMENT_PATH = PROJECT_ROOT / "spikes" / "state" / "assignment.json"


class Engine:
    def __init__(
        self,
        cfg: Config | None = None,
        memory: Any | None = None,
        llm: Any | None = None,
        embedder: Any | None = None,
        parse_opml_fn: Any = parse_opml,
        load_topics_fn: Any = load_topics,
        discovery_cls: Any = Discovery,
        pipeline_cls: Any = DedupPipeline,
        build_digest_fn: Any = build_digest,
        publish_fn: Any = publish,
    ) -> None:
        """Constructor DI: collaborators are injectable so tests never patch
        module globals (coding-standards: DI over patching). Defaults keep
        production wiring unchanged."""
        load_env()
        self._cfg = cfg if cfg is not None else Config.from_env()
        self._memory = memory if memory is not None else Memory(self._cfg, DB_PATH)
        self._llm = llm if llm is not None else LLM(self._cfg)
        self._embedder = embedder if embedder is not None else Embedder(self._cfg)
        self._parse_opml = parse_opml_fn
        self._load_topics = load_topics_fn
        self._discovery_cls = discovery_cls
        self._pipeline_cls = pipeline_cls
        self._build_digest = build_digest_fn
        self._publish = publish_fn

    # -- setup (FR-1/FR-2: one-and-done) -------------------------------------

    def setup(self, force: bool = False) -> int:
        """One-and-done: parse OPML, persist exclusion set + curated topics.

        Re-run only when the user adds/removes a topic. The recurring run
        (`run`) reads the stored blacklist and topics — it never touches OPML.
        `force` bypasses the shrink guard for a deliberate large unsubscribe.
        """
        print("[setup] OPML -> exclusion set + topics")
        known_domains, feeds = self._parse_opml(PROJECT_ROOT / "feedly.opml")
        if not known_domains:
            print("FATAL: OPML parsed zero domains — refusing to persist an empty exclusion set")
            print("       (corrupt/truncated feedly.opml? fix it, then re-run setup)")
            return 1
        previous = self._memory.blacklist()
        ratio = self._cfg.min_blacklist_ratio
        if previous and not force and len(known_domains) < ratio * len(previous):
            print(
                f"FATAL: OPML parsed {len(known_domains)} domains vs {len(previous)} previously stored "
                f"— a drop this large (>{1 - ratio:.0%}) looks like a truncated/partial export, "
                "refusing to shrink the exclusion set (the PRD forbids a partial blacklist: it voids "
                "the zero-duplication guarantee). Fix feedly.opml, or re-run `setup --force` if the "
                "shrink is a deliberate unsubscribe."
            )
            return 1
        # Persist + verify the exclusion set FIRST — a blacklist write that
        # doesn't stick must leave NOTHING behind (no topics seeded into a
        # half-configured store). Then seed topics; a zero-seed rolls the
        # blacklist back so setup is atomic in both failure directions.
        self._memory.save_blacklist(known_domains)
        if self._memory.blacklist() != known_domains:
            # The failed write may have already wiped the stored set (partial
            # DELETE+INSERT) — restore the last-good exclusion set so the
            # recurring run keeps working, matching the zero-seed rollback.
            self._memory.save_blacklist(previous)
            print("FATAL: exclusion-set write incomplete — refusing to complete setup (no partial blacklist)")
            return 1
        try:
            seeded = self._seed_from_curated()
        except Exception as exc:  # noqa: BLE001 — a seed crash must not leave a partial setup
            self._memory.save_blacklist(previous)  # roll back: no partial setup
            print(f"FATAL: topics seed failed ({type(exc).__name__}) — refusing to persist a partial setup")
            return 1
        if seeded <= 0:
            self._memory.save_blacklist(previous)  # roll back: no partial setup
            print("FATAL: topics seed produced zero topics — refusing to persist a partial setup")
            return 1
        print(f"      {len(feeds)} feeds, {len(known_domains)} blacklist domains stored")
        print("[setup] done — topics + exclusion set persisted")
        return 0

    # -- recurring run (FR-8) -------------------------------------------------

    def run(self) -> int:
        known_domains = self._memory.blacklist()
        if not known_domains:
            print("FATAL: no exclusion set stored — run `python -m signalflow setup` first")
            return 1
        topics = self._memory.topics()
        if not topics:
            print("FATAL: no topics stored — run `python -m signalflow setup` first")
            return 1
        print(f"[1/6] engine: {len(known_domains)} blacklist domains, {len(topics)} topics (stored)")

        print("[2/6] discovery (registries + Exa per topic strategy)")
        candidates = self._discovery_cls(self._cfg).discover(topics)
        print(f"      {len(candidates)} candidates across {len(topics)} topics")

        print("[3/6] dedup (L1-L4) + evaluation")
        pipeline = self._pipeline_cls(self._cfg, known_domains, self._memory, self._llm, self._embedder)
        events = pipeline.process(candidates)

        print("[4/6] digest")
        if events:
            self._build_digest(self._cfg, events, DIGEST_PATH)
            self._publish(self._cfg, DIGEST_PATH)
        else:
            print("      no new events — keeping previous digest")

        print("[5/6] prune")
        removed = self._memory.prune()
        print(f"      pruned {removed} events older than {self._cfg.retention_days} days")

        print("[6/6] done")
        return 0

    def _seed_from_curated(self) -> int:
        """Seed the topics table from the curated topics.json (walkthrough final set)."""
        topics = self._load_topics()
        assignment = {
            "topics": {
                t["name"]: {
                    "n_feeds": len(t.get("sources", [])),
                    "gap": len(t.get("sources", [])) < self._cfg.min_feeds_per_topic,
                    "strategy": {},
                }
                for t in topics
            }
        }
        inserted = self._memory.seed_topics(assignment)
        print(f"      seeded {inserted} curated topics from signalflow/topics.json")
        return inserted

    def reseed_topics(self) -> int:
        """Replace the topics table with the curated set (idempotent)."""
        self._memory.clear_topics()
        return self._seed_from_curated()

    # -- diagnostics ---------------------------------------------------------

    def smoke(self) -> int:
        """Fail-fast self-check: opml + memory + embeddings + router chat."""
        print("smoke: opml")
        known_domains, feeds = self._parse_opml(PROJECT_ROOT / "feedly.opml")
        print(f"  ok ({len(feeds)} feeds, {len(known_domains)} domains)")
        print("smoke: memory")
        self._memory.topics()
        print(f"  ok ({len(self._memory.topics())} topics)")
        print("smoke: embeddings")
        vecs = self._embedder.embed(["grid decarbonization", "supply chain logistics"])
        print(f"  ok ({len(vecs[0])}-dim)")
        print("smoke: router chat")
        data = self._llm.chat_json('Respond with JSON only: {"ok": true}', max_tokens=64)
        print(f"  ok ({data})")
        print("SMOKE OK")
        return 0

    def show_topics(self) -> int:
        for t in self._memory.topics():
            regs = ", ".join(t["strategy"].get("registries", [])) or "none"
            print(f"[{t['status']:<8}] {t['feed_count']:>3} feeds | {t['name']} | registries: {regs}")
        return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "run"
    if command == "sources":
        from .source_lists import main as sources_main  # lazy: no Engine needed

        return sources_main(args[1:])
    engine = Engine()
    if command == "smoke":
        return engine.smoke()
    if command == "topics":
        return engine.show_topics()
    if command == "topics-doc":
        path = write_doc(load_topics())
        print(f"wrote {path}")
        return 0
    if command == "reseed":
        count = engine.reseed_topics()
        print(f"reseeded {count} topics from signalflow/topics.json")
        return 0
    if command == "prune":
        removed = engine._memory.prune()
        print(f"pruned {removed} events")
        return 0
    if command == "setup":
        return engine.setup(force="--force" in args)
    if command == "run":
        return engine.run()
    print(
        "usage: python -m signalflow "
        + "[run|setup [--force]|smoke|topics|topics-doc|reseed|prune|sources <topic>]  (default: run)"
    )
    return 2
