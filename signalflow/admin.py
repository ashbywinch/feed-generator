"""Admin status page: rendered from the runner's run records.

Reads spikes/state/runs/{ts}.json (newest first; latest.json is a mirror and
is skipped) and renders site/admin/index.html: per-run rotation subset, fresh
skips, per-topic status (ok/failed, picks, story version, verdict count, list
status) with error + traceback excerpts. Pure rendering — no network, no LLM,
every value HTML-escaped (records carry model-generated and error text).

Run: make admin  (spikes/build_admin.py)
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

LATEST_NAME = "latest.json"  # mirror of the newest run record — never rendered twice


def _load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """Timestamped run records, newest first. Corrupt records are skipped with
    a warning (one bad night must not blank the whole page)."""
    if not runs_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True):
        if path.name == LATEST_NAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"      admin: skipping corrupt run record {path.name} ({exc})")
            continue
        if isinstance(data, dict):
            runs.append(data)
    return runs


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _render_results(results: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for r in results:
        status = "ok" if r.get("ok") else "FAILED"
        rows.append(
            "<tr>"
            f"<td>{_esc(r.get('topic'))}</td>"
            f"<td>{_esc(r.get('slug'))}</td>"
            f"<td>{status}</td>"
            f"<td>{_esc(r.get('picked'))}</td>"
            f"<td>v{_esc(r.get('story_version'))}</td>"
            f"<td>{_esc(r.get('verdicts'))}</td>"
            f"<td>{_esc(r.get('list'))}</td>"
            "</tr>"
        )
        if r.get("error"):
            rows.append(f"<tr><td colspan='7' class='error'>{_esc(r.get('error'))}</td></tr>")
        for pick in r.get("picks", []) or []:
            title = _esc(pick.get("title") if isinstance(pick, dict) else "")
            url = _esc(pick.get("url") if isinstance(pick, dict) else "")
            reason = _esc(pick.get("reason") if isinstance(pick, dict) else "")
            rows.append(
                "<tr class='pick'><td colspan='7'>"
                f"&#8627; <a href='{url}'>{title}</a>"
                f"{' — ' + reason if reason else ''}"
                "</td></tr>"
            )
        if r.get("traceback"):
            rows.append(f"<tr><td colspan='7'><pre>{_esc(r.get('traceback'))}</pre></td></tr>")
    return "\n".join(rows) or "<tr><td colspan='7'>no topics ran</td></tr>"


def _render_run(run: dict[str, Any]) -> str:
    ts = _esc(run.get("ts"))
    topics = _esc(", ".join(run.get("weekly_topics") or []) or "all stale topics")
    fresh = _esc(", ".join(f.get("topic", "") for f in run.get("fresh", []) or []))
    summary = run.get("summary") or {}
    summary_line = (
        f"{_esc(summary.get('ok'))} ok / {_esc(summary.get('failed'))} failed (of {_esc(summary.get('total'))})"
    )
    fresh_line = f"<p>fresh (skipped): {fresh}</p>" if fresh else ""
    return (
        f"<section class='run'>"
        f"<h2>{ts}</h2>"
        f"<p>rotation: {topics} &mdash; {summary_line}</p>"
        f"{fresh_line}"
        f"<table><tr><th>topic</th><th>slug</th><th>status</th><th>picks</th>"
        f"<th>story</th><th>verdicts</th><th>list</th></tr>"
        f"{_render_results(run.get('results', []) or [])}"
        f"</table></section>"
    )


def render_admin(runs_dir: Path) -> str:
    """Render the admin page HTML from the run records (empty state included)."""
    runs = _load_runs(runs_dir)
    sections = "\n".join(_render_run(run) for run in runs)
    if not sections:
        sections = (
            "<p>No runs yet — the nightly job has not produced a run record. "
            "Run <code>make spike-weekly-all</code> locally or wait for the "
            "GitHub Actions schedule.</p>"
        )
    return (
        "<!doctype html>"
        "<html lang='en'><head><meta charset='utf-8'>"
        "<title>SignalFlow — nightly runs</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}"
        "h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem}"
        "table{border-collapse:collapse;width:100%} td,th{border:1px solid #ccc;padding:.3rem .5rem;"
        "text-align:left;font-size:.9rem}"
        ".error{color:#b00020} pre{background:#f4f4f4;padding:.5rem;overflow-x:auto;font-size:.8rem}"
        "tr.pick td{color:#444;font-size:.85rem}"
        "</style></head><body>"
        "<h1>SignalFlow — nightly runs</h1>"
        f"{sections}"
        "</body></html>"
    )
