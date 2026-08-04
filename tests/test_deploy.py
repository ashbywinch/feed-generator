"""Static site deploy to Cloudflare Pages (Direct Upload API): file map +
blake3 hashes + upload-token/assets/deployments flow. No network — HTTP is
injected; what is tested is the wiring: skip behavior, the exact endpoints +
auth headers, the manifest contract, and error propagation.

API contract source: wrangler src/api/pages/deploy.ts + src/pages/{upload,validate,hash}.ts
(e643b19d) and the Cloudflare Pages "Create deployment" API reference.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
import requests

from signalflow.config import Config
from signalflow.deploy import (
    ASSETS_UPLOAD_URL,
    CHECK_MISSING_URL,
    DEPLOY_URL,
    UPLOAD_TOKEN_URL,
    UPSERT_HASHES_URL,
    deploy_site,
    file_hash,
    site_files,
)


def _cfg(
    cf_api_token: str = "",
    cf_account_id: str = "",
    cf_project: str = "",
    site_base_url: str = "https://feeds.example.com",
) -> Config:
    return Config(
        llm_key="k",
        llm_base="https://router/v1",
        llm_model="m",
        embed_model="e",
        google_key="g",
        exa_key="x",
        cf_api_token=cf_api_token,
        cf_account_id=cf_account_id,
        cf_project=cf_project,
        site_base_url=site_base_url,
    )


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "feeds").mkdir(parents=True)
    (site / "topics" / "01-x").mkdir(parents=True)
    (site / "feeds" / "01-x.xml").write_text("<rss/>", encoding="utf-8")
    (site / "topics" / "01-x" / "index.html").write_text("<html/>", encoding="utf-8")
    return site


def _authed(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- file map + hashes ------------------------------------------------------


def test_site_files_reads_tree_flat(tmp_path: Path) -> None:
    files = site_files(_site(tmp_path))
    assert files == {
        "feeds/01-x.xml": b"<rss/>",
        "topics/01-x/index.html": b"<html/>",
    }


def test_site_files_excludes_hidden_files_and_dirs(tmp_path: Path) -> None:
    """A stray .env (or any dotfile) in the site dir must never be uploaded."""
    site = _site(tmp_path)
    (site / ".env").write_text("SECRET=leak", encoding="utf-8")
    (site / ".git").mkdir()
    (site / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (site / ".secrets").mkdir()
    (site / ".secrets" / "token").write_text("t", encoding="utf-8")
    files = site_files(site)
    assert ".env" not in files
    assert ".git/HEAD" not in files
    assert ".secrets/token" not in files
    assert "feeds/01-x.xml" in files  # visible files still ship


def test_site_files_excludes_worker_from_assets(tmp_path: Path) -> None:
    """_worker.js (advanced-mode Pages worker) is a multipart field on the
    deployment POST, never an uploaded asset (wrangler IGNORE_LIST)."""
    site = _site(tmp_path)
    (site / "_worker.js").write_text("export default {}", encoding="utf-8")
    assert "_worker.js" not in site_files(site)


def test_file_hash_matches_wrangler_algorithm() -> None:
    """blake3(base64(content) + extension)[:32 hex] — ground truth computed
    with the blake3 package against wrangler's src/pages/hash.ts."""
    assert file_hash(b"<rss/>", "xml") == "7f0de94f9d9e8434240b2f160ad88d80"


def test_file_hash_differs_by_extension() -> None:
    assert file_hash(b"<rss/>", "xml") != file_hash(b"<rss/>", "html")


# --- deploy wiring ----------------------------------------------------------


def test_deploy_site_skipped_without_credentials(tmp_path: Path, capsys) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no HTTP should happen without credentials")

    assert deploy_site(_cfg(), _site(tmp_path), http_get=boom, http_post=boom) is None
    assert "skipped (no CF_API_TOKEN / CF_ACCOUNT_ID / CF_PROJECT)" in capsys.readouterr().out


