"""CLI 装配：``minidsh run`` / ``minidsh replay``。

对应源码：packages/boot 的命令装配 + ch03 的 replay 语义。

- ``minidsh run [--storage jsonl|sqlite] <dir>``
  加载项目（配置来自 models.json + settings.json），进入 loop 持续执行。
- ``minidsh replay <path> [--session-id ID]``
  从 jsonl/sqlite 重放会话时间线。

配置管理不设子命令：模型与 harness 设置分别手写 ``models.json`` / ``settings.json``。
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .loader import load_project
from ...capabilities.session.reporting import replay_session, load_session_events

__all__ = ["main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minidsh", description="最小化 DeepSeek Harness（dsh）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="加载项目目录并进入 loop")
    run.add_argument("dir", help="项目目录路径")
    run.add_argument("--storage", choices=["jsonl", "sqlite"], default=None, help="持久化后端")
    run.add_argument("--profile", default=None, help="profile 名或文件路径（名字=选，路径=覆盖）")

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


# ---------- run ----------


async def _run_repl(ctx) -> None:
    """读 stdin 逐行作为用户消息驱动 loop。

    读到 ``exit`` / ``quit`` 或 EOF（Ctrl-D）即结束。退出即 flush，会话落盘完整。
    """
    loop = ctx.probe("agent_loop")
    agent = loop.create()

    prompt = "> " if sys.stdin.isatty() else ""
    try:
        for line in sys.stdin:
            text = line.rstrip("\n")
            if text.strip().lower() in ("exit", "quit"):
                break
            if text.strip() == "":
                continue
            if prompt:
                print(prompt, end="", file=sys.stderr)
            agent.send(text)
            await agent.run()
    finally:
        # 落盘屏障：确保缓冲全部写盘（尤其无 trailing assistant-message 的会话）
        ctx.emit("session/flush", agent.session.id)
        backend = getattr(ctx, "_persistence_backend", None)
        if backend is not None and hasattr(backend, "close"):
            backend.close()


def _cmd_run(args) -> int:
    from pathlib import Path as _Path

    # --profile 合一：文件存在 → 当 argv 覆盖路径；否则 → 当命名 profile 名
    profile_arg = args.profile
    argv_path = profile_arg if (profile_arg and _Path(profile_arg).exists()) else None
    profile_name = None if argv_path else profile_arg

    ctx = load_project(
        args.dir,
        storage=args.storage,
        profile=profile_name,
        argv_path=argv_path,
    )
    asyncio.run(_run_repl(ctx))
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "plugin":
        return _cmd_plugin(args)
    parser.error(f"未知命令：{args.command}")
    return 2