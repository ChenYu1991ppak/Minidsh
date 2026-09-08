"""subprocess 的本地 provider：经 asyncio 起子进程（构造即注册 ctx.subprocess）。

源码对应：packages/subprocess/subprocess-local。三角色的「提供方」。

[教学简化] 相对官方：
- 终止只杀直接子进程（无进程树级 SIGTERM→grace→SIGKILL 升级、无分离进程组）；
- collect 读法简化：settle 后一次性读完整尾部 + optional spill 文件；
- ``DSH_*`` 命名空间 + 父环境清除：spawn 前丢弃父环境中已有 ``DSH_*``，
  再合并显式 env（str=opt-in 保留、None=tombstone 删除）。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile

from ..definition import (
    CollectedOutput,
    SubprocessHandle,
    SubprocessOutcome,
    SubprocessService,
    SubprocessSpawnSpec,
    DSH_ENV_PREFIX,
)
from minidsh.cordis import CapabilityProvider

__all__ = ["LocalSubprocessService"]

name = "minidsh.subprocess"
inject = []

# collect 缺省内存上限（字节）。
_MAX_BYTES_DEFAULT = 64 * 1024


class LocalSubprocessService(SubprocessService, CapabilityProvider):
    """本地 asyncio 子进程执行者。"""

    async def spawn(self, spec: SubprocessSpawnSpec) -> SubprocessHandle:
        argv, cwd, stdio = spec.argv, spec.cwd, spec.stdio
        env = self._scrub_env(spec.env)

        stdin_arg = None
        if stdio.stdin == "ignore":
            stdin_arg = asyncio.subprocess.DEVNULL
        elif isinstance(stdio.stdin, dict):
            stdin_arg = asyncio.subprocess.PIPE  # {data} 批量：写后关闭

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=stdin_arg,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if isinstance(stdio.stdin, dict) and stdin_arg is not None:
            proc.stdin.write(stdio.stdin.get("data", "").encode())
            await proc.stdin.drain()
            proc.stdin.close()

        state = {}  # 结算后填入 collected（SubprocessHandle.collected 结算后可读）

        async def done() -> SubprocessOutcome:
            out_bytes, err_bytes = await proc.communicate()
            state["collected"] = {
                **self._collect("stdout", out_bytes, stdio.stdout),
                **self._collect("stderr", err_bytes, stdio.stderr),
            }
            return SubprocessOutcome(exit_code=proc.returncode, signal=None)

        handle = SubprocessHandle(proc.pid, done(), state, proc)
        return handle

    @staticmethod
    def _collect(key: str, raw: bytes, mode) -> dict:
        """把一条流的原始字节转成 {key: CollectedOutput}；inherit/pipe 不进 collected。

        [教学简化] 裸字符串 ``"collect"`` 视为默认上限的有界 collect（官方必须是 dict）。
        """
        if mode == "inherit" or mode == "pipe":
            return {}
        if not isinstance(mode, dict):
            if mode == "collect":
                mode = {"maxBytes": _MAX_BYTES_DEFAULT}
            else:
                return {}
        max_bytes = int(mode.get("maxBytes", _MAX_BYTES_DEFAULT))
        truncated = len(raw) > max_bytes
        text_bytes = raw[-max_bytes:] if truncated else raw
        spill_path = None
        if truncated and mode.get("spill") is not None:
            spill_path = LocalSubprocessService._spill(raw)
        return {
            key: CollectedOutput(
                text=text_bytes.decode("utf-8", errors="replace"),
                truncated=truncated,
                spill_path=spill_path,
            )
        }

    @staticmethod
    def _spill(raw: bytes) -> str:
        fd, path = tempfile.mkstemp(prefix="dsh-spill-", suffix=".bin")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return path

    @staticmethod
    def _scrub_env(explicit: dict | None) -> dict:
        """丢弃父环境中已有 DSH_*，再合并显式 env（scrubbedParentEnv 的简化）。"""
        base = {k: v for k, v in os.environ.items() if not k.startswith(DSH_ENV_PREFIX)}
        for k, v in (explicit or {}).items():
            if v is None:
                base.pop(k, None)   # tombstone：删除普通环境已有值
            else:
                base[k] = v
        return base

    async def resolve_executable(self, command: str, env: dict | None = None) -> str:
        """绝对路径校验；裸名经清理后 PATH 解析（resolveExecutable）。"""
        if command.startswith("/"):
            if os.path.isfile(command) and os.access(command, os.X_OK):
                return command
            raise FileNotFoundError(f"绝对路径不可执行：{command!r}")
        return shutil.which(command, path=env.get("PATH") if env else None) or command


def apply(ctx):
    LocalSubprocessService(ctx)  # 构造即注册 ctx.subprocess