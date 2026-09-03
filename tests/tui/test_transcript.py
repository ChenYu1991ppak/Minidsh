"""T1 验收测试：transcript 事件→turn 树（纯视图模型，无 Textual）。"""
from __future__ import annotations

from minidsh.infrastructure.tui.transcript import Block, Turn, fold

from minidsh.packages.services.session.event import SessionEvent


def _ev(seq, type, **payload):
    return SessionEvent(session_id="s", seq=seq, type=type, payload=payload)


def test_user_to_assistant_turn():
    events = [
        _ev(0, "user-message", text="你好"),
        _ev(1, "assistant-chunk", text="你"),
        _ev(2, "assistant-chunk", text="好"),
        _ev(3, "assistant-message", content="你好", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert [t.kind for t in turns] == ["user", "assistant"]
    assert turns[0].text == "你好"
    assert turns[1].text == "你好"  # 流式累积 + flush 锁定


def test_empty_events_yields_empty():
    assert fold([]) == []


def test_tool_call_result_folds_to_block():
    events = [
        _ev(0, "user-message", text="跑命令"),
        _ev(1, "tool-call", name="bash", arguments={"cmd": "echo hi"}),
        _ev(2, "tool-result", name="bash", result="hi", is_error=False),
        _ev(3, "assistant-message", content="完成", stop_reason="end-turn"),
    ]
    turns = fold(events)
    blocks = turns[1].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "tool"
    assert blocks[0].state == "done"
    assert "echo" in blocks[0].header
    assert blocks[0].body == "hi"


def test_tool_result_is_error():
    events = [
        _ev(0, "tool-call", name="bash", arguments={}),
        _ev(1, "tool-result", name="bash", result="boom", is_error=True),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "error"
    assert blocks[0].body == "boom"


def test_pending_tool_without_result():
    events = [_ev(0, "tool-call", name="bash", arguments={})]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "pending"


def test_subagent_nested_block():
    events = [
        _ev(0, "subagent-spawn", agent="reviewer", task="审查"),
        _ev(1, "subagent-result", agent="reviewer", result="结论"),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "subagent"
    assert blocks[0].state == "done"
    assert blocks[0].body == "结论"


def test_compaction_and_skill_and_error_side_notes():
    events = [
        _ev(0, "user-message", text="x"),
        _ev(1, "compaction", reason="pressure"),
        _ev(2, "skill-loaded", name="relay"),
        _ev(3, "error", message="max react steps exceeded"),
    ]
    turns = fold(events)
    kinds = [b.kind for b in turns[1].blocks]
    assert kinds == ["compaction", "skill", "error"]


def test_multiple_turns_sequence():
    events = [
        _ev(0, "user-message", text="a"),
        _ev(1, "assistant-message", content="A", stop_reason="end-turn"),
        _ev(2, "user-message", text="b"),
        _ev(3, "assistant-message", content="B", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert [(t.kind, t.text) for t in turns] == [
        ("user", "a"), ("assistant", "A"), ("user", "b"), ("assistant", "B"),
    ]