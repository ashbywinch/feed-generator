"""FR-4/FR-5: four-layer dedup pipeline + LLM evaluation.

Order matters — cheapest first, and the LLM is never called before L2:
  L1 domain blacklist (subscribed) -> discard
  L2 exact URL hash (already seen) -> discard
  LLM evaluation (approve? topic, empirical_event, core_thesis)
  L3 vector cosine vs memory       -> sim > high: discard; low..high: L4
  L4 delta evaluator               -> "new data beyond recorded?" no: discard
Approved events are stored with their embedding (FR-6).
"""

from __future__ import annotations

from urllib.parse import urlparse

from .config import Config
from .embed import Embedder
from .llm import LLM
from .memory import Memory
from .models import Analysis, ApprovedEvent, Candidate

EVALUATE_PROMPT = """You are the evaluation gate for a personal discovery engine.

Candidate article for an expert reader in systems engineering, macro, applied technology, and history:
Title: {title}
URL: {url}
Summary: {summary}

Available topics (choose the best-matching one, verbatim):
{topics}

STRICT SELECTION CRITERIA:
- MUST describe a NEW empirical event, observed data shift, policy enactment,
  program stage-gate transition, or first-principles systems analysis.
- MUST NOT be speculative hype, political horse-race coverage, or shallow reporting.

Respond with STRICT JSON only:
{{"is_approved": true/false, "topic": "<verbatim topic or ''>",
 "empirical_event": "<1 sentence: the observed event/data>",
 "core_thesis": "<1 sentence: the structural argument>"}}
"""

DELTA_PROMPT = """An event was previously surfaced and stored:
Recorded on {date}: {past_event}

New candidate empirical event: {new_event}

Does the candidate provide NEW empirical data or a structural shift beyond
what was already recorded? (Follow-up commentary repeating the same facts
does NOT count.)

Respond with STRICT JSON only: {{"has_new_info": true/false, "reason": "<one short sentence>"}}
"""


class DedupPipeline:
    def __init__(self, cfg: Config, known_domains: set[str], memory: Memory, llm: LLM, embedder: Embedder) -> None:
        self._cfg = cfg
        self._known_domains = known_domains
        self._memory = memory
        self._llm = llm
        self._embedder = embedder
        self._topics = [t["name"] for t in memory.topics()]

    def process(self, candidates: list[Candidate]) -> list[ApprovedEvent]:
        approved: list[ApprovedEvent] = []
        stats = {"l1": 0, "l2": 0, "rejected": 0, "l3": 0, "l4": 0}
        for c in candidates:
            if self._l1_blocked(c):
                stats["l1"] += 1
                continue
            if self._memory.has_url(c.url):
                stats["l2"] += 1
                continue
            analysis = self._evaluate(c)
            if not analysis.approved:
                stats["rejected"] += 1
                continue
            embedding = self._embedder.embed([analysis.empirical_event])[0]
            sim = self._memory.best_similar(embedding, self._cfg.sim_low)
            if sim is not None and sim[0] >= self._cfg.sim_high:
                stats["l3"] += 1
                continue
            if (
                sim is not None
                and self._cfg.sim_low <= sim[0] < self._cfg.sim_high
                and not self._delta_has_new_info(sim[1], analysis.empirical_event)
            ):
                stats["l4"] += 1
                continue
            event = ApprovedEvent(candidate=c, analysis=analysis, embedding=embedding)
            self._memory.save_event(c.url, c.title, analysis.empirical_event, analysis.topic, embedding)
            approved.append(event)
        print(
            f"      dedup: {len(candidates)} in -> {len(approved)} approved "
            f"(L1 blacklist {stats['l1']}, L2 seen {stats['l2']}, "
            f"rejected {stats['rejected']}, L3 dup {stats['l3']}, L4 no-delta {stats['l4']})"
        )
        return approved

    def _l1_blocked(self, c: Candidate) -> bool:
        host = urlparse(c.url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return any(kd in host for kd in self._known_domains)

    def _evaluate(self, c: Candidate) -> Analysis:
        topics = "\n".join(f"- {t}" for t in self._topics) or "(none — candidate may define a new one)"
        data = self._llm.chat_json(
            EVALUATE_PROMPT.format(title=c.title, url=c.url, summary=c.summary[:800], topics=topics)
        )
        return Analysis.from_dict(data)

    def _delta_has_new_info(self, past_event: str, new_event: str) -> bool:
        data = self._llm.chat_json(
            DELTA_PROMPT.format(date="the recorded date", past_event=past_event[:300], new_event=new_event[:300])
        )
        return bool(data.get("has_new_info"))
