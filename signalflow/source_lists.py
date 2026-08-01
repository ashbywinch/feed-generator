"""FR-2.2 repeatable per-topic discovery source-list generator.

The loop: generator agent (tool-use loop, `web_search` backed by Exa) ->
mechanical gates (schema, DNS, subscription collision) -> reviewer agent ->
iterate until zero blocker/major findings. Prompts are the versioned files in
`prompts/`.

Mechanical gates run before the reviewer so LLM budget is spent on judgment:
DNS-typo bugs (e.g. `redefiningenergy.com`) never reach the reviewer again.

Run one topic: `make topic-sources TOPIC="Grid & Net Zero economics"`
"""

from __future__ import annotations

import json
import logging
import re
import socket
import sys
from collections.abc import Callable
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Config
from .env import PROJECT_ROOT, load_env
from .llm import LLM, LLMError
from .opml import parse_opml
from .topics import load_topics

log = logging.getLogger(__name__)

PROMPTS_DIR = PROJECT_ROOT / "prompts"
DISCOVERY_DIR = PROJECT_ROOT / "docs" / "discovery"
EXA_URL = "https://api.exa.ai/search"
MAX_ITER = 4
MAX_TOOL_ROUNDS = 30
MAX_SEARCHES = 10  # free Exa tier (~$10/mo credits); existence is DNS-checked mechanically

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web; returns titles, URLs and short snippets. Use it to "
            "verify a domain exists and hosts the claimed content."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


class AgentError(RuntimeError):
    pass


# -- agent: tool-use loop ---------------------------------------------------


def _exa_search(cfg: Config, query: str, num: int = 3) -> list[dict[str, str]]:
    """web_search implementation: Exa neural search (PRD External Services).

    Cost-aware: NO `contents` text extraction (billed per page at $1/1k);
    title+URL suffice for domain verification. numResults <= 10 keeps the
    base $7/1k rate (extra results bill separately).
    """
    if not cfg.exa_key:
        raise AgentError("EXA_API_KEY missing — web_search tool needs it")
    resp = requests.post(
        EXA_URL,
        headers={"x-api-key": cfg.exa_key},
        json={"query": query, "numResults": num, "type": "neural"},
        timeout=30,
    )
    resp.raise_for_status()
    out: list[dict[str, str]] = []
    for r in resp.json().get("results", []):
        out.append({"title": (r.get("title") or "")[:160], "url": r.get("url", "")})
    return out


