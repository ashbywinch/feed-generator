#!/usr/bin/env python3
"""Eval: are the topic's discovery queries GLOBAL and well-formed?

The discovery queries drive the engine's Exa search tier. Their original
failure: 3 of 5 were anchored to the UK ("GB grid connection queue
statistics", "UK CfD allocation round", "GB prices"). This eval gates them.

Two gates:

1. MECHANICAL — hard, deterministic:
   - 5-7 non-empty, unique queries.
   - No geography anchors: UK/GB/Britain/British/Ofgem/NESO/Elexon/"National
     Grid"/NEMO/DESNZ. A query naming a single jurisdiction can only surface
     that jurisdiction's news.
   - Each query is a search-shaped noun phrase (>= 2 words, no leading
     article).

2. LLM JUDGMENT — for each query: is it GLOBAL (no jurisdiction binding),
   MECHANISM-FIRST (describes the phenomenon, not a place), IN-SCOPE, and
   DISTINCT from the others? Plus: does the set cover the subareas (at most
   MAX_UNCOVERED may be left out)?

Modes:
  spikes/eval_queries.py            eval the queries currently in the doc
  spikes/eval_queries.py --generate generate new queries via the prompt,
                                     eval them, and persist to docs/discovery/
                                     only when both gates pass.

Run: make eval-queries   (--generate: make refresh-queries)

Exit 0 = pass; 1 = any gate fails. Never prints API keys.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.config import Config  # noqa: E402
from signalflow.env import load_env  # noqa: E402
from signalflow.llm import LLM  # noqa: E402
from signalflow.ratelimit import RateLimiter  # noqa: E402
from signalflow.source_lists import render_markdown  # noqa: E402
from signalflow.topics import load_topics  # noqa: E402

load_env(ROOT / ".env")

TOPIC_NAME = os.environ.get("TOPIC", "Grid & Net Zero economics")
DISCOVERY_DIR = ROOT / "docs" / "discovery"
PROMPTS_DIR = ROOT / "prompts"
QUERIES_PROMPT_PATH = PROMPTS_DIR / "generate_discovery_queries.md"

LLM_BASE = os.environ.get("OPENCODE_GO_BASE_URL", "")
LLM_KEY = os.environ.get("OPENCODE_GO_API_KEY", "")
LLM_MODEL = os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash")

MIN_QUERIES = 5
MAX_QUERIES = 13  # upper bound; a topic's actual subarea count may be lower (see main)
QUERY_SLACK = 2  # extra queries tolerated beyond one-per-subarea (prompt: "strong subareas may get two")

MAX_UNCOVERED = 3  # subareas a query set may leave out and still pass
EVAL_INTERVAL = 1.0
LLM_MAX_TOKENS = 8192

# Coverage tokens are DERIVED from each subarea's name (distinctive words
# minus generic stopwords), so the gate works for ANY topic — no per-topic
# hand-maintained map that silently fails on the next topic's subareas.
SUBAREA_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "beyond",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "vs",
        "&",
        "new",
        "power",
        "grid",
        "market",
        "markets",
        "storage",
        "data",
        "economics",
        "economic",
        "policy",
        "technology",
        "technologies",
        "sector",
        "industry",
    ]
)


def subarea_tokens(name: str) -> tuple[str, ...]:
    """Distinctive words of a subarea name, minus stopwords, with singular/plural variants.

    Emits each significant word plus its singular/plural variant so "batteries"
    in a subarea matches "battery" in a query (and vice versa). Acronyms like
    CAES keep their exact spelling (the bare trailing-s strip would mangle them).
    """
    words = re.findall(r"[a-z0-9]+", name.lower())
    out = []
    for w in words:
        if w in SUBAREA_STOPWORDS or len(w) <= 3:
            continue
        out.append(w)
        if w.endswith("ies"):
            out.append(w[:-3] + "y")  # batteries -> battery
        elif w.endswith("s") and not w.endswith(("ss", "is", "us")):
            out.append(w[:-1])  # markets -> market
    return tuple(dict.fromkeys(out))  # dedupe, keep order


def parse_bool(value: Any) -> bool:
    """Strict truthiness for LLM booleans: only real True or true-ish strings.

    bool("false") is True — a model emitting the string "false" must not pass
    the gate. Accepts bool True and strings in (true, yes, 1); everything else
    (including "false"/"no"/0) is False.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return False


# Hard geography anchors: a query naming any of these can only find that
# jurisdiction's news. "European" is softer (multi-country) but still local;
# keep the strict list to single-jurisdiction terms. U.K. gets its own branch
# with a (?!\w) lookahead — the trailing \b on the group would require a word
# char right after the period, which never happens (dead alternative).
GEO_ANCHORS = re.compile(
    r"\b(GB|UK|Britain|British|England|Wales|Scotland|N\.Ireland|"
    + r"Ofgem|NESO|Elexon|National Grid|NEMO|DESNZ|ERCOT|FERC|CAISO)\b|"
    + r"U\.K\.(?!\w)",
    re.IGNORECASE,
)


