"""AcpServer provider：Agent Client Protocol JSON-RPC stdio server（教学版）。

对齐官方 ``dsh-acp``（packages/acp/acp/src/index.ts）的 ACP v1 子集。传输层 ndjson
（每行一个 JSON-RPC 2.0 对象）；stdout 只走协议流量，日志走 stderr。

[教学简化] 单会话核心闭环：initialize / authenticate / session/new /
session/set_config_option / session/prompt / session/cancel。无 session/list、
resume、close；无 capabilities 动态枚举；无 MCP；无 image prompts。
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from minidsh.cordis import CapabilityProvider
from ..definition import (
    AcpServer,
    AGENT_MESSAGE_CHUNK,
    AGENT_THOUGHT_CHUNK,
    TOOL_CALL,
    TOOL_CALL_UPDATE,
    USAGE_UPDATE,
)
from .transport import (
    read_request,
    write_response,
    write_notification,
    write_error,
    JsonRpcError,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
)

__all__ = ["AcpServerProvider"]


class AcpServerProvider(AcpServer, CapabilityProvider):
    """ACP JSON-RPC stdio server。构造即注册 ctx.acp。"""

    service_name = "acp"

    def _init(self, ctx):
        self._sessions: dict[str, Any] = {}       # sessionId → ReactLoopAgent
        self._running: dict[str, asyncio.Task] = {}  # sessionId → 运行中的 prompt task
        self._active = False                       # start() 后为 True，stop() 后为 False
        self._stopped = False
        # 订阅会话事件：start() 后才把事件映射成 ACP session/update 通知（避免
        # 非 ACP 前端（如 tui-textual）也加载本服务时污染 stdout）。
        ctx.on("session/event", self._on_session_event)

    # ---------- 事件桥 ----------

    def _on_session_event(self, event) -> None:
        """session/event → ACP session/update 通知（stdout）。

        仅在 start() 激活后转发；且只转发本 server 创建的 session（self._sessions）。
        非 ACP session 的事件被静默跳过（不污染 stdout）。
        """
        if not self._active:
            return
        if event.session_id not in self._sessions:
            return
        update = self._to_update(event)
        if update is None:
            return
        write_notification(
            "session/update",
            {"sessionId": event.session_id, **update},
        )

    def _to_update(self, event) -> dict | None:
        """映射一条会话事件为 ACP session/update 的 ``{sessionUpdate, ...}`` 片段。

        ``assistant-chunk``（流式增量）→ ``agent_message_chunk``；``assistant-message``
        是 flush 边界（含完整聚合文本），其内容已由前面的 ``assistant-chunk`` 流式发送，
        故**不**再映射，否则前端收到两遍。
        """
        t = event.type
        p = event.payload
        if t == "assistant-chunk":
            return {"sessionUpdate": AGENT_MESSAGE_CHUNK,
                    "content": {"type": "text", "text": p.get("text", "")}}
        if t == "reasoning-chunk":
            return {"sessionUpdate": AGENT_THOUGHT_CHUNK,
                    "content": {"type": "text", "text": p.get("text", "")}}
        if t == "tool-call":
            return {"sessionUpdate": TOOL_CALL,
                    "toolCallId": p.get("call_id"),
                    "title": p.get("name", "tool"),
                    "kind": "other",
                    "status": "in_progress"}
        if t == "tool-result":
            return {"sessionUpdate": TOOL_CALL_UPDATE,
                    "toolCallId": p.get("call_id"),
                    "content": [{"type": "content", "content": p.get("result", "")}]}
        return None

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        """读 stdin，逐行处理 JSON-RPC 请求，直到 EOF 或 stop()。"""
        loop = asyncio.get_event_loop()
        self._active = True
        self._stopped = False
        while not self._stopped:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if line == "" or line is None:  # EOF
                break
            obj = read_request(line)
            if obj is None:
                continue
            await self._dispatch(obj)
        await self.stop()

    async def stop(self) -> None:
        """关闭：取消所有运行中的 prompt task，标记停止。"""
        self._active = False
        self._stopped = True
        for task in list(self._running.values()):
            if not task.done():
                task.cancel()

    # ---------- JSON-RPC 分发 ----------

    async def _dispatch(self, obj: dict) -> None:
        method = obj.get("method")
        message_id = obj.get("id")
        params = obj.get("params") or {}

        if method == "initialize":
            write_response(message_id, self._initialize(params))
        elif method == "authenticate":
            write_response(message_id, {})
        elif method == "session/new":
            write_response(message_id, self._new_session(params))
        elif method == "session/set_config_option":
            self._set_config_option(params, message_id)
        elif method == "session/prompt":
            self._start_prompt(params, message_id)
        elif method == "session/cancel":
            self._cancel(params, message_id)
        else:
            write_error(message_id, JsonRpcError(METHOD_NOT_FOUND, f"unknown method {method}"))

    # ---------- 方法实现 ----------

    def _initialize(self, params: dict) -> dict:
        """返回 ACP v1 协议版本 + capabilities。"""
        return {
            "protocolVersion": 1,
            "capabilities": {
                "promptCapabilities": {"text": True},
                "modelSelection": True,
                "reasoningEffort": True,
            },
        }

    def _new_session(self, params: dict) -> dict:
        """创建新会话，返回 sessionId。"""
        loop = self.ctx.agent_loop
        agent = loop.create()
        self._sessions[agent.session.id] = agent
        return {"sessionId": agent.session.id}

    def _set_config_option(self, params: dict, message_id: Any) -> None:
        """设置会话配置项（model / reasoning_effort）。

        [教学简化] 无 per-session 配置隔离——直接改全局 llm 运行时，与 TUI /model 一致。
        """
        key = params.get("key")
        value = params.get("value")
        try:
            if key == "model":
                spec = self.ctx.config.find(value)
                if spec is None:
                    raise JsonRpcError(INVALID_PARAMS, f"unknown model {value!r}")
                self.ctx.llm.reconfigure(spec)
            elif key == "reasoning_effort":
                spec = self.ctx.config.current
                if spec is None:
                    raise JsonRpcError(INVALID_PARAMS, "no current model configured")
                spec.reasoning_effort = value
                self.ctx.llm.reconfigure(spec)
            else:
                raise JsonRpcError(INVALID_PARAMS, f"unsupported config option {key!r}")
        except JsonRpcError as e:
            write_error(message_id, e)
            return
        write_response(message_id, {"key": key, "value": value})

    def _start_prompt(self, params: dict, message_id: Any) -> None:
        """发送 prompt：后台 task 跑 agent，完成后写响应。"""
        session_id = params.get("sessionId")
        agent = self._sessions.get(session_id)
        if agent is None:
            write_error(message_id, JsonRpcError(INVALID_PARAMS, f"unknown session {session_id!r}"))
            return
        text = params.get("text") or ""
        task = asyncio.get_event_loop().create_task(
            self._run_prompt(session_id, agent, text, message_id)
        )
        self._running[session_id] = task

    async def _run_prompt(self, session_id: str, agent, text: str, message_id: Any) -> None:
        """跑一条 prompt：agent.send + agent.run，完成后写 session/prompt 响应。"""
        try:
            agent.send(text)
            await agent.run()
            self._safe_write(lambda: write_response(message_id, {"stopReason": "end_turn"}))
        except asyncio.CancelledError:
            self._safe_write(lambda: write_response(message_id, {"stopReason": "cancelled"}))
            raise
        except BrokenPipeError:
            # 客户端（pi-tui 前端）已退出，管道断裂——静默收敛，不再尝试写响应
            pass
        finally:
            self._running.pop(session_id, None)

    def _safe_write(self, fn) -> None:
        """写协议响应；客户端已断开（BrokenPipeError）时静默忽略，不让后台 task 崩溃。"""
        try:
            fn()
        except BrokenPipeError:
            pass

    def _cancel(self, params: dict, message_id: Any) -> None:
        """取消当前 turn：取消该 session 的运行中 task。"""
        session_id = params.get("sessionId")
        task = self._running.get(session_id)
        if task is not None and not task.done():
            task.cancel()
        write_response(message_id, {})