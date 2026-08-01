# feed-generator (SignalFlow)

Personal information fiduciary & outside-discovery engine. Ingests the user's
Feedly OPML as an exclusion set, builds a per-user topic model, and for each
topic runs a crafted discovery strategy (Exa search + program registries) to
surface novel empirical events and first-principles analysis from **outside**
the user's subscriptions — deduplicated against semantic memory and emitted as
a private RSS digest Feedly consumes.

Spec: `docs/prd.md` (v1) · `docs/prd-phase2-kids.md` (phase 2).

## Quick Start

```sh
make setup      # venv + deps + pre-commit hooks + .env
make smoke      # engine self-check (opml + memory + embeddings + chat)
make test       # lint + typecheck + test suite
make run        # daily engine run (FR-8)
```

## Docs

| Doc | What |
|---|---|
| `docs/prd.md` | v1 product requirements (engine stages, FRs, acceptance) |
| `docs/prd-phase2-kids.md` | phase 2 — kids learning-content engine |
| `docs/topics.md` | curated 13-topic set (rendered from `signalflow/topics.json`) |
| `docs/coding-standards.md` | code conventions |
| `docs/testing-standards.md` | test conventions |
| `docs/writing-documentation.md` | documentation conventions |
| `prompts/` | per-topic source-list generation + review prompts (repeatable process) |

## Secrets & personal data

API keys live in `.env` (never committed; template `.env.example`). Personal
data — `feedly.opml`, `history_memory.db`, `signalflow_digest.xml` — is
gitignored. Never print or log API keys.
