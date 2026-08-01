# Writing Documentation — feed-generator (SignalFlow)

Content conventions follow `skill://write-documentation`. Summary:

- **Context-efficient.** One topic per doc; ~150–200 line ceiling; link, don't
  copy. The reader is a future agent or engineer who wants the decision, not
  the journey.
- **Lead with the conclusion.** Facts, constraints, tradeoffs, decisions,
  checks — in that order of value.
- **Docs are code.** Update them in the same change that changes behavior.
  A doc that contradicts the code is worse than no doc.
- **Specs live in `docs/prd.md`** (v1) and `docs/prd-phase2-kids.md` (phase 2).
  New requirements amend the PRD, not scattered notes.

## Where things go

| Artifact | Location |
|---|---|
| Product requirements / decisions | `docs/prd.md` |
| Curated topic set | `docs/topics.md` (rendered from `signalflow/topics.json`) |
| Per-topic discovery source lists | `docs/discovery/` |
| Code/test/doc conventions | `docs/coding-standards.md` / `docs/testing-standards.md` / this file |
| Repeatable process prompts | `prompts/` |
