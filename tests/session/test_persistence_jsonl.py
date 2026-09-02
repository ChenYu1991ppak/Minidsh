"""T4 验收测试：SessionPersistence 协调器 + jsonl 后端。"""
from __future__ import annotations

import json

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.session import Session, SessionEvent, SessionStore
from minidsh.packages.services.persistence import PersistenceCoordinator
from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence


def _harness(tmp_path):
    """装配：Context + SessionStore + Coordinator(jsonl)，返回可继续构造会话的容器。"""
    ctx = Context()
    store = SessionStore(ctx)
    ctx.provide("sessions", store)
    backend = JsonlSessionPersistence(tmp_path)
    coord = PersistenceCoordinator(ctx, backend)
    ctx.provide("sessionPersistence", coord)
    return ctx, store, coord, backend


def _events(session_id, n):
    return [SessionEvent(session_id, i, "user-message", {"n": i}) for i in range(n)]


# ---------- 协调器：seq 连续契约 ----------


def test_append_rejects_seq_gap(tmp_path):
    _, _, coord, _ = _harness(tmp_path)
    with pytest.raises(ValueError):
        coord.append("s", [SessionEvent("s", 5, "user-message")])  # 期望首条 seq=0


def test_append_advances_cursor(tmp_path):
    _, _, coord, _ = _harness(tmp_path)
    coord.append("s", _events("s", 3))
    assert coord.cursors["s"] == 3
    # 续写必须从 seq=3 开始（seq 断裂 → 拒绝）
    coord.append("s", _events("s", 2)[0:0] + [SessionEvent("s", 3, "user-message")])
    assert coord.cursors["s"] == 4


def test_coord_load_aligns_cursor(tmp_path):
    _, _, coord, _ = _harness(tmp_path)
    coord.append("s", _events("s", 4))
    events = coord.load("s")
    assert len(events) == 4
    assert coord.cursors["s"] == 4
    assert coord.load("nope") is None


# ---------- 写路径：订阅 session/event → 边界刷盘 ----------


def test_write_path_flushes_on_assistant_message(tmp_path):
    ctx, store, coord, backend = _harness(tmp_path)
    s = store.create()
    s.append("user-message", {"text": "hi"})       # 不触发刷盘（非边界）
    s.append("assistant-chunk", {"text": "he"})     # 不触发
    s.append("assistant-message", {"text": "hello"})  # 边界 → 刷盘

    events = backend.load_stored(s.id)
    assert events is not None
    assert [e.type for e in events] == [
        "user-message",
        "assistant-chunk",
        "assistant-message",
    ]
    # 边界过后 cursor 对齐
    assert coord.cursors[s.id] == 3


def test_explicit_flush_barrier(tmp_path):
    ctx, store, coord, backend = _harness(tmp_path)
    s = store.create()
    s.append("user-message", {"text": "no boundary yet"})
    assert backend.load_stored(s.id) is None  # 尚未到边界
    ctx.emit("session/flush", s.id)           # 显式屏障
    events = backend.load_stored(s.id)
    assert events is not None and len(events) == 1


# ---------- jsonl 后端：读写 & 行完整性 ----------


def test_jsonl_roundtrip(tmp_path):
    _, store, coord, backend = _harness(tmp_path)
    s = store.create()
    s.append("user-message", {"text": "你好"})
    s.append("assistant-message", {"text": "回复"})

    # 后端直读：两行合法 JSON，字段齐全
    path = backend.log_path(s.id)
    lines = path.read_text(encoding="utf-8").strip("\n").split("\n")
    assert len(lines) == 2
    for line in lines:
        d = json.loads(line)
        assert set(d) == {"session_id", "seq", "type", "payload"}

    loaded = backend.load_stored(s.id)
    assert loaded == s.events()  # 读回与内存日志相等


def test_jsonl_list(tmp_path):
    ctx, store, _, backend = _harness(tmp_path)
    for _ in range(2):
        store.create()
    # 写两个会话各一条边界事件
    for s in store.list():
        s.append("assistant-message")
    assert sorted(backend.list()) == sorted(s.id for s in store.list())


def test_jsonl_load_missing_returns_none(tmp_path):
    _, _, _, backend = _harness(tmp_path)
    assert backend.load_stored("missing") is None