"""Topic rotation: which topics run each night (deterministic, no network/LLM).

13 topics, 2 per night x 7 nights = 14 slots -> Mon-Sat run 2, Sunday runs 1.
Fixed weekly schedule (no week-offset): each topic has a fixed weekday slot,
which is what guarantees ANY 7 consecutive days cover every topic at least
once — the property that makes the rotation the self-healing recovery path.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_spike(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "spikes" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load spike {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tr = _load_spike("topic_rotation")

TOPICS = [
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "Juliett",
    "Kilo",
    "Lima",
    "Mike",  # 13 topics
]

MON = date(2026, 8, 3)  # a Monday


def test_every_topic_exactly_once_per_week() -> None:
    week = [MON + timedelta(days=i) for i in range(7)]
    seen = [t for d in week for t in tr.rotation_for(d, TOPICS)]
    assert sorted(seen) == sorted(TOPICS)
    assert len(seen) == 13


def test_two_per_night_until_sunday_solo() -> None:
    for i in range(6):  # Mon-Sat
        assert len(tr.rotation_for(MON + timedelta(days=i), TOPICS)) == 2
    assert len(tr.rotation_for(MON + timedelta(days=6), TOPICS)) == 1  # Sunday


def test_any_seven_consecutive_days_cover_all_topics() -> None:
    for offset in range(7):  # every possible window start weekday
        window = [MON + timedelta(days=offset + i) for i in range(7)]
        covered = {t for d in window for t in tr.rotation_for(d, TOPICS)}
        assert covered == set(TOPICS)


def test_rotation_is_deterministic() -> None:
    assert tr.rotation_for(MON, TOPICS) == tr.rotation_for(MON, TOPICS)
    assert tr.rotation_for(MON, TOPICS) == tr.rotation_for(MON - timedelta(days=7), TOPICS)  # same weekday


def test_schedule_repeats_weekly() -> None:
    # Same weekday in consecutive weeks picks the same topics (fixed schedule).
    assert tr.rotation_for(MON, TOPICS) == tr.rotation_for(MON + timedelta(days=7), TOPICS)


def test_cli_prints_tonight_topics(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(tr, "load_topics", lambda: [{"name": n} for n in TOPICS])
    assert tr.main(["--date", MON.isoformat()]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert sorted(out) == sorted(tr.rotation_for(MON, TOPICS))
    assert len(out) == 2


def test_cli_csv_format(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(tr, "load_topics", lambda: [{"name": n} for n in TOPICS])
    assert tr.main(["--date", MON.isoformat(), "--csv"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == ",".join(tr.rotation_for(MON, TOPICS))


def test_cli_bad_date_exits_nonzero(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(tr, "load_topics", lambda: [{"name": n} for n in TOPICS])
    assert tr.main(["--date", "not-a-date"]) == 2
    assert "usage" in capsys.readouterr().out.lower()
