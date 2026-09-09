"""pydsh.app-tui：pi-tui 终端前端（app 插件）。

经 ``pydsh --profile tui`` 启动。spawn Node.js pi-tui 前端子进程并等待其退出。

进程架构：pi-tui 前端持有终端（raw mode），它内部 spawn ``pydsh --profile acp``
（或经 ``PYDSH_ACP_PROFILE`` 指定的 profile）作为 ACP backend——ACP server 是子进程，
pi-tui 是主进程，这样 pi-tui 的 ProcessTerminal 才能直接访问真实终端。

[教学简化] 不做 pi-tui 子进程的环境隔离、不做崩溃自动重启。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

name = "pydsh.app-tui"
inject = []


def _frontend_command(cwd: str) -> list[str]:
    """定位 pi-tui 前端入口，返回 node 启动命令。"""
    frontend_dir = Path(__file__).resolve().parent / "pi-tui"
    dist_entry = frontend_dir / "dist" / "index.js"

    if dist_entry.is_file():
        return ["node", str(dist_entry), cwd]
    # 回退：开发模式用 tsx 直接运行 TS 源码
    src_entry = frontend_dir / "src" / "index.ts"
    return ["npx", "tsx", str(src_entry), cwd]


def apply(ctx, args) -> int:
    """spawn pi-tui 前端，继承终端，等待其退出。"""
    # 归一为绝对路径（subprocess cwd 需绝对路径；pi-tui 传给 ACP backend 也要绝对路径）
    cwd = str(Path(getattr(args, "dir", None) or os.getcwd()).resolve())
    cmd = _frontend_command(cwd)

    # 传递 pydsh 二进制路径给 pi-tui 前端（subprocess 内部需要 spawn 它）
    env = dict(os.environ)
    env["PYDSH_BIN"] = sys.argv[0]  # 当前进程的二进制路径

    print(f"[pydsh] 启动 pi-tui 前端: {' '.join(cmd)}", file=sys.stderr)

    proc = subprocess.run(cmd, cwd=cwd, env=env)
    return proc.returncode