def redact(message: str) -> str:
    for secret in (LLM_KEY,):
        if secret:
            message = message.replace(secret, "***")
    return message


def load_listing(topic_name: str) -> tuple[dict[str, Any] | None, str]:
    """(listing, slug) for the topic; slug keys the discovery file."""
    for path in DISCOVERY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"      WARNING: {path.name}: unreadable JSON — skipped")
            continue
        if data.get("topic") == topic_name:
            return data, path.stem
    return None, ""


def query_bounds(subareas: list[str]) -> tuple[int, int]:
    """Mechanical gate bounds that can never deadlock generation.

    Lower bound tracks the topic's real subarea count (a topic with fewer
    subareas than MIN_QUERIES legitimately generates fewer queries — the
    prompt mandates EXACTLY one per subarea), not a hardcoded 5. Upper bound
    is one-per-subarea plus a small slack for the prompt's "strong subareas
    may get two", minus nothing.
    """
    lo = min(len(subareas), MIN_QUERIES)
    hi = max(len(subareas), MIN_QUERIES) + QUERY_SLACK
    return lo, hi


def mechanical_check(queries: list[str], min_queries: int = MIN_QUERIES, max_queries: int = MAX_QUERIES) -> list[str]:
    failures: list[str] = []
    if not (min_queries <= len(queries) <= max_queries):
        failures.append(f"{len(queries)} queries (need {min_queries}-{max_queries})")
    seen: set[str] = set()
    for q in queries:
        qq = q.strip()
        if not qq:
            failures.append("empty query")
            continue
        if qq.lower() in seen:
            failures.append(f"duplicate: {qq!r}")
        seen.add(qq.lower())
        words = qq.split()
        if len(words) < 2:
            failures.append(f"too short: {qq!r}")
        if words[0].lower() in ("the", "a", "an"):
            failures.append(f"leading article: {qq!r}")
        m = GEO_ANCHORS.search(qq)
        if m:
            failures.append(f"geography anchor '{m.group(0)}' in: {qq!r}")
    return failures


def coverage_check(queries: list[str], subareas: list[str]) -> list[str]:
    """Deterministic: every subarea needs a query containing one of its tokens.

    Tokens are derived from each subarea name (subarea_tokens), so any topic's
    subareas are covered — nothing is hardcoded per topic.
    """
    lowered = [q.lower() for q in queries]
    uncovered = []
    for sa in subareas:
        tokens = subarea_tokens(sa)
        if not tokens:
            # Subarea name made entirely of stopwords: cannot judge coverage
            # mechanically — fail loudly rather than silently pass.
            uncovered.append(f"{sa} (no derivable tokens)")
            continue
        if not any(any(re.search(rf"\b{t}\b", q) for t in tokens) for q in lowered):
            uncovered.append(sa)
    return uncovered


def llm_check(queries: list[str], topic: dict[str, Any], llm: LLM, limiter: RateLimiter) -> list[str]:
    """LLM judgment per query: global, mechanism-first, in-scope, distinct.

    Coverage is judged deterministically (coverage_check), not by the LLM —
    the model's coverage verdict was unstable across runs.
    """
    q_rows = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(queries))
    prompt = f"""You are auditing the search-query set for a personal discovery engine.

Topic: {topic["name"]}
IN scope: {topic["in"]}
OUT of scope: {topic["out"]}

Queries under audit:
{q_rows}

For EACH query judge four properties:
- global: NOT bound to one country/region. A query mentioning a place is
  local even if the mechanism is general; "grid connection queues" is global,
  "GB grid connection queues" is not.
- mechanism_first: describes the underlying phenomenon (market, mechanism,
  technology, tension) rather than a place or an outlet.
- in_scope: stays inside the IN scope, not the OUT scope.
- distinct: not a near-duplicate of another query in the set.

Respond with STRICT JSON only:
{{"judgments": [{{"global": true/false, "mechanism_first": true/false,
"in_scope": true/false, "distinct": true/false}}]}}"""
    failures: list[str] = []
    try:
        limiter.wait()
        data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — a router error must FAIL the gate, not crash it
        for i, q in enumerate(queries):
            failures.append(f"query {i + 1} ({q!r}): LLM call failed ({redact(str(exc))[:100]})")
        return failures
    if not isinstance(data, dict):
        # Malformed model output: every query fails the gate, don't crash.
        for i, q in enumerate(queries):
            failures.append(f"query {i + 1} ({q!r}): no parseable LLM judgment")
        return failures
    judgments = data.get("judgments") or []
    if len(judgments) != len(queries):
        # A partial judgment set means the gate could pass on unjudged queries —
        # fail loudly instead of letting misalignment slide.
        for i, q in enumerate(queries):
            failures.append(f"query {i + 1} ({q!r}): no judgment returned ({len(judgments)}/{len(queries)})")
        return failures
    for i, (q, j) in enumerate(zip(queries, judgments, strict=True)):
        if not isinstance(j, dict):
            failures.append(f"query {i + 1} ({q!r}): no judgment returned")
            continue
        if not parse_bool(j.get("global")):
            failures.append(f"query {i + 1} ({q!r}): not global")
        if not parse_bool(j.get("mechanism_first")):
            failures.append(f"query {i + 1} ({q!r}): not mechanism-first")
        if not parse_bool(j.get("in_scope")):
            failures.append(f"query {i + 1} ({q!r}): out of scope")
        if not parse_bool(j.get("distinct")):
            failures.append(f"query {i + 1} ({q!r}): duplicates another query")
    return failures


