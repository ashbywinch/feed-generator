#!/usr/bin/env python3
"""Which topics run each night (the two-topics-per-night rotation).

13 topics, 2 per night x 7 nights = 14 slots -> Mon-Sat run 2, Sunday runs 1.
FIXED weekly schedule (no week-offset): every topic has a fixed weekday slot.
That is what guarantees ANY 7 consecutive days cover every topic at least
once — the property that makes the rotation the self-healing recovery path
(a missed run leaves topics stale; the next week's slots re-cover everything).

Run: python spikes/topic_rotation.py [--date YYYY-MM-DD] [--csv]
     (default: today; --csv emits one comma-separated line for the workflow)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from signalflow.topics import load_topics  # noqa: E402

PAIRS_PER_NIGHT = 2


def rotation_for(day: date, topics: list[str]) -> list[str]:
    """The 1-2 topics scheduled for `day`. Deterministic; fixed per weekday.

    Sorted topic names are chunked Mon-Sat into pairs and Sunday takes the
    final single topic. Any 7 consecutive days therefore cover all topics.
    """
    names = sorted(topics)
    n = len(names)
    day_index = day.weekday()  # 0 = Monday .. 6 = Sunday
    start = day_index * PAIRS_PER_NIGHT
    end = min(start + PAIRS_PER_NIGHT, n)
    return names[start:end]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    day = date.today()
    csv = False
    i = 0
    while i < len(args):
        if args[i] == "--date":
            i += 1
            if i >= len(args):
                print("usage: topic_rotation.py [--date YYYY-MM-DD] [--csv]")
                return 2
            try:
                day = date.fromisoformat(args[i])
            except ValueError:
                print("usage: topic_rotation.py [--date YYYY-MM-DD] [--csv]")
                return 2
        elif args[i] == "--csv":
            csv = True
        else:
            print("usage: topic_rotation.py [--date YYYY-MM-DD] [--csv]")
            return 2
        i += 1

    names = [t["name"] for t in load_topics()]
    picks = rotation_for(day, names)
    if csv:
        print(",".join(picks))
    else:
        print("\n".join(picks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
