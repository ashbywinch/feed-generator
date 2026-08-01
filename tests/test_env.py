"""Env loading: .env fills gaps, never overrides the real environment."""

from __future__ import annotations

import os

from signalflow.env import load_env


def test_load_env_fills_and_never_overrides(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_VAR=from_file\nPRESERVED=file_value\n", encoding="utf-8")
    monkeypatch.setenv("PRESERVED", "real_value")
    monkeypatch.delenv("NEW_VAR", raising=False)
    load_env(env_file)
    assert os.environ["NEW_VAR"] == "from_file"
    assert os.environ["PRESERVED"] == "real_value"
