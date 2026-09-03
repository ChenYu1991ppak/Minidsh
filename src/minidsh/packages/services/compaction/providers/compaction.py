"""base 插件：compaction（BasicCompactionEngine，CompactionEngine 的唯一 provider）。"""
from __future__ import annotations

from minidsh.packages.services.compaction.definition import (
    CompactionEngine,
    CompactionStrategy,
    PruneStrategy,
    measure_messages,
)
from minidsh.packages.services.token_meter import estimate_message
from minidsh.cordis import CapabilityProvider

name = "minidsh.compaction"
inject = ["sessions", "llm", "config", "tokenMeter"]


def _measure(agent) -> int:
    """估算当前 agent 消息列表的 token 总量：优先 tokenMeter，否则 chars/4。"""
    if hasattr(agent.ctx, "tokenMeter"):
        m = agent.ctx.tokenMeter.measure(agent.session, messages=agent.messages)
        return m.total_tokens
    total = 0
    for msg in agent.messages:
        total += estimate_message(msg)
    return total


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
        total = _measure(agent)
        if total < self.threshold:
            return None
        before = total
        agent.messages = await self.strategy.compact(agent.messages, self.ctx.llm)
        after = _measure(agent)
        agent.session.append(
            "compaction",
            {"reason": "pressure", "from_tokens": before, "to_tokens": after},
        )
        return {"from_tokens": before, "to_tokens": after}

    async def compact_now(self, agent) -> dict | None:
        before = _measure(agent)
        agent.messages = await self.strategy.compact(agent.messages, self.ctx.llm)
        after = _measure(agent)
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