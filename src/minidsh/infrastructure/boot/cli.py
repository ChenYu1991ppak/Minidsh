"""CLI 装配：通用 launcher（对齐官方 dsh --profile <name>）。

launcher 只解析自己的 flag（``--profile`` / ``--patch`` / ``--storage`` / ``--session``），
第一个不认识的 token 起原样传给 app 插件——app 形态（TUI / ACP / headless）由
profile/插件决定，不硬编码启动入口。

- ``minidsh [--profile <name>] [--patch <file>...] [--storage jsonl|sqlite] [--session <id>] [dir] [app-args...]``
  拣选 app 插件（plugins 名单里 ``minidsh.app-`` 前缀者）并调用其 ``apply(ctx, args)``。
- ``minidsh replay <path> [--session-id ID]``  从 jsonl 重放会话时间线（纯数据读取，不经 app 插件）。
- ``minidsh plugin add|remove|ls ...``          安装/卸载/列举插件。

``--profile``：文件存在 → 当 argv 覆盖路径；否则 → 当命名 profile 名（~/.minidsh/profiles/<n>.yaml）。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .loader import load_project
from .app_plugin import find_app_plugin
from ...packages.services.session.reporting import replay_session, load_session_events

__all__ = ["main"]

# 仅有的两个子命令；其余 argv 一律按通用 launcher 处理。
_SUBCOMMANDS = ("replay", "plugin")

# 持久化后端白名单（--storage 校验）
_STORAGE_CHOICES = ("jsonl", "sqlite")


@dataclass
class BootArgs:
    """launcher 自有 flag 的解析结果 + 剩余 app-args。"""

    dir: str | None = None
    profile: str | None = None
    patch: list[str] = field(default_factory=list)
    storage: str | None = None
    session: str | None = None
    app_args: list[str] = field(default_factory=list)


def _parse_boot(argv: list[str]) -> BootArgs:
    """解析 launcher 自有 flag；第一个不认识的 token 起全部归 app_args。

    ``dir`` 是位置参数（项目目录）；放在 flag 之前或之后均可（只要不被 app 插件
    抢占）。约定：最后一个未被 flag 消费的 bare token 若在 app_args 之前则是 dir。
    """
    args = BootArgs()
    i = 0
    pending_dir: list[str] = []
    while i < len(argv):
        tok = argv[i]
        if tok == "--profile":
            args.profile = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif tok == "--patch":
            args.patch.append(argv[i + 1] if i + 1 < len(argv) else "")
            i += 2
        elif tok == "--storage":
            args.storage = argv[i + 1] if i + 1 < len(argv) else ""
            if args.storage not in _STORAGE_CHOICES:
                print(
                    f"[minidsh] 非法存储后端 {args.storage!r}（可选 {sorted(_STORAGE_CHOICES)}）",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            i += 2
        elif tok == "--session":
            args.session = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif tok.startswith("-"):
            # 第一个不认识的 flag 起，全部归 app 插件
            args.app_args = argv[i:]
            break
        else:
            pending_dir.append(tok)
            i += 1
    # 未被 flag 消费的 bare token：若 app_args 为空（全是 dir），最后一个算 dir
    if pending_dir and not args.app_args:
        args.dir = pending_dir[-1]
    elif pending_dir:
        # dir 出现在 app_args 之前：pending_dir 归 dir（取第一个），其余并入 app_args
        args.dir = pending_dir[0]
    return args


# ---------- 通用 launcher ----------


def _boot(args: BootArgs) -> int:
    """装配 Context → 拣选 app 插件 → app 接管进程。"""
    # profile 合一：文件存在 → argv 覆盖路径；否则 → 命名 profile 名
    profile_arg = args.profile
    argv_path = profile_arg if (profile_arg and Path(profile_arg).exists()) else None
    profile_name = None if argv_path else profile_arg

    # 若 profile 名不存在于 ~/.minidsh/profiles/，则视为额外 bundle 名追加到 base
    extra_bundles: list[str] = []
    if profile_name is not None:
        from ..profile import profile_path as _pp

        if not _pp(profile_name).is_file():
            # 归一为 bundle 名（bundle 文件命名 minidsh.<name>.yaml）
            bundle_name = profile_name if profile_name.startswith("minidsh.") else f"minidsh.{profile_name}"
            extra_bundles.append(bundle_name)
            profile_name = None

    ctx = load_project(
        args.dir or os.getcwd(),
        storage=args.storage,
        profile=profile_name,
        argv_path=argv_path,
        extra_bundles=extra_bundles if extra_bundles else None,
    )

    # 拣选 app 插件：plugins 名单里第一个 minidsh.app- 前缀者
    from .loader import _profile_plugins

    entries = _profile_plugins(
        profile_name, Path(args.dir or os.getcwd()), argv_path, quiet=False,
        extra_bundles=extra_bundles if extra_bundles else None,
    )
    apply_fn = find_app_plugin(ctx, entries)
    if apply_fn is None:
        print(
            "[minidsh] 无 app 插件：请在 profile 的 plugins 里激活一个 minidsh.app-* 前端"
            "（例如 --profile tui-textual）",
            file=sys.stderr,
        )
        return 1

    # app 接管进程：apply(ctx, args) 自建 agent、启动前端、返回退出码
    return apply_fn(ctx, args)


# ---------- replay ----------


def _cmd_replay(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="minidsh replay", description="重放一个会话的时间线")
    parser.add_argument("path", help="jsonl 文件 / 含 sessions 或 sessions.db 的目录")
    parser.add_argument("--session-id", default=None, help="sqlite/目录来源时必填")
    args = parser.parse_args(argv)
    events = load_session_events(args.path, session_id=args.session_id)
    if not events:
        print("（无事件）", file=sys.stderr)
        return 0
    print(replay_session(events))
    return 0


# ---------- plugin ----------


def _cmd_plugin(argv: list[str]) -> int:
    from ..packaging import plugin_add, plugin_remove, plugin_list

    parser = argparse.ArgumentParser(prog="minidsh plugin", description="安装/卸载/列举插件")
    sub = parser.add_subparsers(dest="plugin_action", required=True)
    p_add = sub.add_parser("add", help="安装一个插件包并记入用户 profile")
    p_add.add_argument("pkg", help="pip 可解析的 spec（本地路径/git+/已发布包名）")
    p_rm = sub.add_parser("remove", help="从用户 profile 移除插件名")
    p_rm.add_argument("name", help="插件名")
    sub.add_parser("ls", help="列出发现到的插件 + 激活状态")
    args = parser.parse_args(argv)

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
        if argv[0] == "replay":
            return _cmd_replay(argv[1:])
        if argv[0] == "plugin":
            return _cmd_plugin(argv[1:])
        return 2
    return _boot(_parse_boot(argv))