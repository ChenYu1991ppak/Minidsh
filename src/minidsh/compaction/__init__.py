"""compaction 模块：token 压力下的上下文压缩。

源码对应（ch10 教学版，逐机制对齐）：
- ``CompactionEngine``        ↔ packages/core/compaction/src/index.ts:19（服务定义）
- ``BasicCompactionEngine``   ↔ packages/core/compaction-basic/src/index.ts:20（提供者）
- resolveCompactSpec          ↔ compaction-basic/index.ts:110
- selectCompactableRange      ↔ compaction-basic/index.ts:122
- summarizeWithLlm            ↔ compaction-basic/index.ts:230
- tool-result-pruner          ↔ compaction-tool-result-pruner/src/index.ts

v1 简化（相对 ch10）：
- 直接操作 loop 的 ``agent.messages``（模型侧历史），不做 surface 投影/replace 事务、
  不做 stability 断言（同步单线程恒成立）。ch10 的 surface/surfaceOp 机制在 v1 用
  ``agent.messages`` 的「原位替换 + 判稳定性」代替。
- 两种策略：``prune``（无模型裁剪尾保留）与 ``summarize``（LLM 摘要）；
  二者实现同一 ``CompactionStrategy`` 接口（策略是 seam，可扩展）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..cordis import Service
from ..llm import estimate_tokens

__all__ = [
    "CompactionStrategy",
    "PruneStrategy",
    "SummarizeStrategy",
    "CompactionEngine",
]

_SUMMARY_INSTRUCTION = "请用一段话概括以下对话，保留关键事实、结论与待办。只输出摘要本身。"


def measure_messages(messages: list[dict]) -> int:
    """估算消息列表的 token 总量（token-meter 的粗估替代）。"""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
    return total


class CompactionStrategy(ABC):
    """压缩策略契约：给定模型侧消息，返回压缩后的消息列表。可插拔，未来可加新策略。"""

    @abstractmethod
    async def compact(self, messages: list[dict], llm) -> list[dict]:
        raise NotImplementedError


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


class CompactionEngine(Service):
    """ctx.compaction：token 压力触发压缩（CompactionEngine / BasicCompactionEngine 合一）。"""

    def __init__(
        self,
        ctx,
        context_window: int = 8000,
        threshold_ratio: float = 0.8,
        strategy: CompactionStrategy | None = None,
    ):
        super().__init__(ctx, "compaction")
        self.context_window = context_window
        self.threshold_ratio = threshold_ratio
        self.strategy = strategy or PruneStrategy()

    @property
    def threshold(self) -> int:
        return int(self.context_window * self.threshold_ratio)

    async def maybe_compact(self, agent) -> dict | None:
        """压力触发：达阈值才压缩；未达返回 None（compact_if_needed，index.ts:21）。

        压缩后写会话事件 ``compaction``（事件契约），返回 {from_tokens, to_tokens}。
        """
        total = measure_messages(agent.messages)
        if total < self.threshold:
            return None

        before = total
        agent.messages = await self.strategy.compact(agent.messages, self.ctx.llm)
        after = measure_messages(agent.messages)
        agent.session.append(
            "compaction",
            {"reason": "pressure", "from_tokens": before, "to_tokens": after},
        )
        return {"from_tokens": before, "to_tokens": after}

    async def compact_now(self, agent) -> dict | None:
        """立即压缩（/compact 命令语义，compact_now，index.ts:24）。不管阈值。"""
        before = measure_messages(agent.messages)
        agent.messages = await self.strategy.compact(agent.messages, self.ctx.llm)
        after = measure_messages(agent.messages)
        agent.session.append(
            "compaction",
            {"reason": "manual", "from_tokens": before, "to_tokens": after},
        )
        return {"from_tokens": before, "to_tokens": after}