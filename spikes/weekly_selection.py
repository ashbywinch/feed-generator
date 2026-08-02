#!/usr/bin/env python3
"""Weekly article-selection for ONE topic's discovery source list.

For each source in the topic's docs/discovery/{slug}.json list, fetch its
feed, window items to the last RECENCY_DAYS, and have the LLM judge each item
against the topic boundary (FR-5 bar: a new empirical event, observed data
shift, or first-principles systems analysis; reject hype, shallow reporting,
off-topic). Zero picks per source is a VALID outcome — a site with nothing
good this week yields nothing, and the report says so.

Repeatability (the point of this pipeline):
  - spikes/state/weekly_feeds.jsonl    crawl_root -> {items, fetched_at}.
        A fresh cache (FETCH_TTL) is reused; stale or failed entries re-fetch
        (failures retried after FAILURE_RETRY_TTL). A source whose fetch fails
        but has ANY cached copy falls back to the cache, flagged stale — a
        transient outage never reads as "site has no articles".
  - spikes/state/weekly_verdicts.jsonl item url -> LLM verdict, keyed by the
        prompt revision (PROMPT_REV). Items already judged under the CURRENT
        prompt skip the LLM, so a same-week re-run is cheap and idempotent;
        bumping PROMPT_REV invalidates every cached verdict, so a stricter bar
        is never silently replayed with old judgments.
  - spikes/state/weekly_picks.jsonl    append-only history of picked urls.
        Urls already picked by an earlier run are excluded BEFORE evaluation
        (engine FR-6 analog: url uniqueness), so a feed without dates cannot
        re-surface the same article week after week. Curation cap: at most
        MAX_PICKS_PER_SOURCE per source per run.
  - spikes/state/stories/{slug}.json   long-form "story" of the topic area:
        per-subarea angles, recent events, open questions (the accumulated
        context that makes "genuinely interesting" judgment possible). Only
        the SOURCE's subarea slice is injected into its evaluation prompt, so
        no prompt grows with the story.
        FOLDING IS DEFERRED AND CONTEXT-CHANGING: picks are queued in `pending`;
        the fold (one LLM call) happens at the START of a later run that has
        genuinely new items to evaluate. Folding bumps the story version, which
        re-keys the verdict cache — so the fresh window is judged against the
        enriched context, exactly like a PROMPT_REV bump. A re-run with NO new
        work (everything cached) never folds and stays cheap; after one
        re-evaluation the system settles (cached verdicts cover the window).
  - Output: spikes/output/weekly_report.md (human) + spikes/state/weekly_picks.json
        (machine-readable picks) + spikes/output/story_{slug}.md (rendered story
        view, like docs/topics.md from topics.json).

Run: make spike-weekly   (TOPIC="Grid & Net Zero economics" is the default)

Never prints API keys. Errors are truncated.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.config import Config  # noqa: E402
from signalflow.env import load_env  # noqa: E402
from signalflow.llm import LLM  # noqa: E402
from signalflow.ratelimit import RateLimiter  # noqa: E402
from signalflow.topics import load_topics  # noqa: E402

load_env(ROOT / ".env")

TOPIC_NAME = os.environ.get("TOPIC", "Grid & Net Zero economics")
DISCOVERY_DIR = ROOT / "docs" / "discovery"
OUT_DIR = ROOT / "spikes" / "output"
STATE_DIR = ROOT / "spikes" / "state"
FEEDS_PATH = STATE_DIR / "weekly_feeds.jsonl"
VERDICTS_PATH = STATE_DIR / "weekly_verdicts.jsonl"
PICKS_HISTORY_PATH = STATE_DIR / "weekly_picks.jsonl"
PICKS_PATH = STATE_DIR / "weekly_picks.json"
STORY_DIR = STATE_DIR / "stories"
PROMPTS_DIR = ROOT / "prompts"
STORY_PROMPT_PATH = PROMPTS_DIR / "generate_area_story.md"

LLM_BASE = os.environ.get("OPENCODE_GO_BASE_URL", "")
LLM_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")
LLM_MODEL = os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash")

RECENCY_DAYS = int(os.environ.get("RECENCY_DAYS", "7"))
FETCH_TTL = 6 * 60 * 60  # same-day re-runs reuse cached items
FAILURE_RETRY_TTL = 24 * 60 * 60  # re-fetch a failed feed after this long
FETCH_WORKERS = 12
FETCH_TIMEOUT = 12
FEED_CAP_BYTES = 300_000  # feed body cap; truncation is detected and flagged, never silent
MAX_ITEMS_PER_SOURCE = 30  # cap on items the LLM judges per source per run
MAX_PICKS_PER_SOURCE = 3  # curation cap: no feed dominates the weekly digest
JUNK_TITLE_MARKERS = ("factsheet", "fact sheet")  # boilerplate docs: filtered BEFORE the LLM
STORY_MAX_ANGLES = 5  # angle lines kept per subarea
STORY_MAX_QUESTIONS = 8  # open questions kept per topic
EVAL_INTERVAL = 1.0  # seconds between router chat calls (global pacing)
LLM_MAX_TOKENS = 8192
PROMPT_REV = 9  # bump when the evaluation prompt changes -> stale verdicts ignored

APPEND_LOCK = threading.Lock()  # serialize JSONL appends from worker threads

# JSON-shaped records from feeds, caches, and the LLM. The engine's convention
# (dict[str, Any] at JSON boundaries) applies: these are runtime-typed by the
# producer, not by the checker.
Item = dict[str, Any]
Source = dict[str, Any]
CacheEntry = dict[str, Any]
Verdict = dict[str, Any]

# One verdict per item, IN ORDER; map back by url defensively. The subarea is
# the SOURCE's subarea — the model must not invent its own. The reason is a
# WHY-RELEVANT note, not a summary: only present when the title alone leaves
# relevance unclear; empty string otherwise. empirical_event is the one-
# sentence observed-event description required for approved verdicts (FR-9
# digest contract — it becomes the digest's Observed Event bullet).
SCHEMA_HINT = """Respond with STRICT JSON only. Return EXACTLY ONE verdict object per
input item, in the SAME ORDER as the input list — never omit or reorder items:
{"verdicts": [{"url": "item url", "approved": true/false,
"reason": "short why-relevant note ONLY when the title alone doesn't make it clear, else ''",
"thesis": "one-sentence systemic thesis if approved, else ''",
"empirical_event": "one-sentence description of the observed event or data shift, REQUIRED if approved, else ''"}]}"""


# --- disk cache helpers ---------------------------------------------------


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    """key -> latest entry (last line per key wins)."""
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn tail line from a crash; that work is redone
        out[entry["key"]] = entry
    return out


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    with APPEND_LOCK, path.open("a", encoding="utf-8") as fh:
        _ = fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_feeds() -> dict[str, dict[str, Any]]:
    return _load_jsonl(FEEDS_PATH)


def load_verdicts(story_version: int, slug: str) -> dict[str, dict[str, Any]]:
    """Cached verdicts for the CURRENT topic, prompt revision, and story version.

    The cache is shared across topics, so a verdict is only reusable when it
    was produced under the same topic (slug) — otherwise topic A's judgment
    could be replayed for the same article URL under topic B. A prompt change
    (PROMPT_REV bump) or a folded story (version bump) also invalidates.
    """
    return {
        k: v
        for k, v in _load_jsonl(VERDICTS_PATH).items()
        if v.get("slug") == slug and v.get("rev") == PROMPT_REV and v.get("story_ver", 0) == story_version
    }


def load_picked_urls() -> set[str]:
    out: set[str] = set()
    if not PICKS_HISTORY_PATH.exists():
        return out
    for line in PICKS_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.add(json.loads(line)["url"])
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def record_pick(entry: dict[str, Any]) -> None:
    _append_jsonl(PICKS_HISTORY_PATH, {"key": entry["url"], "picked_at": datetime.now(UTC).isoformat(), **entry})


# --- feed fetching --------------------------------------------------------


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def normalize_url(url: str) -> str:
    """Drop feed tracking params so one article has ONE url across runs."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def fetch_feed(source: Source) -> Source:
    """Fetch one source's feed; items carry {url, title, summary, published, undated}.

    Never feedparser.parse(url) — it fetches with NO timeout. Fetch via
    requests (bounded), then parse. Mutates and returns the source dict so the
    caller's cache attachment lands on the same object living in `sources`.
    """
    source["items"] = []
    try:
        with requests.get(
            source["crawl_root"],
            timeout=FETCH_TIMEOUT,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SignalFlow spike/0.1)"},
        ) as resp:
            resp.raise_for_status()
            resp.raw.decode_content = True
            # Cap feeds at 300 KB, but read one extra byte to DETECT truncation —
            # a feed bigger than the cap must not be silently parsed as a clean
            # full item set and cached as a fresh successful fetch.
            content = resp.raw.read(FEED_CAP_BYTES + 1)
            if len(content) > FEED_CAP_BYTES:
                source["truncated"] = True
                content = content[:FEED_CAP_BYTES]
        parsed = feedparser.parse(content)
        seen: set[str] = set()
        for entry in parsed.entries:
            url = normalize_url((entry.link or "").strip())
            if not url or url in seen:
                continue
            seen.add(url)
            title = strip_html(entry.title)[:200]
            if not title:
                continue
            summary = strip_html(
                entry.summary or (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else "")
            )[:400]
            published = None
            for attr in ("published_parsed", "updated_parsed"):
                t = getattr(entry, attr, None)
                if t:
                    published = datetime(*t[:6], tzinfo=UTC)
                    break
            source["items"].append(
                {
                    "url": url,
                    "title": title,
                    "summary": summary,
                    "published": published.isoformat() if published else None,
                    "undated": published is None,
                }
            )
    except Exception as exc:  # noqa: BLE001 — feed fetch/parse fails in many ways; log and continue
        source["error"] = redact(str(exc))[:120]
    return source


