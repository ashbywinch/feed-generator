#!/usr/bin/env python3
"""Eval: can the area story contextualize a fresh article?

Acceptance criterion (the point of the story): a smart person whose only
exposure to the area is a generic news feed must be able to contextualize a
new article into the big picture by reading the story's BACKGROUND material.

Two gates:

1. MECHANICAL — the story must BE background material, not a question list:
   - The overview is a real narrative (>= OVERVIEW_MIN_WORDS words, mostly
     declarative sentences, no URLs/dates-as-events).
   - Every subarea section carries declarative background sentences
     (>= MIN_DECLARATIVE_PER_SECTION), not just open questions.
   - No story section is dominated by interrogatives (<= MAX_QUESTION_FRAC
     of its sentences).
   - No URLs or ISO dates leak into the story (events don't belong).

2. CONTEXTUALIZATION — for each of K held-out articles (approved or not,
   drawn from the feed cache but NOT from the story's own evidence), an LLM
   reader is given the story + the article and must write the one-sentence
   caption that links the article into the big picture, then judge whether
   the story alone gave enough background to do it (no general-knowledge
   imports). Passes when >= PASS_FRAC of the articles are contextualizable.

Run: make eval-story   (or: .venv/bin/python spikes/eval_story.py)

Exit 0 = eval passes; 1 = any gate fails. Never prints API keys.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
STATE_DIR = ROOT / "spikes" / "state"
FEEDS_PATH = STATE_DIR / "weekly_feeds.jsonl"
VERDICTS_PATH = STATE_DIR / "weekly_verdicts.jsonl"
PICKS_HISTORY_PATH = STATE_DIR / "weekly_picks.jsonl"
STORY_DIR = STATE_DIR / "stories"

LLM_BASE = os.environ.get("OPENCODE_GO_BASE_URL", "")
LLM_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")
LLM_MODEL = os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash")

# Eval-gate thresholds live on the Config env surface (PRD config contract,
# r15): the eval and the weekly pipeline share one source of truth so a
# threshold changed via .env cannot silently drift the two apart.
CFG = Config(
    llm_key=LLM_KEY,
    llm_base=LLM_BASE,
    llm_model=LLM_MODEL,
    google_key=os.environ.get("GOOGLE_API_KEY", ""),
    embed_model=os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001"),
    exa_key=os.environ.get("EXA_API_KEY", ""),
)

OVERVIEW_MIN_WORDS = CFG.eval_overview_min_words
MIN_DECLARATIVE_PER_SECTION = CFG.eval_min_declarative
MAX_QUESTION_FRAC = CFG.eval_max_question_frac
EVAL_INTERVAL = CFG.weekly_eval_interval
LLM_MAX_TOKENS = 8192
MAX_EVAL_ARTICLES = CFG.eval_max_articles  # held-out articles judged per run
PASS_FRAC = CFG.eval_pass_frac  # fraction of articles that must contextualize
RECENCY_DAYS = CFG.weekly_recency_days  # sample window matches the weekly pipeline

# Global-coverage fixtures: held-out articles from OUTSIDE the UK/EU feed bias.
# The feed cache is UK/EU-heavy, so without fixtures the eval never tests whether
# a non-UK story can be placed. These are always judged, in addition to feed
# articles, so "is the system global?" is checked on every run.
GLOBAL_FIXTURES: list[Item] = [
    {
        "url": "https://example.org/ethiopia-ev-policy",
        "title": "Ethiopia becomes first country to ban petrol car imports, betting on an EV fleet",
        "summary": (
            "Ethiopia has banned import of petrol and diesel cars, a first globally. "
            "With nearly all cars imported and a hydropower-heavy grid, the government is betting "
            "on EVs to cut fuel imports and leverage clean electricity. Analysts note grid "
            "capacity and charging infrastructure constraints."
        ),
        "source": "fixture (global EV policy)",
    },
    {
        "url": "https://example.org/vietnam-grid-battery",
        "title": "Vietnam opens its first grid-scale battery storage tender as renewables outpace grid investment",
        "summary": (
            "Vietnam has launched a tender for grid-scale battery storage, seeking to firm up "
            "solar output as connection constraints grow. Developers say the revenue framework "
            "is unclear, and international players are waiting on tariff design before bidding."
        ),
        "source": "fixture (global storage tender)",
    },
]

Item = dict[str, Any]


def redact(message: str) -> str:
    for secret in (LLM_KEY,):
        if secret:
            message = message.replace(secret, "***")
    return message


def parse_bool(value: Any) -> bool:
    """Strict truthiness for LLM booleans: only real True or true-ish strings.

    bool("false") is True — a model emitting the string "false" must not be
    counted as sufficient. Accepts bool True and strings in (true, yes, 1);
    everything else (including "false"/"no"/0) is False.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return False


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1  # torn tail line from a crash; that work is redone
            continue
        out[entry["key"]] = entry
    if skipped:
        print(f"      WARNING: {path.name}: skipped {skipped} corrupt line(s) — work will be redone")
    return out


