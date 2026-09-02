"""subagent 模块导出。"""
from __future__ import annotations

from .definition import (
    SubagentError,
    SubagentResult,
    SubagentProvider,
    SubagentRegistry,
    InProcessSubagentProvider,
)
from .task import make_task_tool

__all__ = [
    "SubagentError",
    "SubagentResult",
    "SubagentProvider",
    "SubagentRegistry",
    "InProcessSubagentProvider",
    "make_task_tool",
]