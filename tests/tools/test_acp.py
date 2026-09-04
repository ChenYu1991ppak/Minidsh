"""M3 验收测试：ACP JSON-RPC stdio server（传输 + 事件映射 + 分发 + 端到端）。"""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.acp import AcpServerProvider
from minidsh.packages.services.acp.providers import transport
from minidsh.packages.services.session import SessionStore
from minidsh.infrastructure.config import Config


# ---------------------------------------------------------------------------
# 传输层（纯函数）
# ---------------------------------------------------------------------------


def test_read_request_valid():
    assert transport.read_request('{"jsonrpc":"2.0","method":"initialize","id":1}') == {
        "jsonrpc": "2.0", "method": "initialize", "id": 1
    }


def test_read_request_blank_and_invalid():
    assert transport.read_request("") is None
    assert transport.read_request("   ") is None
    assert transport.read_request("{not json") is None
    assert transport.read_request("[1,2]") is None  # 非对象


def test_write_response_json():
    out = io.StringIO()
    transport.write_response(1, {"protocolVersion": 1}, stream=out)
    obj = json.loads(out.getvalue())
    assert obj["jsonrpc"] == "2.0"
    assert obj["id"] == 1
    assert obj["result"] == {"protocolVersion": 1}


def test_write_notification_no_id():
    out = io.StringIO()
    transport.write_notification("session/update", {"sessionId": "s1"}, stream=out)
    obj = json.loads(out.getvalue())
    assert obj["jsonrpc"] == "2.0"
    assert obj["method"] == "session/update"
    assert "id" not in obj


def test_write_error():
    out = io.StringIO()
    transport.write_error(1, transport.JsonRpcError(-32601, "unknown"), stream=out)
    obj = json.loads(out.getvalue())
    assert obj["error"]["code"] == -32601
    assert obj["error"]["message"] == "unknown"


def test_jsonrpc_error_to_dict():
    e = transport.JsonRpcError(-32602, "bad", data={"x": 1})
    assert e.to_dict() == {"code": -32602, "message": "bad", "data": {"x": 1}}


# ---------------------------------------------------------------------------
# 事件映射（纯函数）
# ---------------------------------------------------------------------------


def _ev(session_id, type_, **payload):
    from minidsh.packages.services.session.event import SessionEvent
    return SessionEvent(session_id=session_id, seq=0, type=type_, payload=payload)


def test_to_update_message_chunk():
    from minidsh.packages.services.acp.definition import AGENT_MESSAGE_CHUNK

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    server = AcpServerProvider(ctx)
    update = server._to_update(_ev("s1", "assistant-chunk", text="你好"))
    assert update["sessionUpdate"] == AGENT_MESSAGE_CHUNK
    assert update["content"]["text"] == "你好"


def test_to_update_thought_chunk():
    from minidsh.packages.services.acp.definition import AGENT_THOUGHT_CHUNK

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    server = AcpServerProvider(ctx)
    update = server._to_update(_ev("s1", "reasoning-chunk", text="思考"))
    assert update["sessionUpdate"] == AGENT_THOUGHT_CHUNK


def test_to_update_tool_call_and_result():
    from minidsh.packages.services.acp.definition import TOOL_CALL, TOOL_CALL_UPDATE

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    server = AcpServerProvider(ctx)
    call = server._to_update(_ev("s1", "tool-call", name="bash", call_id="c1"))
    assert call["sessionUpdate"] == TOOL_CALL
    assert call["toolCallId"] == "c1"
    assert call["status"] == "in_progress"

    result = server._to_update(_ev("s1", "tool-result", result="hi", call_id="c1"))
    assert result["sessionUpdate"] == TOOL_CALL_UPDATE
    assert result["toolCallId"] == "c1"


def test_to_update_ignores_audit_events():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    server = AcpServerProvider(ctx)
    assert server._to_update(_ev("s1", "turn/start", turn=1)) is None
    assert server._to_update(_ev("s1", "session/title", title="x")) is None


# ---------------------------------------------------------------------------
# 分发（直接驱动 _dispatch，捕获 stdout）
# ---------------------------------------------------------------------------


def _server_with_llm(script):
    """装配一个带假 llm / agent_loop / config 的 AcpServerProvider。"""
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.provide("config", Config())
    from minidsh.packages.services.tool_runtime import ToolRuntime
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
    LocalSystemPromptService(ctx)
    from tests.helpers.fake_llm import make_fake_llm
    ctx.plugin(make_fake_llm(script))
    from minidsh.packages.services.loop import AgentLoop
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)
    server = AcpServerProvider(ctx)
    return ctx, server


