#!/usr/bin/env python3
"""Multi-topic weekly catch-up runner (FR-9 multi-topic iteration, spike).

Regenerates every topic whose last weekly selection is NOT fresh — no
per-topic picks file (or matching legacy single-file) with generated_at inside
RECENCY_DAYS. At most WEEKLY_WORKERS topics run at a time (3 by default),
sharing ONE RateLimiter so parallel topics can never burst past the global LLM
pacing quota. Topics without a docs/discovery/{slug}.json are skipped and
reported (FR-9: they cannot be feed-selected until make topic-sources runs).

Run: make spike-weekly-all   (WEEKLY_WORKERS=3 default)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import spikes.weekly_selection as ws  # noqa: E402  (sys.path bootstrap above)
from signalflow.config import Config  # noqa: E402
from signalflow.env import load_env  # noqa: E402
from signalflow.ratelimit import RateLimiter  # noqa: E402
from signalflow.topics import load_topics  # noqa: E402

load_env(ROOT / ".env")

CFG = Config.from_env_optional()
DISCOVERY_DIR = ws.DISCOVERY_DIR
STATE_DIR = ws.STATE_DIR
OUT_DIR = ws.OUT_DIR
PICKS_DIR = STATE_DIR / "picks"  # per-topic picks: spikes/state/picks/{slug}.json
LEGACY_PICKS_PATH = ws.PICKS_PATH  # single-file legacy (last single-topic run)
RECENCY_DAYS = CFG.weekly_recency_days
WORKERS = CFG.weekly_workers
EVAL_INTERVAL = CFG.weekly_eval_interval


@dataclass(frozen=True)
class RunSpec:
    """One stale topic ready to run: everything run_topic needs + its outputs."""

    topic: dict[str, Any]
    slug: str
    listing: dict[str, Any]
    sources: list[dict[str, Any]]
    out: ws.TopicOut


@dataclass(frozen=True)
class Plan:
    """Classification of every topic: what to run, what to skip, and why."""

    to_run: list[RunSpec] = field(default_factory=list)
    fresh: list[tuple[str, str]] = field(default_factory=list)  # (topic name, slug)
    no_list: list[str] = field(default_factory=list)  # topic names, no discovery list


@dataclass
class RunResult:
    slug: str
    topic: str
    ok: bool
    error: str = ""
    picked: int = 0


# --- freshness --------------------------------------------------------------


def _payload_fresh(payload: dict[str, Any] | None, now: datetime, recency_days: int) -> bool:
    """True when the picks payload's generated_at is strictly inside the window."""
    if not payload:
        return False
    generated_at = payload.get("generated_at") or ""
    try:
        dt = datetime.fromisoformat(generated_at)
    except ValueError:
        return False  # malformed timestamp: cannot prove freshness -> stale
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # naive writes are legacy-UTC
    return now - dt < timedelta(days=recency_days)


def is_topic_fresh(
    topic_name: str,
    per_topic: dict[str, Any] | None,
    legacy: dict[str, Any] | None,
    now: datetime,
    recency_days: int,
) -> bool:
    """A topic is fresh if its most recent selection happened within the window.

    The per-topic picks file is authoritative. The legacy single-file
    (spikes/state/weekly_picks.json) holds the LAST single-topic run's topic,
    so it counts only when its topic field matches — otherwise pre-runner
    state would make every topic look stale once and re-run needlessly.
    """
    if _payload_fresh(per_topic, now, recency_days):
        return True
    if legacy is not None and legacy.get("topic") == topic_name:
        return _payload_fresh(legacy, now, recency_days)
    return False


# --- planning ---------------------------------------------------------------


