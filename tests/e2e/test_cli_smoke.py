"""T18 验收测试：CLI 装配 + examples/demo + e2e 冒烟。

用 ``minidsh ... [dir]`` 直接调用（交互面是 TUI，测试经 monkeypatch 隔离 TUI 启动），
配合 monkeypatched stdin/stdout 断言端到端行为。对应 spec S1 / S2 / S3。

LLM 走 openai mock：monkeypatch ``cli.load_project`` 注入假 client（跳过真实 key 与网络）。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import shutil

from minidsh.infrastructure.boot import cli as cli_module
from minidsh.infrastructure.boot.cli import main

from tests.helpers.openai_fake import make_scripted_client


def _run_cli(argv, stdin_text=""):
    """调用 CLI main，捕获 stdout/stderr。"""
    import sys

    real_stdin, real_stdout, real_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO(stdin_text)
    out, err = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = out, err
    try:
        code = main(argv)
    finally:
        sys.stdin, sys.stdout, sys.stderr = real_stdin, real_stdout, real_stderr
    return code, out.getvalue(), err.getvalue()


def _patch_loader(monkeypatch, script=None):
    """把 cli.load_project 换成注入假 llm provider 插件的版本；并用 headless TUI
    测试驱动替代真终端 run（agent 经会话事件折回转录）。"""
    from minidsh.infrastructure.boot import cli as cli_module

    def fake_load(project_dir, *, storage=None, **kw):
        from minidsh.infrastructure.boot.loader import load_project

        import minidsh.packages.services.llm.providers.openai as llm_pg
        from minidsh.packages.services.llm.providers.openai import OpenAILlm
        from tests.helpers.openai_fake import make_scripted_client

        client = make_scripted_client(script if script is not None else [{"text": "回复"}])
        orig_apply = llm_pg.apply

        def fake_apply(ctx):
            OpenAILlm(ctx, client=client, model="fake")  # 构造即注册 ctx.llm

        monkeypatch.setattr(llm_pg, "apply", fake_apply)
        try:
            return load_project(project_dir, storage=storage, quiet=False, **kw)
        finally:
            monkeypatch.setattr(llm_pg, "apply", orig_apply)

    monkeypatch.setattr(cli_module, "load_project", fake_load)
    # TUI 启动换成 headless 驱动：读 stdin 逐行驱动（等价旧 _run_repl），退出 flush，
    # 输出会话转录（Transcript render，不启动真终端）。
    from minidsh.infrastructure.boot.cli import _launch_tui_app

    def fake_launch(ctx, agent):
        from minidsh.infrastructure.tui.transcript import fold
        from minidsh.infrastructure.tui.app import _Transcript

        import asyncio
        import sys as _sys

        async def _drive():
            for line in _sys.stdin:
                text = line.rstrip("\n")
                if text.strip().lower() in ("exit", "quit") or text.strip() == "":
                    continue
                agent.send(text)
                await agent.run()
            # 落盘屏障（等价旧 _run_repl）
            ctx.emit("session/flush", agent.session.id)
            backend = getattr(ctx, "_persistence_backend", None)
            if backend is not None and hasattr(backend, "close"):
                backend.close()

        asyncio.run(_drive())
        turns = fold(agent.session.events())
        _sys.stdout.write(_Transcript().render_turns(turns))
        return 0

    monkeypatch.setattr(cli_module, "_launch_tui_app", fake_launch)


DEMO = Path(__file__).resolve().parents[2] / "examples" / "demo"


def test_run_completes_closed_loop(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    shutil.copytree(DEMO, demo)
    _patch_loader(monkeypatch)

    code, out, err = _run_cli([str(demo)], stdin_text="问候\n")

    assert code == 0, err
    # 转录渲染出 user turn（"### 你"）与 assistant turn（"### assistant"）
    assert "### 你" in out
    assert "### assistant" in out


def test_run_persists_session_jsonl(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    shutil.copytree(DEMO, demo)
    _patch_loader(monkeypatch)

    code, _, _ = _run_cli([str(demo)], stdin_text="你好\n")
    assert code == 0

    sessions_dir = demo / ".dsh" / "sessions"
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    assert len(jsonl_files) >= 1
    types = set()
    for line in jsonl_files[-1].read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            types.add(json.loads(line)["type"])
    assert {"user-message", "assistant-message"} <= types


def test_run_persists_session_sqlite(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    shutil.copytree(DEMO, demo)
    _patch_loader(monkeypatch)

    code, _, _ = _run_cli([str(demo), "--storage", "sqlite"], stdin_text="你好\n")
    assert code == 0
    assert (demo / ".dsh" / "sessions.db").exists()


def test_replay_cli_reads_session(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    shutil.copytree(DEMO, demo)
    _patch_loader(monkeypatch)

    _run_cli([str(demo)], stdin_text="你好\n")

    sessions_dir = demo / ".dsh" / "sessions"
    jsonl_file = list(sessions_dir.glob("*.jsonl"))[0]

    code, out, _ = _run_cli(["replay", str(jsonl_file)])
    assert code == 0
    assert "user-message" in out


def test_demo_project_files_present():
    """examples/demo 三要素齐全（spec S4 的前置）。"""
    assert (DEMO / "AGENTS.md").is_file()
    assert (DEMO / ".minidsh" / "models.json").is_file()
    assert (DEMO / ".minidsh" / "settings.json").is_file()
    assert (DEMO / "skills" / "relay" / "SKILL.md").is_file()
    assert (DEMO / "agents" / "reviewer.md").is_file()