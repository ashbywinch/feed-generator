"""Admin page: rendered from spikes/state/runs/ run records — pure rendering,
every value escaped (run records carry model-generated + error text)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalflow.admin import render_admin


def _write_run(runs_dir: Path, ts: str, **fields: Any) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": ts,
        "weekly_topics": None,
        "fresh": [],
        "results": [],
        "summary": {"total": 0, "ok": 0, "failed": 0},
    }
    record.update(fields)
    (runs_dir / f"{ts.replace(':', '-')}.json").write_text(json.dumps(record), encoding="utf-8")


def _ok_result(**kw: Any) -> dict[str, Any]:
    base = {
        "slug": "01-a",
        "topic": "Topic A",
        "ok": True,
        "picked": 2,
        "picks": [],
        "generated_sources": False,
        "sources_approved": False,
        "story_version": 3,
        "verdicts": 7,
        "list": "present",
        "error": "",
        "traceback": "",
    }
    base.update(kw)
    return base


def test_render_admin_empty_state(tmp_path: Path) -> None:
    html = render_admin(tmp_path / "runs")
    assert "No runs yet" in html


def test_render_admin_lists_runs_newest_first(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "2026-08-03T06:00:00+00:00", results=[_ok_result(slug="01-a", topic="Older")])
    _write_run(tmp_path / "runs", "2026-08-04T06:00:00+00:00", results=[_ok_result(slug="01-a", topic="Newer")])
    html = render_admin(tmp_path / "runs")
    assert html.index("2026-08-04") < html.index("2026-08-03")


def test_render_admin_skips_latest_duplicate(tmp_path: Path) -> None:
    """latest.json mirrors the newest {ts}.json — rendering must not show it twice."""
    runs = tmp_path / "runs"
    _write_run(runs, "2026-08-04T06:00:00+00:00", results=[_ok_result(topic="Only Run")])
    (runs / "latest.json").write_text(json.dumps({"ts": "2026-08-04T06:00:00+00:00"}), encoding="utf-8")
    html = render_admin(runs)
    assert html.count("Only Run") == 1


def test_render_admin_escapes_all_values(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "runs",
        "2026-08-04T06:00:00+00:00",
        results=[
            _ok_result(
                ok=False,
                topic="<script>alert('t')</script>",
                error="<script>alert('e')</script>",
                traceback="<b>traceback</b> & more",
            )
        ],
    )
    html = render_admin(tmp_path / "runs")
    assert "<script>alert('t')</script>" not in html
    assert "<script>alert('e')</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>traceback</b>" not in html
    assert "&lt;b&gt;traceback&lt;/b&gt;" in html


def test_render_admin_shows_failure_details(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "runs",
        "2026-08-04T06:00:00+00:00",
        results=[
            _ok_result(ok=True, topic="Good Topic", picked=4),
            _ok_result(
                ok=False,
                slug="02-b",
                topic="Broken Topic",
                error="router exploded",
                traceback="Traceback (most recent call last):\nRuntimeError: router exploded",
            ),
        ],
    )
    html = render_admin(tmp_path / "runs")
    assert "Good Topic" in html and "Broken Topic" in html
    assert "router exploded" in html
    assert "RuntimeError: router exploded" in html  # traceback excerpt visible


def test_render_admin_shows_rotation_fresh_and_summary(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "runs",
        "2026-08-04T06:00:00+00:00",
        weekly_topics=["Topic A", "Topic B"],
        fresh=[{"topic": "Topic C", "slug": "03-c"}],
        results=[_ok_result(), _ok_result(slug="02-b", topic="Topic B")],
        summary={"total": 2, "ok": 2, "failed": 0},
    )
    html = render_admin(tmp_path / "runs")
    assert "Topic A, Topic B" in html
    assert "Topic C" in html  # fresh skip shown
    assert "2 ok" in html


def test_render_admin_shows_picks(tmp_path: Path) -> None:
    _write_run(
        tmp_path / "runs",
        "2026-08-04T06:00:00+00:00",
        results=[
            _ok_result(picks=[{"title": "Grid milestone", "url": "https://a.example/1", "reason": "why relevant"}])
        ],
    )
    html = render_admin(tmp_path / "runs")
    assert "Grid milestone" in html
    assert "https://a.example/1" in html
    assert "why relevant" in html


def test_render_admin_survives_corrupt_record(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "2026-08-04T06-00-00+00-00.json").write_text("{not json", encoding="utf-8")
    _write_run(runs, "2026-08-03T06:00:00+00:00", results=[_ok_result(topic="Clean Run")])
    html = render_admin(runs)  # corrupt record skipped, clean one still renders
    assert "Clean Run" in html
