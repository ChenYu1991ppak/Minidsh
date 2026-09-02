"""CLI --profile argv 覆盖层测试：run 子命令接受 --profile（名字=选，路径=覆盖）。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from minidsh.cordis import Context
from minidsh.infrastructure.boot import cli as cli_module
from minidsh.infrastructure.boot.cli import main


def _run_cli(argv, stdin_text=""):
    real_stdin, real_stdout, real_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO(stdin_text)
    out, err = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = out, err
    try:
        code = main(argv)
    finally:
        sys.stdin, sys.stdout, sys.stderr = real_stdin, real_stdout, real_stderr
    return code, out.getvalue(), err.getvalue()


def _fake_ctx():
    ctx = Context()
    ctx.provide("agent_loop", _FakeLoop(ctx))
    ctx._persistence_backend = None
    return ctx


class _FakeSession:
    id = "fake"


class _FakeAgent:
    def __init__(self):
        self.sent = []
        self.session = _FakeSession()

    def send(self, text):
        self.sent.append(text)

    async def run(self):
        pass


class _FakeLoop:
    def __init__(self, ctx):
        self.ctx = ctx
        self.agent = _FakeAgent()

    def create(self):
        return self.agent


def test_run_profile_path_vs_name(tmp_path, monkeypatch):
    """--profile 文件存在 → argv 覆盖路径；不存在 → 命名 profile 名。"""
    captured = {}

    def spy_load(project_dir, *, storage=None, profile=None, argv_path=None, **kw):
        captured.update(profile=profile, argv_path=argv_path)
        return _fake_ctx()

    monkeypatch.setattr(cli_module, "load_project", spy_load)

    # 文件存在 → argv_path
    mine = tmp_path / "mine.yaml"
    mine.write_text("plugins:\n  - x\n", encoding="utf-8")
    _run_cli(["run", "--profile", str(mine), "./demo"], stdin_text="")
    assert captured["argv_path"] == str(mine)
    assert captured["profile"] is None

    # 名字（不存在）→ profile 名
    captured.clear()
    _run_cli(["run", "--profile", "demo", "./demo"], stdin_text="")
    assert captured["profile"] == "demo"
    assert captured["argv_path"] is None


def test_reject_invalid_storage_choice():
    import pytest

    with pytest.raises(SystemExit):
        _run_cli(["run", "--storage", "nope", "./demo"], stdin_text="")


def test_run_repl_loop_break_and_flush(tmp_path, monkeypatch):
    real_ctx = _fake_ctx()
    captured = {}

    def spy_load(project_dir, *, storage=None, profile=None, argv_path=None, **kw):
        captured["loaded"] = True
        return real_ctx

    monkeypatch.setattr(cli_module, "load_project", spy_load)

    code, _, _ = _run_cli(["run", "./demo"], stdin_text="你好\n\nquit\n")
    assert code == 0
    assert captured["loaded"]
    assert real_ctx.probe("agent_loop").agent.sent == ["你好"]


def test_replay_no_events(tmp_path, monkeypatch):
    from minidsh.infrastructure.boot import cli as cli_module
    monkeypatch.setattr(cli_module, "load_session_events", lambda *a, **k: [])

    code, _, err = _run_cli(["replay", str(tmp_path / "none.jsonl")])
    assert code == 0
    assert "无事件" in err


def test_plugin_subcommand_dispatch(monkeypatch):
    calls = {}

    import minidsh.infrastructure.packaging as packaging
    monkeypatch.setattr(packaging, "plugin_add", lambda pkg: calls.update(add=pkg) or 0)
    monkeypatch.setattr(packaging, "plugin_remove", lambda name: calls.update(remove=name) or 0)
    monkeypatch.setattr(packaging, "plugin_list", lambda: calls.update(ls=True) or 0)

    _run_cli(["plugin", "add", "./pkg"])
    _run_cli(["plugin", "remove", "x"])
    _run_cli(["plugin", "ls"])

    assert calls["add"] == "./pkg"
    assert calls["remove"] == "x"
    assert calls["ls"] is True