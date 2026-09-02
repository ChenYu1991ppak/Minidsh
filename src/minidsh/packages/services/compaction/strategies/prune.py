"""压缩策略：无模型裁剪（provider / 策略实现）。

保留首条 + 尾部 ``retain`` 条，中间替换为省略标记。
"""
from __future__ import annotations

from ..definition import CompactionStrategy

__all__ = ["PruneStrategy"]


class PruneStrategy(CompactionStrategy):
    """无模型裁剪：保留首条 + 尾部 ``retain`` 条，中间替换为省略标记。"""

    def __init__(self, retain: int = 4):
        self.retain = retain

    async def compact(self, messages: list[dict], llm) -> list[dict]:
        if len(messages) <= self.retain + 1:
            return messages  # 太短不裁
        head = messages[:1]
        tail = messages[-(self.retain):]
        marker = {"role": "user", "content": "（较早的对话内容已省略）"}
        return head + [marker] + tail