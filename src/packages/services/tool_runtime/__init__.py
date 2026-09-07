"""tools 能力：工具运行时（注册面 + 守卫管线 + 输出契约）。

shell / fs 等具体能力定义在 capabilities/shell、capabilities/fs（三角色各归其位），
不在本模块——本模块只提供「工具运行时」这个横切注册面（consumer 的 inject="tools"）。
"""
from __future__ import annotations

from .runtime import (
    ToolDefinition,
    ToolOutput,
    ToolResult,
    ToolExecution,
    ToolRuntime,
    PreToolDecision,
    PostToolDecision,
)
from .guard import (
    ToolGuard,
    GuardRegistry,
    RepeatedToolReminder,
    DEFAULT_REPEAT_THRESHOLDS,
    GENTLE_REMINDER,
)

__all__ = [
    "ToolDefinition",
    "ToolOutput",
    "ToolResult",
    "ToolExecution",
    "ToolRuntime",
    "PreToolDecision",
    "PostToolDecision",
    "ToolGuard",
    "GuardRegistry",
    "RepeatedToolReminder",
    "DEFAULT_REPEAT_THRESHOLDS",
    "GENTLE_REMINDER",
]
