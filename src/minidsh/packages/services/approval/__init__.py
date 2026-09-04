"""approval 能力。

ctx.approval：审批 seam（策略 + 应答者 waterfall）。
"""
from __future__ import annotations

from .definition import (
    ApprovalOutcome,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalService,
    APPROVAL_POLICIES,
)
from .providers.approval import ApprovalProvider

__all__ = [
    "ApprovalOutcome",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalService",
    "ApprovalProvider",
    "APPROVAL_POLICIES",
]