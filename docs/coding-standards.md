# Coding Standards — feed-generator (SignalFlow)

Materialised from the global house standard (`omp-config/docs/coding-standards.md`),
plus project-specific rules below. Deviations must be justified in the PR.
The PR-Agent reviewer enforces ONLY what is in this file — keep it the full
semantic rule set, never a condensation.

## Design principles

- **Separation of concerns.** One reason to change per module/class/function.
  HTTP vs business vs persistence live in different modules with one-way
  dependency chains. An urge to import from a sibling layer or mix I/O with
  computation means split, not shortcut.
- **Cohesive modules and classes.** Data + behaviour together. A module/class
  owns its invariants; external code never reaches into structures to compute
  derived values. Public-field classes that others manipulate are
  poorly-organised dicts; accessor chains feeding procedural code are missed
  abstractions.
- **Names communicate intent.** Domain names, not shapes: `monthlyPayment`
  not `calculateValue3`. A name needing a comment is a failed name. Classes
  are domain nouns; functions are verbs; variables hold what they name
  (`price`, not `x`); booleans read in `if` (`hasSchool`, not `schoolFlag`);
  an id is never a label.
- **Semantic types over primitives.** A point in time is a date type with
  awareness, not a bare string; structured data is an object with named
  fields, not a bare dict; enumerated values are enums; units are part of the
  value. Before reaching for a primitive: "is there a type that makes this
  impossible to misuse?"
- **Each class in its own module.** Named after the class; exception for a
  module grouping closely related handful-of-fields models that share one
  reason to change.
- **Anti-fragile: correct by construction.** Types make invalid states
  unrepresentable; pure functions preferred; error paths explicit; never cast
  or suppress type-checker flags; happy paths read naturally. Signs of
  coincidental correctness: works only in your test env, reordering "happens
  to work", unrelated breakage, unwritten rules ("always call X before Y").
- **Fail fast, never swallow errors.** Every `except`/`catch` must log,
  re-raise, or handle observably. Invisible failure is a bug:
  ```python
  # ✗ invisible
  try:
      do_something()
  except Exception:
      pass
  # ✓ observable
  try:
      do_something()
  except Exception as e:
      logger.debug("do_something failed (non-fatal): %s", e)
  ```
- **Two-tier failure messages.** A fail-fast path triggered by environment,
  configuration, or user error emits two messages: a plain-language user line
  (what happened + what to do next, no internal identifiers, no stack traces)
  and a dev log (root cause + exact resolution). One half alone is a bug.
- **No backward-compat shims.** Delete the old path; migrate callers in the
  same change. No aliases, no re-exports, no "will remove later". A shim
  compiles, passes tests, and never gets cleaned up.
- **Boring over clever.** Prefer the obvious implementation a future reader
  can understand in any editor. Correctness first, then the next maintainer.

## Dependency injection

DI over patching. Inject the dependency (service, output path, fake) — never
`monkeypatch`/`patch` global state. If something isn't reachable through DI,
refactor the code to accept a dependency. Fakes subclass the real protocol so
the type checker still holds at edit time.

## Testing

- Tests mirror module paths; deterministic (no wall-clock, network, or order
  dependence; seeded randoms); assert behaviour not implementation.
- A test that cannot fail on a plausible bug is not a test (no tautological
  fixtures — validate real artifacts).
- Pure functions need no mocking; function-param injection next; containers
  after that; global patching is a last resort and a smell.
- Project specifics (TDD rule, PR review loop, PRD acceptance contracts):
  see `docs/testing-standards.md`.

## Documentation

- **Delete, don't archive.** Obsolete content is a liability; remove it. No
  archive dirs, no deprecation notices.
- **Single source of truth.** Each fact in exactly one place; other docs
  link, never repeat.
- **Docs must match code.** Rename a function/module → update the docs in the
  same change. The reviewer's compliance checks treat docs as ground truth
  and will cite them verbatim when they lag.
- **Docs are anti-fragile.** Don't restate what the code says (signatures,
  defaults, file lists); reference the code instead.
- Project conventions: see `docs/writing-documentation.md`.

## Project-specific: pipeline invariants

- De-dup order is fixed: L1 domain blacklist → L2 hash → L3 vector → L4 delta
  evaluator (cheapest first). Never call the LLM before L2.
- Embedding model is never mixed in the store (`EMBEDDING_MODEL`); switching
  requires re-embedding.
- A failed run never publishes a partial or empty digest over a good one
  (atomic swap).
- Per-topic discovery queries come only from stored strategies — never a
  global fixed query list.
- The recurring run (FR-8) executes STORED strategies (FR-3 discovery +
  FR-9 feed selection) and never re-derives them; setup (OPML → blacklist +
  topics) is one-and-done and never re-runs inside the daily loop.
- Setup is atomic: a failed blacklist write or zero-seed leaves NO partial
  state (persist + verify blacklist first, roll back on zero-seed).

## Project-specific: secrets

- API keys live only in the environment / `.env`. Never print, log, or commit
  key values; redact in exception messages (`LLM._redact`).

## Project-specific: style (ruff)

`select = E,F,I,UP,B,SIM,N`, `line-length = 120`, double quotes, `fixable =
ALL`. Python >= 3.12, type-checked with basedpyright. Run via `make lint` /
`make format` — never ad-hoc tool commands.
