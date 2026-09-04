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


def test_reasoning_folds_into_thinking():
    events = [
        _ev(0, "user-message", text="问题"),
        _ev(1, "reasoning-chunk", text="让我"),
        _ev(2, "reasoning-chunk", text="想想"),
        _ev(3, "assistant-chunk", text="答"),
        _ev(4, "assistant-message", content="答案", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert turns[1].thinking == "让我想想"   # 思考进 thinking，不进 text
    assert turns[1].text == "答案"


def test_reasoning_rendered_with_dim_markup():
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([
        _ev(0, "reasoning-chunk", text="思考"),
        _ev(1, "assistant-message", content="回复", stop_reason="end-turn"),
    ])
    out = _Transcript().render_turns(turns)
    assert "思考" in out.plain          # 思考文本渲染出来
    assert "回复" in out.plain
    # 思考段带 dim 样式：找到思考文本所在的 span 有 dim 风格
    thinking_styled = any(
        "dim" in getattr(span, "style", "") for span in out.spans if "思考" in out.plain[span.start:span.end]
    )
    assert thinking_styled


def test_markup_brackets_not_parsed_as_style():
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([
        _ev(0, "assistant-message", content='{"x": [1, 2]} 天气[00]:晴朗', stop_reason="end-turn"),
    ])
    out = _Transcript().render_turns(turns)
    # 含 [1, 2] 这类方括号的 payload 不再抛 MarkupError，原样渲染
    assert "[1," in out.plain or "天气" in out.plain


# ---------- M1 bound_body ----------


def test_bound_body_small():
    from minidsh.infrastructure.tui.transcript import bound_body

    assert bound_body("hi") == "hi"
    assert bound_body("") == ""
    assert bound_body(None) == ""


def test_bound_body_large():
    from minidsh.infrastructure.tui.transcript import bound_body, MAX_BLOCK_BODY_CHARS

    big = "x" * (MAX_BLOCK_BODY_CHARS + 1000)
    result = bound_body(big)
    assert len(result) < len(big)
    assert "截断" in result
    assert f"原文 {len(big)} 字符" in result


def test_bound_body_at_limit():
    from minidsh.infrastructure.tui.transcript import bound_body, MAX_BLOCK_BODY_CHARS

    exact = "y" * MAX_BLOCK_BODY_CHARS
    assert bound_body(exact) == exact  # 恰好等于上限，不截断


def test_large_body_in_fold_is_truncated():
    """79KB tool-result 进 fold 后 body 被截断，不会再卡死 Rich Text。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    huge = "Z" * 80_000
    events = [
        _ev(0, "tool-call", name="web_fetch", arguments={"url": "http://x"}),
        _ev(1, "tool-result", name="web_fetch", result=huge, is_error=False),
    ]
    turns = fold(events)
    body = turns[0].blocks[0].body
    assert len(body) <= MAX_BLOCK_BODY_CHARS + 100  # 截断标记额外字符
    assert "截断" in body


def test_render_turns_output_has_upper_bound():
    """render_turns 输出不再含 79KB 纯文本段。"""
    from minidsh.infrastructure.tui.app import _Transcript
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    huge = "Q" * 80_000
    turns = fold([
        _ev(0, "tool-call", name="web_fetch", arguments={"url": "http://x"}),
        _ev(1, "tool-result", name="web_fetch", result=huge, is_error=False),
    ])
    out = _Transcript().render_turns(turns)
    # 输出总长度受限于截断后的 body + 少量装饰文本
    assert len(out.plain) < MAX_BLOCK_BODY_CHARS + 2000


def test_fold_consumes_meta():
    """M5：tool-result 事件带 meta → Block.meta 承接。"""
    events = [
        _ev(0, "tool-call", name="web_fetch", arguments={"url": "http://x"}),
        _ev(1, "tool-result", name="web_fetch", result="body", is_error=False,
            meta={"url": "http://x", "statusCode": 200, "truncated": False}),
    ]
    turns = fold(events)
    block = turns[0].blocks[0]
    assert block.meta == {"url": "http://x", "statusCode": 200, "truncated": False}


def test_fold_without_meta_is_none():
    """无 meta 的 tool-result → Block.meta 为 None（向后兼容）。"""
    events = [
        _ev(0, "tool-call", name="bash", arguments={}),
        _ev(1, "tool-result", name="bash", result="hi", is_error=False),
    ]
    turns = fold(events)
    assert turns[0].blocks[0].meta is None


def test_meta_summary_renders_fetch_and_search():
    from minidsh.infrastructure.tui.app import _meta_summary

    assert "http://x" in _meta_summary({"url": "http://x", "statusCode": 200, "truncated": False})
    assert "truncated" in _meta_summary({"url": "http://x", "statusCode": 200, "truncated": True})
    assert "2 source(s)" in _meta_summary({"sources": [1, 2], "truncated": False})
    assert _meta_summary({"unknown": 1}) == ""
    assert _meta_summary(None) == ""


def test_approval_asked_decided_folds_to_block():
    """M6：approval/asked + approval/decided 配对折叠成审批块。"""
    events = [
        _ev(0, "approval/asked", id="a1", tool_name="bash", reason="敏感操作"),
        _ev(1, "approval/decided", id="a1", outcome="allowed-once"),
    ]
    turns = fold(events)
    blocks = turns[0].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "approval"
    assert blocks[0].state == "done"      # allowed-once → done
    assert "bash" in blocks[0].header
    assert "allowed-once" in blocks[0].body


def test_approval_rejected_is_error_state():
    events = [
        _ev(0, "approval/asked", id="a2", tool_name="bash"),
        _ev(1, "approval/decided", id="a2", outcome="rejected"),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "error"


def test_approval_pending_without_decided():
    """只有 asked 无 decided → pending 状态。"""
    events = [_ev(0, "approval/asked", id="a3", tool_name="bash")]
    blocks = fold(events)[0].blocks
    assert blocks[0].kind == "approval"
    assert blocks[0].state == "pending"


def test_approval_reason_bounded():
    """审批 reason 超长被截断（有界展示）。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    long_reason = "R" * (MAX_BLOCK_BODY_CHARS + 500)
    events = [
        _ev(0, "approval/asked", id="a4", tool_name="bash", reason=long_reason),
        _ev(1, "approval/decided", id="a4", outcome="rejected"),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks[0].body) < len(long_reason)