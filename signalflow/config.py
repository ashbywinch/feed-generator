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
    # Setup: refuse to persist a blacklist that dropped below this fraction of
    # the previously stored set (truncated-export guard; PRD zero-duplication).
    min_blacklist_ratio: float = 0.5
    # FR-9 weekly selection (PRD config table: spike constants moved here)
    weekly_recency_days: int = 7
    weekly_max_picks_per_source: int = 3
    weekly_max_items_per_source: int = 30
    weekly_fetch_ttl: int = 6 * 60 * 60  # same-day re-runs reuse cached items
    weekly_failure_retry_ttl: int = 24 * 60 * 60  # re-fetch a failed feed after this long
    weekly_eval_interval: float = 1.0  # seconds between router chat calls
    weekly_prompt_rev: int = 9  # bump when the eval prompt changes -> stale verdicts ignored
    weekly_story_max_angles: int = 5  # angle lines kept per subarea
    weekly_story_max_questions: int = 8  # open questions kept per topic
    # Eval-gate thresholds (r15: eval scripts must share the Config env surface
    # so evals and the weekly pipeline cannot silently drift apart)
    eval_pass_frac: float = 0.75  # story eval: fraction of articles that must contextualize
    eval_max_articles: int = 4  # story eval: held-out articles judged per run
    eval_overview_min_words: int = 50  # story eval: overview length floor
    eval_min_declarative: int = 2  # story eval: declarative sentences per subarea section
    eval_max_question_frac: float = 0.35  # story eval: interrogative ceiling per section
    eval_min_queries: int = 5  # queries eval: lower bound on query count
    eval_query_slack: int = 2  # queries eval: extras beyond one-per-subarea tolerated
    eval_max_uncovered: int = 3  # queries eval: subareas a set may leave out
    # FR-8 recurring schedule (PRD config table; DAILY_CRON/WEEKLY_CRON merged)
    recurring_cron: str = "0 6 * * *"
    # FR-9 spike infrastructure (r21: Config-never-hardcoded — thresholds and
    # budgets live here with env defaults, one place for engine + spikes)
    weekly_fetch_workers: int = 12
    weekly_fetch_timeout: int = 12  # seconds
    weekly_feed_cap_bytes: int = 300_000  # feed body cap; truncation flagged, never silent
    weekly_junk_title_markers: tuple[str, ...] = ("factsheet", "fact sheet")  # boilerplate docs filtered pre-LLM
    llm_max_tokens: int = 8192
    # Multi-topic weekly runner (spike-weekly-all): concurrent topics, site layout
    weekly_workers: int = 3  # topics regenerated at a time (3 threads)
    site_base_url: str = "https://signalflow.local"  # placeholder until hosting decided (OQ-3)
    # Publishing
    publish_target: str = "netlify"
    deploy_token: str = ""

    @classmethod
    def from_env(cls) -> Config:
        """Strict loader: raise if any required key is missing (engine paths)."""
        return cls._from_env(required=True)

    @classmethod
    def from_env_optional(cls) -> Config:
        """Tolerant loader: read env with defaults when keys are missing.

        The spike scripts construct Config at module import time, which runs in
        CI (no keys) — but they MUST honor env overrides (PROMPT_REV,
        RECENCY_DAYS, EVAL_PASS_FRAC, ...) in real runs. One loader keeps the
        Config env surface as the single source of truth for both (r19).
        """
        return cls._from_env(required=False)

    @classmethod
    def _from_env(cls, required: bool) -> Config:
        required_vars = ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL", "GOOGLE_API_KEY")
        missing = [v for v in required_vars if not os.environ.get(v)]
        if required and missing:
            raise SystemExit(f"FATAL: missing env vars: {', '.join(missing)} — check .env")
        return cls(
            llm_key=os.environ.get("OPENCODE_GO_API_KEY", ""),
            llm_base=os.environ.get("OPENCODE_GO_BASE_URL", ""),
            llm_model=os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash"),
            embed_model=os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"),
            google_key=os.environ.get("GOOGLE_API_KEY", ""),
            exa_key=os.environ.get("EXA_API_KEY", ""),
            sim_high=float(os.environ.get("SIM_THRESHOLD_HIGH", "0.82")),
            sim_low=float(os.environ.get("SIM_THRESHOLD_LOW", "0.65")),
            retention_days=int(os.environ.get("RETENTION_DAYS", "365")),
            max_candidates_per_topic=int(os.environ.get("MAX_CANDIDATES_PER_TOPIC", "25")),
            embed_interval=float(os.environ.get("EMBED_INTERVAL", "20.0")),
            embed_batch=int(os.environ.get("EMBED_BATCH", "25")),
            min_feeds_per_topic=int(os.environ.get("MIN_FEEDS_PER_TOPIC", "3")),
            min_blacklist_ratio=float(os.environ.get("MIN_BLACKLIST_RATIO", "0.5")),
            weekly_recency_days=int(os.environ.get("RECENCY_DAYS", "7")),
            weekly_max_picks_per_source=int(os.environ.get("MAX_PICKS_PER_SOURCE", "3")),
            weekly_max_items_per_source=int(os.environ.get("MAX_ITEMS_PER_SOURCE", "30")),
            weekly_fetch_ttl=int(os.environ.get("FETCH_TTL", str(6 * 60 * 60))),
            weekly_failure_retry_ttl=int(os.environ.get("FAILURE_RETRY_TTL", str(24 * 60 * 60))),
            weekly_eval_interval=float(os.environ.get("EVAL_INTERVAL", "1.0")),
            weekly_prompt_rev=int(os.environ.get("PROMPT_REV", "9")),
            weekly_story_max_angles=int(os.environ.get("STORY_MAX_ANGLES", "5")),
            weekly_story_max_questions=int(os.environ.get("STORY_MAX_QUESTIONS", "8")),
            eval_pass_frac=float(os.environ.get("EVAL_PASS_FRAC", "0.75")),
            eval_max_articles=int(os.environ.get("EVAL_MAX_ARTICLES", "4")),
            eval_overview_min_words=int(os.environ.get("EVAL_OVERVIEW_MIN_WORDS", "50")),
            eval_min_declarative=int(os.environ.get("EVAL_MIN_DECLARATIVE", "2")),
            eval_max_question_frac=float(os.environ.get("EVAL_MAX_QUESTION_FRAC", "0.35")),
            eval_min_queries=int(os.environ.get("EVAL_MIN_QUERIES", "5")),
            eval_query_slack=int(os.environ.get("EVAL_QUERY_SLACK", "2")),
            eval_max_uncovered=int(os.environ.get("EVAL_MAX_UNCOVERED", "3")),
            recurring_cron=os.environ.get("RECURRING_CRON", "0 6 * * *"),
            weekly_fetch_workers=int(os.environ.get("FETCH_WORKERS", "12")),
            weekly_fetch_timeout=int(os.environ.get("FETCH_TIMEOUT", "12")),
            weekly_feed_cap_bytes=int(os.environ.get("FEED_CAP_BYTES", "300000")),
            weekly_junk_title_markers=tuple(
                m.strip() for m in os.environ.get("JUNK_TITLE_MARKERS", "factsheet,fact sheet").split(",") if m.strip()
            ),
            llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "8192")),
            weekly_workers=int(os.environ.get("WEEKLY_WORKERS", "3")),
            site_base_url=os.environ.get("SITE_BASE_URL", "https://signalflow.local"),
            publish_target=os.environ.get("PUBLISH_TARGET", "netlify"),
            deploy_token=os.environ.get("DEPLOY_TOKEN", ""),
        )
