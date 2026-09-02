"""sandbox 模块：进程文件效果策略的约束 seam（ctx.sandbox）。

源码对应：packages/sandbox/sandbox/src/index.ts。

- ``SandboxMode`` 仅管控**文件系统效果**：read-only / workspace-write / danger-full-access。
- ``danger-full-access`` 的消费方直接 spawn 原始 argv，**不调 ctx.sandbox**；
  只有前两种模式可被 ``SandboxPolicy`` 携带，送给 provider。
- 强制执行完整性是后端报告的事实：``full`` = 后端管控该模式承诺的全部文件效果，
  ``partial`` = 仅子集，要求绝对边界的消费方必须拒绝或上抛（绝不静默当 full）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from minidsh.cordis import CapabilityDefinition

__all__ = [
    "SandboxMode",
    "ConfinedSandboxMode",
    "SandboxEnforcement",
    "SandboxExecutionPolicy",
    "SandboxService",
]

SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
ConfinedSandboxMode = Literal["read-only", "workspace-write"]
SandboxEnforcement = Literal["full", "partial"]


@dataclass(frozen=True)
class SandboxExecutionPolicy:
    """一次能力调用的完整文件效果策略（index.ts SandboxExecutionPolicy）。

    ``workspaceRoot`` 即便在 read-only 下也携带（消费方可解析一次再选路径）。
    """

    mode: ConfinedSandboxMode
    workspace_root: str


class SandboxService(CapabilityDefinition):
    """ctx.sandbox：把子进程 argv 包进文件效果策略，不耦合具体平台运行器。"""

    service_name = "sandbox"

    async def confine(self, argv: list[str], cwd: str,
                      policy: SandboxExecutionPolicy) -> "object":
        """以 ``policy`` 约束的 argv 起一个进程，返回 SubprocessHandle。"""
        raise NotImplementedError

    @property
    def enforcement(self) -> SandboxEnforcement:
        """后端报告的强制完整性（full | partial）。"""
        raise NotImplementedError