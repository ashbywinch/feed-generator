# Coding Standards — feed-generator (SignalFlow)

House conventions (see `skill://new-repo-scaffold`); deviations must be
justified in the PR.

## Design principles

- **Fail fast.** Missing OPML or API keys aborts the run with a clear error
  (FR-1, NFR Reliability). Never silently degrade to a partial blacklist.
- **Never swallow errors.** Every `except` logs; bare `except: pass` is
  forbidden. Log failures with enough context to diagnose (`%r` on inputs).
- **Semantic types over primitives.** `Candidate`, `Config`, `LLMError` —
  domain shapes are dataclasses/models (`signalflow/models.py`), not ad-hoc
  dicts or tuples.
- **Class-per-module.** One concern per module (`opml`, `topics`, `discovery`,
  `dedup`, `embed`, `llm`, `memory`, `digest`, `ratelimit`, `engine`); one
  class per module where state is involved.
- **No backward-compat shims.** Move every caller when an interface changes;
  delete dead code and aliases. No deprecated paths.
- **DI over patching.** Inject `Config`/clients via constructors; tests use
  fakes, not `unittest.mock.patch` on module globals.
- **Config, never hardcoded.** Thresholds, providers, budgets, cron, publish
  target come from `Config` (env-driven, PRD Config table). Defaults live in
  `config.py`, not scattered through the pipeline.

## Pipeline invariants

- De-dup order is fixed: L1 domain blacklist → L2 hash → L3 vector → L4 delta
  evaluator (cheapest first). Never call the LLM before L2.
- Embedding model is never mixed in the store (`EMBEDDING_MODEL`); switching
  requires re-embedding.
- A failed run never publishes a partial or empty digest over a good one
  (atomic swap).
- Per-topic discovery queries come only from stored strategies — never a
  global fixed query list.

## Secrets

- API keys live only in the environment / `.env`. Never print, log, or commit
  key values; redact in exception messages (`LLM._redact`).

## Style (ruff)

`select = E,F,I,UP,B,SIM,N`, `line-length = 120`, double quotes, `fixable =
ALL`. Python >= 3.12, type-checked with basedpyright. Run via `make lint` /
`make format` — never ad-hoc tool commands.
