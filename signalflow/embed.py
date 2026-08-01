"""Google gemini-embedding client (PRD FR-4 L3).

The router has NO embeddings endpoint (verified). Free-tier quotas are per
model: 100 RPM / 30K TPM / 1,000 RPD, and batchEmbedContents counts each
sub-request toward RPM — hence batch 25 at 20s pacing (75/min, under the
cap). Key travels in a header, never the URL; errors are sanitized.
"""

from __future__ import annotations

import time

import requests

from .config import Config
from .ratelimit import RateLimiter

EMB_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbedError(RuntimeError):
    pass


class Embedder:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._limiter = RateLimiter(cfg.embed_interval)
        self._key = cfg.google_key

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._cfg.embed_batch):
            out.extend(self._batch(texts[i : i + self._cfg.embed_batch]))
            time.sleep(0.5)  # stay under per-minute windows between batches
        return out

    def _batch(self, texts: list[str]) -> list[list[float]]:
        url = f"{EMB_BASE}/models/{self._cfg.embed_model}:batchEmbedContents"
        payload = {
            "requests": [
                {"model": f"models/{self._cfg.embed_model}", "content": {"parts": [{"text": t}]}} for t in texts
            ]
        }
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                resp = requests.post(url, headers={"x-goog-api-key": self._key}, json=payload, timeout=90)
                if resp.status_code == 429:
                    self._limiter.penalty(60)  # rate windows are per-minute
                    last_exc = EmbedError(f"embed HTTP 429 (attempt {attempt + 1})")
                    time.sleep(30)
                    continue
                if resp.status_code >= 500:
                    last_exc = EmbedError(f"embed HTTP {resp.status_code} (attempt {attempt + 1})")
                    time.sleep(5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    raise EmbedError(f"embed HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                if "embeddings" not in data:
                    raise EmbedError(f"embed response missing 'embeddings': {str(data)[:200]}")
                return [e["values"] for e in data["embeddings"]]
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(5 * (attempt + 1))
        raise EmbedError(f"embed failed after retries: {last_exc}") from last_exc
