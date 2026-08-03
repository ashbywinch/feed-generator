#!/usr/bin/env python3
"""FR-2 topic-elicitation spike, resumable (copy of topic_elicitation.py).

Pipeline: OPML -> sample recent items per feed (feedparser) -> embed fragments
(gemini-embedding-001 via Google batchEmbedContents) -> spherical k-means over
item embeddings -> feed plurality mapping -> name each topic + draft per-topic
strategy (deepseek-v4-flash via the Opencode go router) -> coverage report.

Resumability: every expensive step is persisted under spikes/state/ the
moment it completes, so a re-run only does the missing work:

  samples.jsonl     one line per sampled feed, keyed by xmlUrl. A feed with
                    cached items is never re-fetched. A feed whose last
                    attempt FAILED is retried after FAILURE_RETRY_TTL, so a
                    transient outage is never cached as permanent deadness.
  embeddings.jsonl  one line per embedded batch, keyed by fragment text.
                    Only fragments not already cached are embedded.
  names.json        cluster signature (sorted feed URLs) -> LLM naming
                    result. Only clusters not already named are sent to the
                    LLM; a failed naming is NOT cached and is retried.

Crash recovery is just re-running the script: completed batches are
skipped, nothing is lost or redone. New feeds appearing in the OPML are
picked up automatically — their sampling/embedding/naming is the only new
work, and clusters that grow/shrink are re-named while unchanged clusters
keep their cached names. Files are written to a temp path and atomically
renamed (or append-only JSONL) so a crash never corrupts the caches.

To start completely fresh, delete spikes/state/.

Concurrency & rate limiting: feed sampling runs in a thread pool (network
bound, no quota). Embedding and naming run on bounded worker queues, and
every external-API call is paced by ONE shared RateLimiter per API — all
workers contend on the same limiter, so thread count can never burst past
a per-minute quota (Google free tier 429s on batch >25 or rapid calls).

Run: make spike   (or: .venv/bin/python spikes/topic_elicitation_resumable.py)

Never prints API keys. Errors are truncated.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.env import load_env  # noqa: E402

load_env(ROOT / ".env")

OPML_PATH = ROOT / "feedly.opml"
OUT_DIR = ROOT / "spikes" / "output"
STATE_DIR = ROOT / "spikes" / "state"
SAMPLES_PATH = STATE_DIR / "samples.jsonl"
EMBEDDINGS_PATH = STATE_DIR / "embeddings.jsonl"
NAMES_PATH = STATE_DIR / "names.json"
INTEGRITY_PATH = STATE_DIR / "integrity.json"
ASSIGNMENT_PATH = STATE_DIR / "assignment.json"

EMB_BASE = "https://generativelanguage.googleapis.com/v1beta"
EMB_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-2")
GOOGLE_KEY = os.environ["GOOGLE_API_KEY"]
LLM_BASE = os.environ["OPENCODE_GO_BASE_URL"]
LLM_KEY = os.environ["OPENCODE_GO_API_KEY"]
LLM_MODEL = os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash")

SAMPLE_ITEMS = 4
FETCH_WORKERS = 12
FETCH_TIMEOUT = 12
BATCH_SIZE = 25  # >25 trips the Google free-tier quota (verified: 100 -> 429)
MIN_FEEDS_PER_TOPIC = 3  # PRD config default
FAILURE_RETRY_TTL = 24 * 60 * 60  # re-fetch a failed feed after this long
INTEGRITY_TTL = 7 * 24 * 60 * 60  # re-audit feed integrity weekly

# Free-tier quotas (research-verified): 100 RPM / 30K TPM / 1,000 RPD per model.
# batchEmbedContents counts EACH sub-request toward RPM — batch=25 at 6s pacing
# = 250 sub-reqs/min, 2.5x over the cap (that caused the 429 wall). 20s pacing
# x 25 = 75/min, under the cap. Known Jan-2026 anomaly: 429 even under quota;
# on 429 back off 30s, and exit cleanly (QUOTA_DEAD) if it persists.
EMBED_INTERVAL = 20.0
EMBED_429_SLEEP = 30.0
EMBED_WORKERS = 2
NAMING_INTERVAL = 1.0  # seconds between router chat calls
NAMING_WORKERS = 3
LLM_MAX_TOKENS = 8192  # reasoning disabled below; cap raised as belt-and-braces

APPEND_LOCK = threading.Lock()  # serialize JSONL appends from worker threads
QUOTA_DEAD = threading.Event()  # set when embedding 429s persist: stop, exit clean, resume later


def parse_opml(path: Path) -> list[dict[str, Any]]:
    """FR-1: feeds with folder, title, xmlUrl. URL-shaped categories are junk, never topics."""
    root = ET.parse(path).getroot()
    body = root.find("body")
    if body is None:
        return []
    feeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in body.findall("outline"):
        folder = cat.get("text") or cat.get("title") or "Uncategorized"
        if re.match(r"^https?://", folder):
            # Mis-imported subscription: URL became a folder name. Feeds are
            # still subscribed — blacklist them, don't topic-label them.
            folder = "Uncategorized"
        for f in cat.findall(".//outline"):
            url = f.get("xmlUrl")
            if not url or url in seen:
                continue
            seen.add(url)
            feeds.append({"folder": folder, "title": f.get("title") or f.get("text") or url, "url": url})
    return feeds


# --- disk cache helpers ---------------------------------------------------


def load_samples() -> dict[str, dict[str, Any]]:
    """url -> latest cached sample entry (last line per url wins)."""
    out: dict[str, dict[str, Any]] = {}
    if not SAMPLES_PATH.exists():
        return out
    for line in SAMPLES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn tail line from a crash; that work is redone
        out[entry["url"]] = entry
    return out


def append_sample(entry: dict[str, Any]) -> None:
    with APPEND_LOCK, SAMPLES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def sample_age(cached: dict[str, Any]) -> float:
    """Seconds since the cached sample was taken; unknown age retries."""
    try:
        return time.time() - datetime.fromisoformat(cached["sampled_at"]).timestamp()
    except (ValueError, TypeError, KeyError):
        return float("inf")


def load_embeddings() -> dict[str, list[float]]:
    """fragment text -> embedding vector."""
    out: dict[str, list[float]] = {}
    if not EMBEDDINGS_PATH.exists():
        return out
    for line in EMBEDDINGS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            batch = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn tail line from a crash; those fragments are re-embedded
        for text, vec in zip(batch["fragments"], batch["embeddings"], strict=True):
            out[text] = vec
    return out


def append_embeddings(fragments: list[str], vecs: list[list[float]]) -> None:
    with APPEND_LOCK, EMBEDDINGS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"fragments": fragments, "embeddings": vecs}, ensure_ascii=False) + "\n")


def load_names() -> dict[str, dict[str, Any]]:
    if not NAMES_PATH.exists():
        return {}
    try:
        return json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"  warning: {NAMES_PATH.relative_to(ROOT)} unreadable; naming starts fresh")
        return {}


def save_names(names: dict[str, dict[str, Any]]) -> None:
    """Atomic replace so a crash never corrupts the whole cache."""
    tmp = NAMES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(names, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(NAMES_PATH)


def load_integrity() -> dict[str, str] | None:
    """Cached integrity flags, or None if absent/stale (> INTEGRITY_TTL)."""
    if not INTEGRITY_PATH.exists():
        return None
    try:
        data = json.loads(INTEGRITY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if time.time() - data.get("audited_at", 0) > INTEGRITY_TTL:
        return None
    return data.get("flagged", {})


def save_integrity(flagged: dict[str, str]) -> None:
    """Atomic persist so resume runs skip the LLM re-audit within the TTL."""
    tmp = INTEGRITY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"audited_at": time.time(), "flagged": flagged}, indent=2) + "\n")
    tmp.replace(INTEGRITY_PATH)


def cluster_signature(cluster: list[dict[str, Any]]) -> str:
    """Stable cache key for a cluster: its sorted feed URLs."""
    return json.dumps(sorted(f["url"] for f in cluster), ensure_ascii=False)


# --- pipeline steps ---------------------------------------------------------


class RateLimiter:
    """Thread-safe global pacing: at most one call per `interval` seconds.

    wait() sleeps holding the lock, so the next slot is booked before any
    other thread can grab it — concurrent workers can never fire a burst.
    penalty() postpones the slot after a quota error (e.g. 429).
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._next_at > now:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = now + self._interval

    def penalty(self, seconds: float) -> None:
        with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + seconds)


