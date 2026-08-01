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


def _post_raw(body):
    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return body

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


def test_chat_tools_passes_tools_and_returns_message(cfg, monkeypatch):
    message = {
        "role": "assistant",
        "content": "done",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"x"}'}}
        ],
    }
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen["json"] = json
        return _post_raw({"choices": [{"message": message}]})

    monkeypatch.setattr("signalflow.llm.requests.post", post)
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    out = LLM(cfg).chat_tools([{"role": "user", "content": "hi"}], tools)
    assert out == message
    assert seen["json"]["tools"] == tools
    assert "response_format" not in seen["json"]  # never mixed with tools


def test_chat_tools_redacts_keys_on_error(cfg, monkeypatch):
    def post(url, headers=None, json=None, timeout=None):
        raise requests.ConnectionError(f"auth failed for {cfg.llm_key}")

    monkeypatch.setattr("signalflow.llm.requests.post", post)
    with pytest.raises(LLMError) as ei:
        LLM(cfg).chat_tools([], [])
    assert cfg.llm_key not in str(ei.value)


def test_chat_tools_malformed_response_is_llm_error(cfg, monkeypatch):
    def post(url, headers=None, json=None, timeout=None):
        return _post_raw({"error": "boom"})  # 200 but no choices[0]

    monkeypatch.setattr("signalflow.llm.requests.post", post)
    with pytest.raises(LLMError):
        LLM(cfg).chat_tools([], [])


def test_keys_never_leak_into_errors(cfg, monkeypatch):
    monkeypatch.setattr("signalflow.llm.requests.post", lambda *a, **k: _post(content="garbage"))
    with pytest.raises(LLMError) as ei:
        LLM(cfg).chat_json("hi")
    assert cfg.llm_key not in str(ei.value)
    assert cfg.google_key not in str(ei.value)