# --- LLM evaluation -------------------------------------------------------


def _item_row(it: Item) -> str:
    pub = it.get("published") or "(no date)"
    return f"- [{pub}] {it['title']} — {it['summary']} ({it['url']})"


def evaluate_source(
    source: Source, items: list[Item], topic: dict[str, Any], llm: LLM, limiter: RateLimiter, story_slice_txt: str
) -> list[Verdict]:
    """One LLM call judging ALL of a source's weekly items. Zero approvals is valid."""
    rows = "\n".join(_item_row(it) for it in items)
    slice_block = f"\nArea story — what we already track here:\n{story_slice_txt}\n" if story_slice_txt else ""
    subarea_label = ", ".join(source.get("subareas") or [source["subarea"]])
    prompt = f"""You select articles for a personal discovery feed on ONE topic.
This feed is CURATED and DEMANDING: it only surfaces genuinely interesting,
relevant articles. Most articles fail. Many weeks a source yields nothing at
all — that is the expected outcome, not a gap.

Topic: {topic["name"]}
Description: {topic["description"]}
IN scope: {topic["in"]}
OUT of scope: {topic["out"]}

Source: {source["name"]} ({source.get("type", "")}) — covers subarea(s): {subarea_label}
Why this source is subscribed: {source.get("why", "")}{slice_block}

This week's items from this source (last {RECENCY_DAYS} days):
{rows}

HARD GATE — apply FIRST, before any other consideration:
If an item's subject falls in the OUT of scope (or is simply not about this
topic at all — e.g. an EV-charging or consumer-battery story on a grid
economics feed), REJECT it outright regardless of how interesting it is.
Apply the OUT terms as SCOPE, not keywords: "Consumer EVs" means consumer
EV products/reviews/gadget content — NOT policy or market stories about
electrification and EV demand growth, which are IN scope (the area tracks
electrification demand as a grid-economics force). Likewise "corporate
sustainability PR" is out, but a country's energy/climate policy decision is
in. There is NO geographic restriction: a policy or market development in
Ethiopia, Vietnam, or Texas counts exactly as much as one in the UK.

Then, approve ONLY if it ALSO meets the INTEREST bar — at least one of:
  * Empirical data shift: concrete numbers that change the picture (prices,
    capacity, costs, market share) with real analytic content.
  * First-principles systems analysis: explains mechanism, incentives, or
    constraints — not merely that something happened.
  * Structural surprise: a finding a careful reader of this topic would not
    already know and would not want to miss.

REJECT, even when in-topic and true:
  * Project announcements: commissioning, inaugurations, groundbreakings,
    tender launches, agreement signings, financings, acquisitions — UNLESS the
    item itself carries an empirical or analytical insight beyond the
    announcement.
  * CEO quotes, corporate PR, SPAC rumors, "X says Y" filler.
  * Factsheets, explainer pages, "what is X" primers, and policy documents
    that merely restate existing plans without new information.
  * Routine market updates with no analysis.
  * Anything already obvious to a regular reader of this topic.

Approve at most {MAX_PICKS_PER_SOURCE} items from this source — only the
strongest. Zero approvals is a VALID and expected outcome. When unsure, reject.

The \"reason\" field is a WHY-RELEVANT clarification, not a summary:
  * Include it ONLY when the article's relevance to this topic is NOT obvious
    from its title alone — opaque titles, indirect relevance, or significance
    that needs one concrete number or connection to land.
  * Keep it to a few words or one short clause. Empty string ('') when the
    title already makes the relevance clear.

For every approved item, ALSO write the \"empirical_event\": one sentence
stating the observed event or data shift the article reports (what actually
happened, with the concrete number or shift), phrased so it can stand as the
digest's Observed Event bullet.

{SCHEMA_HINT}"""
    limiter.wait()
    data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    verdicts: dict[str, dict[str, Any]] = {
        v["url"]: v for v in data.get("verdicts", []) if isinstance(v, dict) and v.get("url")
    }
    missing = [it for it in items if it["url"] not in verdicts]
    if missing:
        # The model occasionally omits items; give it ONE focused retry on
        # exactly the missing ones before falling back to reject.
        retry_rows = "\n".join(_item_row(it) for it in missing)
        retry_prompt = f"""You omitted verdicts for these items from the previous batch.
Same rules — this call is stateless, so the full bar is restated:

Topic: {topic["name"]}
IN scope: {topic["in"]}
OUT of scope: {topic["out"]}

Source: {source["name"]} — covers subarea \"{source["subarea"]}\"

HARD GATE first: REJECT outright anything in the OUT of scope (apply OUT as
scope, not keywords — EV/policy/market stories are IN, consumer EV content is
OUT). Then approve only empirical data shifts, first-principles systems
analysis, or structural surprises; reject announcements, PR, explainers, and
routine updates. When unsure, reject. Zero approvals is valid.

Return EXACTLY one verdict per item below, same order:
{retry_rows}

{SCHEMA_HINT}"""
        try:
            limiter.wait()
            data = llm.chat_json(retry_prompt, max_tokens=LLM_MAX_TOKENS)
            for v in data.get("verdicts", []):
                if isinstance(v, dict) and v.get("url"):
                    _ = verdicts.setdefault(v["url"], v)
        except Exception as exc:  # noqa: BLE001 — retry is best-effort
            print(f"      retry failed for {source['name']}: {redact(str(exc))[:160]}")

    # Approved verdicts MUST carry an empirical_event sentence (FR-9 digest
    # contract). The model sometimes approves without one; retry those once,
    # then demote any still missing to rejected rather than emitting an empty
    # Observed Event bullet.
    missing_event = [
        it
        for it in items
        if parse_bool(verdicts.get(it["url"], {}).get("approved"))
        and not str(verdicts[it["url"]].get("empirical_event", "")).strip()
    ]
    if missing_event:
        retry_rows = "\n".join(_item_row(it) for it in missing_event)
        retry_prompt = f"""You approved these items but omitted the required \"empirical_event\"
sentence. Add it: ONE sentence stating the observed event or data shift the
article reports, phrased to stand as the digest's Observed Event bullet.

{retry_rows}

{SCHEMA_HINT}"""
        try:
            limiter.wait()
            data = llm.chat_json(retry_prompt, max_tokens=LLM_MAX_TOKENS)
            for v in data.get("verdicts", []):
                if isinstance(v, dict) and v.get("url"):
                    # DIRECT assignment: the retried verdict must REPLACE the
                    # empty-event one (setdefault would silently discard it).
                    verdicts[v["url"]] = v
        except Exception as exc:  # noqa: BLE001 — retry is best-effort
            print(f"      empirical_event retry failed for {source['name']}: {redact(str(exc))[:160]}")

    out: list[Verdict] = []
    for it in items:
        v = verdicts.get(it["url"])
        if v is None:
            v = {"approved": False, "reason": "no verdict returned", "thesis": "", "empirical_event": ""}
        approved = parse_bool(v.get("approved"))
        if approved and not str(v.get("empirical_event", "")).strip():
            # Still missing after retry: demote — a digest bullet must not be empty.
            approved = False
            v = {
                **v,
                "approved": False,
                "reason": "approved but missing empirical_event",
                "thesis": "",
                "empirical_event": "",
            }
        out.append(
            {
                "url": it["url"],
                "title": it["title"],
                "approved": approved,
                "reason": str(v.get("reason", ""))[:200],
                "subarea": source["subarea"],  # the source's subarea, never model-invented
                "thesis": str(v.get("thesis", ""))[:200],
                "empirical_event": str(v.get("empirical_event", ""))[:200] if approved else "",
            }
        )
    return out


