"""Static site deploy (Netlify Deploy API) for the per-topic feeds + pages.

Uploads the built site directory (spikes/output/site/) to a Netlify site so
the feeds are reachable at public URLs (Feedly polls URLs, not local files —
FR-7 publish contract). Local-only until DEPLOY_TOKEN + NETLIFY_SITE_ID are
set; the deploy is then one authenticated POST of a zip of the site files
(atomic per-deploy: Netlify swaps the site only after the upload completes).

Netlify Deploy API: POST /api/v1/sites/{site_id}/deploys
    Authorization: Bearer {deploy_token}
    multipart body with a `files.zip` field carrying the site at the zip root.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from .config import Config

DEPLOY_URL = "https://api.netlify.com/api/v1/sites/{site_id}/deploys"


def zip_site(site_dir: Path) -> bytes:
    """Site directory -> zip bytes, files at the zip root (no nesting).

    Hidden paths are excluded — any component starting with '.', not just the
    basename: a stray .env OR a file inside .git/.secrets must never be
    uploaded with the deploy.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(site_dir.rglob("*")):
            rel = path.relative_to(site_dir)
            if path.is_file() and not any(part.startswith(".") for part in rel.parts):
                zf.write(path, rel.as_posix())
    return buf.getvalue()


def deploy_site(
    cfg: Config,
    site_dir: Path,
    *,
    http_post: Callable[..., Any] = requests.post,
) -> dict[str, Any] | None:
    """Upload site_dir to the configured Netlify site; None when not configured.

    http_post is injectable for tests — the real call is requests.post with a
    multipart `files.zip` body (Netlify's documented deploy format).
    """
    if not cfg.deploy_token or not cfg.netlify_site_id:
        print("      deploy: skipped (no DEPLOY_TOKEN / NETLIFY_SITE_ID) — site is local-only; see docs/prd.md FR-7")
        return None
    if cfg.site_base_url == "https://signalflow.local":
        print(
            "      deploy: refused — SITE_BASE_URL is still the placeholder; publishing would ship "
            "feeds whose absolute URLs point at a non-existent host (FR-7: reachable at a public URL)"
        )
        return None
    url = DEPLOY_URL.format(site_id=cfg.netlify_site_id)
    files = {"files.zip": ("files.zip", zip_site(site_dir), "application/zip")}
    resp = http_post(url, headers={"Authorization": f"Bearer {cfg.deploy_token}"}, files=files, timeout=300)
    resp.raise_for_status()
    return resp.json()
