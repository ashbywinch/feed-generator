#!/usr/bin/env python3
"""Grounded feed descriptions for the topic-model walkthrough.

For every feed in the current model (topics, singletons, ambiguous), fetch
recent items and write spikes/output/feed_descriptions.md — so topic
decisions are made on real content, not titles. Reusable as the model
changes: re-run after any re-clustering.

Run: .venv/bin/python spikes/describe_feeds.py
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import topic_elicitation_resumable as s  # noqa: E402

STATE = s.STATE_DIR
OUT = s.OUT_DIR / "feed_descriptions.md"

samples = {}
for line in (STATE / "samples.jsonl").read_text().splitlines():
    e = json.loads(line)
    samples[e["title"]] = e

assignment = json.loads((STATE / "assignment.json").read_text(encoding="utf-8"))

# Collect every feed mentioned anywhere in the model.
wanted: dict[str, str] = {}  # title -> section tag
for name, info in (assignment.get("topics") or {}).items():
    tag = f"topic: {name}"
    for title in info.get("feeds", []):
        wanted[title] = tag
for f in assignment.get("ambiguous", []):
    wanted.setdefault(f["title"], "ambiguous")
for url, reason in (assignment.get("flagged") or {}).items():
    title = next((t for t, e in samples.items() if e["url"] == url), url)
    wanted.setdefault(title, f"flagged: {reason[:60]}")


def fetch(title: str) -> tuple[str, dict]:
    e = samples.get(title)
    if not e:
        return title, {"url": "?", "folder": "?", "items": [], "error": "not in samples"}
    f = s.sample_feed({"url": e["url"], "title": title, "folder": e.get("folder", "?")})
    return title, {"url": e["url"], "folder": e.get("folder", "?"), "items": f.get("items", []), "error": f.get("error", "")}


results: dict[str, dict] = {}
with ThreadPoolExecutor(max_workers=12) as ex:
    futures = [ex.submit(fetch, t) for t in wanted]
    for fut in as_completed(futures):
        title, info = fut.result()
        results[title] = info

lines = ["# Feed descriptions (grounded — fetched from live feeds)", ""]
for title, tag in sorted(wanted.items(), key=lambda kv: kv[1]):
    info = results[title]
    lines.append(f"## {title}  _[{tag}]_")
    lines.append(f"- url: {info['url']}")
    if info["folder"]:
        lines.append(f"- feedly folder: {info['folder']}")
    if info.get("error"):
        lines.append(f"- fetch error: {info['error']}")
    for item in info["items"]:
        lines.append(f"  - {item}")
    lines.append("")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines))
print(f"described {len(wanted)} feeds -> {OUT.relative_to(s.ROOT)}")