# --- report ---------------------------------------------------------------


def render_report(summary: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    lines = [
        "# SignalFlow — Weekly Article Selection Report (spike)",
        "",
        f"- Topic: {summary['topic']}",
        f"- Run: {summary['generated_at']} | window: last {summary['recency_days']} days",
        f"- Sources: {summary['sources_total']} | fetched ok: {summary['sources_ok']} | "
        + f"failed: {summary['sources_failed']} | cache reuse: {summary['cache_reuse']}",
        f"- Items in window: {summary['items_window']} (undated: {summary['items_undated']}) | "
        + f"evaluated now: {summary['items_new']} | verdict cached: {summary['items_cached']}",
        f"- Picks: {summary['picked']} | sources with zero picks: {summary['zero_pick_sources']}",
        f"- Area story: v{summary['story_version']} (updated {summary['story_updated'] or '—'}) "
        + "— see spikes/output/story_*.md",
        "",
    ]
    for sec in sections:
        lines.append(f"## {sec['source']} ({sec['domain']}) — {sec['subarea']}")
        lines.append("")
        if sec["fetch_error"]:
            lines.append(f"- **fetch failed**: {sec['fetch_error']}")
        if sec["eval_error"]:
            lines.append(f"- **evaluation failed** (no verdicts judged): {sec['eval_error']}")
        if sec["stale"]:
            lines.append("- **stale cache fallback** (fetch failed, cached items shown)")
        lines.append(f"- items in window: {sec['n_items']} | picked: {sec['n_picked']}")
        lines.append("")
        if sec["picks"]:
            for p in sec["picks"]:
                lines.append(f"- **{p['title']}** <{p['url']}>")
                if p.get("reason"):
                    lines.append(f"  - why relevant: {p['reason']}")
                if p.get("thesis"):
                    lines.append(f"  - thesis: {p['thesis']}")
                if p.get("empirical_event"):
                    lines.append(f"  - observed event: {p['empirical_event']}")
        else:
            lines.append("- 0 picked — nothing worth surfacing this week (valid outcome).")
        lines.append("")
    return "\n".join(lines)


# --- area story ----------------------------------------------------------

# Story record: {"version": int, "updated_at": iso, "overview": str (the big
# picture), "angles": {subarea: [str]} (durable mechanisms/questions),
# "open_questions": [str], "pending": [pick dicts]}. The story is generated
# BIG-PICTURE-FIRST from the topic boundary + subareas (prompts/generate_area_story.md)
# with NO article input; folds only ADAPT the big picture (never append article
# specifics). Picks are folded at the START of a later run that has new work;
# folding bumps the version, which re-keys the verdict cache (same semantics as
# PROMPT_REV). A fold that changes nothing keeps the version.


def story_path(slug: str) -> Path:
    return STORY_DIR / f"{slug}.json"


def empty_story() -> dict[str, Any]:
    return {"version": 0, "updated_at": "", "overview": "", "angles": {}, "open_questions": [], "pending": []}


def load_story(slug: str) -> dict[str, Any]:
    p = story_path(slug)
    if not p.exists():
        return empty_story()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print(f"      warning: story for {slug} unreadable — starting fresh")
        return empty_story()
    for key, default in (
        ("version", 0),
        ("updated_at", ""),
        ("overview", ""),
        ("angles", {}),
        ("open_questions", []),
        ("pending", []),
    ):
        data.setdefault(key, default)
    return data


def save_story(slug: str, story: dict[str, Any]) -> None:
    STORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = story_path(slug).with_suffix(".tmp")
    _ = tmp.write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _ = tmp.replace(story_path(slug))


def seed_story(
    slug: str, topic: dict[str, Any], listing: dict[str, Any], llm: LLM, limiter: RateLimiter
) -> dict[str, Any]:
    """Generate the INITIAL big-picture story from the topic boundary + subareas.

    Deliberately takes NO article/feed content: the story must not be biased
    by any single crawl or outlet's editorial line. One LLM call; on failure
    fall back to an empty story (evaluation then runs with no context rather
    than crashing the spike).
    """
    if not STORY_PROMPT_PATH.exists():
        print(f"      warning: {STORY_PROMPT_PATH.relative_to(ROOT)} missing — starting with empty story")
        return empty_story()
    prompt_tmpl = STORY_PROMPT_PATH.read_text(encoding="utf-8")
    subareas = ""
    for sa in listing.get("subareas") or []:
        types = sorted({s.get("type", "") for s in sa.get("sources") or [] if s.get("type")})
        subareas += f"- {sa.get('name', '?')} ({sa.get('coverage', '?')}): {', '.join(types)}\n"
    # {topic.name} style needs attribute access; SimpleNamespace supplies it.
    # Plain replace (not .format): the template contains JSON example braces.
    ns = SimpleNamespace(**topic)
    prompt = (
        prompt_tmpl.replace("{topic.name}", ns.name)
        .replace("{topic.description}", ns.description)
        .replace("{topic.in}", getattr(ns, "in"))
        .replace("{topic.out}", ns.out)
        .replace("{subareas}", subareas.strip())
    )
    try:
        limiter.wait()
        data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — seed is best-effort
        print(f"      story seed failed: {redact(str(exc))[:160]}")
        return empty_story()
    if not isinstance(data, dict) or not isinstance(data.get("angles"), dict) or not data.get("angles"):
        print("      story seed returned no angles — starting with empty story")
        return empty_story()
    angles: dict[str, Any] = data.get("angles") or {}
    return {
        "version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "overview": str(data.get("overview", "")).strip(),
        "angles": {
            str(k): [str(a).strip() for a in v][:STORY_MAX_ANGLES] for k, v in angles.items() if isinstance(v, list)
        },
        "open_questions": [str(q).strip() for q in (data.get("open_questions") or [])][:STORY_MAX_QUESTIONS],
        "pending": [],
    }


def story_slice(story: dict[str, Any], subarea: str) -> str:
    """Compact per-subarea slice injected into a source's evaluation prompt.

    Only this source's subarea: its big-picture angles plus a couple of the
    topic's open questions. Never the whole story — no prompt grows with it.
    """
    lines: list[str] = []
    angles = story.get("angles", {}).get(subarea, [])
    if angles:
        lines.append(f"Big-picture angles we track on this subarea ({subarea}):")
        lines.extend(f"- {a}" for a in angles[:STORY_MAX_ANGLES])
    questions = story.get("open_questions", [])
    if questions:
        lines.append("Open questions this area is tracking:")
        lines.extend(f"- {q}" for q in questions[:3])
    return "\n".join(lines)


def fold_story(
    story: dict[str, Any], picks: list[dict[str, Any]], topic: dict[str, Any], llm: LLM, limiter: RateLimiter
) -> bool:
    """Adapt the story's BIG PICTURE from approved picks: one LLM call.

    The story stays big-picture: angles evolve only when the new evidence
    shifts a mechanism/tension/question; article specifics (titles, deals,
    numbers) are NEVER appended. If the model judges nothing material changed
    (returns the current story), the version is NOT bumped — so a quiet fold
    leaves the verdict cache intact.

    Returns True when the fold ran to completion (changed OR unchanged); False
    when the LLM call failed or returned malformed output — the caller must
    then KEEP the pending queue so the fold is retried, not silently dropped.
    """
    rows = "\n".join(
        f"- [{p.get('date', '?')}] ({p.get('subarea', '')}) {p['title']} "
        + f"— {p.get('reason', '')} | thesis: {p.get('thesis', '')} | {p['url']}"
        for p in picks
    )
    current = {k: v for k, v in story.items() if k != "pending"}
    prompt = f"""You maintain the long-form story of a topic area for a personal discovery feed.
The story is BACKGROUND MATERIAL: a narrative overview, per-subarea sections
that explain how the area works (mechanisms, tensions, what is changing), and a
few open questions. It must stay in the big picture — it is NOT a log of
articles and NOT a list of questions.

Topic: {topic["name"]}
IN scope: {topic["in"]}
OUT of scope: {topic["out"]}

Current story:
{json.dumps(current, indent=2, ensure_ascii=False)}

Newly approved articles (evidence about the big picture, not content of it):
{rows}

Adapt the story ONLY where the evidence genuinely shifts the big picture:
1. overview: revise only if the area's shape materially changed (rare). Keep it a
   3-6 sentence narrative introduction.
2. angles: per subarea, 2-{STORY_MAX_ANGLES} DECLARATIVE background sentences that
   explain how the subarea works. Update a sentence only when the evidence changes
   the mechanism, tension, or trajectory being described. NEVER add article titles,
   deals, or datapoints; keep at most ONE question per section.
3. open_questions: up to {STORY_MAX_QUESTIONS}; add a genuinely new question the
   evidence opens, drop one now answered.
If nothing materially changed, return the current story UNCHANGED.

Respond with STRICT JSON only:
{{"overview": "...", "angles": {{"<subarea>": ["..."]}}, "open_questions": ["..."]}}"""
    try:
        limiter.wait()
        data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — fold is best-effort; keep the current story
        print(f"      story fold failed: {redact(str(exc))[:160]}")
        return False
    raw_angles = data.get("angles")
    if not isinstance(data, dict) or not isinstance(raw_angles, dict) or not raw_angles:
        print("      story fold returned no angles — pending kept for retry")
        return False
    angles = {
        str(k): [str(a).strip() for a in v][:STORY_MAX_ANGLES] for k, v in raw_angles.items() if isinstance(v, list)
    }
    questions = [str(q).strip() for q in (data.get("open_questions") or [])][:STORY_MAX_QUESTIONS]
    overview = str(data.get("overview", story.get("overview", ""))).strip()
    if angles == story.get("angles") and questions == story.get("open_questions") and overview == story.get("overview"):
        print("      story unchanged by fold — version kept")
        return True
    story["overview"] = overview
    story["angles"] = angles
    story["open_questions"] = questions
    story["version"] = int(story.get("version", 0)) + 1
    story["updated_at"] = datetime.now(UTC).isoformat()
    return True


def render_story_markdown(story: dict[str, Any], topic_name: str) -> str:
    lines = [f"# {topic_name} — Area Story", ""]
    lines.append(f"Version {story.get('version', 0)} · updated {story.get('updated_at', '')[:10]}")
    lines.append("")
    overview = story.get("overview", "")
    if overview:
        lines.append("## Overview")
        lines.append("")
        lines.append(overview)
        lines.append("")
    for subarea, angles in sorted(story.get("angles", {}).items()):
        lines.append(f"## {subarea}")
        lines.append("")
        lines.extend(f"- {a}" for a in angles)
        lines.append("")
    if story.get("open_questions"):
        lines.append("## Open questions")
        lines.append("")
        lines.extend(f"- {q}" for q in story["open_questions"])
        lines.append("")
    pending = story.get("pending", [])
    if pending:
        lines.append(f"## Pending (queued, folded at next run's start: {len(pending)})")
        lines.append("")
        lines.extend(f"- {p.get('title', '')}" for p in pending)
        lines.append("")
    return "\n".join(lines)


# --- main -----------------------------------------------------------------


def redact(message: str) -> str:
    for secret in (LLM_KEY,):
        if secret:
            message = message.replace(secret, "***")
    return message


def parse_bool(value: Any) -> bool:
    """Strict truthiness for LLM booleans: only real True or true-ish strings.

    bool("false") is True — a model emitting the string "false" must reject,
    not approve. Accepts bool True and strings in (true, yes, 1); everything
    else (including "false"/"no"/0) is False.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return False


def smoke_test() -> None:
    """Fail fast on config/auth/model errors before any expensive work."""
    print("[0/6] smoke test: router chat ...")
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
    print("      ok")


def load_source_list(topic_name: str) -> tuple[dict[str, Any] | None, list[Source], str]:
    """Find the topic's discovery listing by its topic field; dedupe sources by crawl_root.

    Returns (listing, sources, slug) where slug is the discovery file stem used
    to key the area story.
    """
    listing: dict[str, Any] | None = None
    slug = ""
    for path in DISCOVERY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("topic") == topic_name:
            listing = data
            slug = path.stem
            break
    if listing is None:
        return None, [], ""
    sources: list[Source] = []
    seen: set[str] = set()
    for sa in listing.get("subareas") or []:
        for s in sa.get("sources") or []:
            root = (s.get("crawl_root") or "").strip()
            if not root:
                continue  # registry entries have no feed
            if root in seen:
                # Same feed listed under several subareas — evaluate once.
                for existing in sources:
                    if existing["crawl_root"] == root:
                        existing["subareas"].append(sa.get("name", ""))
                continue
            seen.add(root)
            sources.append(
                {
                    "name": s.get("name", root),
                    "domain": s.get("domain", ""),
                    "type": s.get("type", ""),
                    "why": s.get("why", ""),
                    "crawl_root": root,
                    "subarea": sa.get("name", ""),
                    "subareas": [sa.get("name", "")],
                }
            )
    return listing, sources, slug


def main(argv: list[str] | None = None) -> int:
    del argv  # config comes from env; signature mirrors the engine's main()
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL"):
        if not os.environ.get(var):
            print(f"FATAL: missing env var {var} — check .env (see .env.example)")
            return 1
    smoke_test()

    topics = load_topics()
    topic = next((t for t in topics if t["name"].lower() == TOPIC_NAME.lower()), None)
    if topic is None:
        print(f"unknown topic: {TOPIC_NAME!r}; available:\n  " + "\n  ".join(t["name"] for t in topics))
        return 1
    listing, sources, slug = load_source_list(topic["name"])
    if listing is None:
        print(f"no discovery source list for {topic['name']!r} — run `make topic-sources TOPIC=...` first")
        return 1
    print(f"[1/6] topic: {topic['name']} | {len(sources)} unique sources (from docs/discovery/)")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    story = load_story(slug)
    llm = LLM(
        Config(
            llm_key=LLM_KEY,
            llm_base=LLM_BASE,
            llm_model=LLM_MODEL,
            google_key=os.environ.get("GOOGLE_API_KEY", ""),
            embed_model=os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"),
            exa_key=os.environ.get("EXA_API_KEY", ""),
        )
    )
    limiter = RateLimiter(EVAL_INTERVAL)
    if not story.get("angles"):
        # No story yet: generate the initial BIG-PICTURE story from the topic
        # boundary + subareas ONLY (no article/feed input — the story must not
        # be biased by any single crawl or outlet).
        print("      seeding initial area story from topic boundary (no article input) ...")
        story = seed_story(slug, topic, listing, llm, limiter)
        if story.get("angles"):
            save_story(slug, story)
            print(
                f"      story seeded: v{story['version']} — "
                + f"{sum(len(v) for v in story['angles'].values())} angles, "
                + f"{len(story['open_questions'])} open questions"
            )
    story_version = int(story.get("version", 0))
    feeds_cache = load_feeds()
    verdicts_cache = load_verdicts(story_version, slug)
    picked_urls = load_picked_urls()
    if story_version:
        print(
            f"      story: v{story_version} ({story.get('updated_at', '')[:10]}) — "
            + f"{sum(len(v) for v in story.get('angles', {}).values())} angles, "
            + f"{len(story.get('open_questions', []))} open questions"
        )

    # Fetch: reuse fresh cache; re-fetch stale or long-failed; a fetch failure
    # falls back to the last cached items (a transient outage never reads as
    # "site has no articles").
    to_fetch: list[Source] = []
    for s in sources:
        cached = feeds_cache.get(s["crawl_root"])
        if cached is None:
            to_fetch.append(s)
            continue
        age = time.time() - cached.get("fetched_at", 0)
        if cached.get("error"):
            if age >= FAILURE_RETRY_TTL:
                to_fetch.append(s)  # failed long ago -> retry
            else:
                s["cached"] = cached  # recent failure: reuse the recorded error
        elif age < FETCH_TTL:
            s["cached"] = cached  # fresh enough
            s["reused"] = True
        else:
            to_fetch.append(s)  # stale: refresh

    print(f"[2/6] fetching {len(to_fetch)} feeds ({len(sources) - len(to_fetch)} from cache) ...")
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futures = [ex.submit(fetch_feed, s) for s in to_fetch]
        for fut in as_completed(futures):
            s = fut.result()
            old = feeds_cache.get(s["crawl_root"], {})
            had_items = bool(old.get("items"))
            # A 200 HTML/bot-wall/redirect page parses to ZERO entries without
            # raising. Treat that like an outage, not "feed went quiet": keep
            # the last good items and flag it, so a transient bot-wall never
            # reads as "site has no articles". Only a genuinely clean empty
            # feed (no items AND none cached before) is stored as empty.
            zero_new = not s.get("error") and not s.get("items") and had_items
            if s.get("error") or zero_new:
                entry: CacheEntry = {
                    "key": s["crawl_root"],
                    "source": s["name"],
                    "fetched_at": time.time(),
                    "items": old.get("items", []),  # keep the last good cache
                }
                if s.get("error"):
                    entry["error"] = s["error"]
                else:
                    entry["error"] = f"parsed 0 entries; kept {len(old.get('items', []))} cached items"
                    entry["stale"] = True
                    s["stale"] = True  # surface in the report, not just the cache
            else:
                entry = {
                    "key": s["crawl_root"],
                    "source": s["name"],
                    "fetched_at": time.time(),
                    "items": s.get("items", []),
                }
            if s.get("truncated"):
                entry["truncated"] = True
                print(
                    f"      WARNING: {s['name']} feed exceeded {FEED_CAP_BYTES} bytes "
                    "— parsed partially (newest entries usually survive)"
                )
            _append_jsonl(FEEDS_PATH, entry)
            s["cached"] = entry

    # Window items to the last RECENCY_DAYS; exclude already-picked urls.
    cutoff = datetime.now(UTC) - timedelta(days=RECENCY_DAYS)
    n_fetched = n_cache = n_failed = n_undated = n_junk = 0
    for s in sources:
        cached = s["cached"]
        if cached.get("error") and not cached.get("items"):
            s["fetch_error"] = cached["error"]  # dead feed: nothing to judge
            n_failed += 1
            s["items"] = []
            s["n_total_window"] = 0
            continue
        if cached.get("error"):
            s["stale"] = True  # fetch failed; showing cached items
            n_failed += 1
        elif s.get("reused"):
            n_cache += 1
        else:
            n_fetched += 1
        items: list[Item] = []
        for it in cached.get("items", []):
            if it["url"] in picked_urls:
                continue  # already surfaced in an earlier run
            if any(m in it["title"].lower() for m in JUNK_TITLE_MARKERS):
                n_junk += 1  # boilerplate document, not an article — never reaches the LLM
                continue
            if it.get("published"):
                try:
                    pub = datetime.fromisoformat(it["published"])
                except ValueError:
                    pub = None
                if pub is not None and pub < cutoff:
                    continue
            items.append(it)
            if it.get("undated"):
                n_undated += 1
        items.sort(key=lambda x: str(x.get("published") or ""), reverse=True)
        s["items"] = items[:MAX_ITEMS_PER_SOURCE]
        s["n_total_window"] = len(items)
    n_window = sum(s["n_total_window"] for s in sources)
    n_with_items = sum(1 for s in sources if s["items"])
    print(f"      sources: {n_fetched} fetched, {n_cache} cache reuse, {n_failed} failed/stale")

    print(
        f"[3/6] window filter: {n_window} items in last {RECENCY_DAYS} days "
        + f"({n_undated} undated, {n_junk} boilerplate-filtered) across {n_with_items} sources"
    )

    # Deferred story fold: queued picks from previous runs fold into the story
    # ONLY when this run has genuinely new items to evaluate (so a same-week
    # re-run — everything cached — never folds, never bumps the version, and
    # stays idempotent). Folding changes the context, so it invalidates the
    # verdict cache; the fresh window is then judged against the enriched story.
    todo_total = sum(1 for s in sources for it in s.get("items", []) if it["url"] not in verdicts_cache)
    if todo_total and story.get("pending"):
        print(f"      folding {len(story['pending'])} queued picks into story ...")
        if fold_story(story, story["pending"], topic, llm, limiter):
            story["pending"] = []
            save_story(slug, story)
            story_version = int(story.get("version", 0))
            verdicts_cache = load_verdicts(story_version, slug)
            print(f"      story now v{story_version} — verdict cache re-keyed")
        else:
            print("      story fold failed — pending picks kept for the next run")

    n_new = n_cached = 0
    print(f"[4/6] LLM evaluation (per source, {EVAL_INTERVAL}s global pacing) ...")
    for s in sources:
        if not s["items"]:
            s["verdicts"] = []
            continue
        todo: list[Item] = []
        for it in s["items"]:
            # Cache key = (slug, subarea, url): the same URL in two sources with
            # different subareas is judged per-subarea (label + story-slice
            # context differ), so each gets its own entry — keying by url alone
            # made the two sources overwrite each other and re-judge every run.
            cached_v = verdicts_cache.get(f"{slug}|{s['subarea']}|{it['url']}")
            if cached_v is not None:
                s.setdefault("cached_verdicts", []).append(cached_v)
                n_cached += 1
            else:
                todo.append(it)
        if todo:
            n_new += len(todo)
            try:
                slices = [story_slice(story, sub) for sub in (s.get("subareas") or [s["subarea"]])]
                verdicts = evaluate_source(s, todo, topic, llm, limiter, "\n\n".join(x for x in slices if x))
            except Exception as exc:  # noqa: BLE001 — keep the run alive; cached verdicts still count
                print(f"      evaluation failed for {s['name']}: {redact(str(exc))[:200]}")
                s["eval_error"] = redact(str(exc))[:200]
                s["verdicts"] = s.get("cached_verdicts", [])
                continue
            for v in verdicts:
                _append_jsonl(
                    VERDICTS_PATH,
                    {
                        "key": f"{slug}|{s['subarea']}|{v['url']}",
                        "slug": slug,
                        "rev": PROMPT_REV,
                        "story_ver": story_version,
                        **v,
                    },
                )
            s["verdicts"] = s.get("cached_verdicts", []) + verdicts
        else:
            s["verdicts"] = s.get("cached_verdicts", [])
    print(f"      evaluated {n_new} new items, {n_cached} from cache")

    picks: list[dict[str, Any]] = []
    seen_pick_urls: set[str] = set()
    for s in sources:
        order = {it["url"]: i for i, it in enumerate(s["items"])}
        approved = sorted(
            (v for v in s.get("verdicts", []) if parse_bool(v.get("approved"))),
            key=lambda v: order.get(v["url"], len(s["items"])),
        )
        if len(approved) > MAX_PICKS_PER_SOURCE:
            print(f"      cap: {s['name']} approved {len(approved)} — keeping {MAX_PICKS_PER_SOURCE}")
        s["picks"] = approved[:MAX_PICKS_PER_SOURCE]
        for v in s["picks"]:
            if v["url"] in seen_pick_urls:
                continue  # same normalized URL surfaced by two feeds: pick once
            seen_pick_urls.add(v["url"])
            picks.append(
                {
                    "url": v["url"],
                    "title": v["title"],
                    "source": s["name"],
                    "domain": s["domain"],
                    "subarea": v.get("subarea") or s["subarea"],
                    "reason": v.get("reason", ""),
                    "thesis": v.get("thesis", ""),
                    "empirical_event": v.get("empirical_event", ""),
                }
            )

    # Queue this run's picks for the NEXT run's fold (deferred — folding now
    # would bump the story version and invalidate the verdicts we just cached,
    # breaking same-week idempotency). A quiet run leaves the queue untouched.
    if picks:
        known_pending = {p.get("url") for p in story.get("pending", [])}
        story["pending"] = story.get("pending", []) + [p for p in picks if p["url"] not in known_pending]
        save_story(slug, story)
    story_md = render_story_markdown(story, topic["name"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / "weekly_report.md"
    story_md_path = OUT_DIR / f"story_{slug}.md"
    summary: dict[str, Any] = {
        "topic": topic["name"],
        "generated_at": datetime.now(UTC).isoformat(),
        "recency_days": RECENCY_DAYS,
        "sources_total": len(sources),
        "sources_ok": n_fetched,
        "sources_failed": n_failed,
        "cache_reuse": n_cache,
        "items_window": n_window,
        "items_undated": n_undated,
        "items_new": n_new,
        "items_cached": n_cached,
        "picked": len(picks),
        "zero_pick_sources": sum(1 for s in sources if s["items"] and not s["picks"]),
        "story_version": story.get("version", 0),
        "story_updated": story.get("updated_at", "")[:10],
    }
    sections = [
        {
            "source": s["name"],
            "domain": s["domain"],
            "subarea": s["subarea"],
            "fetch_error": s.get("fetch_error", ""),
            "eval_error": s.get("eval_error", ""),
            "stale": s.get("stale", False),
            "n_items": s.get("n_total_window", len(s["items"])),
            "n_picked": len(s.get("picks", [])),
            "picks": s.get("picks", []),
        }
        for s in sources
    ]
    _ = report_path.write_text(render_report(summary, sections), encoding="utf-8")
    _ = story_md_path.write_text(story_md, encoding="utf-8")

    tmp = PICKS_PATH.with_suffix(".tmp")
    payload = json.dumps(
        {"generated_at": summary["generated_at"], "topic": topic["name"], "picks": picks},
        indent=2,
        ensure_ascii=False,
    )
    _ = tmp.write_text(payload + "\n", encoding="utf-8")
    _ = tmp.replace(PICKS_PATH)

    # Record the pick history ONLY after every output artifact is written — a
    # crash before this point must not permanently exclude URLs from future
    # evaluation (picked URLs never re-enter the window).
    for p in picks:
        record_pick({"url": p["url"], "title": p["title"], "source": p["source"]})
    print(f"[5/6] picked {len(picks)} articles")
    for p in picks:
        print(f"      - [{p['source']}] {p['title'][:90]}")
    zero = [s["name"] for s in sources if s["items"] and not s["picks"]]
    if zero:
        print(f"      zero picks ({len(zero)}): {', '.join(zero[:8])}{' …' if len(zero) > 8 else ''}")
    print(f"[6/6] report -> {report_path.relative_to(ROOT)}")
    print(f"      picks  -> {PICKS_PATH.relative_to(ROOT)}")
    print(f"      story  -> {story_md_path.relative_to(ROOT)} (v{story.get('version', 0)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
