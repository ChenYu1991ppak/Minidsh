"""permission 模块：审批 seam（seam 预留）。

对应 ch14 的 approval seam。v1 为 no-op 实现：默认**自动通过**（Allow），
为未来「人工 ask-first 审批门」预留接口——敏感工具前置一个 ApprovalService，
先 approve 再放行。

扩展方式：定义 ``ApprovalService`` 子类，覆写 ``approve``（同步放行默认实现）
与 ``ask``（无人工时降级 deny），在 tools 的 pre-execute 守卫里消费。
"""
from __future__ import annotations

from ...cordis import Service

__all__ = ["ApprovalService", "AllowAllApprovalService"]


class ApprovalService(Service):
    """审批服务定义（seam）：决定一次敏感操作是否放行。默认 no-op = 全通过。"""

    def __init__(self, ctx):
        super().__init__(ctx, "permission")

    def approve(self, kind: str, detail: dict) -> bool:
        """同步审批：返回 True 放行。no-op 实现恒 True，未来接人工审批门。"""
        return True

    async def ask(self, kind: str, detail: dict) -> bool:
        """异步审批（无人工时降级 deny）。no-op 实现恒 False。"""
        return False


class AllowAllApprovalService(ApprovalService):
    """显式「全放行」命名实现：等价 no-op，语义更直白。"""

    pass