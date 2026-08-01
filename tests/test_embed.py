"""Embed client: batch splitting, key-in-header (never URL), 429 backoff."""

from typing import Any

import pytest

from signalflow.config import Config
from signalflow.embed import Embedder, EmbedError


def _cfg(**over):
    base: dict[str, Any] = dict(
        llm_key="k",
        llm_base="https://r/v1",
        llm_model="m",
        embed_model="gemini-embedding-001",
        google_key="g-test-key",
        exa_key="",
        embed_batch=2,
        embed_interval=0.0,
    )
    base.update(over)
    return Config(**base)


def test_batch_splitting_and_key_header(cfg, monkeypatch):
    calls = []

    def post(url, headers=None, json: dict[str, Any] | None = None, timeout=None):
        calls.append((url, headers, json))
        assert json is not None
        n = len(json["requests"])
        return _resp(200, {"embeddings": [{"values": [1.0, 0.0]} for _ in range(n)]})

    monkeypatch.setattr("signalflow.embed.requests.post", post)
    out = Embedder(_cfg(embed_batch=2)).embed(["a", "b", "c"])
    assert len(out) == 3
    assert len(calls) == 2  # 3 texts / batch 2 -> 2 calls
    url, headers, _ = calls[0]
    assert "gemini-embedding-001" in url
    assert cfg.google_key not in url  # key NEVER in the URL
    assert headers.get("x-goog-api-key") == cfg.google_key


def test_429_retries_then_sanitized_error(cfg, monkeypatch):
    monkeypatch.setattr("signalflow.embed.time.sleep", lambda s: None)  # no real waits
    seq = [_resp(429, {"error": "quota"}) for _ in range(4)]

    def post(url, headers=None, json=None, timeout=None):
        return seq.pop(0)

    monkeypatch.setattr("signalflow.embed.requests.post", post)
    with pytest.raises(EmbedError) as ei:
        Embedder(_cfg()).embed(["x"])
    assert cfg.google_key not in str(ei.value)


def _resp(status, body):
    class R:
        status_code = status
        text = str(body)

        def raise_for_status(self):
            pass

        def json(self):
            return body

    return R()
