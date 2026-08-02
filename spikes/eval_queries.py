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

LLM_BASE = os.environ["OPENCODE_GO_BASE_URL"]
LLM_KEY = os.environ["OPENCODE_GO_API_KEY"]
LLM_MODEL = os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash")

MIN_QUERIES = 5
MAX_QUERIES = 13  # one per subarea (the topic has 13)
MAX_UNCOVERED = 3  # subareas a query set may leave out and still pass
EVAL_INTERVAL = 1.0
LLM_MAX_TOKENS = 8192

# Deterministic coverage: subarea -> distinctive tokens. A subarea is covered
# when ANY query contains one of its tokens (case-insensitive). Token lists are
# chosen to avoid cross-matching (e.g. "storage" alone would match everything).
SUBAREA_TOKENS: dict[str, tuple[str, ...]] = {
    "Grid-scale batteries & storage": ("battery",),
    "Grid connection queues & network charging": ("connection queue", "network charging"),
    "Ancillary services & frequency markets": ("ancillary", "frequency market"),
    "Interconnectors & market coupling": ("interconnector", "market coupling"),
    "CfD auctions & capacity market (policy)": ("cfd", "capacity market", "strike price"),
    "Demand-side flexibility & electrification demand growth": ("demand-side", "demand side", "electrification"),
    "Nuclear new-build economics (RAB, CfDs, SMRs)": ("nuclear", "smr"),
    "Storage beyond lithium-ion (CAES, thermal, gravity, flow)": (
        "long-duration", "lithium-ion", "caes", "thermal storage"
    ),
    "Offshore wind": ("offshore wind", "floating wind"),
    "Carbon markets / ETS & climate-economics data": ("carbon market", "ets", "carbon price"),
    "Regulation, market design & price controls": ("market design", "price control", "regulation"),
    "Distribution vs transmission & grid data analytics": ("distribution", "grid data", "transmission"),
    "Hydrogen for power": ("hydrogen",),
}

# Hard geography anchors: a query naming any of these can only find that
# jurisdiction's news. "European" is softer (multi-country) but still local;
# keep the strict list to single-jurisdiction terms.
GEO_ANCHORS = re.compile(
    r"\b(GB|UK|U\.K\.|Britain|British|England|Wales|Scotland|N\.Ireland|"
    + r"Ofgem|NESO|Elexon|National Grid|NEMO|DESNZ|ERCOT|FERC|CAISO)\b",
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
            continue
        if data.get("topic") == topic_name:
            return data, path.stem
    return None, ""


def mechanical_check(queries: list[str]) -> list[str]:
    failures: list[str] = []
    if not (MIN_QUERIES <= len(queries) <= MAX_QUERIES):
        failures.append(f"{len(queries)} queries (need {MIN_QUERIES}-{MAX_QUERIES})")
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

    Returns uncovered subarea names.
    """
    lowered = [q.lower() for q in queries]
    uncovered = []
    for sa in subareas:
        tokens = SUBAREA_TOKENS.get(sa)
        if tokens is None:
            continue  # unknown subarea: not this eval's job
        if not any(any(t in q for t in tokens) for q in lowered):
            uncovered.append(sa)
    return uncovered


def llm_check(
    queries: list[str], topic: dict[str, Any], llm: LLM, limiter: RateLimiter
) -> list[str]:
    """LLM judgment per query: global, mechanism-first, in-scope, distinct.

    Coverage is judged deterministically (coverage_check), not by the LLM —
    the model's coverage verdict was unstable across runs.
    """
    q_rows = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(queries))
    prompt = f"""You are auditing the search-query set for a personal discovery engine.

Topic: {topic['name']}
IN scope: {topic['in']}
OUT of scope: {topic['out']}

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
    limiter.wait()
    data = llm.chat_json(prompt, max_tokens=LLM_MAX_TOKENS)
    failures: list[str] = []
    judgments = data.get("judgments") or []
    for i, (q, j) in enumerate(zip(queries, judgments, strict=False)):
        if not isinstance(j, dict):
            failures.append(f"query {i + 1} ({q!r}): no judgment returned")
            continue
        if not j.get("global"):
            failures.append(f"query {i + 1} ({q!r}): not global")
        if not j.get("mechanism_first"):
            failures.append(f"query {i + 1} ({q!r}): not mechanism-first")
        if not j.get("in_scope"):
            failures.append(f"query {i + 1} ({q!r}): out of scope")
        if not j.get("distinct"):
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
    queries = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
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

    failures = mechanical_check(queries)
    print(f"[2/3] mechanical gate: {'PASS' if not failures else 'FAIL'} ({len(failures)} finding(s))")
    for f in failures:
        print(f"      - {f}")

    subareas = [sa.get("name", "?") for sa in listing.get("subareas") or []]
    uncovered = coverage_check(queries, subareas)
    if len(uncovered) > MAX_UNCOVERED:
        failures.append(f"{len(uncovered)} subareas uncovered (limit {MAX_UNCOVERED}): {', '.join(uncovered[:6])}")
    print(f"      coverage: {len(subareas) - len(uncovered)}/{len(subareas)} subareas "
          + (f"— uncovered: {', '.join(uncovered[:6])}" if uncovered else "— all covered"))

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
