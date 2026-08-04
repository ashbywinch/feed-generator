"""FR-7: RSS digest (signalflow_digest.xml) + Feedly publishing.

Entries: title prefixed [Topic]; body = Observed Event + Systemic Thesis +
direct outbound link; per-entry id = stable source URL (Feedly de-dupes on
id). The digest must be reachable at a public URL for Feedly — publishing
copies it into the site directory and deploys the site via the Cloudflare
Pages Direct Upload adapter (docs/deployment-plan.md); without credentials
the digest stays local-only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from feedgen.feed import FeedGenerator

from .config import Config
from .deploy import deploy_site
from .env import PROJECT_ROOT
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


def publish(
    cfg: Config,
    digest_path: Path,
    *,
    site_dir: Path | None = None,
    deploy_fn: Callable[..., Any] = deploy_site,
) -> None:
    """Deploy the digest to the static host: copy it into the site directory
    and publish the site (FR-7). Local-only until the CF credentials are set.
    site_dir/deploy_fn are injectable for tests — the real path is the repo
    site dir + signalflow.deploy.
    """
    if not (cfg.cf_api_token and cfg.cf_account_id and cfg.cf_project):
        print(
            "      publish: skipped (no CF_API_TOKEN / CF_ACCOUNT_ID / CF_PROJECT) — "
            "digest is local-only; see docs/deployment-plan.md"
        )
        return
    site_dir = site_dir or (PROJECT_ROOT / "spikes" / "output" / "site")
    site_dir.mkdir(parents=True, exist_ok=True)
    dest = site_dir / digest_path.name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(digest_path.read_bytes())
    tmp.replace(dest)  # atomic: a failed write never ships a partial digest
    result = deploy_fn(cfg, site_dir)
    if result:
        print(f"      publish: live at {result.get('url')}")
