"""Digest: valid RSS, two bullets per entry, atomic replace, entry ids."""

from dataclasses import replace

import feedparser

from signalflow.digest import build_digest, publish
from signalflow.models import Analysis, ApprovedEvent, Candidate


def _events():
    def ev(url: str, topic: str, title: str, event: str, thesis: str) -> ApprovedEvent:
        cand = Candidate(title=title, summary="s", url=url, source_tier="search", topic=topic)
        analysis = Analysis(approved=True, topic=topic, empirical_event=event, core_thesis=thesis)
        return ApprovedEvent(candidate=cand, analysis=analysis)

    return [
        ev("https://a.example/1", "Energy", "Big thing", "Grid milestone reached", "Thesis one"),
        ev("https://a.example/2", "Maritime", "Other thing", "Port shift observed", "Thesis two"),
    ]


def test_digest_is_valid_rss_with_two_bullets(cfg, tmp_path):
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert out.exists()
    parsed = feedparser.parse(str(out))
    assert len(parsed.entries) == 2
    energy = next(e for e in parsed.entries if e.title.startswith("[Energy]"))  # order not guaranteed
    desc = energy.description
    assert "Grid milestone reached" in desc  # observed event bullet
    assert "Thesis one" in desc  # systemic thesis bullet
    assert any(link.href == "https://a.example/1" for link in energy.links)


def test_digest_atomic_no_temp_left(cfg, tmp_path):
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert not (tmp_path / "signalflow_digest.xml.tmp").exists()


def test_digest_relative_path_branch(cfg, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # out_path under cwd -> relative_to() succeeds
    out = tmp_path / "signalflow_digest.xml"
    build_digest(cfg, _events(), out)
    assert out.exists()


def test_publish_skipped_without_credentials(cfg, tmp_path, capsys):
    publish(cfg, tmp_path / "signalflow_digest.xml")
    assert "skipped (no CF_API_TOKEN / CF_ACCOUNT_ID / CF_PROJECT)" in capsys.readouterr().out


def test_publish_copies_digest_into_site_and_deploys(cfg, tmp_path, capsys):
    """FR-7 publish: the digest lands in the site directory and the site is
    deployed through the CF adapter (fake deploy_fn records the call)."""
    digest = tmp_path / "signalflow_digest.xml"
    digest.write_text("<digest/>", encoding="utf-8")
    site_dir = tmp_path / "site"
    seen: dict[str, object] = {}

    def fake_deploy(cfg_, site):
        seen["cfg"] = cfg_
        seen["site_dir"] = site
        return {"url": "https://signalflow.pages.dev"}

    publish(
        replace(cfg, cf_api_token="t", cf_account_id="a", cf_project="p"),
        digest,
        site_dir=site_dir,
        deploy_fn=fake_deploy,
    )

    assert seen["site_dir"] == site_dir
    assert (site_dir / "signalflow_digest.xml").read_text(encoding="utf-8") == "<digest/>"
    assert "live at https://signalflow.pages.dev" in capsys.readouterr().out


def test_publish_creates_site_dir_and_leaves_no_temp(cfg, tmp_path):
    """A first-ever publish has no site dir yet — it is created; the copy is
    atomic (no .tmp left behind), and a deploy refusal (e.g. placeholder URL)
    is not a crash."""
    digest = tmp_path / "signalflow_digest.xml"
    digest.write_text("<digest/>", encoding="utf-8")
    site_dir = tmp_path / "site"

    def fake_deploy(cfg_, site):
        return None  # deploy adapter refused (placeholder SITE_BASE_URL)

    publish(
        replace(cfg, cf_api_token="t", cf_account_id="a", cf_project="p"),
        digest,
        site_dir=site_dir,
        deploy_fn=fake_deploy,
    )
    assert (site_dir / "signalflow_digest.xml").read_text(encoding="utf-8") == "<digest/>"
    assert not (site_dir / "signalflow_digest.xml.tmp").exists()
