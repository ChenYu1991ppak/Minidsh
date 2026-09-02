"""T14 验收测试：compaction（token 压力触发 + 摘要/裁剪）。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.compaction import PruneStrategy, SummarizeStrategy, measure_messages
from minidsh.packages.services.compaction.providers.compaction import BasicCompactionEngine
from minidsh.packages.services.loop import AgentLoop
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.tool_runtime import ToolRuntime

from tests.helpers.fake_llm import make_fake_llm


class _FakeAgent:
    """只需实现 compaction 依赖的 attribute：messages + session。"""

    def __init__(self, ctx, messages):
        self.ctx = ctx
        self.messages = messages
        self.session = ctx.sessions.create()


def _ctx_with_engine():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.plugin(make_fake_llm([{"text": "摘要结果"}]))
    LocalSystemPromptService(ctx)
    ctx.provide("tools", ToolRuntime(ctx))
    engine = BasicCompactionEngine(ctx, context_window=100, threshold_ratio=0.5)
    return ctx, engine


def _long_messages(n=20):
    return [{"role": "user", "content": "x" * 100} for _ in range(n)]


# ---------- measure_messages ----------


def test_measure_messages():
    assert measure_messages([{"role": "user", "content": "abcd"}]) == 1
    assert measure_messages([{"role": "user", "content": ""}]) == 1
    assert measure_messages([{"role": "user", "content": None}]) == 0


# ---------- 阈值触发 ----------


async def test_maybe_compact_below_threshold_returns_none():
    ctx, engine = _ctx_with_engine()
    agent = _FakeAgent(ctx, [{"role": "user", "content": "short"}])  # ~1 token < 50
    assert await engine.maybe_compact(agent) is None
    assert len(agent.session) == 0  # 无事件（未触发）


async def test_maybe_compact_triggers_prune_and_emits_event():
    ctx, engine = _ctx_with_engine()
    agent = _FakeAgent(ctx, _long_messages())  # 20×25 = 500 tokens > threshold 50
    result = await engine.maybe_compact(agent)
    assert result is not None
    assert result["from_tokens"] > result["to_tokens"]  # 压缩后下降
    # 会话事件 compaction 已记录
    types = [e.type for e in agent.session]
    assert types == ["compaction"]
    e = agent.session.events()[0]
    assert e.payload["reason"] == "pressure"
    # 裁剪后：首条 + 省略标记 + 尾部 4 条
    assert len(agent.messages) <= 1 + 1 + 4


# ---------- prune 策略 ----------


async def test_prune_keeps_head_marker_tail():
    ctx, _ = _ctx_with_engine()
    strategy = PruneStrategy(retain=3)
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    out = await strategy.compact(msgs, ctx.llm)
    assert out[0] == msgs[0]  # 首条保留
    assert out[1]["content"].startswith("（较早")  # 省略标记
    assert out[-3:] == msgs[-3:]  # 尾部 3 条保留


async def test_prune_short_returns_unchanged():
    ctx, _ = _ctx_with_engine()
    strategy = PruneStrategy(retain=4)
    msgs = [{"role": "user", "content": "a"}]
    assert await strategy.compact(msgs, ctx.llm) == msgs


# ---------- summarize 策略 ----------


async def test_summarize_uses_llm():
    ctx, _ = _ctx_with_engine()
    strategy = SummarizeStrategy(retain=3)
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    out = await strategy.compact(msgs, ctx.llm)
    assert "[对话摘要]" in out[0]["content"]
    assert out[-3:] == msgs[-3:]


async def test_summarize_short_returns_unchanged():
    ctx, _ = _ctx_with_engine()
    strategy = SummarizeStrategy(retain=4)
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    assert await strategy.compact(msgs, ctx.llm) == msgs


# ---------- compact_now ----------


async def test_compact_now_ignores_threshold():
    ctx, engine = _ctx_with_engine()
    agent = _FakeAgent(ctx, [{"role": "user", "content": "hi"}])  # 远低于阈值
    result = await engine.compact_now(agent)
    assert result is not None  # manual 压缩不看阈值
    e = agent.session.events()[0]
    assert e.payload["reason"] == "manual"