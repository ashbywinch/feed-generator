"""Environment-driven configuration (see docs/prd.md, Config section)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Opencode go router (reasoning)
    llm_key: str
    llm_base: str
    llm_model: str
    # Google embeddings
    embed_model: str
    google_key: str
    # Exa search
    exa_key: str
    # Dedup thresholds (PRD defaults; proposal's 0.85 diagram value rejected)
    sim_high: float = 0.82
    sim_low: float = 0.65
    # Memory
    retention_days: int = 365
    # Discovery caps
    max_candidates_per_topic: int = 25
    # Embedding pacing (research-verified free-tier quota: 100 RPM counts
    # sub-requests; batch 25 at 20s = 75/min, under the cap)
    embed_interval: float = 20.0
    embed_batch: int = 25
    # Coverage
    min_feeds_per_topic: int = 3
    # Publishing
    publish_target: str = "netlify"
    deploy_token: str = ""

    @classmethod
    def from_env(cls) -> Config:
        required = ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL", "GOOGLE_API_KEY")
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            raise SystemExit(f"FATAL: missing env vars: {', '.join(missing)} — check .env")
        return cls(
            llm_key=os.environ["OPENCODE_GO_API_KEY"],
            llm_base=os.environ["OPENCODE_GO_BASE_URL"],
            llm_model=os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash"),
            embed_model=os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"),
            google_key=os.environ["GOOGLE_API_KEY"],
            exa_key=os.environ.get("EXA_API_KEY", ""),
            sim_high=float(os.environ.get("SIM_THRESHOLD_HIGH", "0.82")),
            sim_low=float(os.environ.get("SIM_THRESHOLD_LOW", "0.65")),
            retention_days=int(os.environ.get("RETENTION_DAYS", "365")),
            max_candidates_per_topic=int(os.environ.get("MAX_CANDIDATES_PER_TOPIC", "25")),
            embed_interval=float(os.environ.get("EMBED_INTERVAL", "20.0")),
            embed_batch=int(os.environ.get("EMBED_BATCH", "25")),
            min_feeds_per_topic=int(os.environ.get("MIN_FEEDS_PER_TOPIC", "3")),
            publish_target=os.environ.get("PUBLISH_TARGET", "netlify"),
            deploy_token=os.environ.get("DEPLOY_TOKEN", ""),
        )
