"""待处理消息队列。

源码对应：packages/core/agent-loop/src/inbox.ts:25。

[教学简化] 只实现 next_turn；next_step（steer/inject，agent.ts:126/:130）不展开。
"""
from __future__ import annotations

from collections import deque

__all__ = ["Inbox"]


class Inbox:
    """待处理队列：消息入队，turn 边界一次性取走。"""

    def __init__(self):
        self.next_turn: deque = deque()

    def enqueue(self, message):
        self.next_turn.append(message)

    def claim(self):
        """在 turn 边界一次性取走全部待处理消息（inbox.ts claim）。"""
        claimed = list(self.next_turn)
        self.next_turn.clear()
        return claimed

    @property
    def has_pending(self) -> bool:
        return bool(self.next_turn)