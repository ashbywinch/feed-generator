#!/usr/bin/env python3
"""Sync spikes/state with the R2 bucket (nightly job state persistence).

Thin wrapper around rclone (an ops binary — never reimplemented here): builds
the RCLONE_CONFIG_R2_* env + data-file filters from the R2_* env vars and runs
`rclone sync` in the right direction. Skips with a message when unconfigured
(local-only). Only the idempotency data files sync — never logs or pid files.

Run: make state-pull   (rclone sync r2:bucket -> spikes/state)
     make state-push   (spikes/state -> r2:bucket)
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "spikes" / "state"

# Idempotency memory only — the files that make re-runs cheap and correct.
# Logs, pid files, and scratch must never leave the runner.
SYNC_FILES = (
    "weekly_feeds.jsonl",
    "weekly_verdicts.jsonl",
    "weekly_picks.jsonl",
    "stories/**",
    "picks/**",
    "runs/**",
)

DEFAULT_BUCKET = "signalflow-state"


def rclone_env() -> dict[str, str] | None:
    """RCLONE_CONFIG_R2_* env from R2_*; None when the credentials are absent."""
    access = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    endpoint = os.environ.get("R2_ENDPOINT", "")
    if not (access and secret and endpoint):
        return None
    return {
        "RCLONE_CONFIG_R2_TYPE": "s3",
        "RCLONE_CONFIG_R2_PROVIDER": "Cloudflare",
        "RCLONE_CONFIG_R2_ACCESS_KEY_ID": access,
        "RCLONE_CONFIG_R2_SECRET_ACCESS_KEY": secret,
        "RCLONE_CONFIG_R2_ENDPOINT": endpoint,
        "RCLONE_CONFIG_R2_REGION": "auto",
        "RCLONE_CONFIG_R2_ACL": "private",
        "R2_BUCKET": os.environ.get("R2_BUCKET", DEFAULT_BUCKET),
    }


def state_filter() -> list[str]:
    """rclone --filter args: whitelist the data files, drop everything else."""
    args: list[str] = []
    for name in SYNC_FILES:
        args += ["--filter", f"+ {name}"]
    args += ["--filter", "- *"]
    return args


def sync(direction: str, *, run: Callable[..., Any] = subprocess.run) -> int:
    """Run rclone sync in the given direction; 0 = done/skipped, 1 = failed."""
    cfg = rclone_env()
    if cfg is None:
        print(
            "      state: no R2 credentials (R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / "
            "R2_ENDPOINT) — local-only, nothing synced"
        )
        return 0
    bucket = cfg["R2_BUCKET"]
    if direction == "pull":
        args = ["rclone", "sync", f"r2:{bucket}", str(STATE_DIR)]
    elif direction == "push":
        args = ["rclone", "sync", str(STATE_DIR), f"r2:{bucket}"]
    else:
        print(f"      state: unknown direction {direction!r} (pull|push)")
        return 1
    args += state_filter()
    try:
        result = run(args, env={**os.environ, **cfg}, check=False)
    except FileNotFoundError:
        print("      state: rclone not installed — install it or the nightly sync is skipped")
        return 1
    if result.returncode != 0:
        print(f"      state: rclone sync {direction} failed (exit {result.returncode})")
        return 1
    print(f"      state: rclone sync {direction} ok ({bucket})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in ("pull", "push"):
        print("usage: state_sync.py pull|push")
        return 2
    return sync(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
