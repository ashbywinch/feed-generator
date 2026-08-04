#!/usr/bin/env python3
"""Deploy the built static site (spikes/output/site/) to Netlify.

Uploads the per-topic feeds + topic background pages to the configured Netlify
site so Feedly can poll public URLs. Local-only (skipped) until DEPLOY_TOKEN
and NETLIFY_SITE_ID are set in .env — see docs/prd.md FR-7 / OQ-3.

Run: make deploy
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.config import Config  # noqa: E402
from signalflow.deploy import deploy_site  # noqa: E402
from signalflow.env import load_env  # noqa: E402

load_env(ROOT / ".env")

CFG = Config.from_env_optional()
SITE_DIR = ROOT / "spikes" / "output" / "site"


def main(argv: list[str] | None = None) -> int:
    del argv  # config comes from env; signature mirrors the engine's main()
    if not SITE_DIR.exists():
        print("      deploy: nothing to deploy — run `make feeds` first")
        return 1
    result = deploy_site(CFG, SITE_DIR)
    if result is None:
        return 0  # local-only: credentials not configured yet
    print(f"      deploy: live at {result.get('ssl_url') or result.get('url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
