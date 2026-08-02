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
    def __init__(self) -> None:
        load_env()
        self._cfg = Config.from_env()
        self._memory = Memory(self._cfg, DB_PATH)
        self._llm = LLM(self._cfg)
        self._embedder = Embedder(self._cfg)

    # -- setup (FR-1/FR-2: one-and-done) -------------------------------------

    def setup(self) -> int:
        """One-and-done: parse OPML, persist exclusion set + curated topics.

        Re-run only when the user adds/removes a topic. The recurring run
        (`run`) reads the stored blacklist and topics — it never touches OPML.
        """
        print("[setup] OPML -> exclusion set + topics")
        known_domains, feeds = parse_opml(PROJECT_ROOT / "feedly.opml")
        if not known_domains:
            print("FATAL: OPML parsed zero domains — refusing to persist an empty exclusion set")
            print("       (corrupt/truncated feedly.opml? fix it, then re-run setup)")
            return 1
        self._memory.save_blacklist(known_domains)
        print(f"      {len(feeds)} feeds, {len(known_domains)} blacklist domains stored")
        self._seed_from_curated()
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
        candidates = Discovery(self._cfg).discover(topics)
        print(f"      {len(candidates)} candidates across {len(topics)} topics")

        print("[3/6] dedup (L1-L4) + evaluation")
        pipeline = DedupPipeline(self._cfg, known_domains, self._memory, self._llm, self._embedder)
        events = pipeline.process(candidates)

        print("[4/6] digest")
        if events:
            build_digest(self._cfg, events, DIGEST_PATH)
            publish(self._cfg, DIGEST_PATH)
        else:
            print("      no new events — keeping previous digest")

        print("[5/6] prune")
        removed = self._memory.prune()
        print(f"      pruned {removed} events older than {self._cfg.retention_days} days")

        print("[6/6] done")
        return 0

    def _seed_from_curated(self) -> int:
        """Seed the topics table from the curated topics.json (walkthrough final set)."""
        topics = load_topics()
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
        known_domains, feeds = parse_opml(PROJECT_ROOT / "feedly.opml")
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
        return engine.setup()
    if command == "run":
        return engine.run()
    print(
        "usage: python -m signalflow "
        + "[run|setup|smoke|topics|topics-doc|reseed|prune|sources <topic>]  (default: run)"
    )
    return 2
