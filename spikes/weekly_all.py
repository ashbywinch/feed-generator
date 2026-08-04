#!/usr/bin/env python3
"""Multi-topic weekly catch-up runner (FR-9 multi-topic iteration, spike).

Regenerates every topic whose last weekly selection is NOT fresh — no
per-topic picks file (or matching legacy single-file) with generated_at inside
RECENCY_DAYS. At most WEEKLY_WORKERS topics run at a time (3 by default),
sharing ONE RateLimiter so parallel topics can never burst past the global LLM
pacing quota. Topics without a docs/discovery/{slug}.json get their source
list generated first (the make topic-sources flow: generate -> gates ->
review until approval), then the weekly selection runs on it.

Run: make spike-weekly-all   (WEEKLY_WORKERS=3 default)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
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
from signalflow.source_lists import slug_for  # noqa: E402
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
LLM_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")
EXA_KEY = os.environ.get("EXA_API_KEY", "")
GOOGLE_KEY = os.environ.get("GOOGLE_API_KEY", "")


@dataclass(frozen=True)
class RunSpec:
    """One stale topic ready to run: everything run_topic needs + its outputs.

    needs_sources: the topic has no docs/discovery list yet — the worker
    generates one (make-topic-sources flow) before running selection.
    """

    topic: dict[str, Any]
    slug: str
    listing: dict[str, Any]
    sources: list[dict[str, Any]]
    out: ws.TopicOut
    needs_sources: bool = False


@dataclass(frozen=True)
class Plan:
    """Classification of every topic: what to run and what is already fresh."""

    to_run: list[RunSpec] = field(default_factory=list)
    fresh: list[tuple[str, str]] = field(default_factory=list)  # (topic name, slug)


@dataclass
class RunResult:
    slug: str
    topic: str
    ok: bool
    error: str = ""
    picked: int = 0
    generated_sources: bool = False
    sources_approved: bool = False
    traceback: str = ""  # redacted excerpt (admin run records); "" when ok


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


def _topic_out(picks_dir: Path, slug: str) -> ws.TopicOut:
    return ws.TopicOut(
        picks_path=picks_dir / f"{slug}.json",
        report_path=OUT_DIR / f"weekly_report_{slug}.md",
        story_md_path=OUT_DIR / f"story_{slug}.md",
    )


def _load_payload(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"      WARNING: {path}: corrupt state file treated as absent ({exc})")
        return None  # corrupt or unreadable: treat as absent (re-run decides)
    return data if isinstance(data, dict) else None


def ensure_per_topic_picks(topic_name: str, slug: str, picks_dir: Path, legacy_path: Path | None) -> bool:
    """Materialize a per-topic picks file from the legacy single-file.

    A topic fresh via the legacy fallback (never re-run under the runner) has
    no per-topic picks file yet; without one the feed builder finds nothing and
    the next freshness check must fall back again. Copy the legacy payload
    (stamping the slug) into picks_dir/{slug}.json — one-time convergence.
    Returns True when a file was written.
    """
    per_topic = picks_dir / f"{slug}.json"
    if per_topic.exists():
        return False  # already per-topic: nothing to converge
    legacy = _load_payload(legacy_path)
    if legacy is None or legacy.get("topic") != topic_name:
        return False  # legacy belongs to another topic (or absent)
    payload = dict(legacy)
    payload["slug"] = slug
    picks_dir.mkdir(parents=True, exist_ok=True)
    per_topic.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def require_opml_if_generating(plan: Plan, opml_path: Path) -> str | None:
    """Fail-fast check: source-list generation parses feedly.opml (exclusion
    set), so a missing OPML must abort ONCE as a setup error — not fail every
    needs-sources topic inside its worker (FR-1). Returns the error message,
    or None when nothing blocks.
    """
    if not any(spec.needs_sources for spec in plan.to_run):
        return None
    if not opml_path.exists():
        try:
            shown = opml_path.relative_to(ROOT)
        except ValueError:
            shown = opml_path  # outside the repo (test tmp dirs)
        return (
            f"missing {shown} — required for source-list generation "
            "(the exclusion set); see AGENTS.md (never commit it)"
        )
    return None


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
    weekly_topics: list[str] | None = None,
) -> Plan:
    """Classify every topic: stale (to_run), fresh (skip), or no source list.

    weekly_topics (the night's rotation subset, case-insensitive) restricts
    planning to those topics; freshness gating still applies within the subset.
    """
    full_topics = topics  # slug_for must index the FULL list (matches source_lists.persist)
    if weekly_topics is not None:
        wanted = {name.lower() for name in weekly_topics}
        topics = [t for t in topics if t["name"].lower() in wanted]
    plan = Plan()
    for topic in topics:
        listing, sources, slug = load_list(topic["name"], discovery_dir)
        if listing is None:
            # No discovery source list yet: generate it, then select — the
            # topic is stale by definition (no list -> no picks). The slug
            # must match source_lists.persist (slug_for over the FULL topic
            # list — never the rotation-filtered subset).
            slug = slug_for(topic["name"], full_topics)
            plan.to_run.append(
                RunSpec(
                    topic=topic,
                    slug=slug,
                    listing={},
                    sources=[],
                    out=_topic_out(picks_dir, slug),
                    needs_sources=True,
                )
            )
            continue
        per_topic = _load_payload(picks_dir / f"{slug}.json")
        legacy = legacy_payload if legacy_payload is not None else _load_payload(legacy_picks_path)
        if is_topic_fresh(topic["name"], per_topic, legacy, now, recency_days):
            plan.fresh.append((topic["name"], slug))
            continue
        plan.to_run.append(
            RunSpec(topic=topic, slug=slug, listing=listing, sources=sources, out=_topic_out(picks_dir, slug))
        )
    return plan


# --- execution --------------------------------------------------------------


def generate_sources(topic: dict[str, Any], *, limiter: RateLimiter | None = None) -> tuple[bool, int]:
    """Generate + persist a topic's discovery source list (make-topic-sources flow).

    Mirrors `python -m signalflow sources <topic>`: generate -> gates -> review
    until approval (MAX_ITER rounds), then persist docs/discovery/{slug}.json.
    Returns (approved, iterations) — a needs-human list is still persisted and
    usable; only a hard failure raises. limiter is the runner's shared one: the
    generation's router calls pace through it like selection's do.
    """
    from signalflow.source_lists import generate_topic_sources, persist

    listing, verdict, iterations, _searches = generate_topic_sources(topic, CFG, ROOT / "feedly.opml", limiter=limiter)
    persist(topic["name"], listing, verdict, iterations)
    return bool(verdict.get("approved")), iterations


def run_all(
    plan: Plan,
    *,
    workers: int = 3,
    run_topic_fn: Callable[..., Any] = ws.run_topic,
    generate_fn: Callable[..., Any] = generate_sources,
    load_list_fn: Callable[..., Any] = ws.load_source_list,
    limiter: RateLimiter | None = None,
) -> list[RunResult]:
    """Run every stale topic, at most `workers` at a time; failures isolated.

    A topic without a discovery list generates its sources first (writes
    docs/discovery/{slug}.json), then reloads the list and selects. One
    topic's exception must never kill the batch: it is captured into its
    RunResult and the remaining topics still run (and still count).
    """
    results: list[RunResult] = []
    claims: set[str] = set()  # URLs picked this run, shared across topics
    claims_lock = threading.Lock()

    def worker(spec: RunSpec) -> RunResult:
        try:
            listing, sources = spec.listing, spec.sources
            generated = approved = False
            if spec.needs_sources:
                try:
                    approved, _iterations = generate_fn(spec.topic, limiter=limiter)
                except Exception as first_exc:  # noqa: BLE001 — retry below, but surface the first failure
                    message = str(first_exc)
                    for secret in (LLM_KEY, EXA_KEY, GOOGLE_KEY):
                        if secret:
                            message = message.replace(secret, "***")
                    print(f"      first generation attempt failed for {spec.topic['name']}, retrying: {message[:200]}")
                    # ONE immediate retry: generation failures are stochastic
                    # (router errors, non-JSON prose); a fresh attempt has a
                    # good chance. Bounded — a second failure fails the topic.
                    approved, _iterations = generate_fn(spec.topic, limiter=limiter)
                generated = True
                listing, sources, _slug = load_list_fn(spec.topic["name"])
                if listing is None:
                    raise RuntimeError(f"source list generation produced no usable list for {spec.topic['name']!r}")
            summary = run_topic_fn(
                spec.topic,
                listing,
                sources,
                spec.slug,
                spec.out,
                limiter=limiter,
                claims=claims,
                claim_lock=claims_lock,
            )
            return RunResult(
                slug=spec.slug,
                topic=spec.topic["name"],
                ok=True,
                picked=int(summary.get("picked", 0)),
                generated_sources=generated,
                sources_approved=approved,
            )
        except Exception as exc:  # noqa: BLE001 — keep the batch alive; log, don't swallow
            tb = traceback.format_exc()
            message = str(exc)
            for secret in (LLM_KEY, EXA_KEY, GOOGLE_KEY):
                if secret:
                    tb = tb.replace(secret, "***")
                    message = message.replace(secret, "***")  # any key can appear in exception text
            print(f"      TRACEBACK for {spec.topic['name']}:\n{tb}")
            return RunResult(
                slug=spec.slug,
                topic=spec.topic["name"],
                ok=False,
                error=message[:300],
                traceback=tb[:2000],  # admin run records: why it failed
            )

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, spec) for spec in plan.to_run]
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.slug)
    return results


# --- run records (admin page source) ----------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    """Atomic write: a crash mid-write never leaves a partial record."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _story_version(stories_dir: Path, slug: str) -> int:
    """The topic story's version (0 when absent/malformed) — shown on admin."""
    path = stories_dir / f"{slug}.json"
    if not path.exists():
        return 0
    try:
        return int((json.loads(path.read_text(encoding="utf-8")) or {}).get("version", 0))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0  # corrupt story file: show the run, not the error


def _verdict_counts(verdicts_path: Path, slugs: list[str]) -> dict[str, int]:
    """Per-topic verdict counts from the shared cache — one scan, not one per topic."""
    counts = {slug: 0 for slug in slugs}
    if not verdicts_path.exists():
        return counts
    try:
        for line in verdicts_path.read_text(encoding="utf-8").splitlines():
            try:
                slug = json.loads(line).get("slug")
            except json.JSONDecodeError:
                continue
            if slug in counts:
                counts[slug] += 1
    except OSError:
        pass
    return counts


def _list_status(discovery_dir: Path, slug: str, generated: bool) -> str:
    if generated:
        return "generated"
    return "present" if (discovery_dir / f"{slug}.json").exists() else "missing"


def _picked_items(picks_dir: Path, slug: str) -> list[dict[str, Any]]:
    """This run's picked items (title/url/reason) for the admin record.

    The picks file holds the full verdict objects; the record keeps the
    operator-facing slice — what was surfaced and why.
    """
    payload = _load_payload(picks_dir / f"{slug}.json")
    items: list[dict[str, Any]] = []
    for pick in (payload or {}).get("picks", []) or []:
        if not isinstance(pick, dict) or not pick.get("url"):
            continue
        items.append(
            {
                "title": str(pick.get("title", ""))[:200],
                "url": str(pick.get("url", "")),
                "reason": str(pick.get("reason", ""))[:300],
            }
        )
    return items


def write_run_record(
    runs_dir: Path,
    results: list[RunResult],
    *,
    now: datetime,
    weekly_topics: list[str] | None,
    fresh: list[tuple[str, str]],
    picks_dir: Path,
    stories_dir: Path,
    discovery_dir: Path,
    verdicts_path: Path,
) -> Path:
    """Write spikes/state/runs/{ts}.json + latest.json for the admin page.

    Machine-readable per-topic status (ok/failed, picks, story version, verdict
    count, source-list status, error + redacted traceback excerpt) plus the
    night's rotation subset and the fresh skips. latest.json mirrors the newest
    record so a local `make admin` renders the same history as the deployed
    page. Returns the timestamped run file.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    counts = _verdict_counts(verdicts_path, [r.slug for r in results])
    record = {
        "ts": now.isoformat(timespec="seconds"),
        "weekly_topics": weekly_topics,
        "fresh": [{"topic": name, "slug": slug} for name, slug in fresh],
        "results": [
            {
                "slug": r.slug,
                "topic": r.topic,
                "ok": r.ok,
                "picked": r.picked,
                "picks": _picked_items(picks_dir, r.slug),
                "generated_sources": r.generated_sources,
                "sources_approved": r.sources_approved,
                "story_version": _story_version(stories_dir, r.slug),
                "verdicts": counts.get(r.slug, 0),
                "list": _list_status(discovery_dir, r.slug, r.generated_sources),
                "error": r.error,
                "traceback": r.traceback,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "ok": sum(1 for r in results if r.ok),
            "failed": sum(1 for r in results if not r.ok),
        },
    }
    content = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    ts_stamp = now.isoformat(timespec="seconds")
    run_path = runs_dir / f"{ts_stamp.replace(':', '-')}.json"
    _atomic_write(run_path, content)
    _atomic_write(runs_dir / "latest.json", content)
    return run_path


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
    weekly_topics = [t.strip() for t in os.environ.get("WEEKLY_TOPICS", "").split(",") if t.strip()] or None
    plan = plan_runs(
        topics,
        discovery_dir=DISCOVERY_DIR,
        picks_dir=PICKS_DIR,
        legacy_picks_path=LEGACY_PICKS_PATH,
        now=now,
        recency_days=RECENCY_DAYS,
        weekly_topics=weekly_topics,
    )

    for name, slug in plan.fresh:
        if ensure_per_topic_picks(name, slug, PICKS_DIR, LEGACY_PICKS_PATH):
            print(f"      migrated {name} picks -> spikes/state/picks/{slug}.json (legacy single-file)")
        payload = _load_payload(PICKS_DIR / f"{slug}.json")
        n = len(payload.get("picks", [])) if payload else 0
        ts = ((payload or {}).get("generated_at") or "?")[:10]
        print(f"[skip] {name} — fresh (last selection {ts}, {n} picks)")
    for spec in plan.to_run:
        if spec.needs_sources:
            print(f"[gen ] {spec.topic['name']} — no source list, generating then selecting ({WORKERS} at a time)")
        else:
            print(f"[run ] {spec.topic['name']} — stale, queued ({len(plan.to_run)} topics, {WORKERS} at a time)")

    if not plan.to_run:
        print(f"nothing to regenerate — {len(plan.fresh)} topics fresh")
        return 0

    setup_error = require_opml_if_generating(plan, ROOT / "feedly.opml")
    if setup_error is not None:
        print(f"FATAL: {setup_error}")
        return 1

    limiter = RateLimiter(EVAL_INTERVAL)  # ONE limiter shared by all worker threads
    results = run_all(plan, workers=WORKERS, limiter=limiter)
    for r in results:
        if r.ok:
            src = f", sources generated (approved={r.sources_approved})" if r.generated_sources else ""
            print(f"      {r.topic} ({r.slug}): ok — {r.picked} picks{src}")
        else:
            print(f"      {r.topic} ({r.slug}): FAILED — {r.error}")
    failed = [r for r in results if not r.ok]
    run_path = write_run_record(
        STATE_DIR / "runs",
        results,
        now=now,
        weekly_topics=weekly_topics,
        fresh=plan.fresh,
        picks_dir=PICKS_DIR,
        stories_dir=ws.STORY_DIR,
        discovery_dir=DISCOVERY_DIR,
        verdicts_path=ws.VERDICTS_PATH,
    )
    print(f"      run record -> {run_path.relative_to(ROOT)} (+ latest.json)")
    print(f"done: {len(results) - len(failed)}/{len(results)} topics regenerated")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
