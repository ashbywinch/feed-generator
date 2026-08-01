# SignalFlow Phase 2 — Kids Learning-Content Engine (PRD)

**Status:** Draft v0.1 · **Audience:** product owner + engineers · **Phase:** 2 — shares the Phase 1 engine core (`docs/prd.md`); topic set explicitly deferred to product owner

## Purpose

The same outside-discovery engine as Phase 1, retargeted at a hyperactive 5-year-old: continuously find highly compelling learning content (science, maths, and a broader topic set to be defined) — content an average non-nerdy kid actively wants to watch more *because it's so cool*.

North-star: the kid keeps asking for more.

## What this is (and isn't)

- **Is:** Huge If True for kids — awe-driven, concrete, visual explainers — with a broader topic set the product owner defines.
- **Isn't:** a curriculum, a parental-control filter, or a passive "safe videos" feed. The bar is **compelling**, not merely safe/educational. Boring-but-educational fails.

## Reuses from Phase 1

- Engine core: discovery tiers, 4-layer de-duplication, semantic memory, digest/publish infra (see `docs/prd.md` FR-3…FR-8).
- LLM access: Opencode router, one key — DeepSeek v4 Flash for reasoning, cheapest router embedding model for de-dup.
- Principles: fail-fast, local-first, config-driven thresholds, content-verified recommendations.

## Differences from Phase 1

| Aspect | Phase 1 | Phase 2 |
|---|---|---|
| Audience | expert reader (parent) | 5-year-old (hyperactive); parent curates |
| Evaluation bar | novel empirical event / structural thesis | "actively wants to watch more because it's so cool" |
| Reject criteria | hype, horse-race, shallow | passive, abstract, dry, scary, slow-paced, long attention demands |
| Topic set | derived from parent's OPML | **defined by product owner — TBD (science, maths, + more)** |
| Exclusion set | parent's Feedly subscriptions | family's already-subscribed channels |
| Output | RSS digest → Feedly | short "tonight's picks" — video-first (format TBD, see OQ-2) |
| Volume | daily digest | daily but tiny: 3–5 picks, never a firehose |

## Functional Requirements

### FR2-1 Topic set & strategies — MUST
- Product owner defines the topic list and, per topic, the discovery strategy (same craft requirement as Phase 1 FR-2: individually tailored queries, domains, channels — no generic one-size-fits-all searches).
- Topics are product-defined, not derived from a subscription list.

### FR2-2 Compellingness evaluation — MUST
- LLM scores each candidate against kid-engagement criteria: visual payoff, concrete demonstration/experiment, humor/energy, short payoff time, "wow" factor.
- **Must reject:** dry lectures, abstract exposition, scary content, anything demanding sustained attention beyond a 5-year-old's range.
- Verdicts and scores recorded per candidate for tuning (FR2-4).

### FR2-3 Output — MUST (format per OQ-2)
- 3–5 picks per run, each with a one-line "why your kid will love this".
- Parent reviews before the kid watches — curated, never direct-to-child.

### FR2-4 Feedback loop — SHOULD
- Parent marks picks "hit" / "miss" → per-topic and per-channel scores tuned on the next run.

### FR2-5 Same de-dup & memory — MUST
- Never re-show a picked video; embeddings of picks stored in the shared memory layer; same 4-layer dedup.

## Open Questions

- **OQ-1:** Which topics beyond science & maths? (product owner to define — explicitly deferred)
- **OQ-2:** Output medium: watchlist page, YouTube playlist export (plays on the TV), or both? Recommendation: both — page for the parent, playlist for the kid.
- **OQ-3:** YouTube search/API access: which key/service discovers and validates videos?
- **OQ-4:** Parent-only curation assumed; is a later "kid-safe auto-play" mode wanted?

## Acceptance Criteria (phase 2 gate — refine after topic set lands)

1. 10 seeded candidates per topic classify as pick / reject with no regressions against the parent's judgment.
2. One week of daily runs yields ≥ 1 "hit" per parent feedback per topic.
3. No video repeats within 12 months (memory layer).
4. Picks list renders in under one screen; one-line reason per pick.
