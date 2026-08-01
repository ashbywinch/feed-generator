"""FR-6: SQLite semantic memory (history_memory.db).

seen_events holds every approved event with its embedding for cosine dedup
(L3); topics holds the per-user topic model + per-topic discovery strategies
(FR-2 output, seeded from the elicitation spike's assignment.json).
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE,
  title TEXT,
  event_summary TEXT,
  embedding_json TEXT,
  topic TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_seen_events_ts ON seen_events(timestamp);
CREATE TABLE IF NOT EXISTS topics (
  name TEXT PRIMARY KEY,
  status TEXT,
  feed_count INTEGER,
  strategy_json TEXT,
  strategy_revision INTEGER DEFAULT 0
);
"""


class Memory:
    def __init__(self, cfg: Config, db_path: Path) -> None:
        self._cfg = cfg
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- topics (FR-2 table) ------------------------------------------------

    def seed_topics(self, assignment: dict[str, Any]) -> int:
        """Upsert the topic model from the elicitation assignment artifact."""
        inserted = 0
        for name, info in (assignment.get("topics") or {}).items():
            cur = self._conn.execute(
                """
                INSERT INTO topics (name, status, feed_count, strategy_json, strategy_revision)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(name) DO UPDATE SET
                  status = excluded.status,
                  feed_count = excluded.feed_count,
                  strategy_json = excluded.strategy_json
                """,
                (
                    name,
                    "gap" if info.get("gap") else "adequate",
                    info.get("n_feeds", 0),
                    json.dumps(info.get("strategy", {}), ensure_ascii=False),
                ),
            )
            inserted += cur.rowcount
        self._conn.commit()
        return inserted

    def topics(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT name, status, feed_count, strategy_json FROM topics").fetchall()
        return [
            {
                "name": name,
                "status": status,
                "feed_count": feed_count,
                "strategy": json.loads(strategy_json) if strategy_json else {},
            }
            for name, status, feed_count, strategy_json in rows
        ]

    # -- events (FR-6) -------------------------------------------------------

    def has_url(self, url: str) -> bool:
        return self._conn.execute("SELECT 1 FROM seen_events WHERE url = ?", (url,)).fetchone() is not None

    def save_event(self, url: str, title: str, event_summary: str, topic: str, embedding: list[float]) -> bool:
        """Insert; returns False when the URL is already known (idempotent)."""
        try:
            self._conn.execute(
                "INSERT INTO seen_events (url, title, event_summary, embedding_json, topic) VALUES (?, ?, ?, ?, ?)",
                (url, title, event_summary, json.dumps(embedding), topic),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def best_similar(self, embedding: list[float], threshold: float) -> tuple[float, str] | None:
        """Highest cosine vs stored events above `threshold`; (sim, summary)."""
        best: tuple[float, str] | None = None
        for row in self._conn.execute("SELECT event_summary, embedding_json FROM seen_events"):
            past = json.loads(row[1])
            sim = self._cosine(embedding, past)
            if sim >= threshold and (best is None or sim > best[0]):
                best = (sim, row[0])
        return best

    def prune(self) -> int:
        """Drop events older than the retention window (PRD FR-6)."""
        # timestamp is stored as 'YYYY-MM-DD HH:MM:SS' (SQLite CURRENT_TIMESTAMP, UTC);
        # compute the cutoff in that same naive-UTC format.
        from datetime import timedelta

        naive_cutoff = (datetime.now(UTC) - timedelta(days=self._cfg.retention_days)).strftime("%Y-%m-%d %H:%M:%S")
        cur = self._conn.execute("DELETE FROM seen_events WHERE timestamp < ?", (naive_cutoff,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()

    def clear_topics(self) -> None:
        self._conn.execute("DELETE FROM topics")
        self._conn.commit()

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