def _agent_chat(
    llm: LLM,
    cfg: Config,
    prompt: str,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
    max_searches: int = MAX_SEARCHES,
) -> tuple[str, int]:
    """Tool-use loop: the model may call web_search; returns its final text.

    Searches are hard-capped at `max_searches`; once the budget is spent the
    model gets budget-exhausted tool results and must finalize. Without the
    cap the model keeps verifying and never terminates.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    searches = 0
    for _ in range(max_rounds):
        msg = llm.chat_tools(messages, [WEB_SEARCH_TOOL], max_tokens=12000)
        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    query = str(args.get("query", "")) if isinstance(args, dict) else ""
                except json.JSONDecodeError:
                    query = ""
                if name == "web_search" and query and searches < max_searches:
                    searches += 1
                    log.info("agent web_search (%d/%d): %r", searches, max_searches, query)
                    try:
                        result = _exa_search(cfg, query)
                    except requests.RequestException as exc:
                        result = [{"error": f"search failed: {str(exc)[:200]}"}]
                    except AgentError as exc:
                        result = [{"error": str(exc)}]
                else:
                    result = [{"error": "search budget exhausted or invalid call — finalize your answer now"}]
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result)[:8000],
                    }
                )
            continue
        content = (msg.get("content") or "").strip()
        if content:
            return content, searches
        raise AgentError("model returned an empty final message")
    raise AgentError("tool loop did not terminate")


def _parse_json(content: str) -> dict[str, Any]:
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise AgentError(f"non-JSON agent output: {content[:200]}") from None
        out = json.loads(m.group(0))
    if not isinstance(out, dict):
        raise AgentError("agent output is not a JSON object")
    return out


# -- mechanical gates (deterministic, before the reviewer) ------------------


def _finding(severity: str, area: str, issue: str, suggestion: str = "") -> dict[str, str]:
    return {"severity": severity, "area": area, "issue": issue, "suggestion": suggestion}


def normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    d = d.split(":")[0]  # strip port (redirects like host:443)
    return d


def gate_schema(listing: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not listing.get("topic"):
        out.append(_finding("blocker", "schema", "missing topic"))
    subareas = listing.get("subareas")
    if not isinstance(subareas, list) or not subareas:
        out.append(_finding("blocker", "schema", "no subareas"))
    else:
        for sa in subareas:
            if not isinstance(sa, dict) or not sa.get("name"):
                out.append(_finding("blocker", "schema", "subarea missing name"))
                continue
            for s in sa.get("sources") or []:
                if not isinstance(s, dict):
                    out.append(_finding("blocker", "schema", f"{sa['name']}: non-object source"))
                    continue
                if not s.get("domain"):
                    out.append(_finding("blocker", "schema", f"{sa['name']}: {s.get('name')} missing domain"))
                if not s.get("type"):
                    out.append(_finding("major", "schema", f"{sa['name']}: {s.get('name')} missing type"))
    if not isinstance(listing.get("queries"), list) or not listing.get("queries"):
        out.append(_finding("major", "schema", "no queries"))
    return out


def _resolve(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def gate_dns(listing: dict[str, Any], resolver: Callable[[str], bool] | None = None) -> list[dict[str, str]]:
    resolve = resolver or _resolve
    out: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for sa in listing.get("subareas", []):
        for s in sa.get("sources", []):
            domain = normalize_domain(s.get("domain", ""))
            if not domain:
                continue
            if domain in seen:
                out.append(
                    _finding(
                        "minor",
                        "duplicates",
                        f"domain {domain} also under '{seen[domain]}'",
                        "reuse across subareas is fine; exact duplicates are noise",
                    )
                )
                continue
            seen[domain] = sa.get("name", "?")
            if not resolve(domain):
                out.append(
                    _finding(
                        "blocker",
                        "verifiability",
                        f"domain '{s.get('domain')}' does not resolve (DNS)",
                        "fix the spelling or remove the source",
                    )
                )
    return out


FEED_PATHS = ("/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml")
STALE_DAYS = 90
NON_FEED_TYPES = {"data/registry", "data/analytics", "data", "regulator", "system operator"}
# The engine crawls with a browser-like UA (default python-requests UA is
# 403/406-blocked by most publishers — verified on renews.biz).
CRAWL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36 SignalFlow/0.1"
    )
}


def _http_get(url: str) -> Any:
    return requests.get(url, timeout=15, headers=CRAWL_HEADERS)


def _is_feed(resp: Any) -> bool:
    ct = str(resp.headers.get("content-type", "")).lower()
    body = (resp.text or "")[:4000]
    if "rss" in ct or "atom" in ct:
        return True
    return ("<rss" in body or "<feed" in body or "<rdf" in body) and "xml" in ct


def _feed_date(resp: Any) -> date | None:
    body = (resp.text or "")[:6000]
    for tag in ("lastBuildDate", "pubDate"):
        m = re.search(rf"<{tag}>([^<]+)</{tag}>", body, re.I)
        if m:
            try:
                return parsedate_to_datetime(m.group(1)).date()
            except (TypeError, ValueError):
                continue
    m = re.search(r"<updated>([^<]+)</updated>", body)
    if m:
        try:
            return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _feed_link_in_html(resp: Any) -> str | None:
    m = re.search(
        r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
        resp.text or "",
        re.I,
    )
    return m.group(1) if m else None


def _probe_homepage(domain: str, fetcher: Callable[[str], Any]) -> dict[str, str] | None:
    """Data/registry sources are API endpoints, not feeds: require the site reachable."""
    url = f"https://{domain}/"
    try:
        resp = fetcher(url)
    except requests.RequestException:
        return _finding(
            "blocker", "crawlability", f"site {domain} unreachable", "remove the source or check the domain"
        )
    if resp.status_code >= 400:
        return _finding(
            "blocker",
            "crawlability",
            f"site {domain} returns HTTP {resp.status_code}",
            "remove the source or check the domain",
        )
    final_host = normalize_domain(urlparse(resp.url or url).netloc)
    if final_host and final_host != domain:
        return _finding(
            "major",
            "crawlability",
            f"'{domain}' redirects to {final_host}",
            f"replace the domain with {final_host}",
        )
    return None


def _probe_source(
    domain: str, crawl_root: str, fetcher: Callable[[str], Any], _depth: int = 0
) -> dict[str, str] | None:
    """Probe a source's feed; return a finding or None if crawlable.

    A redirect to another domain is not a knockback: if the redirect target
    serves a working feed, the finding tells the generator to swap in the
    actual domain. Only a dead redirect target is a blocker.
    """
    if _depth > 2:
        return _finding("blocker", "crawlability", f"redirect chain too deep for {domain}", "remove the source")
    base = f"https://{domain}"
    candidates = [crawl_root] if crawl_root and crawl_root.startswith("http") else []
    candidates += [f"{base}{p}" for p in FEED_PATHS]
    for url in candidates:
        try:
            resp = fetcher(url)
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue
        final_host = normalize_domain(urlparse(resp.url or url).netloc)
        if final_host and final_host != domain:
            # domain repurposed/redirected: judge the redirect target, not the claim
            if _is_feed(resp):
                return _finding(
                    "major",
                    "crawlability",
                    f"'{domain}' redirects to {final_host}, which serves a working feed",
                    f"replace the domain with {final_host}",
                )
            link = _feed_link_in_html(resp)
            if link:
                return _finding(
                    "major",
                    "crawlability",
                    f"'{domain}' redirects to {final_host}; its homepage advertises feed {link}",
                    f"set the domain to {final_host} and crawl_root to {link}",
                )
            target = _probe_source(final_host, "", fetcher, _depth + 1)
            if target is None:
                return _finding(
                    "major",
                    "crawlability",
                    f"'{domain}' redirects to {final_host}, which has a working feed",
                    f"replace the domain with {final_host}",
                )
            return _finding(
                "blocker",
                "crawlability",
                f"'{domain}' redirects to {final_host}, which has no crawlable feed",
                "remove the source or find the real domain",
            )
        if _is_feed(resp):
            feed_date = _feed_date(resp)
            if feed_date and (date.today() - feed_date).days > STALE_DAYS:
                return _finding(
                    "major",
                    "crawlability",
                    f"feed at {url} stale since {feed_date} (> {STALE_DAYS} days)",
                    "replace with a fresher source or remove",
                )
            if crawl_root and url.rstrip("/") != crawl_root.rstrip("/"):
                return _finding(
                    "minor",
                    "crawlability",
                    f"crawl_root {crawl_root} is wrong — working feed is {url}",
                    f"set crawl_root to {url}",
                )
            return None
        link = _feed_link_in_html(resp)
        if link:
            return _finding(
                "major",
                "crawlability",
                f"no standard feed path for {domain}; homepage advertises {link}",
                f"set crawl_root to {link}",
            )
        return _finding(
            "major",
            "crawlability",
            f"no feed found at {domain} (homepage returned HTML without a feed link)",
            "set crawl_root to the real feed URL or remove",
        )
    # all feed-path candidates failed — the homepage may advertise the real feed
    try:
        resp = fetcher(f"https://{domain}/")
    except requests.RequestException:
        resp = None
    if resp is not None and resp.status_code < 400:
        if _is_feed(resp):
            return None
        link = _feed_link_in_html(resp)
        if link:
            return _finding(
                "major",
                "crawlability",
                f"no standard feed path for {domain}; homepage advertises {link}",
                f"set crawl_root to {link}",
            )
    return _finding(
        "blocker",
        "crawlability",
        f"no reachable feed for {domain} — every probe failed (bot-blocked or missing)",
        "remove the source or provide a working crawl_root",
    )


def gate_crawlability(listing: dict[str, Any], fetcher: Callable[[str], Any] | None = None) -> list[dict[str, str]]:
    """Probe every source's feed with the same HTTP client the engine crawls with.

    Catches what DNS cannot: domains repurposed/redirected, bot-blocks (403/406),
    missing feeds, wrong crawl_roots, stale feeds.
    """
    fetch = fetcher or _http_get
    out: list[dict[str, str]] = []
    for sa in listing.get("subareas", []):
        for s in sa.get("sources", []):
            domain = normalize_domain(s.get("domain", ""))
            if not domain:
                continue
            if str(s.get("type", "")).lower() in NON_FEED_TYPES:
                finding = _probe_homepage(domain, fetch)
            else:
                finding = _probe_source(domain, str(s.get("crawl_root", "")), fetch)
            if finding:
                out.append(finding)
    return out


def gate_collision(listing: dict[str, Any], known_domains: set[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for sa in listing.get("subareas", []):
        for s in sa.get("sources", []):
            domain = normalize_domain(s.get("domain", ""))
            if domain and domain in known_domains:
                out.append(
                    _finding(
                        "blocker",
                        "outside-subscription",
                        f"'{s.get('name')}' ({domain}) is already subscribed — L1 discards it",
                        "replace with an outside source",
                    )
                )
    return out


def exclude_domains(feeds: list[dict[str, Any]], topic: dict[str, Any]) -> list[str]:
    """Resolve the topic's subscribed source names to their OPML domains."""
    names = [s.lower() for s in topic.get("sources", [])]
    out: set[str] = set()
    for f in feeds:
        host = urlparse(f["url"]).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if any(n in f["title"].lower() for n in names):
            out.add(host)
    return sorted(out)


