"""trace 模块：会话事件流 → 终端渲染 + 落盘接线 + 重放。

可观测性落点（spec §10 S2/S3）：每一条会话事件，既实时渲染到终端（纯结构化行，
spec §11-3），又经 SessionPersistence 落盘（jsonl/sqlite，spec §11-2），事后可
``minidsh replay`` 重放。

角色划分：
- ``ConsoleRenderer``：把 ``SessionEvent`` 渲染成一行可读文本，直接打印。
- ``PersistenceCoordinator``（session 模块）：负责落盘写路径（已接线，见 T4/T5）。
  本模块只负责「订阅事件 → 渲染打印」，落盘由 coordinator 独立订阅同一条
  ``session/event`` 完成——两端解耦，渲染崩了不丢落盘。
"""
from __future__ import annotations

from .renderer import ConsoleRenderer, render_event
from .replay import replay_session, load_session_events

__all__ = ["ConsoleRenderer", "render_event", "replay_session", "load_session_events"]