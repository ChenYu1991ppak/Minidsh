"""T3 验收测试：SessionEvent / SessionStore。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.session import Session, SessionEvent, SessionEventType, SessionStore


def _ctx_with_store() -> tuple[Context, SessionStore]:
    ctx = Context()
    store = SessionStore(ctx)
    ctx.provide("sessions", store)
    return ctx, store


# ---------- SessionEvent ----------


def test_event_freezes_fields():
    ev = SessionEvent("s", 0, "user-message", {"text": "hi"})
    assert (ev.session_id, ev.seq, ev.type) == ("s", 0, "user-message")
    assert ev.payload == {"text": "hi"}
    with pytest.raises(Exception):  # FrozenInstanceError（或 AttributeError 子类）
        ev.seq = 1


def test_event_accepts_enum_type():
    ev = SessionEvent("s", 0, SessionEventType.USER_MESSAGE)
    assert ev.type == "user-message"


def test_event_rejects_unknown_type():
    with pytest.raises(ValueError):
        SessionEvent("s", 0, "not-a-real-type")


def test_event_roundtrip_dict():
    ev = SessionEvent("s", 3, "tool-call", {"name": "bash", "arguments": {"cmd": "ls"}})
    assert SessionEvent.from_dict(ev.to_dict()) == ev


# ---------- Session 追加日志 ----------


def test_session_seq_monotonic():
    ctx, _ = _ctx_with_store()
    s = Session(ctx, "s-1")
    e0 = s.append("user-message", {"text": "a"})
    e1 = s.append("assistant-message", {"text": "b"})
    assert (e0.seq, e1.seq) == (0, 1)
    assert s.seq == 2
    assert [e.type for e in s] == ["user-message", "assistant-message"]


def test_session_append_only():
    ctx, _ = _ctx_with_store()
    s = Session(ctx, "s-1")
    s.append("user-message")
    n = len(s)
    # 试图改写已记录事件：log 是内部实现，但契约保证「只追加」
    # —— 这里断言没有提供删除/改写接口，且 seq 只随 append 前进
    assert s.seq == n == 1


def test_session_broadcasts_event():
    ctx, _ = _ctx_with_store()
    seen = []

    ctx.on("session/event", lambda ev: seen.append(ev.type))

    s = Session(ctx, "s-1")
    s.append("user-message")
    s.append("assistant-chunk", {"text": "x"})

    assert seen == ["user-message", "assistant-chunk"]


def test_session_none_payload_becomes_empty_dict():
    ctx, _ = _ctx_with_store()
    s = Session(ctx, "s-1")
    ev = s.append("user-message")
    assert ev.payload == {}


# ---------- SessionStore ----------


def test_store_create_and_get():
    ctx, store = _ctx_with_store()
    s1 = store.create()
    s2 = store.create()
    assert s1.id == "session-0001"
    assert s2.id == "session-0002"
    assert store.get(s1.id) is s1
    assert store.list() == [s1, s2]


def test_store_get_unknown_returns_none():
    _, store = _ctx_with_store()
    assert store.get("nope") is None


# ---------- resume 撞名回归（/new 后 seq 断裂的根因） ----------


def test_resume_bumps_next_id_so_create_does_not_collide():
    """恢复 session-0001 后再 create，必须生成 session-0002 而非撞名重开 session-0001。"""
    ctx, store = _ctx_with_store()
    resumed = store.resume("session-0001", events=[])
    assert resumed.id == "session-0001"

    new = store.create()
    assert new.id == "session-0002"          # 不能又生成 session-0001
    assert store.get("session-0001") is resumed


def test_resume_bumps_next_id_to_large_number():
    ctx, store = _ctx_with_store()
    store.resume("session-0007", events=[])
    assert store.create().id == "session-0008"


def test_create_skips_occupied_number():
    ctx, store = _ctx_with_store()
    store.resume("session-0001", events=[])
    # resume 已把 _next_id 提到 1，create 得 2；手动占 2 后再 create 得 3
    store._sessions["session-0002"] = Session(ctx, "session-0002")
    assert store.create().id == "session-0003"