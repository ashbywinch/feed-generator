# Deployment Plan — Scheduled Job on GitHub Actions + Netlify (site, admin, state service)

Audience: the operator (you). Single topic: how the weekly selection system runs
unattended — the nightly job on GitHub Actions, the static front end on Netlify,
the two-topics-per-night rotation, and the tiny state web service on Netlify.
Cost/sufficiency verdict at the end.

Related: `docs/prd.md` FR-7 (publish), FR-8 (recurring run), FR-9 (weekly
selection). The run pipeline itself is `spikes/weekly_all.py` + `spikes/build_feeds.py`
+ `spikes/deploy_site.py` (see AGENTS.md).

## Architecture

```mermaid
flowchart LR
    S[GitHub Actions schedule\n0 6 * * *] --> R[nightly job]
    subgraph R [job: checkout → uv sync → state-sync pull]
        O[rotation: pick tonight's 1-2 topics]
        W[spikes/weekly_all.py\nWEEKLY_TOPICS=…]
        F[spikes/build_feeds.py → site/]
        A[make admin → site/admin/]
        O --> W --> F --> A
    end
    R -->|state-sync push| N[Netlify]
    N --> E1[site: /feeds/*, /topics/*, /admin/]
    N --> E2[state service:\n/.netlify/functions/state/{key}\nFunction + Blobs]
    subgraph B [state service]
        direction LR
        P1[GET key → blob] 
        P2[PUT key ← blob]
        P1 --- BLOB[(Netlify Blobs\nper-site, 5 GB/object)]
        P2 --- BLOB
    end
```

State stays out of git: `spikes/state/` (feeds/verdicts/picks JSONL + stories +
per-topic picks) is the idempotency memory — feed TTL, verdict cache, pick
exclusion. It lives in the Netlify state service and is pulled into the
ephemeral runner at job start, pushed back at job end.

## State web service (Netlify Function + Blobs)

One synchronous Function, `netlify/functions/state.ts` (~40 lines), keyed by
relative path. **Language note: Netlify Functions do not run Python** — this is
the one non-Python file in the repo (ops infra, not engine code).

```ts
// netlify/functions/state.ts
export default async (req: Request, context: any) => {
  const key = new URL(req.url).pathname.split("/").filter(Boolean).pop() ?? "";
  if (!key) return new Response("key required", { status: 400 });
  if (req.method === "GET") {
    const blob = await context.blobs.get(key);
    return new Response(blob ?? "", { status: blob ? 200 : 404 });
  }
  if (req.method === "PUT") {
    const expected = context.environment?.STATE_WRITE_TOKEN ?? "";
    if (!expected || req.headers.get("x-write-token") !== expected) {
      return new Response("forbidden", { status: 403 }); // 3-line write guard; reads stay public
    }
    await context.blobs.set(key, await req.text());
    return new Response("ok");
  }
  return new Response("method not allowed", { status: 405 });
};
```

Blob keys (one blob per state file, values are the file bytes):

| Key | Local file | Written by |
|---|---|---|
| `feeds.jsonl` | `spikes/state/weekly_feeds.jsonl` | run |
| `verdicts.jsonl` | `spikes/state/weekly_verdicts.jsonl` | run |
| `picks_history.jsonl` | `spikes/state/weekly_picks.jsonl` | run |
| `stories/{slug}.json` | `spikes/state/stories/{slug}.json` | run |
| `picks/{slug}.json` | `spikes/state/picks/{slug}.json` | run |
| `runs/latest.json` (+ history) | `spikes/state/runs/` | runner (new) |

Protocol: **GET whole blob / PUT whole blob** (no append-diff — keeps the client
dumb). Limits that shape the design:

- Function payload ceiling: **6 MB buffered** (~4.5 MB effective) — fine today
  (state ≈ 1 MB total, largest blob ≈ 350 KB), and a forcing function for the
  compaction the PRD already requires (FR-9: rewrite each JSONL keeping the
  latest line per key) before state nears the ceiling. Add compaction to the
  yearly maintenance, not v1.
- Write exposure: a public PUT means anyone can poison state. You said no auth;
  the minimal guard is a shared `x-write-token` header the function checks on
  PUT (3 lines, unguessable, invisible to readers). Reads stay public.
- **Single-writer assumption**: only the GitHub job writes (the workflow's
  `concurrency` group prevents overlap). A manual local run against the same
  store would last-write-wins — never run local and scheduled simultaneously.

Runner-side sync (keeps the runner file-based; tests unchanged): new
`signalflow/state_sync.py` (pure: enumerates the keys above, GET→file /
file→PUT, injectable http) + `spikes/state_sync.py` CLI. Workflow calls
`state-sync pull` before the run and `state-sync push` after.

## Nightly rotation (two topics per night)

13 topics, 2 per night × 7 nights = 14 slots → 6 nights of 2, 1 night of 1.

Required change (not yet implemented): `spikes/weekly_all.py` accepts
`WEEKLY_TOPICS` env (comma-separated topic names) and `plan_runs` filters to
that subset — freshness gating still applies, so a topic in tonight's slot that
ran < 7 days ago is skipped (cheap night, correct).

Required new script: `spikes/topic_rotation.py` — deterministic from the date:

- Sort topic names; index `t = (topic_idx + week_offset) % 13`, chunk the
  sorted list into 7 groups of 2 (last group of 1), assign group `d` to
  weekday `d`, `week_offset = iso_week % 7` shuffles pairings weekly.
- Output: tonight's topic names, one per line (`--csv` for the workflow).
- Property that makes the rotation the recovery path: a missed or wiped run
  leaves topics stale, and the rotation re-covers every topic within ~a week
  automatically. A full state wipe never needs a manual mega-run.

