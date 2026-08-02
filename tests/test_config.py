"""Config parsing: env overrides + fail-fast on missing keys."""

import pytest

from signalflow.config import Config


def test_from_env_missing_key_fails_fast(monkeypatch):
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        Config.from_env()


def test_from_env_parses_overrides(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    monkeypatch.setenv("OPENCODE_GO_BASE_URL", "https://router/v1")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("SIM_THRESHOLD_HIGH", "0.9")
    monkeypatch.setenv("SIM_THRESHOLD_LOW", "0.5")
    monkeypatch.setenv("EMBED_BATCH", "10")
    monkeypatch.setenv("OPENCODE_GO_MODEL", "kimi-k3")
    cfg = Config.from_env()
    assert cfg.sim_high == 0.9
    assert cfg.sim_low == 0.5
    assert cfg.embed_batch == 10
    assert cfg.llm_model == "kimi-k3"
    assert cfg.embed_interval == 20.0  # research-verified default preserved


def test_weekly_selection_env_overrides(monkeypatch):
    """FR-9 config contract: spike constants surface as env (r14)."""
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    monkeypatch.setenv("OPENCODE_GO_BASE_URL", "https://router/v1")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("RECENCY_DAYS", "10")
    monkeypatch.setenv("MAX_PICKS_PER_SOURCE", "4")
    monkeypatch.setenv("MAX_ITEMS_PER_SOURCE", "40")
    monkeypatch.setenv("FETCH_TTL", "3600")
    monkeypatch.setenv("FAILURE_RETRY_TTL", "7200")
    monkeypatch.setenv("EVAL_INTERVAL", "2.5")
    monkeypatch.setenv("PROMPT_REV", "12")
    monkeypatch.setenv("STORY_MAX_ANGLES", "6")
    monkeypatch.setenv("STORY_MAX_QUESTIONS", "9")
    cfg = Config.from_env()
    assert cfg.weekly_recency_days == 10
    assert cfg.weekly_max_picks_per_source == 4
    assert cfg.weekly_max_items_per_source == 40
    assert cfg.weekly_fetch_ttl == 3600
    assert cfg.weekly_failure_retry_ttl == 7200
    assert cfg.weekly_eval_interval == 2.5
    assert cfg.weekly_prompt_rev == 12
    assert cfg.weekly_story_max_angles == 6
    assert cfg.weekly_story_max_questions == 9


def test_defaults_are_prd_values(cfg):
    assert cfg.sim_high == 0.82
    assert cfg.sim_low == 0.65
    assert cfg.retention_days == 365
    assert cfg.embed_model == "gemini-embedding-001"
    assert cfg.weekly_recency_days == 7  # PRD config table
    assert cfg.weekly_max_picks_per_source == 3
    assert cfg.weekly_max_items_per_source == 30
    assert cfg.weekly_fetch_ttl == 6 * 60 * 60
    assert cfg.weekly_failure_retry_ttl == 24 * 60 * 60
    assert cfg.weekly_eval_interval == 1.0
    assert cfg.weekly_prompt_rev == 9
    assert cfg.weekly_story_max_angles == 5
    assert cfg.weekly_story_max_questions == 8
