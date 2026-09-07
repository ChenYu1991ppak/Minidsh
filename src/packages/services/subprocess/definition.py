"""subprocess seam：完全显式的进程执行（Service Definition）

源码对应：packages/subprocess/subprocess/src/types.ts（SpawnSpec/Outcome/Handle）。

三角色：
- ``SubprocessService``（定义，``ctx.subprocess``）——argv 执行 + 可执行文件解析；
- ``subprocess-local``（provider，经 asyncio 起子进程）；
- Consumer：shell（M8 bash 执行器用 collect 批量输出）、LSP（pipe 协议分帧）等。

[教学简化] 相对官方：
- 砍掉 AbortSignal/graceMs 终止升级（SIGTERM→宽限→SIGKILL 树），保留 ``terminate()``
  只杀直接子进程（asyncio ``proc.kill/terminate``）；
- stdin 三模式、stdout/stderr 的 pipe/inherit/collect 三处置保留（collect 有界尾 + spill）；
- collect 的 offset-based 增量 reader 简化成「结算后读完整尾部」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from minidsh.cordis import CapabilityDefinition

__all__ = [
    "CollectedOutput",
    "SubprocessStdinMode",
    "SubprocessOutputMode",
    "SubprocessStdio",
    "SubprocessSpawnSpec",
    "SubprocessOutcome",
    "SubprocessHandle",
    "SubprocessService",
]

# harness 拥有的子进程事实环境命名空间（types.ts DSH_ENV_PREFIX）。
DSH_ENV_PREFIX = "DSH_"

# stdin 处置：'ignore' → /dev/null；'pipe' → 暴露 stdin；{data} → 写字节后关闭（批量形态）。
SubprocessStdinMode = Literal["ignore"] | Literal["pipe"] | dict

# stdout/stderr 处置：'pipe' 原始协议 / 'inherit' 透传 / collect 有界批（尾 + spill）。
SubprocessOutputMode = Literal["pipe"] | Literal["inherit"] | dict


@dataclass(frozen=True)
class CollectedOutput:
    """一条被收集流：截断时保留**尾部** + 完整流可 spill（types.ts CollectedOutput）。"""

    text: str
    truncated: bool = False
    spill_path: str | None = None


@dataclass(frozen=True)
class SubprocessStdio:
    """三流显式处置（types.ts SubprocessStdio）。"""

    stdin: SubprocessStdinMode = "ignore"
    stdout: SubprocessOutputMode = "collect"
    stderr: SubprocessOutputMode = "collect"


@dataclass(frozen=True)
class SubprocessSpawnSpec:
    """完全显式的 spawn 请求（types.ts SubprocessSpawnSpec）。argv 绝不 shell 解释。"""

    argv: list[str]
    cwd: str
    stdio: SubprocessStdio = field(default_factory=SubprocessStdio)
    env: dict[str, str | None] | None = None   # str=有意 opt-in；None=tombstone 删除环境值


@dataclass(frozen=True)
class SubprocessOutcome:
    """一次关闭进程的退出事实（types.ts SubprocessOutcome）。不承载原因分类。"""

    exit_code: int | None
    signal: str | None = None


class SubprocessHandle:
    """一次存活子进程（types.ts SubprocessHandle）。collect 输出结算后仍可读。

    ``collected`` 是动态读取（结算前为空 dict，结算后含 stdout/stderr 的
    CollectedOutput）——匹配官方「结算后仍可经 handle.collected 读取」。
    """

    def __init__(self, pid: int, done, collected_state: dict, proc):
        self.pid = pid
        self.done = done              # awaitable：解析为 SubprocessOutcome
        self._collected_state = collected_state  # 由 done() 结算时填入
        self._proc = proc

    @property
    def collected(self) -> dict:
        return self._collected_state.get("collected", {})

    def terminate(self):
        """终止直接子进程（[教学简化] 无树级 SIGTERM→grace→SIGKILL 升级）。"""
        if self._proc is not None and self._proc.returncode is None:
            self._proc.kill()

    async def wait_for_exit(self) -> bool:
        await self.done
        return True


class SubprocessService(CapabilityDefinition):
    """ctx.subprocess：进程执行 seam。

    - ``spawn``：完全显式 argv 起子进程，绝不 shell 解释；
    - ``resolve_executable``：绝对路径校验，或经清理后 PATH 解析裸名。
    """

    service_name = "subprocess"

    async def spawn(self, spec: SubprocessSpawnSpec) -> SubprocessHandle:
        raise NotImplementedError

    async def resolve_executable(self, command: str, env: dict | None = None) -> str:
        raise NotImplementedError