Acceptance: `python spikes/topic_rotation.py` on any date prints 2 (or 1)
distinct topic names; across any 7 consecutive days every topic appears ≥ 1×.

## Workflow (reference)

`.github/workflows/weekly.yml` — schedule `0 6 * * *` (matches
`RECURRING_CRON` default) + `workflow_dispatch` for manual runs:

```yaml
name: weekly
on:
  schedule: [{ cron: "0 6 * * *" }]
  workflow_dispatch: {}
concurrency: { group: weekly, cancel-in-progress: false }
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: echo "$FEEDLY_OPML_B64" | base64 -d > feedly.opml   # exclusion set
        env: { FEEDLY_OPML_B64: ${{ secrets.FEEDLY_OPML_B64 }} }
      - run: uv run python spikes/state_sync.py pull
        env: { STATE_BASE_URL: ${{ vars.STATE_BASE_URL }}, STATE_WRITE_TOKEN: ${{ secrets.STATE_WRITE_TOKEN }} }
      - run: echo "topics=$(.venv/bin/python spikes/topic_rotation.py --csv)" >> "$GITHUB_OUTPUT"
        id: rotation
      - run: TOPICS="${{ steps.rotation.outputs.topics }}" uv run python spikes/weekly_all.py
        env: { OPENCODE_GO_API_KEY: ..., OPENCODE_GO_BASE_URL: ..., EXA_API_KEY: ... }
      - run: uv run python spikes/build_feeds.py
      - run: uv run python spikes/deploy_site.py
        env: { DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}, NETLIFY_SITE_ID: ${{ secrets.NETLIFY_SITE_ID }} }
      - run: uv run python spikes/state_sync.py push
        if: always()   # partial state is better than none; next run is idempotent
        env: { STATE_BASE_URL: ${{ vars.STATE_BASE_URL }}, STATE_WRITE_TOKEN: ${{ secrets.STATE_WRITE_TOKEN }} }
```

Secrets (GitHub repo secrets, private repo): `OPENCODE_GO_API_KEY`,
`OPENCODE_GO_BASE_URL`, `EXA_API_KEY`, `FEEDLY_OPML_B64` (base64 of
`feedly.opml` — only read when a source list regenerates, but required for the
runner's generate path), `DEPLOY_TOKEN`, `NETLIFY_SITE_ID`,
`STATE_WRITE_TOKEN`; `STATE_BASE_URL` as a repo variable.

## Front end + admin (Netlify)

Layout served from `spikes/output/site/`: `/feeds/{slug}.xml` (Feedly polls),
`/topics/{slug}/` (long reads), `/admin/` (status + failures, **public — your
call, no auth**). Deploy: existing `make deploy` (Deploy API, atomic). Free
tier: 100 GB bandwidth/mo — ample.

Required change (not yet implemented): the runner writes machine-readable run
records (`spikes/state/runs/{ts}.json` + `latest.json`: per-topic status,
picks, verdict counts, story version, list status, failure + traceback excerpt)
and `make admin` renders `site/admin/` from them — same pure-rendering pattern
as `make feeds`. "Why it's failing" = the failure page rendered from those
records + the per-topic tracebacks the runner already logs.

## Failure modes

| Failure | Effect | Recovery |
|---|---|---|
| LLM/Exa/router error on one topic | Topic fails, batch continues (isolated, traceback logged) | Auto-retried once in-run; re-queued next rotation |
| GitHub outage / missed schedule | No run that night | Rotation self-heals within the week |
| State service down at pull | Run starts from empty state | Rotation re-covers all topics over the next week |
| State service down at push | State on Netlify is stale by one night | Next push overwrites; runs are idempotent |
| Netlify outage | Feeds 404, Feedly poll fails | Next deploy restores |
| Public PUT poisons state | Garbage in → garbage selection one night | Token check on PUT (recommended); re-push from a local backup |

## Cost

| Item | Plan | Cost |
|---|---|---|
| GitHub Actions | free, 2000 min/mo private repos; nightly job ≈ 60–120 min/mo | $0 |
| Netlify site + Functions | free tier; ~60 function calls/night (pull+push of ~10 keys), well under the monthly credit budget at this volume | $0 |
| Netlify Blobs | per-site store, 5 GB/object; state ≈ 1 MB total | $0 |
| LLM + Exa | unchanged — the router key's existing spend; 2 topics/night is a small slice | existing budget |

## Sufficiency verdict

Yes — sufficient for a single-user personal system, and the state service is
strictly more durable than the actions/cache alternative (no 7-day eviction;
state survives GitHub entirely). The tradeoffs to accept: one non-Python file
(the ~40-line TS function), a network dependency inside the run (benign —
failures degrade to the empty-state recovery week), the 6 MB function ceiling
(compaction is the documented yearly follow-up), and public write access
(mitigated by the 3-line write-token header). You outgrow it when you need:
guaranteed uptime, real auth on the admin, or state that legitimately exceeds
a few MB without compaction.

## Implementation order

1. `spikes/weekly_all.py`: `WEEKLY_TOPICS` filter in `plan_runs` (test-first).
2. `spikes/topic_rotation.py` + date-rotation test.
3. Runner run records (`spikes/state/runs/`) + `make admin` rendering.
4. `signalflow/state_sync.py` + `spikes/state_sync.py` (test-first, fake http)
   + `netlify/functions/state.ts` (Function + Blobs, write-token check).
5. `.github/workflows/weekly.yml` + secrets + feedly.opml secret.
6. Verify: `workflow_dispatch` run → pull/push round-trips state, admin page
   shows the night's 2 topics, feed XML updates on Netlify, second consecutive
   night is cheap (cached).
