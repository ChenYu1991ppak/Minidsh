"""CLI 装配：``minidsh``（TUI）· ``minidsh replay`` · ``minidsh plugin``。

对应源码：packages/boot 的命令装配 + ch03 的 replay 语义。

- ``minidsh [dir] [--storage jsonl|sqlite] [--profile ...]``
  ``dir`` 缺省 = 当前工作目录；**无子命令直接启动交互式 TUI**（参考 Claude Code TUI）。
- ``minidsh replay <path> [--session-id ID]``
  从 jsonl/sqlite 重放会话时间线。
- ``minidsh plugin ...``
  安装/卸载/列举插件。

无 ``run`` 子命令——``replay``/``plugin`` 是仅有的两个子命令，其余一律走 TUI。
配置管理不设子命令：模型与 harness 设置分别手写 ``models.json`` / ``settings.json``。
"""
from __future__ import annotations

import argparse
import os
import sys

from .loader import load_project
from ...packages.services.session.reporting import replay_session, load_session_events

__all__ = ["main"]

# 仅有的两个子命令；其余 argv 一律按 TUI 的位置参数 dir 处理。
_SUBCOMMANDS = ("replay", "plugin")


def build_parser() -> argparse.ArgumentParser:
    """replay / plugin 子命令解析器。"""
    parser = argparse.ArgumentParser(
        prog="minidsh", description="最小化 DeepSeek Harness（dsh）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="重放一个会话的时间线")
    replay.add_argument("path", help="jsonl 文件 / 含 sessions 或 sessions.db 的目录")
    replay.add_argument("--session-id", default=None, help="sqlite/目录来源时必填")

    plugin = sub.add_parser("plugin", help="安装/卸载/列举插件")
    plugin_sub = plugin.add_subparsers(dest="plugin_action", required=True)
    p_add = plugin_sub.add_parser("add", help="安装一个插件包并记入用户 profile")
    p_add.add_argument("pkg", help="pip 可解析的 spec（本地路径/git+/已发布包名）")
    p_rm = plugin_sub.add_parser("remove", help="从用户 profile 移除插件名")
    p_rm.add_argument("name", help="插件名")
    plugin_sub.add_parser("ls", help="列出发现到的插件 + 激活状态")

    return parser


def _build_tui_parser() -> argparse.ArgumentParser:
    """TUI 专用解析：``minidsh [dir] [--storage ...] [--profile ...]``。"""
    parser = argparse.ArgumentParser(
        prog="minidsh", description="最小化 DeepSeek Harness（dsh）"
    )
    parser.add_argument("dir", nargs="?", default=None, help="项目目录路径（缺省=当前目录）")
    parser.add_argument("--storage", choices=["jsonl", "sqlite"], default=None, help="持久化后端")
    parser.add_argument("--profile", default=None, help="profile 名或文件路径（名字=选，路径=覆盖）")
    parser.add_argument("--session", default=None, help="恢复指定 session_id（从持久化后端加载事件续聊）")
    return parser


# ---------- TUI ----------


def _cmd_tui(args) -> int:
    from pathlib import Path as _Path

    project_dir = args.dir or os.getcwd()

    # --profile 合一：文件存在 → 当 argv 覆盖路径；否则 → 当命名 profile 名
    profile_arg = args.profile
    argv_path = profile_arg if (profile_arg and _Path(profile_arg).exists()) else None
    profile_name = None if argv_path else profile_arg

    ctx = load_project(
        project_dir,
        storage=args.storage,
        profile=profile_name,
        argv_path=argv_path,
    )
    loop = ctx.probe("agent_loop")
    session_id = getattr(args, "session", None)
    if session_id:
        agent = _resume_agent(ctx, loop, session_id)
        if agent is None:
            return 1
    else:
        agent = loop.create()
    return _launch_tui_app(ctx, agent)


def _resume_agent(ctx, loop, session_id: str):
    """从持久化后端加载 session_id 的事件，恢复 agent；失败返回 None。"""
    backend = getattr(ctx, "_persistence_backend", None)
    if backend is None:
        print(f"[minidsh] 无持久化后端，无法恢复会话 {session_id!r}", file=sys.stderr)
        return None
    events = backend.load_stored(session_id)
    if not events:
        print(f"[minidsh] 会话 {session_id!r} 不存在或无事件", file=sys.stderr)
        return None
    return loop.resume(session_id, events=events)


def _launch_tui_app(ctx, agent) -> int:
    """装配 TuiApp 并进入交互循环（测试可 monkeypatch 此孤立的启动入口）。"""
    from ...infrastructure.tui.app import TuiApp

    TuiApp(ctx, agent).run()
    return 0


# ---------- replay ----------


def _cmd_replay(args) -> int:
    events = load_session_events(args.path, session_id=args.session_id)
    if not events:
        print("（无事件）", file=sys.stderr)
        return 0
    print(replay_session(events))
    return 0


# ---------- plugin ----------


def _cmd_plugin(args) -> int:
    from ..packaging import plugin_add, plugin_remove, plugin_list

    if args.plugin_action == "add":
        return plugin_add(args.pkg)
    if args.plugin_action == "remove":
        return plugin_remove(args.name)
    if args.plugin_action == "ls":
        return plugin_list()
    return 2


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _SUBCOMMANDS:
        args = build_parser().parse_args(argv)
        if args.command == "replay":
            return _cmd_replay(args)
        if args.command == "plugin":
            return _cmd_plugin(args)
        return 2
    # 缺省：一律走 TUI（dir 是可选的第一个位置参数；无 `run` 子命令，历史命令不保留）
    return _cmd_tui(_build_tui_parser().parse_args(argv))