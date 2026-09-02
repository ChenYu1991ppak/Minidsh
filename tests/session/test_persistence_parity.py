"""T5 验收测试：sqlite 后端 + 双后端回放等价。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.persistence import PersistenceCoordinator
from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence
from minidsh.packages.services.persistence.providers.sqlite import SqliteSessionPersistence


def _feed_and_flush(ctx, store):
    """构造一个带完整事件流的会话并经边界 flush 落盘。"""
    s = store.create()
    s.append("user-message", {"text": "你好"})
    s.append("assistant-chunk", {"text": "ch-1"})
    s.append("tool-call", {"name": "bash", "arguments": {"cmd": "ls"}})
    s.append("tool-result", {"name": "bash", "result": {"ok": True}})
    s.append("assistant-message", {"text": "完成"})  # 边界 → 刷盘
    return s


def _sqlite_harness(tmp_path):
    ctx = Context()
    store = SessionStore(ctx)
    ctx.provide("sessions", store)
    backend = SqliteSessionPersistence(tmp_path)
    coord = PersistenceCoordinator(ctx, backend)
    ctx.provide("sessionPersistence", coord)
    return ctx, store, coord, backend


# ---------- sqlite 后端：读写 ----------


def test_sqlite_roundtrip(tmp_path):
    ctx, store, _, backend = _sqlite_harness(tmp_path)
    s = _feed_and_flush(ctx, store)
    loaded = backend.load_stored(s.id)
    assert loaded == s.events()
    backend.close()


def test_sqlite_list(tmp_path):
    ctx, store, coord, backend = _sqlite_harness(tmp_path)
    s1 = _feed_and_flush(ctx, store)
    s2 = _feed_and_flush(ctx, store)
    assert backend.list() == [s1.id, s2.id]
    backend.close()


def test_sqlite_load_unknown_session_returns_none(tmp_path):
    _, _, _, backend = _sqlite_harness(tmp_path)
    assert backend.load_stored("missing") is None
    backend.close()


def test_sqlite_seq_primary_key_guards_duplicate(tmp_path):
    """直接对 backend 写同 seq 两行：主键 (session_id, seq) 使后写覆盖先写。"""
    _, _, _, backend = _sqlite_harness(tmp_path)
    from minidsh.packages.services.session import SessionEvent

    # 绕过协调器的 seq 连续校验，直接测存储层主键去重
    backend.append_batch("s", [SessionEvent("s", 0, "user-message")])
    backend.append_batch("s", [SessionEvent("s", 0, "assistant-message")])
    events = backend.load_stored("s")
    assert len(events) == 1
    assert events[0].type == "assistant-message"
    backend.close()


# ---------- 双后端回放等价（T5 强制验收） ----------


def test_jsonl_sqlite_replay_parity(tmp_path):
    """同一会话写入 jsonl 与 sqlite 两后端，load 结果逐条相等。"""
    # 用同一事件流分别喂给两个独立 harness
    jsonl_dir = tmp_path / "jsonl"
    sqlite_dir = tmp_path / "sqlite"

    # jsonl 侧
    ctx1 = Context()
    store1 = SessionStore(ctx1)
    ctx1.provide("sessions", store1)
    coord1 = PersistenceCoordinator(ctx1, JsonlSessionPersistence(jsonl_dir))
    s1 = _feed_and_flush(ctx1, store1)
    jsonl_loaded = coord1.load(s1.id)

    # sqlite 侧
    ctx2 = Context()
    store2 = SessionStore(ctx2)
    ctx2.provide("sessions", store2)
    backend2 = SqliteSessionPersistence(sqlite_dir)
    coord2 = PersistenceCoordinator(ctx2, backend2)
    s2 = _feed_and_flush(ctx2, store2)
    sqlite_loaded = coord2.load(s2.id)
    backend2.close()

    # 回放等价：逐条字段相等
    assert len(jsonl_loaded) == len(sqlite_loaded)
    for je, se in zip(jsonl_loaded, sqlite_loaded):
        assert je.session_id == se.session_id == s1.id == s2.id
        assert je.seq == se.seq
        assert je.type == se.type
        assert je.payload == se.payload
    # 明确断言事件类型序列符合契约（白名单 + 顺序）
    assert [e.type for e in jsonl_loaded] == [
        "user-message",
        "assistant-chunk",
        "tool-call",
        "tool-result",
        "assistant-message",
    ]