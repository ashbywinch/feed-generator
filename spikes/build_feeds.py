#!/usr/bin/env python3
"""Build per-topic RSS feeds + topic background pages from current state.

Reads the per-topic picks (spikes/state/picks/{slug}.json), the area stories
(spikes/state/stories/{slug}.json) and the feed cache for preview snippets,
then renders the static site layout into spikes/output/site/:

    site/feeds/{slug}.xml          per-topic RSS (Feedly subscribable)
    site/topics/{slug}/index.html  topic background long read

URLs are built from SITE_BASE_URL (default https://signalflow.local until
hosting is decided — see docs/prd.md OQ-3). Pure rendering: no network, no LLM.

Run: make feeds
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.config import Config  # noqa: E402
from signalflow.env import load_env  # noqa: E402
from signalflow.weekly_feed import build_site  # noqa: E402

load_env(ROOT / ".env")

CFG = Config.from_env_optional()
PICKS_DIR = ROOT / "spikes" / "state" / "picks"
STORIES_DIR = ROOT / "spikes" / "state" / "stories"
FEEDS_CACHE = ROOT / "spikes" / "state" / "weekly_feeds.jsonl"
SITE_DIR = ROOT / "spikes" / "output" / "site"


def main(argv: list[str] | None = None) -> int:
    del argv  # config comes from env; signature mirrors the engine's main()
    built = build_site(
        picks_dir=PICKS_DIR,
        stories_dir=STORIES_DIR,
        feeds_path=FEEDS_CACHE,
        site_dir=SITE_DIR,
        base_url=CFG.site_base_url,
    )
    if not built:
        print("no feeds built — no topics with both picks and a story (run make spike-weekly-all first)")
        return 1
    for slug, n in built:
        print(f"      feed {slug}: {n} entries -> site/feeds/{slug}.xml")
        print(f"      page {slug}: topic background -> site/topics/{slug}/index.html")
    print(f"built {len(built)} topic feeds (base URL: {CFG.site_base_url})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
