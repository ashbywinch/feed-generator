"""Shared test fixtures: a Config and a fake HTTP response."""

from __future__ import annotations

import pytest
import requests

from signalflow.config import Config


@pytest.fixture
def cfg():
    """Minimal Config with dummy keys — tests never touch real APIs."""
    return Config(
        llm_key="k-test",
        llm_base="https://router.test/v1",
        llm_model="deepseek-v4-flash",
        embed_model="gemini-embedding-001",
        google_key="g-test-key",
        exa_key="e-test-key",
    )


class FakeResponse:
    def __init__(self, status: int, body) -> None:
        self.status_code = status
        self._body = body

    @property
    def text(self) -> str:
        return str(self._body)[:200]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


@pytest.fixture
def fake_response():
    return FakeResponse
