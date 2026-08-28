"""终端渲染：SessionEvent → 结构化行。

纯文本渲染（spec §11-3），不做 ANSI 彩色——重放与观测主载体是落盘事件流，
终端行只是即时透出。每行格式统一：

    [session_id:seq] type key=value key=value...

value 里的换行折叠为 ``\\n``，避免单条事件撑破行结构。
"""
from __future__ import annotations

import json
from typing import Any

from ..session import SessionEvent

__all__ = ["ConsoleRenderer", "render_event"]


def _scalar(v: Any) -> str:
    """把 payload 值压成单行可读片段。dict/list 走紧凑 JSON；字符串折叠换行。"""
    if isinstance(v, str):
        return v.replace("\n", "\\n")
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def render_event(event: SessionEvent) -> str:
    """把一条事件渲染成一行。"""
    parts = []
    for key, value in event.payload.items():
        parts.append(f"{key}={_scalar(value)}")
    suffix = (" " + " ".join(parts)) if parts else ""
    return f"[{event.session_id}:{event.seq}] {event.type}{suffix}"


class ConsoleRenderer:
    """订阅 ``session/event``，逐条打印结构化行。

    挂到某个 Context 后，该容器内所有会话事件都会实时透出。
    落盘由 PersistenceCoordinator 独立订阅同一条事件流，二者解耦。
    """

    def __init__(self, ctx, out=None):
        self.ctx = ctx
        self._out = out
        self._off = ctx.on("session/event", self._on_event)

    def _on_event(self, event: SessionEvent):
        line = render_event(event)
        if self._out is not None:
            self._out(line + "\n")
        else:
            print(line)

    def detach(self):
        """停止订阅。"""
        self._off()