def load_story(slug: str) -> dict[str, Any] | None:
    p = STORY_DIR / f"{slug}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation; drop empties."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def is_question(s: str) -> bool:
    starters = ("how ", "what ", "why ", "when ", "where ", "which ", "who ", "is ", "are ", "can ", "will ", "should ")
    return s.rstrip().endswith("?") or s.strip().lower().startswith(starters)


def question_frac(text: str) -> float:
    ss = sentences(text)
    if not ss:
        return 0.0
    return sum(1 for s in ss if is_question(s)) / len(ss)


def contamination(text: str) -> list[str]:
    """URLs and ISO dates are events/links — they don't belong in background."""
    out: list[str] = []
    if re.search(r"https?://|www\.", text):
        out.append("contains URL(s)")
    if re.search(r"\d{4}-\d{2}-\d{2}", text):
        out.append("contains ISO date(s)")
    return out


def mechanical_check(story: dict[str, Any]) -> list[str]:
    """Return a list of failures (empty = pass)."""
    failures: list[str] = []
    overview = str(story.get("overview", "")).strip()
    ov_words = len(overview.split())
    ov_qfrac = question_frac(overview)
    if ov_words < OVERVIEW_MIN_WORDS:
        failures.append(f"overview too short ({ov_words} words < {OVERVIEW_MIN_WORDS})")
    elif ov_qfrac > MAX_QUESTION_FRAC:
        failures.append(f"overview is mostly questions ({ov_qfrac:.0%} interrogative)")
    for bad in contamination(overview):
        failures.append(f"overview {bad}")

    angles = story.get("angles", {})
    if not isinstance(angles, dict) or not angles:
        failures.append("no subarea sections in story")
    else:
        for subarea, lines in angles.items():
            if not isinstance(lines, list):
                failures.append(f"section '{subarea}': malformed (not a list)")
                continue
            text = "\n".join(str(x) for x in lines)
            declarative = sum(1 for s in sentences(text) if not is_question(s))
            qfrac = question_frac(text)
            if declarative < MIN_DECLARATIVE_PER_SECTION:
                failures.append(
                    f"section '{subarea}': only {declarative} declarative sentence(s) — questions, not background"
                )
            if qfrac > MAX_QUESTION_FRAC:
                failures.append(f"section '{subarea}': {qfrac:.0%} interrogative (background, not a question list)")
            for bad in contamination(text):
                failures.append(f"section '{subarea}': {bad}")
    return failures


def render_story_text(story: dict[str, Any], topic_name: str) -> str:
    lines = [f"# {topic_name} — Area Story", ""]
    if story.get("overview"):
        lines.append(str(story["overview"]))
        lines.append("")
    for subarea, sec_lines in sorted(story.get("angles", {}).items()):
        lines.append(f"## {subarea}")
        lines.append("")
        for x in sec_lines:
            lines.append(f"- {x}")
        lines.append("")
    if story.get("open_questions"):
        lines.append("## Open questions")
        lines.append("")
        for q in story["open_questions"]:
            lines.append(f"- {q}")
        lines.append("")
    return "\n".join(lines)