def _load_payload(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # corrupt or unreadable: treat as absent (re-run decides)
    return data if isinstance(data, dict) else None


def plan_runs(
    topics: list[dict[str, Any]],
    *,
    discovery_dir: Path,
    picks_dir: Path,
    legacy_picks_path: Path | None,
    now: datetime,
    recency_days: int,
    load_list: Callable[..., Any] = ws.load_source_list,
    legacy_payload: dict[str, Any] | None = None,
) -> Plan:
    """Classify every topic: stale (to_run), fresh (skip), or no source list."""
    plan = Plan()
    for topic in topics:
        listing, sources, slug = load_list(topic["name"], discovery_dir)
        if listing is None:
            plan.no_list.append(topic["name"])
            continue
        per_topic = _load_payload(picks_dir / f"{slug}.json")
        legacy = legacy_payload if legacy_payload is not None else _load_payload(legacy_picks_path)
        if is_topic_fresh(topic["name"], per_topic, legacy, now, recency_days):
            plan.fresh.append((topic["name"], slug))
            continue
        plan.to_run.append(
            RunSpec(
                topic=topic,
                slug=slug,
                listing=listing,
                sources=sources,
                out=ws.TopicOut(
                    picks_path=picks_dir / f"{slug}.json",
                    report_path=OUT_DIR / f"weekly_report_{slug}.md",
                    story_md_path=OUT_DIR / f"story_{slug}.md",
                ),
            )
        )
    return plan


# --- execution --------------------------------------------------------------


def run_all(
    plan: Plan,
    *,
    workers: int = 3,
    run_topic_fn: Callable[..., Any] = ws.run_topic,
    limiter: RateLimiter | None = None,
) -> list[RunResult]:
    """Run every stale topic, at most `workers` at a time; failures isolated.

    One topic's exception must never kill the batch: it is captured into its
    RunResult and the remaining topics still run (and still count).
    """
    results: list[RunResult] = []

    def worker(spec: RunSpec) -> RunResult:
        try:
            summary = run_topic_fn(spec.topic, spec.listing, spec.sources, spec.slug, spec.out, limiter=limiter)
            return RunResult(slug=spec.slug, topic=spec.topic["name"], ok=True, picked=int(summary.get("picked", 0)))
        except Exception as exc:  # noqa: BLE001 — keep the batch alive; log, don't swallow
            return RunResult(slug=spec.slug, topic=spec.topic["name"], ok=False, error=str(exc)[:300])

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, spec) for spec in plan.to_run]
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.slug)
    return results


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    del argv  # config comes from env; signature mirrors the engine's main()
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL"):
        if not os.environ.get(var):
            print(f"FATAL: missing env var {var} — check .env (see .env.example)")
            return 1
    ws.smoke_test()

    topics = load_topics()
    now = datetime.now(UTC)
    plan = plan_runs(
        topics,
        discovery_dir=DISCOVERY_DIR,
        picks_dir=PICKS_DIR,
        legacy_picks_path=LEGACY_PICKS_PATH,
        now=now,
        recency_days=RECENCY_DAYS,
    )

    for name, slug in plan.fresh:
        per_topic = _load_payload(PICKS_DIR / f"{slug}.json")
        n = len((per_topic or {}).get("picks", [])) if per_topic else 0
        ts = ((per_topic or {}).get("generated_at") or "?")[:10]
        print(f"[skip] {name} — fresh (last selection {ts}, {n} picks)")
    for name in plan.no_list:
        print(f"[skip] {name} — no discovery source list (run `make topic-sources TOPIC=...`)")
    for spec in plan.to_run:
        print(f"[run ] {spec.topic['name']} — stale, queued ({len(plan.to_run)} topics, {WORKERS} at a time)")

    if not plan.to_run:
        print(f"nothing to regenerate — {len(plan.fresh)} fresh, {len(plan.no_list)} without source lists")
        return 0

    limiter = RateLimiter(EVAL_INTERVAL)  # ONE limiter shared by all worker threads
    results = run_all(plan, workers=WORKERS, limiter=limiter)
    for r in results:
        if r.ok:
            print(f"      {r.topic} ({r.slug}): ok — {r.picked} picks")
        else:
            print(f"      {r.topic} ({r.slug}): FAILED — {r.error}")
    failed = [r for r in results if not r.ok]
    print(f"done: {len(results) - len(failed)}/{len(results)} topics regenerated")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
