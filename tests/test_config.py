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


def test_defaults_are_prd_values(cfg):
    assert cfg.sim_high == 0.82
    assert cfg.sim_low == 0.65
    assert cfg.retention_days == 365
    assert cfg.embed_model == "gemini-embedding-001"