def held_out_articles(
    feeds_cache: dict[str, dict[str, Any]], picked_urls: set[str], story: dict[str, Any]
) -> list[Item]:
    """Held-out articles: GLOBAL fixtures always, then feed articles up to the cap.

    The fixtures guarantee the eval tests non-UK placement every run; the feed
    articles add the current week's real coverage. Feed articles are excluded if
    they were the story's own evidence (picks/pending).
    """
    story_urls = {e.get("url") for e in story.get("pending", [])}
    out: list[Item] = [dict(f) for f in GLOBAL_FIXTURES]
    seen_sources = {f["source"] for f in GLOBAL_FIXTURES}
    cutoff = datetime.now(UTC) - timedelta(days=RECENCY_DAYS)
    for feed in feeds_cache.values():
        for it in feed.get("items", []):
            if len(out) >= MAX_EVAL_ARTICLES:
                return out
            url = it.get("url", "")
            if url in picked_urls or url in story_urls:
                continue
            if not it.get("title") or not it.get("summary"):
                continue
            if it.get("published"):
                try:
                    pub = datetime.fromisoformat(it["published"])
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=UTC)  # legacy naive write: assume UTC (r17)
                except ValueError:
                    pub = None
                if pub is not None and pub < cutoff:
                    continue
            elif it.get("first_seen"):
                # undated items window on first_seen, exactly like the weekly
                # pipeline (is_item_in_window) — stale undated articles must
                # not be held out (r18 suggestion)
                try:
                    first = datetime.fromisoformat(it["first_seen"])
                    if first.tzinfo is None:
                        first = first.replace(tzinfo=UTC)
                except ValueError:
                    first = None
                if first is not None and first < cutoff:
                    continue
            source = feed.get("source", "?")
            if source in seen_sources:
                continue
            seen_sources.add(source)
            out.append(
                {
                    "url": url,
                    "title": it.get("title", ""),
                    "summary": it.get("summary", ""),
                    "source": source,
                }
            )
    return out


def contextualize(article: Item, story_text: str, topic_name: str, llm: LLM, limiter: RateLimiter) -> dict[str, Any]:
    """Give the story + article to a reader; get the linking caption + self-judgment.

    The criterion is PLACEMENT: can the reader fit the article into the story's
    big picture (which subarea/mechanism/tension it speaks to) using the story's
    background alone? The story is not expected to mention the article or its
    specifics; correctly placing a routine article as 'routine, not structural'
    counts as successful placement.
    """
    prompt = f"""You are a smart reader of a personal discovery feed. Your ONLY background on
this topic is the story below — you have not otherwise followed the area beyond
what scrolls past in a generic news feed.

Topic: {topic_name}

STORY (background material):
{story_text}

NEW ARTICLE:
Title: {article["title"]}
Summary: {article["summary"]}

First, WHERE does this article fit in the big picture? Name the specific
subarea, mechanism, or tension from the STORY that this article speaks to
(e.g. 'CfD auction design', 'battery revenue streams', 'grid connection
queues'). If the article is routine or marginal (a routine data publication,
a corporate announcement with no structural import), saying so and naming the
area it touches is a valid placement.

Then write the ONE-sentence caption that would sit under the article's title
in a curated feed — the sentence that links the article into the big picture
using ONLY the story's background.

Then judge: did the story's background give you enough STRUCTURE to place this
article? It counts as sufficient if the story has background on the AREA the
article concerns (e.g. a storage article is placeable when the story explains
storage economics), even if the story never mentions the article. It is
insufficient only if the story lacks background on the area entirely.

Respond with STRICT JSON only:
{{"fits": "subarea/mechanism/tension named, or 'routine — not structural'",
"caption": "the one-sentence caption",
"sufficient": true/false,
"missing": "one short phrase: the AREA background the story lacked, or '' if sufficient"}}"""
    try:
        limiter.wait()
        data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — a router error must FAIL the gate, not crash it
        return {
            "url": article["url"],
            "title": article["title"],
            "source": article["source"],
            "fits": "",
            "caption": "",
            "sufficient": False,
            "missing": f"LLM call failed: {redact(str(exc))[:100]}",
        }
    if not isinstance(data, dict):
        # Malformed model output: judge this article INSUFFICIENT, don't crash.
        return {
            "url": article["url"],
            "title": article["title"],
            "source": article["source"],
            "fits": "",
            "caption": "",
            "sufficient": False,
            "missing": "no parseable LLM judgment",
        }
    return {
        "url": article["url"],
        "title": article["title"],
        "source": article["source"],
        "fits": str(data.get("fits", "")),
        "caption": str(data.get("caption", "")),
        "sufficient": parse_bool(data.get("sufficient")),
        "missing": str(data.get("missing", ""))[:200],
    }


