"""permission 能力：审批 seam（seam 预留）。

v1 为 no-op：默认自动放行（Allow）；为未来「人工 ask-first 审批门」预留接口。
"""
from __future__ import annotations

from .definition import ApprovalService, AllowAllApprovalService

__all__ = ['ApprovalService', 'AllowAllApprovalService']
