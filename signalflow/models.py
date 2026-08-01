"""Pipeline data types (PRD Key Terms)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    """A raw ingestion item (FR-2 discovery output)."""

    title: str
    summary: str
    url: str
    source_tier: str  # "registry" | "search"
    topic: str = ""


@dataclass
class Analysis:
    """LLM evaluation output (FR-5), strict JSON schema."""

    approved: bool
    topic: str
    empirical_event: str
    core_thesis: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Analysis:
        return cls(
            approved=bool(data.get("is_approved")),
            topic=str(data.get("topic", "")),
            empirical_event=str(data.get("empirical_event", "")),
            core_thesis=str(data.get("core_thesis", "")),
        )


@dataclass
class ApprovedEvent:
    """An event that cleared all four dedup layers (FR-4) and is stored (FR-6)."""

    candidate: Candidate
    analysis: Analysis
    embedding: list[float] = field(default_factory=list)
