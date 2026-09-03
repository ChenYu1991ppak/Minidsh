"""loop 模块：agent-loop 闭环 + inbox。

- ``Inbox``：待处理消息队列
- ``AgentLoop``：被容器装配出来的服务（create 产出 agent）
- ``ReactLoopAgent``：反应式循环驱动器（kick/turn/react）

消费 llm/prompt/tools，产出会话事件（事件契约 §plan）。内核同步，loop 层用
asyncio 适配 LLM 流式（spec §11-5）。

[教学简化] 消息历史（模型侧 conversation）以 ``self.messages`` 在 loop 内持有，
不从事件流反投影（deriveMessages，session/src/index.ts:726-747）——那是 ch03
SessionProjection 的机制，v1 不做投影，compaction（T14）直接改写该列表。
"""
from __future__ import annotations

from .inbox import Inbox
from .agent_loop import AgentLoop, ReactLoopAgent, derive_messages

__all__ = ["AgentLoop", "ReactLoopAgent", "derive_messages", "Inbox"]