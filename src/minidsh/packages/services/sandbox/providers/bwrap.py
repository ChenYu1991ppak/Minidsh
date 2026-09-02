"""sandbox 的 bwrap provider：用 bubblewrap 真 confining（构造即注册 ctx.sandbox）。

源码对应：packages/sandbox/sandbox-local 的 Linux（bwrap）后端语义。

实现：
- ``read-only``：``--ro-bind / /`` + ``--dev /dev`` → 只有 ``/dev/null`` 等必需 sink 可写；
- ``workspace-write``：只读根之上再 ``--bind workspaceRoot workspaceRoot`` 使其可写；
- 后端报告 ``full``（bwrap 管控了承诺的文件效果）；找不到 bwrap 时 fail-closed 抛错，
  **绝不静默降级 partial/full**（sandbox.zh.md「要求绝对边界的消费方必须拒绝」）。

[教学简化] 相对官方：无 spill 文件、无 Landlock/Seatbelt/ACL 多后端，只 bwrap；
进程可见性 / 网络不在本 seam 词汇内（官方同样如此）。
"""
from __future__ import annotations

import os
import shutil

from ..definition import (
    SandboxExecutionPolicy,
    SandboxService,
)
from minidsh.cordis import CapabilityProvider
from minidsh.packages.services.subprocess.providers.local import LocalSubprocessService
from minidsh.packages.services.subprocess.definition import SubprocessSpawnSpec, SubprocessStdio

__all__ = ["BwrapSandboxService"]

name = "minidsh.sandbox"
inject = ["subprocess"]

_BWRAP = "bwrap"


class BwrapSandboxService(SandboxService, CapabilityProvider):
    """bubblewrap 后端：只读根 + workspace 可写两模式。"""

    def _init(self, ctx):
        self._bwrap = shutil.which(_BWRAP)

    @property
    def enforcement(self):
        return "full" if self._bwrap is not None else "partial"

    def _argv_for(self, argv: list[str], cwd: str, policy: SandboxExecutionPolicy) -> list[str]:
        """拼 bwrap 包装后的 argv。进出都经真 bwrap（无 bwrap → fail-closed）。"""
        # 构建 read-only 根：ro-bind 宿主根 + dev
        wrapped = [self._bwrap, "--ro-bind", "/", "/", "--dev", "/dev"]
        if policy.mode == "workspace-write":
            # workspace 根可写：bind 自身使其逃逸只读根
            wrapped += ["--bind", policy.workspace_root, policy.workspace_root]
        wrapped += ["--chdir", cwd, "--"]
        wrapped += argv
        return wrapped

    async def confine(self, argv: list[str], cwd: str, policy: SandboxExecutionPolicy):
        """以 policy 约束起子进程。wrapped argv 交给 subprocess 执行。"""
        if self._bwrap is None:
            raise RuntimeError(
                "bwrap 不可用：无法提供完整文件效果约束，拒绝 confined 执行（fail-closed）"
            )
        wrapped = self._argv_for(argv, cwd, policy)
        spec = SubprocessSpawnSpec(
            argv=wrapped,
            cwd=cwd,
            stdio=SubprocessStdio(stdout="collect", stderr="collect"),
        )
        subprocess_svc = self.ctx.probe("subprocess")
        return await subprocess_svc.spawn(spec)


def apply(ctx):
    BwrapSandboxService(ctx)  # 构造即注册 ctx.sandbox