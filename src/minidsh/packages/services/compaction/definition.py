"""compaction 能力定义：token 压力下的上下文压缩。

源码对应（ch10 教学版，逐机制对齐）：
- ``CompactionEngine``        ↔ packages/core/compaction/src/index.ts:19（服务定义）
- ``CompactionStrategy``      ↔ 压缩策略契约（seam，可扩展）
- resolveCompactSpec          ↔ compaction-basic/index.ts:110
- selectCompactableRange      ↔ compaction-basic/index.ts:122
- summarizeWithLlm            ↔ compaction-basic/index.ts:230
- tool-result-pruner          ↔ compaction-tool-result-pruner/src/index.ts

策略实现（prune / summarize）在 ``strategies/`` 下，见各文件。

v1 简化（相对 ch10）：
- 直接操作 loop 的 ``agent.messages``（模型侧历史），不做 surface 投影/replace 事务、
  不做 stability 断言（同步单线程恒成立）。ch10 的 surface/surfaceOp 机制在 v1 用
  ``agent.messages`` 的「原位替换 + 判稳定性」代替。
- 两种策略：``prune``（无模型裁剪尾保留）与 ``summarize``（LLM 摘要）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from minidsh.cordis import CapabilityDefinition
from ..llm import estimate_tokens

__all__ = [
    "CompactionStrategy",
    "CompactionEngine",
    "measure_messages",
    "PruneStrategy",
    "SummarizeStrategy",
]


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


from .strategies.prune import PruneStrategy
from .strategies.summarize import SummarizeStrategy


class CompactionEngine(CapabilityDefinition):
    """ctx.compaction：token 压力触发压缩。纯接口——具体实现见 providers/compaction。"""

    service_name = "compaction"

    @property
    def threshold(self) -> int:
        raise NotImplementedError

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