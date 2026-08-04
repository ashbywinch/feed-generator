#!/usr/bin/env python3
"""Render the admin status page (site/admin/) from run records + install the
Google-OAuth gate worker (site/_worker.js). Pure rendering: no network, no LLM
(worker is a committed artifact, copied verbatim).

Run: make admin
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.admin import render_admin  # noqa: E402

RUNS_DIR = ROOT / "spikes" / "state" / "runs"
SITE_DIR = ROOT / "spikes" / "output" / "site"
WORKER_SRC = ROOT / "spikes" / "pages_worker.js"


def main(argv: list[str] | None = None) -> int:
    del argv  # config comes from state; signature mirrors the engine's main()
    html = render_admin(RUNS_DIR)
    admin_out = SITE_DIR / "admin" / "index.html"
    admin_out.parent.mkdir(parents=True, exist_ok=True)
    tmp = admin_out.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(admin_out)  # atomic: a failed render never publishes a partial page

    worker_out = SITE_DIR / "_worker.js"
    tmp_w = worker_out.with_suffix(".js.tmp")
    tmp_w.write_bytes(WORKER_SRC.read_bytes())
    tmp_w.replace(worker_out)

    print("      admin -> site/admin/index.html (from spikes/state/runs/)")
    print("      worker -> site/_worker.js (Google OAuth gate for /admin/*)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
