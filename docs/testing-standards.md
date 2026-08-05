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
- **If code isn't amenable to fakes/DI, refactor it before testing.** A test
  that needs `monkeypatch`/`patch` to reach a hard-constructed collaborator
  (`LLM(CFG)` inside `run_topic`, a hard-coded file path) is a smell — the
  seam is missing, not the test. Refactor the code to accept the collaborator
  as a defaulted parameter (factory or path), then write the test with a fake.
  See `docs/coding-standards.md` §Dependency injection for the pattern and
  example.
- **Real errors, real boundaries.** Test transitions, thresholds, precedence,
  and failures — not plumbing or incidental defaults.
- **Exercise the real code path.** A test must call the production function it
  claims to pin — never re-implement the logic inline. A test that
  re-implements the code (e.g. copies its sort/compare/filter) passes even
  when the code is broken and proves nothing. If the logic is embedded in a
  long function, extract a small pure helper first so the test can call it.

## TDD is mandatory (RED → GREEN)

Every bug fix, feature, or behavioral change ships with a failing test that
reproduces the bug FIRST. The order is non-negotiable:

1. Write the test that asserts the desired behavior.
2. Run it — it MUST FAIL against the current code (the RED run). A test that
   passes before the fix is written is either testing the wrong thing or
   re-implementing the code; delete or rewrite it. A red run that fails for a
   different reason (bad fixture, syntax error, wrong expectation) is also
   not valid — fix the test until it fails *because the behavior is missing*.
3. Implement the fix.
4. Run it — it MUST PASS (the GREEN run).
5. For review-driven fixes: also confirm the test goes RED when the fix is
   reverted, so the test genuinely pins the change and isn't a tautology.

**RED run vs the make gates:** `make test` gates on lint + typecheck before
pytest runs, so a new test that references an API that does not exist yet
fails the gates first — a wrong-target red, not the missing-behavior red the
rule requires. For the RED proof, invoke the test runner directly on the new
file(s) (`.venv/bin/python -m pytest tests/test_x.py -x`) so the failure is
the missing behavior, then make the code exist and the file pass lint. The
GREEN run and every subsequent run go through `make test` — the direct
invocation is only for the RED evidence, never the final gate.

Weak tests are forbidden and are caught by the RED step:
- **Inline reimplementation** — the test copies the logic instead of calling
  the code under test (passes regardless of the code).
- **Tautologies** — `assert True`, assertions on constants, or tests that
  never reach the code being fixed.
- **Wrong-target reds** — failing for a broken fixture rather than missing
  behavior.

## PR review loop (the iterate-to-nits pattern)

PRs go through automated AI review; the loop is the hardening mechanism:

1. Create the PR; wait for BOTH CI and the AI review to complete (do not
   cancel a running review; ~3–5 min, longer on large PRs).
2. Read the ENTIRE review comment — every section (security, focus areas,
   compliance, suggestions), not just `<details>` counts. Inline comments and
   separate comments count too.
3. Triage every finding: fix all actionable ones (bugs, standards
   violations, security) IN THIS SESSION; note ignorable ones (pre-existing,
   style, config self-review).
4. Every fix follows the TDD rule above — failing test first.
5. Re-run the full gate (`make test`), push, and let the review run again.
6. **Stop when diminishing returns hit**: a round that returns only
   nitpicks, matters of opinion, or things we disagree with. Not when a
   round happens to be clean — a reviewer will keep finding *something*
   (including your own regressions), and each fix adds new diff surface.
   The discipline is: fix every actionable finding, and stop only when the
   findings are no longer actionable.

   Note: the reviewer sees only the final diff — it cannot verify you did
   TDD. RED→GREEN evidence lives in the session, not the PR. That is why
   step 5 (full gate) and the TDD rule are the agent's responsibility, not
   the reviewer's.

## PRD acceptance criteria are the test contracts

- FR-1: N subscribed feeds → `known_domains` contains exactly N domains.
- FR-4: three articles about one event → exactly one approval (the milestone
  one).
- FR-6: re-running a day emits no duplicates; a 13-month-old event is evicted.
- FR-7: digest parses with `feedparser`; entries have both bullets and a
  working outbound URL.
- FR-8: two runs with unchanged inputs produce identical digests.

A bug fix ships with a failing test that reproduces it first.
