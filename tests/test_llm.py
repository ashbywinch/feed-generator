"""Router chat client: JSON mode, response_format fallback, key redaction."""

from typing import Any

import pytest
import requests

from signalflow.llm import LLM, LLMError


def _post(status=200, content='{"ok": true}'):
    class R:
        status_code = status

        def raise_for_status(self):
            if status >= 400:
                raise requests.HTTPError(f"HTTP {status}")

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return R()


def test_chat_json_ok(cfg, monkeypatch):
    monkeypatch.setattr("signalflow.llm.requests.post", lambda *a, **k: _post())
    assert LLM(cfg).chat_json("hi") == {"ok": True}


def test_retries_without_response_format_on_http_error(cfg, monkeypatch):
    calls = []

    def side(url, headers=None, json: dict[str, Any] | None = None, timeout=None):
        calls.append(json)
        assert json is not None
        if json.get("response_format"):
            raise requests.HTTPError("400")
        return _post()

    monkeypatch.setattr("signalflow.llm.requests.post", side)
    assert LLM(cfg).chat_json("hi") == {"ok": True}
    assert calls[-1].get("response_format") is None


def test_non_json_content_raises(cfg, monkeypatch):
    monkeypatch.setattr("signalflow.llm.requests.post", lambda *a, **k: _post(content="plain text"))
    with pytest.raises(LLMError):
        LLM(cfg).chat_json("hi")


def test_keys_never_leak_into_errors(cfg, monkeypatch):
    monkeypatch.setattr("signalflow.llm.requests.post", lambda *a, **k: _post(content="garbage"))
    with pytest.raises(LLMError) as ei:
        LLM(cfg).chat_json("hi")
    assert cfg.llm_key not in str(ei.value)
    assert cfg.google_key not in str(ei.value)