def _capture_stdout():
    """替换 sys.stdout 捕获协议输出，返回 (StringIO, restore)。"""
    import sys
    out = io.StringIO()
    real = sys.stdout
    sys.stdout = out
    return out, real


def _restore_stdout(real):
    import sys
    sys.stdout = real


async def test_initialize_roundtrip():
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        await server._dispatch({"jsonrpc": "2.0", "method": "initialize", "id": 1})
        obj = json.loads(out.getvalue().strip())
        assert obj["id"] == 1
        assert obj["result"]["protocolVersion"] == 1
    finally:
        _restore_stdout(real)


async def test_session_new_roundtrip():
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        await server._dispatch({"jsonrpc": "2.0", "method": "session/new", "id": 1})
        obj = json.loads(out.getvalue().strip())
        assert obj["result"]["sessionId"].startswith("session-")
        assert obj["result"]["sessionId"] in server._sessions
    finally:
        _restore_stdout(real)


async def test_prompt_end_to_end_streams_updates():
    """session/new + session/prompt → 推送 session/update → session/prompt 响应。"""
    ctx, server = _server_with_llm([{"text": "你好"}])
    out, real = _capture_stdout()
    try:
        # 激活 server（模拟 start 的 _active 状态）
        server._active = True

        await server._dispatch({"jsonrpc": "2.0", "method": "session/new", "id": 1})
        sid = json.loads(out.getvalue().splitlines()[0])["result"]["sessionId"]
        out.truncate(0); out.seek(0)

        await server._dispatch({
            "jsonrpc": "2.0", "method": "session/prompt", "id": 2,
            "params": {"sessionId": sid, "text": "你好"},
        })
        # 等 prompt task 完成
        await server._running[sid] if sid in server._running else asyncio.sleep(0)
        if sid in server._running:
            await server._running[sid]

        lines = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
        # 至少有一条 assistant-message 的 session/update 通知
        updates = [l for l in lines if l.get("method") == "session/update"]
        assert len(updates) >= 1
        assert any(u["params"]["sessionUpdate"] == "agent_message_chunk" for u in updates)
        # 最后一条是 session/prompt 响应
        resp = [l for l in lines if "result" in l and l.get("id") == 2]
        assert resp and resp[0]["result"]["stopReason"] == "end_turn"
    finally:
        _restore_stdout(real)


async def test_prompt_unknown_session_errors():
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        await server._dispatch({
            "jsonrpc": "2.0", "method": "session/prompt", "id": 1,
            "params": {"sessionId": "ghost", "text": "x"},
        })
        obj = json.loads(out.getvalue().strip())
        assert obj["error"]["code"] == transport.INVALID_PARAMS
    finally:
        _restore_stdout(real)


async def test_unknown_method_errors():
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        await server._dispatch({"jsonrpc": "2.0", "method": "nope", "id": 1})
        obj = json.loads(out.getvalue().strip())
        assert obj["error"]["code"] == transport.METHOD_NOT_FOUND
    finally:
        _restore_stdout(real)


async def test_set_config_option_model():
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        # 假 config 无模型 → unknown model 报错
        await server._dispatch({
            "jsonrpc": "2.0", "method": "session/set_config_option", "id": 1,
            "params": {"sessionId": "s1", "key": "model", "value": "ghost"},
        })
        obj = json.loads(out.getvalue().strip())
        assert obj["error"]["code"] == transport.INVALID_PARAMS
    finally:
        _restore_stdout(real)


def test_events_not_forwarded_when_inactive():
    """非激活（_active=False）时 session/event 不写 stdout。"""
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        server._active = False
        server._on_session_event(_ev("s1", "assistant-chunk", text="x"))
        assert out.getvalue() == ""
    finally:
        _restore_stdout(real)


def test_events_only_forwarded_for_owned_sessions():
    """只转发 server 自己创建的 session 的事件。"""
    ctx, server = _server_with_llm([{"text": "hi"}])
    out, real = _capture_stdout()
    try:
        server._active = True
        # ghost 不在 _sessions → 不转发
        server._on_session_event(_ev("ghost", "assistant-chunk", text="x"))
        assert out.getvalue() == ""
    finally:
        _restore_stdout(real)