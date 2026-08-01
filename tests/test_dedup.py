"""Four-layer dedup pipeline: L1 blacklist, L2 seen URL, L3 cosine, L4 delta.

Deterministic fakes: the embedder maps event-text markers to fixed vectors,
the LLM reads the candidate title from the prompt. No real APIs involved.
"""

from __future__ import annotations

import re
from typing import Any

from signalflow.config import Config
from signalflow.dedup import DedupPipeline
from signalflow.embed import Embedder
from signalflow.llm import LLM
from signalflow.memory import Memory
from signalflow.models import Candidate


class FakeEmbedder(Embedder):
    """dup -> [1,0,0], band -> [0.8,0.6,0], anything else -> [0,0,1]."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self.calls: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.extend(texts)
        out: list[list[float]] = []
        for t in texts:
            low = t.lower()
            if "dup" in low:
                out.append([1.0, 0.0, 0.0])
            elif "band" in low:
                out.append([0.8, 0.6, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out


class FakeLLM(LLM):
    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self.evaluated: list[str] = []

    def chat_json(self, prompt: str, **kwargs) -> dict[str, Any]:
        if "evaluation gate" in prompt:
            self.evaluated.append(prompt)
            title = re.search(r"Title: ([^\n]+)", prompt)
            assert title is not None
            return {
                "is_approved": "reject" not in title.group(1).lower(),
                "topic": "T",
                "empirical_event": title.group(1).lower(),
                "core_thesis": "thesis",
            }
        new_event = re.search(r"New candidate empirical event: ([^\n]+)", prompt)
        assert new_event is not None
        return {"has_new_info": "yes" in new_event.group(1), "reason": "r"}


def _pipeline(tmp_path, cfg, known_domains: set[str]):
    mem = Memory(cfg, tmp_path / "test.db")
    llm = FakeLLM(cfg)
    emb = FakeEmbedder(cfg)
    return DedupPipeline(cfg, known_domains, mem, llm, emb), mem, llm, emb


def test_all_four_layers(cfg, tmp_path):
    pipe, mem, llm, _ = _pipeline(tmp_path, cfg, known_domains={"subscribed.com"})
    mem.save_event("https://baseline.example/e", "b", "past", "T", [1.0, 0.0, 0.0])
    mem.save_event("https://seen.example/a", "s", "seen", "T", [0.0, 1.0, 0.0])

    def cand(url: str, title: str = "new event") -> Candidate:
        return Candidate(title=title, summary="", url=url, source_tier="search")

    candidates = [
        cand("https://www.subscribed.com/x", "anything"),  # L1: subscribed domain
        cand("https://x.example/reject", "reject hype article"),  # not approved
        cand("https://x.example/dup", "dup event coverage"),  # L3: cos 1.0
        cand("https://x.example/bandno", "band event no new data"),  # L4: delta no
        cand("https://x.example/bandyes", "band event yes new milestone"),  # L4: delta yes
        cand("https://x.example/new", "new event fresh data"),  # approved
        cand("https://seen.example/a", "dup again"),  # L2: seen URL
    ]
    approved = pipe.process(candidates)
    urls = {e.candidate.url for e in approved}
    assert urls == {"https://x.example/bandyes", "https://x.example/new"}
    assert mem.has_url("https://x.example/bandyes")
    assert mem.has_url("https://x.example/new")
    assert not mem.has_url("https://x.example/dup")
    assert not mem.has_url("https://x.example/bandno")
    # LLM never called for L1-blacklisted or L2-seen candidates: exactly 5 evaluations
    assert len(llm.evaluated) == 5


def test_duplicate_candidate_url_not_stored_twice(cfg, tmp_path):
    pipe, mem, _, _ = _pipeline(tmp_path, cfg, known_domains=set())
    cand = Candidate(title="new event alpha", summary="", url="https://x.example/alpha", source_tier="search")
    first = pipe.process([cand])
    second = pipe.process([cand])  # re-run same day: L2 blocks
    assert len(first) == 1
    assert len(second) == 0
    assert mem.has_url("https://x.example/alpha")