def redact(message: str) -> str:
    """Strip known API keys from any message before it is logged or printed."""
    for secret in (GOOGLE_KEY, LLM_KEY):
        if secret:
            message = message.replace(secret, "***")
    return message


def smoke_test() -> None:
    """Fail fast on config/auth/model errors before the long pipeline.

    One chat call + one embed call: a 401 key or 404 model id surfaces in
    seconds here, not after 15 minutes of sampling (both bit us in dev).
    """
    print("[0/6] smoke test: router chat + embeddings ...")
    try:
        r = requests.post(
            f"{LLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_KEY}"},
            json={"model": LLM_MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(redact(f"FATAL: router/LLM config ({LLM_MODEL}): {exc}")) from exc
    try:
        r = requests.post(
            f"{EMB_BASE}/models/{EMB_MODEL}:batchEmbedContents",
            headers={"x-goog-api-key": GOOGLE_KEY},
            json={"requests": [{"model": f"models/{EMB_MODEL}", "content": {"parts": [{"text": "ping"}]}}]},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(redact(f"FATAL: embedding config ({EMB_MODEL}): {exc}")) from exc
    print("      ok")


def sample_feed(feed: dict[str, Any]) -> dict[str, Any]:
    """Fetch recent item titles with a hard timeout. Dead feeds are tolerated.

    Never feedparser.parse(url) — it fetches with NO timeout and hung the
    original spike for an hour. Fetch via requests (bounded), then parse.
    """
    feed["items"] = []
    try:
        with requests.get(
            feed["url"],
            timeout=FETCH_TIMEOUT,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SignalFlow spike/0.1)"},
        ) as resp:
            resp.raise_for_status()
            # raw.decode_content handles gzip — version-proof across requests builds
            resp.raw.decode_content = True
            content = resp.raw.read(300_000)  # cap: feeds can be multi-MB
        parsed = feedparser.parse(content)
        for entry in parsed.entries[:SAMPLE_ITEMS]:
            title = (getattr(entry, "title", "") or "").strip()
            if title:
                feed["items"].append(title)
    except Exception as exc:  # noqa: BLE001 — spike: log and continue
        feed["error"] = redact(str(exc))[:120]
    return feed


def embed_batch(texts: list[str], limiter: RateLimiter) -> list[list[float]]:
    """Embed up to BATCH_SIZE texts. Key goes in a header, never the URL.

    429 -> 60s penalty + retry (rate windows are per-minute); 5xx -> short
    backoff. Errors are sanitized so a key can never be echoed.
    """
    url = f"{EMB_BASE}/models/{EMB_MODEL}:batchEmbedContents"
    payload = {"requests": [{"model": f"models/{EMB_MODEL}", "content": {"parts": [{"text": t}]}} for t in texts]}
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.post(url, headers={"x-goog-api-key": GOOGLE_KEY}, json=payload, timeout=90)
            if resp.status_code == 429:
                limiter.penalty(60)
                last_exc = RuntimeError(f"embed HTTP 429 (attempt {attempt + 1})")
                if QUOTA_DEAD.is_set():
                    break  # window is dead — stop burning time on it
                time.sleep(EMBED_429_SLEEP)
                continue
            if resp.status_code >= 500:
                last_exc = RuntimeError(f"embed HTTP {resp.status_code} (attempt {attempt + 1})")
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(redact(f"embed HTTP {resp.status_code}: {resp.text[:200]}"))
            data = resp.json()
            if "embeddings" not in data:
                raise RuntimeError(f"embed response missing 'embeddings': {str(data)[:200]}")
            return [e["values"] for e in data["embeddings"]]
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(redact(f"embed failed after retries: {last_exc}")) from last_exc


def spherical_kmeans(vecs: list[list[float]], k: int, iters: int = 25, seed: int = 42) -> list[int]:
    """Spherical k-means (cosine) with k-means++ init; returns item->cluster labels.

    Greedy incremental-mean clustering failed on this data: centroids drift
    toward the global mean and absorb everything (158/158 feeds -> 1 cluster;
    cross-feed mean sim 0.72 > intra-feed item sim 0.56). K-means is
    threshold-free and has no chaining. numpy is a spike-only dependency.
    """
    import numpy as np  # noqa: PLC0415 — spike-only dep; fail at call, not import

    x = np.asarray(vecs, dtype=np.float64)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    x = x / np.where(norms == 0, 1, norms)
    rng = np.random.default_rng(seed)
    n = len(x)
    centroids = [x[rng.integers(n)]]
    for _ in range(k - 1):
        d2 = np.clip(1.0 - x @ np.asarray(centroids).T, 0, None)  # 1-cos can go tiny-negative
        d2 = np.clip(d2.min(axis=1), 1e-12, None)  # guard all-zero (degenerate) case
        probs = d2 / d2.sum()
        centroids.append(x[rng.choice(n, p=probs)])
    c = np.asarray(centroids)
    labels: np.ndarray = np.empty(0, dtype=int)
    for _ in range(iters):
        labels = (x @ c.T).argmax(axis=1)
        new_c = np.array([x[labels == i].mean(axis=0) if np.any(labels == i) else c[i] for i in range(k)])
        new_c = new_c / np.linalg.norm(new_c, axis=1, keepdims=True)
        if np.allclose(c, new_c, atol=1e-6):
            break
        c = new_c
    return labels.tolist()


def check_feed_integrity(feeds: list[dict[str, Any]], limiter: RateLimiter) -> dict[str, str]:
    """Flag feeds whose recent items are off-topic vs their title.

    Domain takeover is real: a dead cooking blog's feedburner URL now emits
    Turkish casino SEO spam, and its content pollutes clustering if allowed
    to vote. Batched LLM audit; returns {url: reason} for flagged feeds.
    """
    flagged: dict[str, str] = {}
    for i in range(0, len(feeds), 25):
        chunk = feeds[i : i + 25]
        rows = []
        for f in chunk:
            items = "; ".join(f["items"][:3])
            rows.append(f"- title: {f['title']} | folder: {f['folder']} | recent items: {items}")
        prompt = f"""You are auditing a subscription list. For each feed below, judge whether the
recent item titles are topically consistent with the feed title. Flag feeds that
appear HIJACKED or REPURPOSED (e.g. a cooking blog now publishing casino/SEO
spam), dead-but-emitting, or clearly off-topic.

{chr(10).join(rows)}

Respond with STRICT JSON only, one entry per feed IN ORDER:
{{"flags": [{{"flagged": true/false, "reason": "<one short sentence, only if flagged>"}}, ...]}}"""
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": LLM_MAX_TOKENS,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        }
        try:
            limiter.wait()
            resp = requests.post(
                f"{LLM_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_KEY}"},
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except Exception as exc:  # noqa: BLE001 — integrity is best-effort
            print(f"      integrity check chunk failed: {redact(str(exc))[:120]}")
            continue
        for feed, flag in zip(chunk, data.get("flags", []), strict=False):  # LLM may omit rows
            if isinstance(flag, dict) and flag.get("flagged"):
                flagged[feed["url"]] = str(flag.get("reason", ""))[:120]
    return flagged


def split_oversized(
    clusters: list[list[dict[str, Any]]], emb_cache: dict[str, list[float]], max_size: int = 15, depth: int = 0
) -> list[list[dict[str, Any]]]:
    """Recursively split clusters above max_size with their own k-means pass.

    One k over the whole corpus leaves a stubborn "professional/opinion blob"
    (29 feeds: 9 energy, 5 business, 3 stories ...) — all hug one centroid.
    Re-clustering the blob's own fragments breaks it into sub-themes.
    """
    out: list[list[dict[str, Any]]] = []
    for cl in clusters:
        if len(cl) > max_size and depth < 2:
            member_texts = [item for f in cl for item in f["items"]] + [f["title"] for f in cl]
            sub_k = max(2, min(10, round(len(cl) / 6)))
            sub_labels = spherical_kmeans([emb_cache[t] for t in member_texts], sub_k, seed=42 + depth)
            idx = 0
            frag: dict[int, list[int]] = {}
            for f in cl:
                frag[id(f)] = sub_labels[idx : idx + len(f["items"]) + 1]
                idx += len(f["items"]) + 1
            sub_map: dict[int, list[dict[str, Any]]] = {}
            for f in cl:
                votes = frag[id(f)]
                best = max(set(votes), key=votes.count)
                sub_map.setdefault(best, []).append(f)
            out.extend(split_oversized([v for _, v in sorted(sub_map.items())], emb_cache, max_size, depth + 1))
        else:
            out.append(cl)
    return out


def name_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = []
    for f in cluster[:10]:
        items = "; ".join(f["items"][:3]) if f.get("items") else "(no items)"
        evidence.append(f"- {f['title']}  [{f['folder']}] — {items}")
    prompt = f"""You are building a topic model for a personal discovery engine.
Feeds below cluster together semantically. Feedly folder names are organizational labels, NOT topics.

{chr(10).join(evidence)}

Respond with STRICT JSON only:
{{
  "topic": "short field-of-inquiry name (5 words max)",
  "definition": "one sentence: what this field of inquiry covers",
  "strategy": {{
    "queries": ["3-5 diverse search query formulations for this topic"],
    "domains": ["2-4 high-density domain patterns, e.g. site:arxiv.org"],
    "source_types": ["independent blogs", "academic", "newsletters"],
    "registries": ["only genuinely relevant: UKRI GtR / ClinicalTrials.gov / Ofgem SIF / none"]
  }}
}}"""
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": LLM_MAX_TOKENS,
        "thinking": {"type": "disabled"},  # verified supported; avoids reasoning eating the budget
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {LLM_KEY}"}
    try:
        resp = requests.post(f"{LLM_BASE}/chat/completions", headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
    except requests.HTTPError:
        # Router may not support response_format — retry without it.
        payload.pop("response_format", None)
        resp = requests.post(f"{LLM_BASE}/chat/completions", headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(redact(f"non-JSON LLM response: {content[:200]}")) from None


def main() -> None:
    # Fail fast on config errors before any expensive work (PRD: fail-fast).
    for var in ("GOOGLE_API_KEY", "OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL"):
        if not os.environ.get(var):
            raise SystemExit(f"FATAL: missing env var {var} — check .env (see .env.example)")
    smoke_test()

    feeds = parse_opml(OPML_PATH)
    print(f"[1/6] OPML parsed: {len(feeds)} feeds")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    samples = load_samples()

    # Reuse cached samples; only fetch uncached feeds and stale failures.
    to_fetch: list[dict[str, Any]] = []
    for f in feeds:
        cached = samples.get(f["url"])
        if cached is None:
            to_fetch.append(f)
            continue
        if cached.get("error") and sample_age(cached) >= FAILURE_RETRY_TTL:
            to_fetch.append(f)  # previous attempt failed long ago -> retry
            continue
        f["items"] = cached.get("items", [])
        if cached.get("error"):
            f["error"] = cached["error"]

    if to_fetch:
        print(f"      fetching {len(to_fetch)} uncached feeds ...")
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
            futures = [ex.submit(sample_feed, f) for f in to_fetch]
            for fut in as_completed(futures):
                f = fut.result()
                entry = {
                    "url": f["url"],
                    "folder": f["folder"],
                    "title": f["title"],
                    "items": f.get("items", []),
                    "sampled_at": datetime.now(UTC).isoformat(),
                }
                if f.get("error"):
                    entry["error"] = f["error"]
                append_sample(entry)  # persist each feed the moment it lands

    ok = [f for f in feeds if f.get("items")]
    failed = [f for f in feeds if not f.get("items")]
    reused = len(feeds) - len(to_fetch)
    print(f"[2/6] sampled: {len(ok)} feeds ok, {len(failed)} dead/empty ({reused} from cache)")
    if ok and len(ok) / len(feeds) < 0.6:
        print(f"      WARNING: only {len(ok)}/{len(feeds)} feeds sampled — check network/feed health")

    # Feed integrity: domain takeovers mean a feed's current content can be
    # spam unrelated to its title (real case: a cooking blog -> Turkish casino
    # SEO). Flagged feeds are excluded from clustering and reported.
    print(f"[2.5/6] feed integrity audit ({len(ok)} feeds) ...")
    flagged = load_integrity()
    if flagged is None:
        flagged = check_feed_integrity(ok, RateLimiter(NAMING_INTERVAL))
        save_integrity(flagged)
        audit_note = "audited"
    else:
        audit_note = "cached"
    if flagged:
        print(f"      flagged {len(flagged)} feeds (hijack/off-topic) — excluded from clustering ({audit_note})")
        for url, reason in flagged.items():
            print(f"        {url}  — {reason}")
        ok = [f for f in ok if f["url"] not in flagged]
    else:
        print(f"      no suspicious feeds ({audit_note})")

    fragments: list[str] = []
    frag_feed: list[dict[str, Any]] = []
    for f in ok:
        for item in f["items"]:
            fragments.append(item)
            frag_feed.append(f)
        fragments.append(f["title"])  # anchor fragment: the feed's self-description
        frag_feed.append(f)

    emb_cache = load_embeddings()
    missing = list(dict.fromkeys(t for t in fragments if t not in emb_cache))
    if missing:
        batches = [missing[i : i + BATCH_SIZE] for i in range(0, len(missing), BATCH_SIZE)]
        print(
            f"[3/6] embedding {len(missing)} new fragments in {len(batches)} batches "
            f"via {EMB_MODEL} ({EMBED_WORKERS} workers, {EMBED_INTERVAL}s global pacing) ..."
        )
        embed_limiter = RateLimiter(EMBED_INTERVAL)
        eq: queue.Queue[list[str] | None] = queue.Queue()
        for b in batches:
            eq.put(b)
        for _ in range(EMBED_WORKERS):
            eq.put(None)  # sentinel: worker exits

        def embed_worker() -> None:
            while True:
                batch = eq.get()
                if batch is None:
                    eq.task_done()
                    return
                if QUOTA_DEAD.is_set():
                    eq.task_done()  # skip remaining work; resume on a later run
                    continue
                try:
                    embed_limiter.wait()  # global pacing BEFORE the call
                    vecs = embed_batch(batch, embed_limiter)
                    append_embeddings(batch, vecs)
                    for text, vec in zip(batch, vecs, strict=True):
                        emb_cache[text] = vec
                except Exception as exc:  # noqa: BLE001 — keep the spike alive
                    if "429" in redact(str(exc)):
                        QUOTA_DEAD.set()
                    print(f"      embed batch of {len(batch)} failed: {redact(str(exc))[:120]}")
                finally:
                    eq.task_done()

        threads = [threading.Thread(target=embed_worker, daemon=True) for _ in range(EMBED_WORKERS)]
        for th in threads:
            th.start()
        eq.join()
        if QUOTA_DEAD.is_set():
            print("      EMBED QUOTA EXHAUSTED — run incomplete; re-run later to resume (checkpointed)")
            sys.exit(2)
    else:
        print(f"[3/6] all {len(fragments)} fragments already embedded")

    agg: dict[int, list[list[float]]] = {}
    for feed, vec in zip(frag_feed, (emb_cache[t] for t in fragments), strict=True):
        agg.setdefault(id(feed), []).append(vec)
    for f in ok:
        v = agg[id(f)]
        dim = len(v[0])
        f["embedding"] = [sum(x[d] for x in v) / len(v) for d in range(dim)]

    # Cluster at ITEM level — feed means collapse toward the global centroid
    # (measured: cross-feed mean sim 0.72 > intra-feed item sim 0.56), so
    # feed-mean clustering is signal-free. Feed -> topic by plurality vote;
    # the feed title is an anchor fragment in that vote.
    topic_k = max(24, min(45, round(len(ok) / 5)))  # TOPIC_K env override below
    topic_k = int(os.environ.get("TOPIC_K", topic_k))
    item_texts: list[str] = [item for f in ok for item in f["items"]] + [f["title"] for f in ok]
    item_labels = spherical_kmeans([emb_cache[t] for t in item_texts], topic_k)
    idx = 0
    frag_labels: dict[int, list[int]] = {}
    for f in ok:
        frag_labels[id(f)] = item_labels[idx : idx + len(f["items"]) + 1]  # items + title
        idx += len(f["items"]) + 1
    topic_map: dict[int, dict[str, Any]] = {}
    ambiguous: list[dict[str, Any]] = []
    for f in ok:
        votes = frag_labels[id(f)]
        best = max(set(votes), key=votes.count)
        if len(votes) >= 3 and votes.count(best) == 1:
            ambiguous.append(f)  # fully scattered votes — no honest cluster; list, don't force-fit
        else:
            topic_map.setdefault(best, {"feeds": []})["feeds"].append(f)
    clusters = split_oversized([v["feeds"] for _, v in sorted(topic_map.items())], emb_cache)
    if ambiguous:
        print(f"      {len(ambiguous)} feeds ambiguous (scattered votes) — listed in report, not clustered")
    sizes = sorted((len(c) for c in clusters), reverse=True)
    print(f"[4/6] clustered {len(ok)} feeds -> {len(clusters)} topics (spherical k-means k={topic_k})")
    print(f"      sizes: {sizes[:30]}")
    if sizes and sizes[0] > 0.4 * len(ok):
        print(f"      WARNING: largest topic is {sizes[0]}/{len(ok)} feeds — consider higher k")

    names = load_names()
    named: list[dict[str, Any]] = []
    print(f"[5/6] naming {len(clusters)} topics ({len(names)} cached names loaded) ...")
    naming_limiter = RateLimiter(NAMING_INTERVAL)
    names_lock = threading.Lock()
    nq: queue.Queue[list[dict[str, Any]] | None] = queue.Queue()
    for cl in clusters:
        nq.put(cl)
    for _ in range(NAMING_WORKERS):
        nq.put(None)  # sentinel: worker exits

    def naming_worker() -> None:
        while True:
            cl = nq.get()
            if cl is None:
                nq.task_done()
                return
            try:
                sig = cluster_signature(cl)
                with names_lock:
                    cached = names.get(sig)
                info: dict[str, Any] = dict(cached) if cached is not None else {}
                note = ""
                if cached is not None:
                    note = "cached"
                else:
                    if len(cl) == 1:
                        # Single-feed topics get no LLM call: too little signal
                        # for a discovery strategy. (The earlier "casino" name
                        # was an ACCURATE read of a hijacked cooking-blog feed
                        # — domain takeover; the integrity audit now excludes
                        # those, so label honestly and let the user verify.)
                        info = {
                            "topic": f"single-feed topic: {cl[0]['title']}",
                            "definition": "Single subscribed feed — verify relevance before treating as a topic.",
                            "strategy": {},
                        }
                        note = "singleton"
                    else:
                        try:
                            naming_limiter.wait()  # global pacing BEFORE the call
                            info = name_cluster(cl)
                        except Exception as exc:  # noqa: BLE001 — keep the spike alive
                            info = {
                                "topic": f"cluster-{len(named)}",
                                "definition": f"naming failed: {redact(str(exc))[:120]}",
                                "strategy": {},
                            }
                            note = "failed"
                            print(f"      ERROR naming a cluster: {redact(str(exc))[:200]}")
                        else:
                            note = "named"
                    if note in ("named", "singleton"):
                        try:
                            with names_lock:
                                names[sig] = info
                                save_names(names)  # persist each name the moment it lands
                        except Exception as exc:  # noqa: BLE001 — cache save must not kill the thread
                            print(f"      WARNING: names cache save failed: {redact(str(exc))[:120]}")
                info["feeds"] = [f["title"] for f in cl]
                info["n_feeds"] = len(cl)
                info["gap"] = len(cl) < MIN_FEEDS_PER_TOPIC
                named.append(info)
                print(f"      [{len(cl):>3} feeds{' GAP' if info['gap'] else ''}] {info['topic']} ({note})")
            except Exception as exc:  # noqa: BLE001 — worker must never die without task_done
                print(f"      ERROR naming worker: {redact(str(exc))[:200]}")
            finally:
                nq.task_done()

    threads = [threading.Thread(target=naming_worker, daemon=True) for _ in range(NAMING_WORKERS)]
    for th in threads:
        th.start()
    nq.join()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / "topic_report.md"
    lines = [
        "# SignalFlow — Topic Elicitation Report (spike)",
        "",
        f"- OPML feeds: {len(feeds)} | sampled: {len(ok)} | dead/empty: {len(failed)}",
        f"- Embedding: {EMB_MODEL} | clustering: spherical k-means (k={topic_k})",
        f"- Topics: {len(named)} | gaps (<{MIN_FEEDS_PER_TOPIC} feeds): {sum(1 for n in named if n['gap'])}",
        "",
    ]
    for n in sorted(named, key=lambda x: -x["n_feeds"]):
        flag = " **GAP**" if n["gap"] else ""
        lines.append(f"## {n['topic']}{flag} — {n['n_feeds']} feeds")
        lines.append(n["definition"])
        st = n.get("strategy") or {}
        if st:
            lines.append("")
            lines.append(f"- queries: {', '.join(st.get('queries', []))}")
            lines.append(f"- domains: {', '.join(st.get('domains', []))}")
            lines.append(f"- source types: {', '.join(st.get('source_types', []))}")
            # Model sometimes emits junk like ["n","o","n","e"] for "none";
            # filter to the known registry set instead of echoing noise.
            known = {"ukri gtr", "clinicaltrials.gov", "ofgem sif"}
            regs = [r.strip() for r in st.get("registries", [])]
            regs = [r for r in regs if r.lower() in known]
            lines.append(f"- registries: {', '.join(regs) if regs else 'none'}")
        lines.append("")
        for title in n["feeds"][:8]:
            lines.append(f"  - {title}")
        if len(n["feeds"]) > 8:
            lines.append(f"  - … +{len(n['feeds']) - 8} more")
        lines.append("")
    if flagged:
        lines.append("")
        lines.append("## Suspected hijacked / off-topic feeds (excluded from topics)")
        lines.append("")
        for url, reason in flagged.items():
            lines.append(f"- {url} — {reason}")
        lines.append("")
    if ambiguous:
        lines.append("")
        lines.append("## Ambiguous feeds (scattered votes — no honest topic; review)")
        lines.append("")
        for f in ambiguous:
            lines.append(f"- {f['title']}  [{f['folder']}] — {f['url']}")
        lines.append("")
    report_path.write_text("\n".join(lines))
    print(f"[6/6] report -> {report_path.relative_to(ROOT)}")

    # Authoritative feed -> topic assignment: seeds the engine's topics table.
    assignment = {
        "generated_at": datetime.now(UTC).isoformat(),
        "topics": {
            n.get("topic", "?"): {
                "n_feeds": n["n_feeds"],
                "gap": n["gap"],
                "strategy": n.get("strategy", {}),
                "feeds": n["feeds"],
            }
            for n in named
        },
        "ambiguous": [{"title": f["title"], "folder": f["folder"], "url": f["url"]} for f in ambiguous],
        "flagged": flagged,
    }
    tmp = ASSIGNMENT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(assignment, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(ASSIGNMENT_PATH)
    print(f"      assignment -> {ASSIGNMENT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