# -- the loop ---------------------------------------------------------------


def _prompt(kind: str) -> str:
    p = PROMPTS_DIR / f"{kind}_topic_sources.md"
    if not p.exists():
        raise FileNotFoundError(f"missing prompt: {p}")
    return p.read_text(encoding="utf-8")


def _topic_input(topic: dict[str, Any], excludes: list[str]) -> dict[str, Any]:
    return {k: topic.get(k) for k in ("name", "description", "in", "out", "sources")} | {"exclude_domains": excludes}


def generate_topic_sources(
    topic: dict[str, Any],
    cfg: Config,
    opml_path: Path,
    *,
    llm: LLM | None = None,
    max_iter: int = MAX_ITER,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    """Run generate -> gates -> review until approval.

    Returns (listing, verdict, iterations, searches_used)."""
    known_domains, feeds = parse_opml(opml_path)
    excludes = exclude_domains(feeds, topic)
    llm = llm or LLM(cfg)
    gen_prompt = _prompt("generate")
    rev_prompt = _prompt("review")
    topic_in = _topic_input(topic, excludes)

    findings: list[dict[str, Any]] = []
    listing: dict[str, Any] = {}
    searches_used = 0
    for iteration in range(1, max_iter + 1):
        log.info("topic sources iteration %d: generate (%d prior findings)", iteration, len(findings))
        feedback = (
            "\n\n## REVIEWER/GATE FEEDBACK FROM PREVIOUS ROUND — fix every blocker/major finding\n"
            + json.dumps(findings, indent=2)
            if findings
            else ""
        )
        content, n = _agent_chat(
            llm, cfg, gen_prompt + "\n\n## TOPIC\n" + json.dumps(topic_in, indent=2) + feedback, max_searches=10
        )
        searches_used += n
        listing = _parse_json(content)

        gate_findings = (
            gate_schema(listing)
            + gate_dns(listing)
            + gate_collision(listing, known_domains)
            + gate_crawlability(listing)
        )
        if gate_findings:
            findings = gate_findings
            log.warning("iteration %d: %d mechanical gate findings — reviewer skipped", iteration, len(findings))
            continue

        log.info("iteration %d: review", iteration)
        content, n = _agent_chat(
            llm,
            cfg,
            rev_prompt
            + "\n\n## TOPIC\n"
            + json.dumps(topic_in, indent=2)
            + "\n\n## GENERATED LIST\n"
            + json.dumps(listing, indent=2),
            max_searches=5,
        )
        searches_used += n
        verdict = _parse_json(content)
        findings = verdict.get("findings", [])
        if verdict.get("approved") is True:
            log.info("APPROVED at iteration %d", iteration)
            return listing, verdict, iteration, searches_used

    raise AgentError(f"no approval in {max_iter} iterations — last findings: {json.dumps(findings)[:400]}")


# -- persistence ------------------------------------------------------------


def slug_for(topic_name: str, topics: list[dict[str, Any]]) -> str:
    idx = next((i + 1 for i, t in enumerate(topics) if t["name"] == topic_name), 0)
    kebab = re.sub(r"[^a-z0-9]+", "-", topic_name.lower()).strip("-")
    return f"{idx:02d}-{kebab}"


def render_markdown(record: dict[str, Any]) -> str:
    lines = [f"# {record['topic']} — Discovery Source List", ""]
    lines.append(
        f"Status: {record['status']} by reviewer loop (iteration {record['iterations']}). "
        f"{len(record['subareas'])} subareas, "
        f"{sum(len(sa.get('sources', [])) for sa in record['subareas'])} sources, "
        f"{len(record.get('queries', []))} queries. Generated {record['approved_at']}."
    )
    lines.append("")
    lines.append("## Subareas")
    for i, sa in enumerate(record["subareas"], 1):
        lines.append(f"### {i}. {sa['name']}")
        if sa.get("coverage"):
            lines.extend(["", sa["coverage"]])
        lines.append("")
        for s in sa.get("sources", []):
            conf = s.get("confidence", "")
            cr = f" · crawl: {s['crawl_root']}" if s.get("crawl_root") else ""
            lines.append(f"- **{s['name']}** (`{s['domain']}`) — {s['type']} — {conf}{cr}")
            if s.get("why"):
                lines.append(f"  {s['why']}")
        lines.append("")
    lines.append("## Registries")
    for r in record.get("registries", []):
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## Queries")
    for i, q in enumerate(record.get("queries", []), 1):
        lines.append(f"{i}. {q}")
    lines.append("")
    lines.append("## News vs analysis")
    lines.append(record.get("news_vs_analysis", ""))
    lines.append("")
    lines.append("## Notes")
    lines.append(record.get("notes", ""))
    lines.append("")
    lines.append("## Review record")
    for f in record.get("review_record", {}).get("findings", []):
        lines.append(f"- [{f['severity']}] {f['area']}: {f['issue']}")
    lines.append("")
    return "\n".join(lines)


def persist(
    topic_name: str,
    listing: dict[str, Any],
    verdict: dict[str, Any],
    iterations: int,
    out_dir: Path = DISCOVERY_DIR,
) -> tuple[Path, Path]:
    topics = load_topics()
    slug = slug_for(topic_name, topics)
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "topic": listing.get("topic", topic_name),
        "status": "approved" if verdict.get("approved") is True else "needs-human",
        "iterations": iterations,
        "approved_at": date.today().isoformat(),
        "subareas": listing.get("subareas", []),
        "registries": listing.get("registries", []),
        "queries": listing.get("queries", []),
        "news_vs_analysis": listing.get("news_vs_analysis", ""),
        "notes": listing.get("notes", ""),
        "review_record": {"findings": verdict.get("findings", [])},
    }
    json_path = out_dir / f"{slug}.json"
    json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path = out_dir / f"{slug}.md"
    md_path.write_text(render_markdown(record), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m signalflow sources <topic-name>")
        return 2
    topic_name = " ".join(args)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_env()
    cfg = Config.from_env()
    topics = load_topics()
    topic = next((t for t in topics if t["name"].lower() == topic_name.lower()), None)
    if topic is None:
        print(f"unknown topic: {topic_name!r}; available:\n  " + "\n  ".join(t["name"] for t in topics))
        return 2
    try:
        listing, verdict, iterations, searches = generate_topic_sources(topic, cfg, PROJECT_ROOT / "feedly.opml")
    except (AgentError, LLMError) as exc:
        print(f"FAILED: {exc}")
        return 1
    json_path, md_path = persist(topic_name, listing, verdict, iterations)
    print(f"approved={verdict.get('approved')} iterations={iterations} exa_searches={searches}")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0
