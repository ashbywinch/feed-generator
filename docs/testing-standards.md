# Testing Standards — feed-generator (SignalFlow)

## Running tests

- ALWAYS use make targets: `make test` (lint + typecheck + suite),
  `make coverage`. Never construct ad-hoc test commands.
- Tests marked `e2e` (live API calls) are excluded by default
  (`addopts = -m "not e2e"`); run them deliberately, never in CI.

## Conventions

- **Mirror module paths.** `signalflow/opml.py` → `tests/test_opml.py`.
  One test module per engine module.
- **Deterministic.** No wall-clock time, no network, no order dependence;
  seeded randoms only. Golden fixtures (e.g. test OPML) are committed under
  `tests/fixtures/`.
- **Assert behavior, not implementation.** Test observable contracts
  (acceptance criteria), not internal call sequences. Use DI fakes over
  `unittest.mock.patch`.
- **Real errors, real boundaries.** Test transitions, thresholds, precedence,
  and failures — not plumbing or incidental defaults.

## PRD acceptance criteria are the test contracts

- FR-1: N subscribed feeds → `known_domains` contains exactly N domains.
- FR-4: three articles about one event → exactly one approval (the milestone
  one).
- FR-6: re-running a day emits no duplicates; a 13-month-old event is evicted.
- FR-7: digest parses with `feedparser`; entries have both bullets and a
  working outbound URL.
- FR-8: two runs with unchanged inputs produce identical digests.

A bug fix ships with a failing test that reproduces it first.
