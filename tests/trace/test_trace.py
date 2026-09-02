"""T15/T16 验收测试：trace 渲染 + 落盘接线 + replay 重放。"""
from __future__ import annotations

import io

from minidsh.cordis import Context
from minidsh.packages.services.session import Session, SessionStore
from minidsh.packages.services.persistence import PersistenceCoordinator
from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence
from minidsh.packages.services.persistence.providers.sqlite import SqliteSessionPersistence
from minidsh.packages.services.session.reporting import ConsoleRenderer, load_session_events, render_event, replay_session


def _harness(tmp_path):
    """装配渲染 + jsonl 落盘（两端独立订阅同一条事件流）。

    tmp_path 为 None 时只用内存渲染（不落盘）；否则用 jsonl 落盘。
    """
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    buf = io.StringIO()
    renderer = ConsoleRenderer(ctx, out=buf.write)
    coord = None
    if tmp_path is not None:
        coord = PersistenceCoordinator(ctx, JsonlSessionPersistence(tmp_path))
    return ctx, renderer, coord, buf


# ---------- render_event ----------


def test_render_event_scalar_and_dict():
    from minidsh.packages.services.session import SessionEvent

    line = render_event(SessionEvent("s", 0, "user-message", {"text": "你好"}))
    assert line == "[s:0] user-message text=你好"

    line2 = render_event(
        SessionEvent("s", 1, "tool-call", {"name": "bash", "arguments": {"cmd": "ls"}})
    )
    assert "name=bash" in line2
    assert "arguments={\"cmd\": \"ls\"}" in line2


def test_render_event_folds_newlines():
    from minidsh.packages.services.session import SessionEvent

    line = render_event(SessionEvent("s", 0, "user-message", {"text": "a\nb"}))
    assert "a\\nb" in line
    assert "\n" not in line.split(" ", 1)[1]  # 除首段外无裸换行


# ---------- ConsoleRenderer ----------


def test_renderer_prints_each_event():
    ctx, renderer, coord, buf = _harness(tmp_path=None)
    s = ctx.sessions.create()
    s.append("user-message", {"text": "hi"})
    s.append("assistant-message", {"content": "yo"})

    lines = buf.getvalue().strip("\n").split("\n")
    assert len(lines) == 2
    assert "user-message" in lines[0]
    assert "assistant-message" in lines[1]


def test_renderer_detach_stops_printing():
    ctx, renderer, coord, buf = _harness(tmp_path=None)
    renderer.detach()
    s = ctx.sessions.create()
    s.append("user-message")
    assert buf.getvalue() == ""  # 已取消订阅


# ---------- 落盘接线：渲染 + 落盘独立工作 ----------


def test_render_and_persist_both_happen(tmp_path):
    ctx, renderer, coord, buf = _harness(tmp_path)
    s = ctx.sessions.create()
    s.append("user-message", {"text": "hi"})
    s.append("assistant-message", {"content": "yo"})  # 边界 → 落盘

    # 渲染侧：两条都打印了
    assert len(buf.getvalue().strip("\n").split("\n")) == 2
    # 落盘侧：持久化独立完成
    events = coord.load(s.id)
    assert len(events) == 2


# ---------- replay：load + 渲染 ----------


def test_load_session_events_from_jsonl_dir(tmp_path):
    ctx, renderer, coord, buf = _harness(tmp_path)
    s = ctx.sessions.create()
    s.append("user-message", {"text": "hi"})
    s.append("assistant-message", {"content": "yo"})

    events = load_session_events(tmp_path, session_id=s.id)
    assert [e.type for e in events] == ["user-message", "assistant-message"]


def test_load_session_events_from_sqlite(tmp_path):
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    coord = PersistenceCoordinator(ctx, SqliteSessionPersistence(tmp_path))
    s = ctx.sessions.create()
    s.append("user-message", {"text": "hi"})
    s.append("assistant-message", {"content": "yo"})
    coord.backend.close()

    events = load_session_events(tmp_path, session_id=s.id)
    assert [e.type for e in events] == ["user-message", "assistant-message"]


def test_load_session_events_from_jsonl_file(tmp_path):
    ctx, renderer, coord, buf = _harness(tmp_path)
    s = ctx.sessions.create()
    s.append("user-message", {"text": "hi"})
    s.append("assistant-message", {"content": "yo"})

    jsonl_file = coord.backend.log_path(s.id)
    events = load_session_events(jsonl_file)
    assert [e.type for e in events] == ["user-message", "assistant-message"]


def test_replay_session_orders_by_seq():
    from minidsh.packages.services.session import SessionEvent

    events = [
        SessionEvent("s", 3, "assistant-message", {"content": "later"}),
        SessionEvent("s", 0, "user-message", {"text": "first"}),
    ]
    text = replay_session(events)
    lines = text.split("\n")
    assert "[s:0] user-message" in lines[0]
    assert "[s:3] assistant-message" in lines[1]


def test_load_missing_storage_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        load_session_events(tmp_path / "nope", session_id="x")