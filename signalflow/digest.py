"""FR-7: RSS digest (signalflow_digest.xml) + Feedly publishing.

Entries: title prefixed [Topic]; body = Observed Event + Systemic Thesis +
direct outbound link; per-entry id = stable source URL (Feedly de-dupes on
id). The digest must be reachable at a public URL for Feedly — publishing is
a static-host deploy (default Netlify); without a token we stay local-only.
"""

from __future__ import annotations

from pathlib import Path

from feedgen.feed import FeedGenerator

from .config import Config
from .models import ApprovedEvent


def build_digest(cfg: Config, events: list[ApprovedEvent], out_path: Path) -> None:
    fg = FeedGenerator()
    fg.id("https://signalflow.local/feed")
    fg.title("SignalFlow Discovery Digest")
    fg.author({"name": "SignalFlow Fiduciary"})
    fg.link(href="https://signalflow.local", rel="alternate")
    fg.description("Filtered novel commentary and empirical developments from outside sources and program registries.")

    for ev in events:
        fe = fg.add_entry()
        fe.id(ev.candidate.url)
        fe.title(f"[{ev.analysis.topic or 'untagged'}] {ev.candidate.title}")
        fe.link(href=ev.candidate.url)
        fe.description(
            f"<p><b>Observed Event:</b> {ev.analysis.empirical_event}</p>"
            f"<p><b>Systemic Thesis:</b> {ev.analysis.core_thesis}</p>"
            f'<p><a href="{ev.candidate.url}">Read original source &rarr;</a></p>'
        )

    tmp = out_path.with_suffix(".tmp")
    fg.rss_file(str(tmp), pretty=True)
    tmp.replace(out_path)  # atomic: a failed run never publishes a partial feed
    try:
        shown = out_path.relative_to(Path.cwd())
    except ValueError:
        shown = out_path
    print(f"      digest -> {shown} ({len(events)} entries)")


def publish(cfg: Config, digest_path: Path) -> None:
    """Deploy the digest to the static host. Local-only until DEPLOY_TOKEN set."""
    if not cfg.deploy_token:
        print("      publish: skipped (no DEPLOY_TOKEN) — digest is local-only; see docs/prd.md FR-7")
        return
    # Netlify deploy API: requires a site id + token. Kept minimal on purpose;
    # hosting choice is the user's call (PRD open question OQ-3).
    site_id = cfg.deploy_token  # placeholder — real flow: NETLIFY_SITE_ID + token auth
    print(f"      publish: not yet wired to Netlify site {site_id!r} — TODO in hosting setup")