def generate_queries(
    topic: dict[str, Any], listing: dict[str, Any], llm: LLM, limiter: RateLimiter
) -> list[str] | None:
    if not QUERIES_PROMPT_PATH.exists():
        print(f"      FATAL: {QUERIES_PROMPT_PATH.relative_to(ROOT)} missing")
        return None
    tmpl = QUERIES_PROMPT_PATH.read_text(encoding="utf-8")
    subareas = ""
    for sa in listing.get("subareas") or []:
        types = sorted({s.get("type", "") for s in sa.get("sources") or [] if s.get("type")})
        subareas += f"- {sa.get('name', '?')} ({sa.get('coverage', '?')}): {', '.join(types)}\n"
    ns = SimpleNamespace(**topic)
    prompt = (
        tmpl.replace("{topic.name}", ns.name)
        .replace("{topic.description}", ns.description)
        .replace("{topic.in}", getattr(ns, "in"))
        .replace("{topic.out}", ns.out)
        .replace("{subareas}", subareas.strip())
    )
    try:
        limiter.wait()
        data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — generation is best-effort
        print(f"      generation failed: {redact(str(exc))[:160]}")
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("queries")
    if isinstance(raw, dict):
        # One query per subarea (subarea -> query): coverage is structural.
        queries = [str(q).strip() for q in raw.values() if str(q).strip()]
    else:
        queries = [str(q).strip() for q in (raw or []) if str(q).strip()]
    return queries or None


def persist_queries(slug: str, listing: dict[str, Any], queries: list[str]) -> tuple[Path, Path]:
    listing = dict(listing)
    listing["queries"] = queries
    json_path = DISCOVERY_DIR / f"{slug}.json"
    _ = json_path.write_text(json.dumps(listing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path = DISCOVERY_DIR / f"{slug}.md"
    _ = md_path.write_text(render_markdown(listing), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    generate = "--generate" in args

    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_GO_BASE_URL"):
        if not os.environ.get(var):
            print(f"FATAL: missing env var {var} — check .env (see .env.example)")
            return 1

    topics = load_topics()
    topic = next((t for t in topics if t["name"].lower() == TOPIC_NAME.lower()), None)
    if topic is None:
        print(f"unknown topic: {TOPIC_NAME!r}")
        return 1
    listing, slug = load_listing(topic["name"])
    if listing is None:
        print(f"no discovery list for {topic['name']!r}")
        return 1

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

    if generate:
        print(f"[0/3] generating queries for {topic['name']} ...")
        queries = generate_queries(topic, listing, llm, limiter)
        if queries is None:
            print("      generation failed")
            return 1
        print(f"      generated {len(queries)} queries")
    else:
        queries = [str(q) for q in (listing.get("queries") or [])]
        print(f"[1/3] eval {len(queries)} queries currently in {slug}.json")

    subareas = [sa.get("name", "?") for sa in listing.get("subareas") or []]
    # Bounds track the topic's real subarea count (one query per subarea),
    # with slack for "strong subareas get two" — never a deadlocked gate.
    min_queries, max_queries = query_bounds(subareas)
    failures = mechanical_check(queries, min_queries, max_queries)
    print(f"[2/3] mechanical gate: {'PASS' if not failures else 'FAIL'} ({len(failures)} finding(s))")
    for f in failures:
        print(f"      - {f}")

    uncovered = coverage_check(queries, subareas)
    if len(uncovered) > MAX_UNCOVERED:
        failures.append(f"{len(uncovered)} subareas uncovered (limit {MAX_UNCOVERED}): {', '.join(uncovered[:6])}")
    print(
        f"      coverage: {len(subareas) - len(uncovered)}/{len(subareas)} subareas "
        + (f"— uncovered: {', '.join(uncovered[:6])}" if uncovered else "— all covered")
    )

    llm_failures = llm_check(queries, topic, llm, limiter)
    print(f"[3/3] LLM judgment gate: {'PASS' if not llm_failures else 'FAIL'} ({len(llm_failures)} finding(s))")
    for f in llm_failures:
        print(f"      - {f}")

    passed = not failures and not llm_failures
    if generate and passed:
        json_path, md_path = persist_queries(slug, listing, queries)
        print(f"      persisted -> {json_path.relative_to(ROOT)} + {md_path.relative_to(ROOT)}")
    elif generate and not passed:
        print("      NOT persisted — gates failed")
    print(f"result: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
