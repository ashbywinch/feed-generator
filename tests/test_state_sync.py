"""R2 state sync: thin rclone wrapper — env mapping, data-only filter, command
shape. rclone itself is an ops binary and is never invoked in tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "spikes" / "state"


def _load() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("state_sync", ROOT / "spikes" / "state_sync.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = _load()


class _FakeResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _set_creds(monkeypatch: Any) -> None:
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_ENDPOINT", "https://acc.r2.cloudflarestorage.com")


def test_rclone_env_none_without_credentials(monkeypatch: Any) -> None:
    for var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    assert ss.rclone_env() is None


def test_rclone_env_maps_to_rclone_config(monkeypatch: Any) -> None:
    _set_creds(monkeypatch)
    monkeypatch.setenv("R2_BUCKET", "my-bucket")
    env = ss.rclone_env()
    assert env is not None
    assert env["RCLONE_CONFIG_R2_TYPE"] == "s3"
    assert env["RCLONE_CONFIG_R2_PROVIDER"] == "Cloudflare"
    assert env["RCLONE_CONFIG_R2_ACCESS_KEY_ID"] == "ak"
    assert env["RCLONE_CONFIG_R2_SECRET_ACCESS_KEY"] == "sk"
    assert env["RCLONE_CONFIG_R2_ENDPOINT"] == "https://acc.r2.cloudflarestorage.com"
    assert env["R2_BUCKET"] == "my-bucket"  # surfaced for the sync command


def test_rclone_env_default_bucket(monkeypatch: Any) -> None:
    _set_creds(monkeypatch)
    assert ss.rclone_env()["R2_BUCKET"] == "signalflow-state"


def test_state_filter_whitelists_data_files_only() -> None:
    flt = ss.state_filter()
    assert flt[0::2] == ["--filter"] * (len(flt) // 2)
    included = {flt[i + 1] for i in range(0, len(flt), 2)}
    assert "+ weekly_feeds.jsonl" in included
    assert "+ weekly_verdicts.jsonl" in included
    assert "+ weekly_picks.jsonl" in included
    assert "+ stories/**" in included
    assert "+ picks/**" in included
    assert "+ runs/**" in included
    assert "- *" in included  # everything else (logs, pids, scratch) stays out
    assert not any(pat.endswith((".log", ".pid")) for pat in included)


def test_sync_pull_builds_rclone_command(monkeypatch: Any, capsys: Any) -> None:
    _set_creds(monkeypatch)
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> _FakeResult:
        seen["args"] = args
        seen["env"] = kwargs["env"]
        return _FakeResult(0)

    assert ss.sync("pull", run=fake_run) == 0
    assert seen["args"][:3] == ["rclone", "sync", "r2:signalflow-state"]
    assert seen["args"][3] == str(STATE_DIR)
    assert seen["args"][4:] == ss.state_filter()
    assert seen["env"]["RCLONE_CONFIG_R2_TYPE"] == "s3"  # rclone config passed through


def test_sync_push_reverses_arguments(monkeypatch: Any) -> None:
    _set_creds(monkeypatch)
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> _FakeResult:
        seen["args"] = args
        return _FakeResult(0)

    assert ss.sync("push", run=fake_run) == 0
    assert seen["args"][2:4] == [str(STATE_DIR), "r2:signalflow-state"]


def test_sync_skipped_without_credentials(monkeypatch: Any, capsys: Any) -> None:
    for var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no rclone without credentials")

    assert ss.sync("pull", run=boom) == 0
    assert "local-only" in capsys.readouterr().out


def test_sync_missing_rclone_binary(monkeypatch: Any, capsys: Any) -> None:
    _set_creds(monkeypatch)

    def missing(args: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError("rclone")

    assert ss.sync("pull", run=missing) == 1
    assert "rclone not installed" in capsys.readouterr().out


def test_sync_propagates_rclone_failure(monkeypatch: Any, capsys: Any) -> None:
    _set_creds(monkeypatch)
    assert ss.sync("push", run=lambda args, **kw: _FakeResult(2)) == 1
    assert "failed (exit 2)" in capsys.readouterr().out


def test_sync_rejects_unknown_direction(monkeypatch: Any, capsys: Any) -> None:
    _set_creds(monkeypatch)
    assert ss.sync("sideways", run=lambda args, **kw: _FakeResult(0)) == 1
    assert "unknown direction" in capsys.readouterr().out


def test_main_usage(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    _set_creds(monkeypatch)
    assert ss.main(["bogus"]) == 2
    assert "usage" in capsys.readouterr().out
    assert ss.main([]) == 2
