"""M5 验收测试：sessionProjections（eager fold + 一致快照 + 变更馈送 + lastMessage 单元）。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.session_projection import (
    ProjectionDefinition,
    SessionProjectionRegistry,
    make_last_message_unit,
)


def _ctx():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    registry = SessionProjectionRegistry(ctx)
    ctx.provide("sessionProjections", registry)
    return ctx, registry


def test_last_message_unit_folds():
    ctx, registry = _ctx()
    registry.register(make_last_message_unit())
    session = ctx.sessions.create()
    session.append("user-message", {"text": "hi"})
    session.append("assistant-message", {"content": "回复一", "stop_reason": "end-turn"})

    state = registry.state_of(session, "lastMessage")
    assert state == {"content": "回复一", "seq": 1}


def test_last_message_ignores_unrelated_events():
    ctx, registry = _ctx()
    registry.register(make_last_message_unit())
    session = ctx.sessions.create()
    session.append("tool-call", {"name": "bash"})
    state = registry.state_of(session, "lastMessage")
    assert state == {"content": "", "seq": -1}   # 无 assistant-message → 初始态


def test_snapshot_consistent_cut():
    ctx, registry = _ctx()
    registry.register(make_last_message_unit())
    session = ctx.sessions.create()
    session.append("assistant-message", {"content": "A", "stop_reason": "end-turn"})
    snap = registry.snapshot(session)
    assert snap.as_of_seq == 0
    assert snap.values["lastMessage"]["content"] == "A"


def test_change_feed_fires_on_state_change():
    ctx, registry = _ctx()
    registry.register(make_last_message_unit())
    events = []
    registry.on_change(lambda sid, key, value, seq: events.append((sid, key, value["content"], seq)))
    session = ctx.sessions.create()
    session.append("tool-call", {"name": "x"})          # 无关 → 无变更
    session.append("assistant-message", {"content": "B"})  # 相关 → 通知一次
    assert events == [(session.id, "lastMessage", "B", 1)]


def test_duplicate_key_different_version_raises():
    ctx, registry = _ctx()
    registry.register(make_last_message_unit())
    unit2 = ProjectionDefinition(
        key="lastMessage",
        init=lambda h: {"content": "", "seq": -1},
        apply=lambda s, e: s,
        state_version=2,
    )
    with pytest.raises(ValueError):
        registry.register(unit2)


def test_unregistered_key_raises():
    ctx, registry = _ctx()
    session = ctx.sessions.create()
    with pytest.raises(KeyError):
        registry.state_of(session, "nope")


def test_lazy_fold_over_existing_log():
    """单元晚于事件流注册：首次触达时 init 折叠已存在日志。"""
    ctx, registry = _ctx()
    session = ctx.sessions.create()
    session.append("assistant-message", {"content": "早期", "stop_reason": "end-turn"})
    # 事件已发生后才注册单元
    registry.register(make_last_message_unit())
    state = registry.state_of(session, "lastMessage")
    assert state == {"content": "早期", "seq": 0}


def test_dispose_removes_unit():
    ctx, registry = _ctx()
    disposer = registry.register(make_last_message_unit())
    session = ctx.sessions.create()
    assert "lastMessage" in registry._units
    disposer()
    assert "lastMessage" not in registry._units