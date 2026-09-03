"""M1 验收测试：token-meter 独立 seam（完整回放快照）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.token_meter import TokenMeterService


def _ctx():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    meter = TokenMeterService(ctx)
    ctx.provide("tokenMeter", meter)
    return ctx, meter


def test_measure_returns_full_snapshot():
    ctx, meter = _ctx()
    session = ctx.sessions.create()
    session.append("user-message", {"text": "你好"})
    session.append("assistant-message", {"content": "回复"})

    m = meter.measure(session, messages=[
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "回复"},
    ])
    assert m.log_revision == 2          # 消费 2 条持久事件
    assert m.total_tokens >= 0
    assert m.surface_tokens == sum(n.tokens for n in m.nodes)
    assert len(m.nodes) == 2
    # 无 usage 锚点 → heuristic/estimated
    assert m.baseline.kind in ("estimated", "none")


def test_measure_empty_surface_none_baseline():
    ctx, meter = _ctx()
    session = ctx.sessions.create()
    m = meter.measure(session, messages=[])
    assert m.baseline.kind == "none"
    assert m.baseline.tokens == 0
    assert m.surface_tokens == 0
    assert m.nodes == []


def test_usage_anchor_replaces_heuristic():
    ctx, meter = _ctx()
    session = ctx.sessions.create()
    session.append("user-message", {"text": "x"})

    meter.record_usage("deepseek-chat", 100, {"prompt_tokens": 10, "completion_tokens": 90})
    m = meter.measure(session, messages=[{"role": "user", "content": "x"}])
    assert m.baseline.kind == "usage"
    assert m.baseline.tokens == 100
    # surface_delta = surface_tokens - baseline.tokens（有符号）
    assert m.surface_delta_tokens == m.surface_tokens - 100


def test_estimate_message_counts_tool_calls():
    from minidsh.packages.services.token_meter import estimate_message

    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"function": {"name": "bash", "arguments": '{"cmd":"echo hi"}'}},
        ],
    }
    assert estimate_message(msg) > 0