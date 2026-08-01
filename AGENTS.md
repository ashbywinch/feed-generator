# feed-generator (SignalFlow)

Personal information fiduciary & outside-discovery engine. Spec: `docs/prd.md`
(v1) and `docs/prd-phase2-kids.md` (phase 2, kids learning-content engine).

Key files:
- `feedly.opml` — user's Feedly export (exclusion set + topic-model seed). Personal data, never commit.
- `.env` — API keys: Opencode go router (chat), Google (embeddings), Exa (search). Never commit; template in `.env.example`.
- `spikes/topic_elicitation_resumable.py` — FR-2 spike (checkpointed to `spikes/state/`, rate-limited + parallel, fail-fast smoke test): sample feeds → embed (gemini-embedding-2) → cluster → name topics.
- `signalflow/` — engine package (v1 under construction).

Conventions (mirror `houses/`): uv + pyproject, ruff, Python >= 3.12.

Run the spike: `make spike`

## Quick start

    make setup      # venv + deps + pre-commit hooks + .env
    make smoke      # engine self-check (opml + memory + embeddings + chat)
    make test       # lint + typecheck + test suite

## Testing rules

- ALWAYS use `make` targets (`make test`, `make lint`, `make typecheck`, `make coverage`); NEVER construct ad-hoc test commands.
- Tests mirror module paths under `tests/`; deterministic, no network; `e2e`-marked tests excluded by default.
- See `docs/testing-standards.md`.

## Docs decision tree

- Product requirements / decisions → `docs/prd.md`; phase 2 → `docs/prd-phase2-kids.md`.
- Code / test / doc conventions → `docs/coding-standards.md`, `docs/testing-standards.md`, `docs/writing-documentation.md`.
- Topic set → `docs/topics.md` (rendered from `signalflow/topics.json`); per-topic discovery source lists → `docs/discovery/`; process prompts → `prompts/`.

## Git

Never commit to main — branch + PR (protected main). Never commit `.env`, `feedly.opml`, `history_memory.db`, or `signalflow_digest.xml` (gitignored).

Never print or log API keys.
