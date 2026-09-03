"""默认接上次会话 + /new 新会话 的验收测试。"""
from __future__ import annotations

from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence
from minidsh.packages.services.persistence.providers.sqlite import SqliteSessionPersistence
from minidsh.packages.services.session.event import SessionEvent


def test_jsonl_latest_returns_most_recent(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    backend.append_batch("session-0001", [SessionEvent("session-0001", 0, "user-message", {"text": "a"})])
    backend.append_batch("session-0002", [SessionEvent("session-0002", 0, "user-message", {"text": "b"})])
    assert backend.latest() == "session-0002"


def test_jsonl_latest_empty_returns_none(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    assert backend.latest() is None


def test_sqlite_latest_returns_most_recent(tmp_path):
    backend = SqliteSessionPersistence(tmp_path)
    backend.append_batch("session-0001", [SessionEvent("session-0001", 0, "user-message", {"text": "a"})])
    backend.append_batch("session-0002", [SessionEvent("session-0002", 0, "user-message", {"text": "b"})])
    assert backend.latest() == "session-0002"
    backend.close()


def test_sqlite_latest_empty_returns_none(tmp_path):
    backend = SqliteSessionPersistence(tmp_path)
    assert backend.latest() is None
    backend.close()