"""base 插件：compaction（BasicCompactionEngine，CompactionEngine 的唯一 provider）。"""
from __future__ import annotations

from minidsh.capabilities.compaction.definition import (
    CompactionEngine,
    CompactionStrategy,
    PruneStrategy,
    measure_messages,
)
from minidsh.cordis import CapabilityProvider

name = "minidsh.compaction"
inject = ["sessions", "llm", "config"]


class BasicCompactionEngine(CompactionEngine, CapabilityProvider):
    """CompactionEngine 的本地实现：完整阈值判定 + 触发压缩。构造即注册 ctx.compaction。"""

    def _init(self, ctx, *, context_window: int = 8000, threshold_ratio: float = 0.8,
              strategy: CompactionStrategy | None = None):
        self.ctx = ctx
        self.context_window = context_window
        self.threshold_ratio = threshold_ratio
        self.strategy = strategy or PruneStrategy()

    @property
    def threshold(self) -> int:
        return int(self.context_window * self.threshold_ratio)

    async def maybe_compact(self, agent) -> dict | None:
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
        before = measure_messages(agent.messages)
        agent.messages = await self.strategy.compact(agent.messages, self.ctx.llm)
        after = measure_messages(agent.messages)
        agent.session.append(
            "compaction",
            {"reason": "manual", "from_tokens": before, "to_tokens": after},
        )
        return {"from_tokens": before, "to_tokens": after}


def apply(ctx):
    BasicCompactionEngine(  # 构造即注册 ctx.compaction
        ctx,
        context_window=ctx.config.context_window,
        threshold_ratio=ctx.config.compaction_threshold_ratio,
    )