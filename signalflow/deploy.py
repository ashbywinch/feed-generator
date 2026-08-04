"""Static site deploy (Cloudflare Pages Direct Upload API) for the feeds + pages.

Uploads the built site directory (spikes/output/site/) to a Cloudflare Pages
project so the feeds are reachable at public URLs (Feedly polls URLs, not
local files — FR-7 publish contract). Local-only until CF_API_TOKEN /
CF_ACCOUNT_ID / CF_PROJECT are set; the deploy is then the wrangler-equivalent
flow against the Pages API:

    GET  /accounts/{a}/pages/projects/{p}/upload-token   (Bearer CF token)
    POST /pages/assets/check-missing                     (Bearer upload JWT)
    POST /pages/assets/upload                            (Bearer upload JWT)
    POST /pages/assets/upsert-hashes                     (Bearer upload JWT)
    POST /accounts/{a}/pages/projects/{p}/deployments    (Bearer CF token)

Asset hashes are blake3(base64(content) + extension)[:32 hex] — the exact
algorithm from wrangler src/pages/hash.ts (verified against e643b19d), so a
nightly re-deploy of unchanged files is a no-op upload (check-missing). The
advanced-mode worker (_worker.js) is excluded from the asset map and shipped
as a multipart field on the deployment POST instead, matching wrangler's
IGNORE_LIST + deploy.ts.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import blake3
import requests

from .config import Config

API_BASE = "https://api.cloudflare.com/client/v4"
DEPLOY_URL = API_BASE + "/accounts/{account_id}/pages/projects/{project}/deployments"
UPLOAD_TOKEN_URL = API_BASE + "/accounts/{account_id}/pages/projects/{project}/upload-token"
CHECK_MISSING_URL = API_BASE + "/pages/assets/check-missing"
ASSETS_UPLOAD_URL = API_BASE + "/pages/assets/upload"
UPSERT_HASHES_URL = API_BASE + "/pages/assets/upsert-hashes"

# Cloudflare hard limits (API + wrangler constants) — fail fast instead of a
# 400 from the API mid-deploy.
MAX_FILE_BYTES = 25 * 1024 * 1024  # per-asset cap
MAX_BUCKET_BYTES = 50 * 1024 * 1024  # per upload-bucket cap (wrangler MAX_BUCKET_SIZE)
MAX_BUCKET_FILES = 100  # per upload-bucket file cap (wrangler MAX_BUCKET_FILE_COUNT)
MAX_FILES = 20_000  # manifest cap (API reference: max 20,000 entries)

WORKER_NAME = "_worker.js"  # advanced-mode Pages worker: multipart field, never an asset


def site_files(site_dir: Path) -> dict[str, bytes]:
    """Site directory -> {relative path: content}, files at the site root.

    Hidden paths are excluded — any component starting with '.', not just the
    basename: a stray .env OR a file inside .git/.secrets must never be
    uploaded with the deploy. _worker.js is also excluded: it is shipped as a
    multipart field on the deployment POST, not an uploaded asset.
    """
    files: dict[str, bytes] = {}
    for path in sorted(site_dir.rglob("*")):
        rel = path.relative_to(site_dir)
        if not path.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        name = rel.as_posix()
        if name == WORKER_NAME:
            continue
        files[name] = path.read_bytes()
    return files


def file_hash(content: bytes, ext: str) -> str:
    """Cloudflare Pages asset hash: blake3(base64(content) + extension)[:32 hex].

    Ground truth: wrangler src/pages/hash.ts — base64 of the file contents
    concatenated with the extension (no dot), hashed with blake3, first 32 hex
    chars. A hash mismatch would re-upload every file every night AND break
    check-missing dedup, so the algorithm is pinned by test vector.
    """
    return blake3.blake3(base64.b64encode(content) + ext.encode()).hexdigest()[:32]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cf_result(resp: Any) -> Any:
    """Cloudflare API envelope -> result. Raises on HTTP errors AND on
    HTTP 200 responses carrying {success: false, errors: [...]} — the API's
    way of reporting "project not found" etc. without an HTTP status."""
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        errors = "; ".join(str(e.get("message", e)) for e in data.get("errors", []))
        raise RuntimeError(f"Cloudflare API error: {errors or data}")
    return data.get("result")


def _buckets(files: Iterable[tuple[str, bytes]]) -> list[list[tuple[str, bytes]]]:
    """Split the asset list into upload buckets (<= 100 files, <= 50 MiB each).

    The site is ~1 MB, so this is one bucket in practice; the caps exist so a
    future large site fails loudly and correctly instead of hitting the API's
    undocumented per-request ceiling mid-upload.
    """
    buckets: list[list[tuple[str, bytes]]] = [[]]
    size = 0
    for name, content in files:
        if len(buckets[-1]) >= MAX_BUCKET_FILES or (size and size + len(content) > MAX_BUCKET_BYTES):
            buckets.append([])
            size = 0
        buckets[-1].append((name, content))
        size += len(content)
    return [b for b in buckets if b]


def deploy_site(
    cfg: Config,
    site_dir: Path,
    *,
    http_get: Callable[..., Any] = requests.get,
    http_post: Callable[..., Any] = requests.post,
) -> dict[str, Any] | None:
    """Upload site_dir to the configured Cloudflare Pages project; None when
    not configured. http_get/http_post are injectable for tests — the real
    calls go to the Cloudflare API (see module docstring for the flow).
    """
    if not (cfg.cf_api_token and cfg.cf_account_id and cfg.cf_project):
        print(
            "      deploy: skipped (no CF_API_TOKEN / CF_ACCOUNT_ID / CF_PROJECT) — "
            "site is local-only; see docs/deployment-plan.md"
        )
        return None
    if cfg.site_base_url == "https://signalflow.local":
        print(
            "      deploy: refused — SITE_BASE_URL is still the placeholder; publishing would ship "
            "feeds whose absolute URLs point at a non-existent host (FR-7: reachable at a public URL)"
        )
        return None

    files = site_files(site_dir)
    if not files:
        print("      deploy: nothing to deploy — run `make feeds` (and `make admin`) first")
        return None
    if len(files) > MAX_FILES:
        raise ValueError(f"deploy: {len(files)} files exceeds Cloudflare's 20,000-file manifest cap")
    for name, content in files.items():
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"deploy: {name} exceeds Cloudflare's 25 MiB per-file limit")
    worker = site_dir / WORKER_NAME
    if any(name.startswith("admin/") for name in files) and not worker.is_file():
        print(
            "      deploy: refused — site/admin/ exists but _worker.js is missing "
            "(the admin page would be served unprotected); run `make admin` first"
        )
        return None

    account = cfg.cf_account_id
    project = cfg.cf_project
    cf_headers = _auth(cfg.cf_api_token)

    # 1. Short-lived upload JWT (assets endpoints authenticate with this, not
    #    the account token).
    resp = http_get(UPLOAD_TOKEN_URL.format(account_id=account, project=project), headers=cf_headers, timeout=60)
    jwt = _cf_result(resp)["jwt"]

    # 2. Hashes + manifest (path -> hash). check-missing then decides what (if
    #    anything) actually needs uploading — unchanged nights are cheap.
    manifest = {f"/{name}": file_hash(content, Path(name).suffix.lstrip(".")) for name, content in files.items()}
    hashes = sorted(set(manifest.values()))

    # 3. Which hashes does Cloudflare already hold? Best-effort: a failure here
    #    is an optimization loss, not a correctness break — uploading every
    #    file is always valid. Logged, never silent.
    try:
        resp = http_post(CHECK_MISSING_URL, headers=_auth(jwt), json={"hashes": hashes}, timeout=120)
        missing = set(_cf_result(resp))
    except Exception as exc:  # noqa: BLE001 — fall back to uploading everything
        print(f"      deploy: check-missing failed ({exc}); uploading all {len(files)} files")
        missing = set(hashes)

    # 4. Upload the missing assets (base64 payloads, bucketed).
    todo = [(name, content) for name, content in files.items() if manifest[f"/{name}"] in missing]
    if not todo:
        print("      deploy: no file changes — all assets already on Cloudflare")
    else:
        for bucket in _buckets(todo):
            payload = [
                {
                    "key": manifest[f"/{name}"],
                    "value": base64.b64encode(content).decode("ascii"),
                    "metadata": {"contentType": mimetypes.guess_type(name)[0] or "application/octet-stream"},
                    "base64": True,
                }
                for name, content in bucket
            ]
            resp = http_post(ASSETS_UPLOAD_URL, headers=_auth(jwt), json=payload, timeout=300)
            _cf_result(resp)

    # 5. Register the hashes so the next check-missing is accurate.
    resp = http_post(UPSERT_HASHES_URL, headers=_auth(jwt), json={"hashes": hashes}, timeout=120)
    _cf_result(resp)

    # 6. Create the deployment: multipart manifest + the advanced-mode worker
    #    as a dedicated field (wrangler deploys it the same way).
    form: dict[str, tuple[Any, ...]] = {
        "manifest": (None, json.dumps(manifest), "application/json"),
        "branch": (None, "main"),
    }
    if worker.is_file():
        form[WORKER_NAME] = (WORKER_NAME, worker.read_bytes(), "application/javascript")
    resp = http_post(
        DEPLOY_URL.format(account_id=account, project=project), headers=cf_headers, files=form, timeout=300
    )
    return _cf_result(resp)
