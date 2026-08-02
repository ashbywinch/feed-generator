#!/usr/bin/env python3
"""Diagnose topic-model quality: folder x topic scatter + composition.

Reuses the spike's cached state (samples/embeddings) and clustering, then
cross-tabs OPML folders against the k-means topics so we can see what got
scattered (e.g. the Energy and Economy folder) and what a grab-bag topic
actually contains.

Run: .venv/bin/python spikes/diagnose_topics.py
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from topic_elicitation_resumable import (  # noqa: E402  # pyright: ignore[reportImplicitRelativeImport]
    OPML_PATH,
    load_embeddings,
    load_samples,
    parse_opml,
    spherical_kmeans,
)

feeds = parse_opml(OPML_PATH)
samples = load_samples()
emb = load_embeddings()

ok = [f for f in feeds if samples.get(f["url"], {}).get("items")]
for f in ok:
    f["items"] = samples[f["url"]]["items"]

# Apply the spike's integrity exclusions (persisted by the main pipeline).
integrity_path = Path(__file__).resolve().parent / "state" / "integrity.json"
flagged = {}
if integrity_path.exists():
    with contextlib.suppress(json.JSONDecodeError):
        flagged = json.loads(integrity_path.read_text(encoding="utf-8")).get("flagged", {})
if flagged:
    ok = [f for f in ok if f["url"] not in flagged]
    print(f"excluding {len(flagged)} integrity-flagged feeds -> {len(ok)} remain")

topic_k = max(24, min(45, round(len(ok) / 5)))
topic_k = int(__import__("os").environ.get("TOPIC_K", topic_k))
item_texts: list[str] = [item for f in ok for item in f["items"]] + [f["title"] for f in ok]
labels = spherical_kmeans([emb[t] for t in item_texts], topic_k)

idx = 0
frag_labels: dict[int, list[int]] = {}
for f in ok:
    frag_labels[id(f)] = labels[idx : idx + len(f["items"]) + 1]
    idx += len(f["items"]) + 1
topic_map: dict[int, list[dict[str, Any]]] = {}
for f in ok:
    votes = frag_labels[id(f)]
    best = max(set(votes), key=votes.count)
    topic_map.setdefault(best, []).append(f)

print(f"k={topic_k} -> {len(topic_map)} topics, {len(ok)} feeds")
print("\n== folder x topic (feed counts) ==")
folder_topics: dict[str, Counter[int]] = defaultdict(Counter)
for label, feeds_in in topic_map.items():
    for f in feeds_in:
        folder_topics[f["folder"]][label] += 1
for folder in sorted(folder_topics):
    counts = folder_topics[folder]
    total = sum(counts.values())
    top = counts.most_common(3)
    sizes = {label: len(topic_map[label]) for label in counts}
    detail = ", ".join(f"topic#{label} ({n}/{sizes[label]})" for label, n in top)
    spread = "SCATTERED" if len(counts) >= 5 else ""
    print(f"  {folder:<22} {total:>3} feeds -> {detail} {spread}")

print("\n== singleton topics ==")
for label, feeds_in in sorted(topic_map.items()):
    if len(feeds_in) == 1:
        print(f"  topic#{label}: {feeds_in[0]['title']}  [{feeds_in[0]['folder']}]")

big = max(topic_map, key=lambda label: len(topic_map[label]))
print(f"\n== largest topic (topic#{big}, {len(topic_map[big])} feeds) folder mix ==")
mix = Counter(f["folder"] for f in topic_map[big])
for folder, n in mix.most_common():
    print(f"  {folder}: {n}")
