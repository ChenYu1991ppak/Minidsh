"""压缩策略：LLM 摘要（provider / 策略实现）。

把早期消息交给模型压成一段摘要，尾部保留。
"""
from __future__ import annotations

from ..definition import CompactionStrategy

__all__ = ["SummarizeStrategy"]

_SUMMARY_INSTRUCTION = "请用一段话概括以下对话，保留关键事实、结论与待办。只输出摘要本身。"


class SummarizeStrategy(CompactionStrategy):
    """LLM 摘要：把早期消息交给模型压成一段摘要，尾部保留。"""

    def __init__(self, retain: int = 4):
        self.retain = retain

    async def compact(self, messages: list[dict], llm) -> list[dict]:
        if len(messages) <= self.retain + 2:
            return messages  # 太短不值得摘要
        head = messages[: -(self.retain)]
        tail = messages[-(self.retain):]
        text = "\n".join(
            f"{m.get('role')}: {m.get('content')}" for m in head if m.get("content")
        )
        chunks = [
            c.text async for c in llm.stream(
                [{"role": "user", "content": f"{_SUMMARY_INSTRUCTION}\n\n{text}"}]
            )
            if c.kind == "text-delta"
        ]
        summary = "".join(chunks).strip() or "（摘要不可用）"
        marker = {"role": "user", "content": f"[对话摘要] {summary}"}
        return [marker] + tail