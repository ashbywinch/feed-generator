# feed-generator (SignalFlow)

Personal information fiduciary & outside-discovery engine. Spec: `docs/prd.md`
(v1) and `docs/prd-phase2-kids.md` (phase 2, kids learning-content engine).

Key files:
- `feedly.opml` — user's Feedly export (exclusion set + topic-model seed). Personal data, never commit.
- `.env` — API keys: Opencode go router (chat), Google (embeddings), Exa (search). Never commit; template in `.env.example`.
- `spikes/topic_elicitation_resumable.py` — FR-2 spike (checkpointed to `spikes/state/`, rate-limited + parallel, fail-fast smoke test): sample feeds → embed (gemini-embedding-2) → cluster → name topics.
- `spikes/weekly_all.py` — multi-topic catch-up runner (`make spike-weekly-all`): regenerates every topic whose last selection isn't fresh (no picks within `RECENCY_DAYS`), 3 topics at a time (`WEEKLY_WORKERS`), one shared rate limiter, failures isolated. Topics without a `docs/discovery/` source list get one generated first (the make-topic-sources flow: generate → gates → review until approval; needs-human lists are still persisted and used), then selection runs on it. Freshness source: per-topic picks `spikes/state/picks/{slug}.json` (legacy single-file fallback, materialized on first pass).
- `spikes/build_feeds.py` + `signalflow/weekly_feed.py` — per-topic RSS feeds + topic background pages (`make feeds` → `spikes/output/site/feeds/{slug}.xml`, `spikes/output/site/topics/{slug}/index.html`). Entry description = our why-it-matters summary; body = summary + link to the topic long read + clickable preview snippet of the article. Pure rendering, no LLM.
- `spikes/build_admin.py` + `signalflow/admin.py` + `spikes/pages_worker.js` — admin status page (`make admin` → `site/admin/index.html` + `site/_worker.js`): rendered from runner run records (`spikes/state/runs/{ts}.json` + `latest.json`) with a Google-OAuth gate worker (PKCE, signed session cookie; Pages project secrets `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`SESSION_SECRET`/`ADMIN_EMAILS`). Pure rendering; the worker is the one JS artifact (see `docs/deployment-plan.md`).
- `spikes/state_sync.py` — thin rclone wrapper for the R2 state store (`make state-pull`/`make state-push`; skips without R2 creds). R2 holds `spikes/state/` idempotency memory; never logs/pids.
- `.github/workflows/weekly.yml` — nightly rotation (`make rotation`) → selection (`make spike-weekly-all`, `WEEKLY_TOPICS`) → feeds → admin → Cloudflare Pages deploy (`make deploy`). CI runs only make targets. Provisioning + secrets: `docs/deployment-plan.md`.
- `spikes/weekly_selection.py` — weekly article-selection pipeline (`make spike-weekly`, TOPIC=…): fetch each source's feed from the topic's `docs/discovery/*.json` list, window to last 7 days, LLM-judge against the topic boundary (FR-5 bar, hard OUT-scope gate, `MAX_PICKS_PER_SOURCE` cap, zero-pick sites valid). Writes per-topic picks to `spikes/state/picks/{slug}.json`. Repeatable via feed/verdict caches + pick history; verdicts keyed on (prompt revision, story version). Maintains a long-form per-topic area story (`spikes/state/stories/`, seeded BIG-PICTURE-FIRST from the topic boundary via `prompts/generate_area_story.md` — no article input; folds only adapt the big picture, never append article specifics; per-subarea slices injected into evaluation prompts). `spikes/eval_story.py` (`make eval-story`) gates story quality: the story must contextualize held-out fresh articles (placement criterion) and stay narrative, not a question list. Destined for the engine, so both ARE type-gated (basedpyright) and lint-gated (ruff), unlike the other spikes; feedparser types come from `typings/`.
- `signalflow/` — engine package (v1 under construction).

Conventions (mirror `houses/`): uv + pyproject, ruff, Python >= 3.12.

Run the spike: `make spike`

## Quick start

    make setup      # venv + deps + pre-commit hooks + .env
    make smoke      # engine self-check (opml + memory + embeddings + chat)
    make run        # recurring run — requires `python -m signalflow setup` first (one-and-done)
    make test       # lint + typecheck + test suite

## Testing rules

- ALWAYS use `make` targets (`make test`, `make lint`, `make typecheck`, `make coverage`); NEVER construct ad-hoc test commands.
- **TDD is mandatory: a failing test comes FIRST, run it RED, then fix, then GREEN.** Tests must call the real code path — never re-implement logic inline. Weak tests (inline reimplementation, tautologies) are forbidden; the RED run is the proof. See `docs/testing-standards.md`.
- **PR review loop:** every PR goes through AI review; read the FULL comment, fix every actionable finding test-first, re-run the full gate, push, repeat. Stop only when a round returns nothing but nitpicks/opinions/disagreements. See `docs/testing-standards.md` §PR review loop.
- Tests mirror module paths under `tests/`; deterministic, no network; `e2e`-marked tests excluded by default.
- See `docs/testing-standards.md`.

## Docs decision tree

- Product requirements / decisions → `docs/prd.md`; phase 2 → `docs/prd-phase2-kids.md`.
- Code / test / doc conventions → `docs/coding-standards.md`, `docs/testing-standards.md`, `docs/writing-documentation.md`.
- Topic set → `docs/topics.md` (rendered from `signalflow/topics.json`); per-topic discovery source lists → `docs/discovery/`; process prompts → `prompts/`.
- Weekly feed selection (mechanism, wire-up contract, decisions) → FR-9 in `docs/prd.md`.

## Git

Never commit to main — branch + PR (protected main). Never commit `.env`, `feedly.opml`, `history_memory.db`, or `signalflow_digest.xml` (gitignored).

Never print or log API keys.
