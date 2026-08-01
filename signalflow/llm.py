"""Opencode go router client (OpenAI-compatible; PRD External Services).

All reasoning goes through this router under one key. deepseek-v4-flash is a
reasoning model, so `thinking: disabled` is used for structured output (its
reasoning tokens otherwise eat the budget and leave content empty).
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from .config import Config


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def chat_json(self, prompt: str, *, max_tokens: int = 4096, temperature: float = 0.2) -> dict[str, Any]:
        """Structured JSON completion. Retries once without response_format."""
        payload = {
            "model": self._cfg.llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._cfg.llm_key}"}
        url = f"{self._cfg.llm_base}/chat/completions"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
        except requests.HTTPError:
            payload.pop("response_format", None)  # some router models reject it
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(self._redact(str(exc))) from exc
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                return json.loads(m.group(0))
            raise LLMError(f"non-JSON LLM response: {self._redact(content[:200])}") from None

    def chat_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Raw chat completion with tool calling; returns the assistant message
        (carrying either `content` or `tool_calls`). No response_format — mixing
        it with tools is rejected by some router models."""
        payload = {
            "model": self._cfg.llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "thinking": {"type": "disabled"},
            "tools": tools,
        }
        headers = {"Authorization": f"Bearer {self._cfg.llm_key}"}
        url = f"{self._cfg.llm_base}/chat/completions"
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(self._redact(str(exc))) from exc
        return resp.json()["choices"][0]["message"]

    def _redact(self, message: str) -> str:
        for secret in (self._cfg.llm_key, self._cfg.google_key):
            if secret:
                message = message.replace(secret, "***")
        return message
