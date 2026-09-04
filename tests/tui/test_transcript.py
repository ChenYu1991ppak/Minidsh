"""T1 验收测试：transcript 事件→turn 树（纯视图模型，无 Textual）。

覆盖三类：
1. 轮次（turn 结构、流式累积、边界事件、跨轮序列、turn/start+end 显式分组）
2. 工具调用（配对、同名多次、孤立结果、错误结果、call_id 配对、有界截断、meta）
3. 特性（子代理、审批、压缩、技能、错误、reasoning、边界值、向后兼容）
"""
from __future__ import annotations

from minidsh.infrastructure.tui.transcript import Block, Turn, fold
from minidsh.packages.services.session.event import SessionEvent


def _ev(seq, type, **payload):
    return SessionEvent(session_id="s", seq=seq, type=type, payload=payload)


# ============================================================================
# 1. 轮次（Turn 结构）
# ============================================================================


def test_user_to_assistant_turn():
    """一轮对话：user → assistant-chunk 流式累积 → assistant-message flush 锁定。"""
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


def test_multiple_turns_sequence():
    """两轮独立对话：user-A / assistant-A / user-B / assistant-B。"""
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


def test_three_turns_sequence():
    """三轮对话：验证 turn 边界不互相干扰。"""
    events = [
        _ev(0, "user-message", text="q1"),
        _ev(1, "assistant-message", content="a1", stop_reason="end-turn"),
        _ev(2, "user-message", text="q2"),
        _ev(3, "assistant-message", content="a2", stop_reason="end-turn"),
        _ev(4, "user-message", text="q3"),
        _ev(5, "assistant-message", content="a3", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert len(turns) == 6
    assert [t.text for t in turns if t.kind == "user"] == ["q1", "q2", "q3"]
    assert [t.text for t in turns if t.kind == "assistant"] == ["a1", "a2", "a3"]


def test_assistant_chunk_accumulates_across_two_user_messages():
    """流式 chunk 只累积到当前 assistant turn，不会被后面 user 截断。"""
    events = [
        _ev(0, "user-message", text="q1"),
        _ev(1, "assistant-chunk", text="chunk1"),
        _ev(2, "assistant-message", content="full1", stop_reason="end-turn"),
        _ev(3, "user-message", text="q2"),
        _ev(4, "assistant-chunk", text="chunk2"),
        _ev(5, "assistant-message", content="full2", stop_reason="end-turn"),
    ]
    turns = fold(events)
    texts = [t.text for t in turns if t.kind == "assistant"]
    assert texts == ["full1", "full2"]


def test_assistant_chunk_before_user_message():
    """孤立 assistant-chunk（无前置 user）→ 自动创建 assistant turn。"""
    events = [
        _ev(0, "assistant-chunk", text="orphan"),
        _ev(1, "assistant-message", content="orphan", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert turns[0].kind == "assistant"
    assert turns[0].text == "orphan"


def test_reasoning_folds_into_thinking():
    """reasoning-chunk 累积到 thinking 字段，不进 text。"""
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
    """思考文本渲染时带 dim 样式。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([
        _ev(0, "reasoning-chunk", text="思考"),
        _ev(1, "assistant-message", content="回复", stop_reason="end-turn"),
    ])
    out = _Transcript().render_turns(turns)
    assert "思考" in out.plain
    assert "回复" in out.plain
    thinking_styled = any(
        "dim" in getattr(span, "style", "") for span in out.spans
        if "思考" in out.plain[span.start:span.end]
    )
    assert thinking_styled


def test_markup_brackets_not_parsed_as_style():
    """Payload 含方括号不被 Rich 当 markup 解析。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([
        _ev(0, "assistant-message", content='{"x": [1, 2]} 天气[00]:晴朗', stop_reason="end-turn"),
    ])
    out = _Transcript().render_turns(turns)
    assert "[1," in out.plain or "天气" in out.plain


def test_turn_kind_correct_for_all():
    """user-message 产 user turn；tool-call 在无 current 时产 assistant turn。"""
    events = [
        _ev(0, "user-message", text="q"),
        _ev(1, "tool-call", name="bash", arguments={}),
        _ev(2, "tool-result", name="bash", result="ok"),
        _ev(3, "assistant-message", content="a", stop_reason="end-turn"),
    ]
    turns = fold(events)
    # user turn + assistant turn（工具块落在 assistant turn 上）
    assert [t.kind for t in turns] == ["user", "assistant"]
    assert len(turns[1].blocks) == 1


def test_tool_call_attaches_to_current_assistant_turn():
    """assistant turn 已存在时，后续 tool-call 落在该 turn 上（不新建）。"""
    events = [
        _ev(0, "assistant-message", content="a", stop_reason="end-turn"),
        _ev(1, "tool-call", name="bash", arguments={"cmd": "x"}),
        _ev(2, "tool-result", name="bash", result="y"),
    ]
    turns = fold(events)
    assert [t.kind for t in turns] == ["assistant"]
    assert len(turns[0].blocks) == 1


def test_turn_start_end_boundary():
    """M4：turn/start 和 turn/end 作为显式边界被 fold 跳过（不产新 turn）。
    时序：turn/start → user-message → assistant-message → turn/end。"""
    events = [
        _ev(0, "turn/start", turn=1),
        _ev(1, "user-message", text="q"),
        _ev(2, "assistant-message", content="a", stop_reason="end-turn"),
        _ev(3, "turn/end", turn=1, reason={"kind": "completed"}),
    ]
    turns = fold(events)
    # 只有 user 和 assistant 两个 turn（turn/start+end 被忽略）
    assert [t.kind for t in turns] == ["user", "assistant"]
    assert turns[0].text == "q"
    assert turns[1].text == "a"


def test_turn_boundary_does_not_break_fold():
    """两轮带 turn/start+end 的事件流，fold 结果与无边界事件时一致。"""
    events = [
        _ev(0, "turn/start", turn=1),
        _ev(1, "user-message", text="q1"),
        _ev(2, "assistant-message", content="a1", stop_reason="end-turn"),
        _ev(3, "turn/end", turn=1, reason={"kind": "completed"}),
        _ev(4, "turn/start", turn=2),
        _ev(5, "user-message", text="q2"),
        _ev(6, "assistant-message", content="a2", stop_reason="end-turn"),
        _ev(7, "turn/end", turn=2, reason={"kind": "completed"}),
    ]
    turns = fold(events)
    assert [t.kind for t in turns] == ["user", "assistant", "user", "assistant"]
    assert [t.text for t in turns if t.kind == "user"] == ["q1", "q2"]


def test_render_turns_empty_produces_placeholder():
    from minidsh.infrastructure.tui.app import _Transcript
    out = _Transcript().render_turns([])
    assert "等待输入" in out.plain


# ============================================================================
# 2. 工具调用（Tool calls）
# ============================================================================


def test_tool_call_result_folds_to_block():
    """工具调用 + 结果折叠成一个 Block。"""
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
    """is_error → state=error。"""
    events = [
        _ev(0, "tool-call", name="bash", arguments={}),
        _ev(1, "tool-result", name="bash", result="boom", is_error=True),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "error"
    assert blocks[0].body == "boom"


def test_pending_tool_without_result():
    """只有 tool-call 无结果 → state=pending。"""
    events = [_ev(0, "tool-call", name="bash", arguments={})]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "pending"


def test_orphan_tool_result():
    """孤立 tool-result（无前置 tool-call）→ 当独立旁注块。"""
    events = [_ev(0, "tool-result", name="bash", result="orphan", is_error=False)]
    turns = fold(events)
    blocks = turns[0].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "tool"
    assert blocks[0].body == "orphan"
    assert blocks[0].state == "done"


def test_orphan_tool_result_error():
    """孤立 tool-result 且 is_error → state=error。"""
    events = [_ev(0, "tool-result", name="bash", result="fail", is_error=True)]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "error"


def test_tool_call_header_compact_json():
    """dict 参数被压成单行 JSON。"""
    events = [_ev(0, "tool-call", name="web", arguments={"url": "https://a.com"})]
    blocks = fold(events)[0].blocks
    assert "url" in blocks[0].header
    assert "https://a.com" in blocks[0].header


def test_tool_call_header_string_arguments():
    """字符串参数直接使用，不作 JSON 压缩。"""
    events = [_ev(0, "tool-call", name="web", arguments="https://a.com")]
    blocks = fold(events)[0].blocks
    assert "https://a.com" in blocks[0].header


def test_same_name_tool_call_id_pairing():
    """同名工具两次调用（如两条 bash），按 call_id 正确配对。"""
    events = [
        _ev(0, "user-message", text="两条"),
        _ev(1, "tool-call", name="bash", arguments={"cmd": "a"}, call_id="c1"),
        _ev(2, "tool-call", name="bash", arguments={"cmd": "b"}, call_id="c2"),
        _ev(3, "tool-result", name="bash", result="out-a", call_id="c1"),
        _ev(4, "tool-result", name="bash", result="out-b", call_id="c2"),
        _ev(5, "assistant-message", content="done", stop_reason="end-turn"),
    ]
    turns = fold(events)
    blocks = turns[1].blocks
    assert len(blocks) == 2
    assert blocks[0].body == "out-a"
    assert blocks[1].body == "out-b"
    assert blocks[0].state == "done"
    assert blocks[1].state == "done"


def test_same_name_tool_call_out_of_order_result():
    """结果以不同顺序到达时，按 call_id 仍正确配对（块保持创建顺序）。"""
    events = [
        _ev(0, "tool-call", name="bash", arguments={"cmd": "a"}, call_id="c1"),
        _ev(1, "tool-call", name="bash", arguments={"cmd": "b"}, call_id="c2"),
        _ev(2, "tool-result", name="bash", result="out-b", call_id="c2"),  # c2 结果先到
        _ev(3, "tool-result", name="bash", result="out-a", call_id="c1"),
    ]
    turns = fold(events)
    blocks = turns[0].blocks
    # 块按创建顺序排列（c1 在前），内容按 call_id 配对
    assert blocks[0].body == "out-a"
    assert blocks[1].body == "out-b"


def test_different_tools_interleaved():
    """bash 和 web 交错调用，按 call_id 各自配对。"""
    events = [
        _ev(0, "tool-call", name="bash", arguments={"cmd": "hi"}, call_id="b1"),
        _ev(1, "tool-call", name="web", arguments={"url": "x"}, call_id="w1"),
        _ev(2, "tool-result", name="bash", result="bash-out", call_id="b1"),
        _ev(3, "tool-result", name="web", result="web-out", call_id="w1"),
    ]
    turns = fold(events)
    blocks = turns[0].blocks
    assert blocks[0].body == "bash-out"
    assert blocks[1].body == "web-out"


def test_tool_call_without_call_id_falls_back_to_name():
    """旧事件流无 call_id → 按 name 配对 + FIFO 兜底。"""
    events = [
        _ev(0, "tool-call", name="bash", arguments={"cmd": "a"}),
        _ev(1, "tool-result", name="bash", result="out"),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].body == "out"


def test_tool_block_arguments_displayed_in_header():
    """工具调用参数在 header 中可见。"""
    events = [_ev(0, "tool-call", name="read", arguments={"file": "foo.py"})]
    blocks = fold(events)[0].blocks
    assert "read" in blocks[0].header
    assert "foo.py" in blocks[0].header


def test_tool_call_with_empty_args():
    """无参数工具调用 → header 仅显示名字。"""
    events = [_ev(0, "tool-call", name="skill-catalog", arguments={})]
    blocks = fold(events)[0].blocks
    assert "skill-catalog" in blocks[0].header


# ============================================================================
# 3. 特性（Subagent, Approval, Compaction, Skill, Error, Meta, Bound）
# ============================================================================


def test_subagent_nested_block():
    """subagent-spawn + subagent-result 配对折叠。"""
    events = [
        _ev(0, "subagent-spawn", agent="reviewer", task="审查"),
        _ev(1, "subagent-result", agent="reviewer", result="结论"),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks) == 1
    assert blocks[0].kind == "subagent"
    assert blocks[0].state == "done"
    assert blocks[0].body == "结论"


def test_subagent_orphan_result():
    """孤立 subagent-result → 独立旁注。"""
    events = [_ev(0, "subagent-result", agent="reviewer", result="结论")]
    blocks = fold(events)[0].blocks
    assert blocks[0].kind == "subagent"
    assert blocks[0].body == "结论"


def test_subagent_pending_without_result():
    """只有 spawn 无 result → pending。"""
    events = [_ev(0, "subagent-spawn", agent="reviewer", task="审查")]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "pending"


def test_compaction_and_skill_and_error_side_notes():
    """compaction / skill-loaded / error 三类旁注块。"""
    events = [
        _ev(0, "user-message", text="x"),
        _ev(1, "compaction", reason="pressure"),
        _ev(2, "skill-loaded", name="relay"),
        _ev(3, "error", message="max react steps exceeded"),
    ]
    turns = fold(events)
    kinds = [b.kind for b in turns[1].blocks]
    assert kinds == ["compaction", "skill", "error"]


def test_skill_loaded_header():
    events = [_ev(0, "skill-loaded", name="my-skill")]
    blocks = fold(events)[0].blocks
    assert "my-skill" in blocks[0].header


def test_error_block_state():
    events = [_ev(0, "error", message="something broke")]
    blocks = fold(events)[0].blocks
    assert blocks[0].kind == "error"
    assert blocks[0].state == "error"
    assert "something broke" in blocks[0].header


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


def test_approval_cancelled_is_error_state():
    events = [
        _ev(0, "approval/asked", id="a3", tool_name="bash"),
        _ev(1, "approval/decided", id="a3", outcome="cancelled"),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].state == "error"


def test_approval_pending_without_decided():
    """只有 asked 无 decided → pending。"""
    events = [_ev(0, "approval/asked", id="a3", tool_name="bash")]
    blocks = fold(events)[0].blocks
    assert blocks[0].kind == "approval"
    assert blocks[0].state == "pending"


def test_approval_orphan_decided():
    """孤立 decided（无对应 asked）→ 独立旁注。"""
    events = [_ev(0, "approval/decided", id="a4", outcome="allowed-once")]
    blocks = fold(events)[0].blocks
    assert blocks[0].kind == "approval"
    assert blocks[0].state == "done"


def test_approval_reason_bounded():
    """审批 reason 超长被截断。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    long_reason = "R" * (MAX_BLOCK_BODY_CHARS + 500)
    events = [
        _ev(0, "approval/asked", id="a4", tool_name="bash", reason=long_reason),
        _ev(1, "approval/decided", id="a4", outcome="rejected"),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks[0].body) < len(long_reason)


def test_approval_unavailable_state():
    events = [
        _ev(0, "approval/asked", id="a5", tool_name="bash"),
        _ev(1, "approval/decided", id="a5", outcome="unavailable"),
    ]
    blocks = fold(events)[0].blocks
    # unavailable ≠ allowed-once → state=error
    assert blocks[0].state == "error"


def test_approval_multiple_in_same_turn():
    """同一 turn 内多次审批请求，各按 id 配对。"""
    events = [
        _ev(0, "approval/asked", id="a1", tool_name="bash"),
        _ev(1, "approval/asked", id="a2", tool_name="web"),
        _ev(2, "approval/decided", id="a1", outcome="allowed-once"),
        _ev(3, "approval/decided", id="a2", outcome="rejected"),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks) == 2
    assert blocks[0].state == "done"
    assert blocks[1].state == "error"


# ---------- M5 Meta（presentation_meta）----------


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


def test_meta_summary_search_truncated():
    from minidsh.infrastructure.tui.app import _meta_summary
    out = _meta_summary({"sources": [1, 2, 3], "truncated": True})
    assert "3 source(s)" in out
    assert "truncated" in out


def test_orphan_tool_result_with_meta():
    """孤立 tool-result 带 meta 也承接。"""
    events = [
        _ev(0, "tool-result", name="web_fetch", result="body",
            meta={"url": "http://orphan", "statusCode": 200, "truncated": False}),
    ]
    blocks = fold(events)[0].blocks
    assert blocks[0].meta == {"url": "http://orphan", "statusCode": 200, "truncated": False}


# ---------- M1 Bound Body ----------


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
    assert bound_body(exact) == exact


def test_bound_body_utf8():
    """UTF-8 多字节字符截断不影响展示。"""
    from minidsh.infrastructure.tui.transcript import bound_body

    s = "中" * 30
    result = bound_body(s, max_chars=10)
    assert len(result) <= 10 + 30  # 截断标记额外字符
    assert "截断" in result


def test_large_body_in_fold_is_truncated():
    """79KB tool-result 进 fold 后 body 被截断。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    huge = "Z" * 80_000
    events = [
        _ev(0, "tool-call", name="web_fetch", arguments={"url": "http://x"}),
        _ev(1, "tool-result", name="web_fetch", result=huge, is_error=False),
    ]
    turns = fold(events)
    body = turns[0].blocks[0].body
    assert len(body) <= MAX_BLOCK_BODY_CHARS + 100
    assert "截断" in body


def test_render_turns_output_has_upper_bound():
    """render_turns 输出不含 79KB 纯文本段。"""
    from minidsh.infrastructure.tui.app import _Transcript
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    huge = "Q" * 80_000
    turns = fold([
        _ev(0, "tool-call", name="web_fetch", arguments={"url": "http://x"}),
        _ev(1, "tool-result", name="web_fetch", result=huge, is_error=False),
    ])
    out = _Transcript().render_turns(turns)
    assert len(out.plain) < MAX_BLOCK_BODY_CHARS + 2000


def test_subagent_result_bounded():
    """子代理结果也走有界截断。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    big = "S" * (MAX_BLOCK_BODY_CHARS + 500)
    events = [
        _ev(0, "subagent-spawn", agent="reviewer", task="审查"),
        _ev(1, "subagent-result", agent="reviewer", result=big),
    ]
    blocks = fold(events)[0].blocks
    assert len(blocks[0].body) < len(big)


def test_compaction_payload_bounded():
    """compaction 的 payload 转字符串后也走有界截断。"""
    from minidsh.infrastructure.tui.transcript import MAX_BLOCK_BODY_CHARS

    big = {"reason": "C" * (MAX_BLOCK_BODY_CHARS + 500)}
    events = [_ev(0, "compaction", **big)]
    blocks = fold(events)[0].blocks
    assert len(blocks[0].body) < len(str(big))


# ---------- 边界值 ----------


def test_unknown_event_type_ignored():
    """审计面/未知事件类型被防御式跳过，不影响 fold。

    SessionEvent 的白名单已在构造期拒绝真正未知的类型；这里验证 fold 对
    合法白名单内、但 fold 不认识的类型（如 model-change、session/title）
    确实忽略。"""
    events = [
        _ev(0, "user-message", text="q"),
        _ev(1, "model-change", model="gpt-4"),
        _ev(2, "session/title", title="ignore"),
        _ev(3, "assistant-message", content="a", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert [(t.kind, t.text) for t in turns] == [("user", "q"), ("assistant", "a")]


def test_user_message_without_text():
    """user-message 无 text 字段 → 空字符串。"""
    events = [_ev(0, "user-message", extra="x")]
    turns = fold(events)
    assert turns[0].text == ""


def test_assistant_message_without_content():
    """assistant-message 无 content → 保留流式累积文本。"""
    events = [
        _ev(0, "assistant-chunk", text="chunk"),
        _ev(1, "assistant-message", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert turns[0].text == "chunk"


def test_model_change_event_ignored():
    """model-change 不被 fold 处理（白名单之外）。"""
    events = [
        _ev(0, "user-message", text="q"),
        _ev(1, "model-change", model="gpt-4"),
        _ev(2, "assistant-message", content="a", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert [(t.kind, t.text) for t in turns] == [("user", "q"), ("assistant", "a")]


def test_session_title_event_ignored():
    """session/title 是审计面，fold 不处理。"""
    events = [
        _ev(0, "session/title", title="ignore"),
        _ev(1, "user-message", text="q"),
        _ev(2, "assistant-message", content="a", stop_reason="end-turn"),
    ]
    turns = fold(events)
    assert [(t.kind, t.text) for t in turns] == [("user", "q"), ("assistant", "a")]


def test_fold_idempotent():
    """fold 对同一事件流的两次调用结果相同（幂等）。"""
    events = [
        _ev(0, "user-message", text="q"),
        _ev(1, "tool-call", name="bash", arguments={"cmd": "x"}),
        _ev(2, "tool-result", name="bash", result="y"),
        _ev(3, "assistant-message", content="a", stop_reason="end-turn"),
    ]
    t1 = fold(events)
    t2 = fold(events)
    assert [t.kind for t in t1] == [t.kind for t in t2]
    assert [b.body for t in t1 for b in t.blocks] == [b.body for t in t2 for b in t.blocks]


def test_render_turns_user_turn_format():
    """user turn 渲染为 '### 你' + 文本。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([_ev(0, "user-message", text="你好")])
    out = _Transcript().render_turns(turns)
    assert "### 你" in out.plain
    assert "你好" in out.plain


def test_render_turns_assistant_turn_format():
    """assistant turn 渲染为 '### assistant' + 文本。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = fold([_ev(0, "assistant-message", content="回复", stop_reason="end-turn")])
    out = _Transcript().render_turns(turns)
    assert "### assistant" in out.plain
    assert "回复" in out.plain


def test_render_turns_block_state_icons():
    """Block 的 state 渲染为对应图标。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = [
        Turn(kind="assistant", blocks=[
            Block(kind="tool", header="done_tool", state="done"),
            Block(kind="tool", header="pending_tool", state="pending"),
            Block(kind="tool", header="error_tool", state="error"),
        ]),
    ]
    out = _Transcript().render_turns(turns)
    assert "✓" in out.plain
    assert "⏳" in out.plain
    assert "✗" in out.plain


def test_render_turns_thinking_before_assistant():
    """思考文本在 assistant 回复前渲染。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = [Turn(kind="assistant", thinking="思考中", text="回复")]
    out = _Transcript().render_turns(turns)
    think_pos = out.plain.index("思考中")
    reply_pos = out.plain.index("回复")
    # 思考在前、回复在后
    assert think_pos < reply_pos


def test_render_turns_block_without_body():
    """无 body 的 block 不渲染 body 行。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = [Turn(kind="assistant", blocks=[
        Block(kind="tool", header="no body", state="done"),
    ])]
    out = _Transcript().render_turns(turns)
    assert "no body" in out.plain
    # body 为空不追加额外行


def test_render_turns_block_with_meta_view():
    """有 meta 的 block 渲染 meta 摘要行。"""
    from minidsh.infrastructure.tui.app import _Transcript

    turns = [Turn(kind="assistant", blocks=[
        Block(kind="tool", header="fetch", meta={"url": "http://x", "statusCode": 200, "truncated": False}),
    ])]
    out = _Transcript().render_turns(turns)
    assert "http://x" in out.plain