def test_deploy_site_refuses_placeholder_base_url(tmp_path: Path, capsys) -> None:
    """Publishing with the default SITE_BASE_URL placeholder would ship broken
    absolute feed URLs — refuse before any HTTP call."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no HTTP should happen with a placeholder URL")

    deploy_site(
        _cfg(cf_api_token="t", cf_account_id="a", cf_project="p", site_base_url="https://signalflow.local"),
        _site(tmp_path),
        http_get=boom,
        http_post=boom,
    )
    assert "placeholder" in capsys.readouterr().out


def test_deploy_site_refuses_unprotected_admin(tmp_path: Path, capsys) -> None:
    """An admin/ dir without the _worker.js gate would be served to anyone —
    refuse the deploy instead of shipping it."""
    site = _site(tmp_path)
    (site / "admin").mkdir()
    (site / "admin" / "index.html").write_text("<html/>", encoding="utf-8")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no HTTP should happen for an unprotected admin")

    assert (
        deploy_site(_cfg(cf_api_token="t", cf_account_id="a", cf_project="p"), site, http_get=boom, http_post=boom)
        is None
    )
    assert "unprotected" in capsys.readouterr().out


def test_deploy_site_full_flow(tmp_path: Path) -> None:
    """upload-token (Bearer CF token) -> check-missing -> upload (base64) ->
    upsert-hashes -> create deployment (multipart manifest + _worker.js)."""
    site = _site(tmp_path)
    (site / "_worker.js").write_text("export default {}", encoding="utf-8")
    cfg = _cfg(cf_api_token="cf-token", cf_account_id="acc-1", cf_project="proj-9")

    seen: list[dict[str, Any]] = []
    deployment = {"id": "d-1", "url": "https://proj-9.pages.dev", "environment": "production"}

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        seen.append({"op": "get", "url": url, **kwargs})
        assert url == UPLOAD_TOKEN_URL.format(account_id="acc-1", project="proj-9")
        assert kwargs["headers"] == _authed("cf-token")
        return _FakeResponse({"success": True, "result": {"jwt": "upload-jwt"}})

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        seen.append({"op": "post", "url": url, **kwargs})
        if url == CHECK_MISSING_URL:
            assert kwargs["headers"] == _authed("upload-jwt")
            all_hashes = [file_hash(content, name.rsplit(".", 1)[-1]) for name, content in site_files(site).items()]
            return _FakeResponse({"success": True, "result": all_hashes})  # everything missing: upload all
        if url == ASSETS_UPLOAD_URL:
            payload = kwargs["json"]
            assert all(item["base64"] is True for item in payload)
            assert {base64.b64decode(item["value"]) for item in payload} == {b"<rss/>", b"<html/>"}
            return _FakeResponse({"success": True, "result": {}})
        if url == UPSERT_HASHES_URL:
            assert kwargs["headers"] == _authed("upload-jwt")
            return _FakeResponse({"success": True, "result": {}})
        assert url == DEPLOY_URL.format(account_id="acc-1", project="proj-9")
        assert kwargs["headers"] == _authed("cf-token")
        form = kwargs["files"]
        manifest = json.loads(form["manifest"][1])
        expected = {
            f"/{name}": file_hash(content, name.rsplit(".", 1)[-1] if "." in name else "")
            for name, content in site_files(site).items()
        }
        assert manifest == expected
        assert manifest["/feeds/01-x.xml"] == file_hash(b"<rss/>", "xml")
        assert form["_worker.js"][0] == "_worker.js"
        assert form["_worker.js"][1] == b"export default {}"
        return _FakeResponse({"success": True, "result": deployment})

    result = deploy_site(cfg, site, http_get=fake_get, http_post=fake_post)

    assert result == deployment
    ops = [s["op"] + ":" + s["url"] for s in seen]
    assert ops == [
        "get:" + UPLOAD_TOKEN_URL.format(account_id="acc-1", project="proj-9"),
        "post:" + CHECK_MISSING_URL,
        "post:" + ASSETS_UPLOAD_URL,
        "post:" + UPSERT_HASHES_URL,
        "post:" + DEPLOY_URL.format(account_id="acc-1", project="proj-9"),
    ]


def test_deploy_site_skips_upload_when_everything_cached(tmp_path: Path) -> None:
    """check-missing returns no missing hashes -> no upload call, deployment still runs."""
    site = _site(tmp_path)
    cfg = _cfg(cf_api_token="t", cf_account_id="a", cf_project="p")

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({"success": True, "result": {"jwt": "j"}})

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        if url == CHECK_MISSING_URL:
            return _FakeResponse({"success": True, "result": []})  # nothing missing
        if url == ASSETS_UPLOAD_URL:
            raise AssertionError("nothing is missing: upload must not be called")
        if url == UPSERT_HASHES_URL:
            return _FakeResponse({"success": True, "result": {}})
        return _FakeResponse({"success": True, "result": {"url": "https://p.pages.dev"}})

    result = deploy_site(cfg, site, http_get=fake_get, http_post=fake_post)
    assert result == {"url": "https://p.pages.dev"}


def test_deploy_site_check_missing_failure_uploads_all(tmp_path: Path) -> None:
    """A failed check-missing is an optimization loss, not a correctness break:
    fall back to uploading every file (still logged, never silent)."""
    site = _site(tmp_path)
    cfg = _cfg(cf_api_token="t", cf_account_id="a", cf_project="p")
    upload_calls: list[Any] = []

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({"success": True, "result": {"jwt": "j"}})

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        if url == CHECK_MISSING_URL:
            raise requests.ConnectionError("network blip")
        if url == ASSETS_UPLOAD_URL:
            upload_calls.append(kwargs["json"])
            return _FakeResponse({"success": True, "result": {}})
        if url == UPSERT_HASHES_URL:
            return _FakeResponse({"success": True, "result": {}})
        return _FakeResponse({"success": True, "result": {"url": "https://p.pages.dev"}})

    deploy_site(cfg, site, http_get=fake_get, http_post=fake_post)
    assert upload_calls and len(upload_calls[0]) == len(site_files(site))


def test_deploy_site_raises_on_api_error(tmp_path: Path, capsys) -> None:
    """CF API envelopes errors as HTTP 200 {success: false, errors: [...]} —
    surface them as an exception, not a silent deploy."""
    site = _site(tmp_path)

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({"success": True, "result": {"jwt": "j"}})

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        if url == CHECK_MISSING_URL:
            return _FakeResponse({"success": True, "result": []})
        if url == ASSETS_UPLOAD_URL:
            return _FakeResponse({"success": True, "result": {}})
        if url == UPSERT_HASHES_URL:
            return _FakeResponse({"success": True, "result": {}})
        return _FakeResponse({"success": False, "errors": [{"message": "project not found"}]})

    with pytest.raises(RuntimeError, match="project not found"):
        deploy_site(
            _cfg(cf_api_token="t", cf_account_id="a", cf_project="p"), site, http_get=fake_get, http_post=fake_post
        )


def test_deploy_site_propagates_http_errors(tmp_path: Path) -> None:
    site = _site(tmp_path)

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({"success": True, "result": {"jwt": "j"}})

    def failing_post(url: str, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse({}, status=500)

    with pytest.raises(requests.HTTPError):
        deploy_site(
            _cfg(cf_api_token="t", cf_account_id="a", cf_project="p"), site, http_get=fake_get, http_post=failing_post
        )


def test_deploy_site_rejects_oversized_file(tmp_path: Path) -> None:
    """Cloudflare caps assets at 25 MiB — fail fast before any HTTP call."""
    site = _site(tmp_path)
    (site / "feeds" / "huge.xml").write_bytes(b"x" * (25 * 1024 * 1024 + 1))

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no HTTP should happen for an oversized asset")

    with pytest.raises(ValueError, match="25 MiB"):
        deploy_site(_cfg(cf_api_token="t", cf_account_id="a", cf_project="p"), site, http_get=boom, http_post=boom)