def contextualization_passes(sufficient: int, total: int, pass_frac: float) -> bool:
    """Gate: does the sufficient/total ratio meet the bar?

    Small samples must not tighten the bar to 100%: with only the 2 fixtures
    (stale/empty feed cache), pass_frac * 2 rounds to 2/2. Allow one miss for
    samples of >= 2 so a single fixture judged insufficient doesn't fail the
    gate — but NEVER for total == 1 (0 >= 0 via total - 1 would pass a fully
    failing single-article gate).
    """
    if total == 0:
        return False
    if total >= 2 and sufficient >= total - 1:
        return True
    return sufficient / total >= pass_frac


def load_picked_urls(path: Path | None = None) -> set[str]:
    """URLs already surfaced (pick history); torn tail lines are skipped + logged.

    Mirrors weekly_selection.load_picked_urls and _load_jsonl — every cache
    reader must tolerate a torn tail line AND surface it (compliance: never
    swallow errors silently). `path` is injectable (DI over patching).
    """
    out: set[str] = set()
    pick_path = path if path is not None else PICKS_HISTORY_PATH
    if not pick_path.exists():
        return out
    skipped = 0
    for line in pick_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.add(json.loads(line)["url"])
        except (json.JSONDecodeError, KeyError):
            skipped += 1  # torn tail line from a crash; that entry is lost anyway
    if skipped:
        print(f"      WARNING: {pick_path.name}: skipped {skipped} corrupt line(s)")
    return out


def main(argv: list[str] | None = None) -> int:
    del argv
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL"):
        if not os.environ.get(var):
            print(f"FATAL: missing env var {var} — check .env (see .env.example)")
            return 1

    topics = load_topics()
    topic = next((t for t in topics if t["name"].lower() == TOPIC_NAME.lower()), None)
    if topic is None:
        print(f"unknown topic: {TOPIC_NAME!r}")
        return 1
    slug = ""
    for path in DISCOVERY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("topic") == topic["name"]:
            slug = path.stem
            break
    if not slug:
        print(f"no discovery list for {topic['name']!r}")
        return 1
    story = load_story(slug)
    if story is None:
        print(f"no story for {slug} — run `make spike-weekly` first (or delete spikes/state/stories/ to re-seed)")
        return 1
    print(f"[1/3] eval story v{story.get('version', 0)} for {topic['name']}")

    failures = mechanical_check(story)
    print(f"[2/3] mechanical gate: {'PASS' if not failures else 'FAIL'} ({len(failures)} finding(s))")
    for f in failures:
        print(f"      - {f}")

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
    picked = load_picked_urls()
    feeds_cache = _load_jsonl(FEEDS_PATH)
    articles = held_out_articles(feeds_cache, picked, story)
    print(f"[3/3] contextualization gate: {len(articles)} held-out article(s)")
    results: list[dict[str, Any]] = []
    for a in articles:
        r = contextualize(a, render_story_text(story, topic["name"]), topic["name"], llm, limiter)
        results.append(r)
        verdict = "sufficient" if r["sufficient"] else "INSUFFICIENT"
        print(f"      - [{verdict}] {r['source']}: {r['title'][:70]}")
        print(f"          caption: {r['caption'][:120]}")
        if r["missing"]:
            print(f"          missing: {r['missing']}")

    n_sufficient = sum(1 for r in results if r["sufficient"])
    n = len(results)
    ctx_pass = contextualization_passes(n_sufficient, n, PASS_FRAC)
    mech_pass = not failures
    print()
    print(f"contextualization: {n_sufficient}/{len(results)} sufficient ({'PASS' if ctx_pass else 'FAIL'})")
    print(f"mechanical:        {'PASS' if mech_pass else 'FAIL'}")
    if not ctx_pass:
        print("  held-out articles could NOT be placed using story background alone —")
        print("  the story is not explaining the area, just listing questions/events.")
    return 0 if (mech_pass and ctx_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())
