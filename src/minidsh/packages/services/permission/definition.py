"""permission 模块：审批 seam（seam 预留）。

对应 ch14 的 approval seam。v1 为 no-op 实现：默认**自动通过**（Allow），
为未来「人工 ask-first 审批门」预留接口——敏感工具前置一个 ApprovalService，
先 approve 再放行。

三角色：``ApprovalService`` 是定义（纯接口），``AllowAllApprovalService`` 是 provider
（构造即注册 ctx.permission）。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition, CapabilityProvider

__all__ = ["ApprovalService", "AllowAllApprovalService"]


class ApprovalService(CapabilityDefinition):
    """审批服务定义（seam）：决定一次敏感操作是否放行。"""

    service_name = "permission"

    def approve(self, kind: str, detail: dict) -> bool:
        raise NotImplementedError

    async def ask(self, kind: str, detail: dict) -> bool:
        raise NotImplementedError


class AllowAllApprovalService(ApprovalService, CapabilityProvider):
    """显式「全放行」provider：同步恒 True、异步恒 False（无人工降级 deny），构造即注册 ctx.permission。"""

    def approve(self, kind: str, detail: dict) -> bool:
        return True

    async def ask(self, kind: str, detail: dict) -> bool:
        return False