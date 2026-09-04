"""approval 的 provider（三角色的「提供方」）：提供 ctx.approval。

对齐官方 user-approval 的 provider：构造即注册 ctx.approval。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityProvider
from ..definition import ApprovalService, ApprovalPolicy

__all__ = ["ApprovalProvider"]

name = "minidsh.approval"
inject = []


class ApprovalProvider(ApprovalService, CapabilityProvider):
    """审批 provider：构造即注册 ctx.approval。

    [教学简化] 默认 ask 策略；无应答者链时 fail-closed（unavailable）。
    """

    def _init(self, ctx, policy: ApprovalPolicy = "ask"):
        self._default_policy = policy


def apply(ctx):
    ApprovalProvider(ctx)  # 构造即注册 ctx.approval
