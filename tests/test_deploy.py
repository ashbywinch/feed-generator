"""Static site deploy to Netlify: zip + authenticated POST, local-only without creds.

No network in tests — the HTTP call is injected; what is tested is the wiring:
skip behavior, the exact endpoint + auth header, zip layout, and error
propagation.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
import requests

from signalflow.config import Config
from signalflow.deploy import DEPLOY_URL, deploy_site, zip_site


def _cfg(deploy_token: str = "", netlify_site_id: str = "", site_base_url: str = "https://feeds.example.com") -> Config:
    return Config(
        llm_key="k",
        llm_base="https://router/v1",
        llm_model="m",
        embed_model="e",
        google_key="g",
        exa_key="x",
        deploy_token=deploy_token,
        netlify_site_id=netlify_site_id,
        site_base_url=site_base_url,
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "feeds").mkdir(parents=True)
    (site / "topics" / "01-x").mkdir(parents=True)
    (site / "feeds" / "01-x.xml").write_text("<rss/>", encoding="utf-8")
    (site / "topics" / "01-x" / "index.html").write_text("<html/>", encoding="utf-8")
    return site


def test_zip_site_flattens_to_zip_root(tmp_path: Path) -> None:
    data = zip_site(_site(tmp_path))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert "feeds/01-x.xml" in names
    assert "topics/01-x/index.html" in names
    assert not any(n.startswith("site/") for n in names)  # site dir itself not nested


def test_zip_site_excludes_hidden_files(tmp_path: Path) -> None:
    """A stray .env (or any dotfile) in the site dir must never be uploaded."""
    site = _site(tmp_path)
    (site / ".env").write_text("SECRET=leak", encoding="utf-8")
    with zipfile.ZipFile(io.BytesIO(zip_site(site))) as zf:
        assert ".env" not in zf.namelist()


def test_zip_site_excludes_nested_hidden_directories(tmp_path: Path) -> None:
    """Files inside hidden directories (site/.git/HEAD, site/.secrets/token)
    must never be uploaded either — any hidden path component is excluded."""
    site = _site(tmp_path)
    hidden = site / ".git"
    hidden.mkdir()
    (hidden / "HEAD").write_text("ref", encoding="utf-8")
    (site / ".secrets" / "token").parent.mkdir(parents=True)
    (site / ".secrets" / "token").write_text("t", encoding="utf-8")
    with zipfile.ZipFile(io.BytesIO(zip_site(site))) as zf:
        names = set(zf.namelist())
    assert ".git/HEAD" not in names
    assert ".secrets/token" not in names
    assert "feeds/01-x.xml" in names  # visible files still ship


def test_deploy_site_skipped_without_credentials(tmp_path: Path, capsys) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("http must not be called without credentials")

    assert deploy_site(_cfg(), _site(tmp_path), http_post=boom) is None
    assert "skipped (no DEPLOY_TOKEN / NETLIFY_SITE_ID)" in capsys.readouterr().out


def test_deploy_site_posts_zip_with_auth(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> Any:
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        seen["files"] = kwargs["files"]
        return _FakeResponse({"ssl_url": "https://signalflow.netlify.app", "url": "https://x.netlify.app"})

    result = deploy_site(_cfg(deploy_token="t-secret", netlify_site_id="site-42"), _site(tmp_path), http_post=fake_post)

    assert seen["url"] == DEPLOY_URL.format(site_id="site-42")
    assert seen["headers"] == {"Authorization": "Bearer t-secret"}
    assert "files.zip" in seen["files"]
    assert result == {"ssl_url": "https://signalflow.netlify.app", "url": "https://x.netlify.app"}


def test_deploy_site_propagates_http_errors(tmp_path: Path) -> None:
    def failing_post(url: str, **kwargs: Any) -> Any:
        return _FakeResponse({}, status=401)

    with pytest.raises(requests.HTTPError):
        deploy_site(_cfg(deploy_token="t", netlify_site_id="s"), _site(tmp_path), http_post=failing_post)


def test_deploy_site_refuses_placeholder_base_url(tmp_path: Path, capsys) -> None:
    """Publishing with the default SITE_BASE_URL placeholder would ship broken
    absolute URLs (FR-7: 'reachable at a public URL') — refuse instead."""

    def boom(url: str, **kwargs: Any) -> Any:
        raise AssertionError("http must not be called with the placeholder base URL")

    assert (
        deploy_site(
            _cfg(deploy_token="t", netlify_site_id="s", site_base_url="https://signalflow.local"),
            _site(tmp_path),
            http_post=boom,
        )
        is None
    )
    assert "placeholder" in capsys.readouterr().out
