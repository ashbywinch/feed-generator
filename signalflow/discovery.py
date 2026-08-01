"""FR-3 discovery tiers: Exa search crawling + direct program registries.

Tier A (registries): UKRI Gateway to Research + ClinicalTrials.gov — direct
milestone tracking per topic strategy (registry relevance comes from the
topic's stored strategy, never a global list).
Tier B (Exa): per-topic query formulations from the strategy table.
Every candidate carries {title, summary, url, source_tier, topic}.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import Config
from .models import Candidate

log = logging.getLogger(__name__)

EXA_URL = "https://api.exa.ai/search"
UKRI_URL = "https://gtr.ukri.org/api/projects"
CLINICAL_URL = "https://clinicaltrials.gov/api/v2/studies"

REGISTRY_NAMES = {"ukri gtr": "UKRI GtR", "clinicaltrials.gov": "ClinicalTrials.gov"}


class Discovery:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def discover(self, topics: list[dict[str, Any]]) -> list[Candidate]:
        """Candidates from every topic's strategy (queries + relevant registries)."""
        out: list[Candidate] = []
        for topic in topics:
            strategy = topic.get("strategy") or {}
            queries = [q for q in strategy.get("queries", []) if isinstance(q, str)][:3]
            out.extend(self._search(topic["name"], queries))
            for reg in strategy.get("registries", []):
                if str(reg).lower() == "ukri gtr" and queries:
                    out.extend(self._ukri(topic["name"], queries[0]))
                if str(reg).lower() == "clinicaltrials.gov" and queries:
                    out.extend(self._clinical(topic["name"], queries[0]))
        # dedupe by url, cap per topic
        seen: set[str] = set()
        capped: list[Candidate] = []
        per_topic: dict[str, int] = {}
        for c in out:
            if c.url in seen:
                continue
            seen.add(c.url)
            if per_topic.get(c.topic, 0) >= self._cfg.max_candidates_per_topic:
                continue
            per_topic[c.topic] = per_topic.get(c.topic, 0) + 1
            capped.append(c)
        return capped

    # -- Tier B: Exa ---------------------------------------------------------

    def _search(self, topic: str, queries: list[str]) -> list[Candidate]:
        if not self._cfg.exa_key or not queries:
            return []
        out: list[Candidate] = []
        for q in queries:
            try:
                resp = requests.post(
                    EXA_URL,
                    headers={"x-api-key": self._cfg.exa_key},
                    json={"query": q, "numResults": 10, "type": "neural", "contents": {"text": {"maxCharacters": 500}}},
                    timeout=30,
                )
                resp.raise_for_status()
                for r in resp.json().get("results", []):
                    out.append(
                        Candidate(
                            title=(r.get("title") or "")[:200],
                            summary=(r.get("text") or "")[:800],
                            url=r.get("url", ""),
                            source_tier="search",
                            topic=topic,
                        )
                    )
            except requests.RequestException as exc:
                log.warning("exa search failed for %r: %s", q, str(exc)[:120])
        return out

    # -- Tier A: registries --------------------------------------------------

    def _ukri(self, topic: str, term: str) -> list[Candidate]:
        """UKRI Gateway to Research: grant milestones (proposal endpoint)."""
        out: list[Candidate] = []
        try:
            resp = requests.get(
                UKRI_URL,
                headers={"Accept": "application/json"},
                params={"term": term, "fetchSize": 5},
                timeout=30,
            )
            resp.raise_for_status()
            for proj in resp.json().get("projectOverview", {}).get("project", [])[:5]:
                ref = proj.get("grantReference", "")
                out.append(
                    Candidate(
                        title=f"UKRI Grant Update: {proj.get('title', '')[:180]}",
                        summary=(
                            f"Grant Status: {proj.get('status')}. Category: {proj.get('grantCategory')}. "
                            f"Total Value: £{proj.get('fund', {}).get('valuePounds', 0):,}."
                        ),
                        url=f"https://gtr.ukri.org/projects?ref={ref}",
                        source_tier="registry",
                        topic=topic,
                    )
                )
        except requests.RequestException as exc:
            log.warning("ukri fetch failed for %r: %s", term, str(exc)[:120])
        return out

    def _clinical(self, topic: str, term: str) -> list[Candidate]:
        """ClinicalTrials.gov v2 API: status shifts + result uploads."""
        out: list[Candidate] = []
        try:
            resp = requests.get(
                CLINICAL_URL,
                params={"query.term": term, "pageSize": 10, "fields": "protocolSection", "format": "json"},
                timeout=30,
            )
            resp.raise_for_status()
            for study in resp.json().get("studies", [])[:10]:
                ps = study.get("protocolSection", {})
                ident = ps.get("identificationModule", {})
                nct = ident.get("nctId", "")
                status = ps.get("statusModule", {}).get("overallStatus", "")
                conds = ", ".join(ps.get("conditionsModule", {}).get("conditions", [])[:3])
                out.append(
                    Candidate(
                        title=f"Clinical Trial: {ident.get('briefTitle', '')[:180]}",
                        summary=f"Status: {status}. Conditions: {conds}.",
                        url=f"https://clinicaltrials.gov/study/{nct}",
                        source_tier="registry",
                        topic=topic,
                    )
                )
        except requests.RequestException as exc:
            log.warning("clinicaltrials fetch failed for %r: %s", term, str(exc)[:120])
        return out
