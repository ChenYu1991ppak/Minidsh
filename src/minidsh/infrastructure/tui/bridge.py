"""TUI 事件桥 + 后台驱动：把 core 的事件流/agent 接入 Textual 消息循环。

职责（不碰 core 机制，只做「只读观察 + 驱动调度」）：
- ``subscribe``：``ctx.on("session/event")`` → 把每条事件投递成 Textual 消息（同 asyncio loop）；
- ``drive``：后台 task 串行消费输入队列，逐条 ``agent.send`` + ``await agent.run()``，
  退出时 flush（``session/flush`` + backend close，对齐旧 ``_run_repl`` 语义）。
"""
from __future__ import annotations

import asyncio

from textual.message import Message

__all__ = ["EventMessage", "subscribe", "drive", "shutdown"]


class EventMessage(Message):
    """一条会话事件消息：从 core loop 转发到 TUI 的载体（不改事件本身）。"""

    def __init__(self, event):
        super().__init__()
        self.event = event


def subscribe(ctx, post_message) -> None:
    """订阅 session/event，每条事件转成一条 EventMessage 投递给 Textual。

    ``post_message`` 是 Textual 的 `app.post_message`（同 loop 直接调用，不需 await）。
    """
    ctx.on("session/event", lambda event: post_message(EventMessage(event)))


async def drive(agent, queue: asyncio.Queue, ctx) -> None:
    """后台驱动：串行消费输入队列 → agent.send + agent.run。

    ``agent`` 可以是 agent 对象，或返回当前 agent 的可调用对象（支持运行时切换会话，
    ``/new`` 换 agent 后驱动自动跟随）。退出（队列收到 None 哨兵）时 flush 会话 +
    关闭持久化后端，保证落盘完整。
    """
    get_agent = agent if callable(agent) else (lambda: agent)
    try:
        while True:
            text = await queue.get()
            if text is None:  # 哨兵：结束
                queue.task_done()
                break
            get_agent().send(text)
            await get_agent().run()
            queue.task_done()
    finally:
        current = get_agent()
        ctx.emit("session/flush", current.session.id)
        backend = getattr(ctx, "_persistence_backend", None)
        if backend is not None and hasattr(backend, "close"):
            backend.close()


async def shutdown(agent, queue: asyncio.Queue, ctx) -> None:
    """发起关闭：投递 None 哨兵并等待驱动 task 收敛（幂等）。"""
    await queue.put(None)