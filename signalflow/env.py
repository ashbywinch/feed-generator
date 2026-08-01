"""Environment loading for SignalFlow.

Keys live only in the project `.env` (gitignored) or the process environment.
Never print, log, or commit key values.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """Load `.env` into the environment; existing env vars win."""
    load_dotenv(path or PROJECT_ROOT / ".env", override=False)
