"""FR-8: daily engine orchestration + CLI.

One daily run: parse OPML -> (topic model already seeded from elicitation)
-> discover (registries + Exa per topic strategy) -> dedup (4 layers) ->
store -> digest -> publish -> prune. Idempotent by construction: dedup L2 +
URL-unique inserts mean a re-run emits no duplicates.
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

    # -- daily run (FR-8) ----------------------------------------------------

    def run(self) -> int:
        print("[1/6] engine: OPML + memory")
        known_domains, feeds = parse_opml(PROJECT_ROOT / "feedly.opml")
        print(f"      {len(feeds)} feeds, {len(known_domains)} blacklist domains")
        self._seed_topics_if_empty()

        print("[2/6] discovery (registries + Exa per topic strategy)")
        topics = self._memory.topics()
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

    def _seed_topics_if_empty(self) -> None:
        if self._memory.topics():
            print("      topics table already populated")
            return
        self._seed_from_curated()

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
    engine = Engine()
    command = args[0] if args else "run"
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
    if command == "run":
        return engine.run()
    print("usage: python -m signalflow [run|smoke|topics|prune]  (default: run)")
    return 2
