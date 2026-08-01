"""Curated topic set — the final 13 from the walkthrough (PRD FR-2).

Canonical source: signalflow/topics.json. Sources are subscribed feeds that
inform discovery for a topic (a feed may inform several) — NOT a partition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TOPICS_PATH = Path(__file__).resolve().parent / "topics.json"
DOCS_PATH = Path(__file__).resolve().parent.parent / "docs" / "topics.md"


def load_topics() -> list[dict[str, Any]]:
    return json.loads(TOPICS_PATH.read_text(encoding="utf-8"))["topics"]


def render_markdown(topics: list[dict[str, Any]]) -> str:
    lines = ["# SignalFlow — Curated Topic Set", ""]
    lines.append(
        f"{len(topics)} topics. Sources are subscribed feeds that inform discovery "
        "for a topic (a feed may inform several); they are NOT a partition."
    )
    lines.append("")
    for i, t in enumerate(topics, 1):
        lines.append(f"## {i}. {t['name']}")
        lines.append("")
        lines.append(t["description"])
        lines.append("")
        lines.append(f"- **In:** {t['in']}")
        lines.append(f"- **Out:** {t['out']}")
        if t.get("sources"):
            lines.append(f"- **Sources:** {', '.join(t['sources'])}")
        lines.append("")
    return "\n".join(lines)


def write_doc(topics: list[dict[str, Any]]) -> Path:
    DOCS_PATH.write_text(render_markdown(topics), encoding="utf-8")
    return DOCS_PATH
