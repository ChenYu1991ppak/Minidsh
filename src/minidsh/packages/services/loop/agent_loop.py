"""agent-loop 与反应式循环驱动器。

源码对应（ch02 教学版，逐机制对齐，并补 react）：
- ``Inbox``            ↔ packages/core/agent-loop/src/inbox.ts:25
- ``ReactLoopAgent``   ↔ packages/core/agent-loop/src/agent.ts:64
- ``AgentLoop``        ↔ packages/core/agent-loop/src/index.ts:296（inject :296-297）

loop 消费 llm/prompt/tools，产出会话事件（§plan 事件契约）。内核同步，本层用
asyncio 适配 LLM 流式（spec §11-5）。

react 决策：一 turn 内可多 step——模型若发起 tool-call，则执行工具并把结果回填进
模型侧消息历史，再触发下一次模型调用，直到模型给出文本回复（end-turn）为止。
"""
from __future__ import annotations

import json
from typing import Any

from minidsh.cordis import CapabilityProvider
from ..session import Session
from ..tool_runtime import ToolExecution
from .inbox import Inbox
from ..llm import Chunk, softmap

__all__ = ["AgentLoop", "ReactLoopAgent", "derive_messages"]

# 安全上限：单 turn 内最多 react 步数，防止模型无休止调工具（教学版常量）。
_MAX_REACT_STEPS = 20


def _parse_arguments(raw: str | None) -> dict:
    """把工具参数 JSON 字符串解析为 dict；失败时返回原始文本包装。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"_raw": raw}


def fallback_session_title(text: str, max_words: int = 8, max_bytes: int = 80) -> str:
    """（M7）确定性会话标题 fallback（对齐官方 normalize.ts）。

    清洗控制字符 → 空白归一 → 取前 ``max_words`` 词 → UTF-8 字节安全截断。
    不连 LLM；首条 user-message 产 ``session/title`` 事件时调用。
    """
    import re

    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", " ", text)
    words = cleaned.split()
    title = " ".join(words[:max_words])
    # UTF-8 安全截断（不劈开码点）
    encoded = title.encode("utf-8")
    if len(encoded) <= max_bytes:
        return title
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def derive_messages(events) -> list[dict]:
    """从会话事件流反投影出模型侧消息历史（官方 deriveMessages 的教学简化版）。

    用于 ``resume``：把落盘的事件流还原成 wire 消息，使恢复后的 agent 接着聊。
    - ``user-message`` → role=user
    - ``assistant-message`` → role=assistant（content）
    - ``tool-call`` / ``tool-result`` → 一批 assistant(tool_calls) 消息 + 各自 tool 消息
      （按 call_id 对齐；事件流里 tool-call/tool-result 是逐条交错的，这里累积到
      assistant-message 边界再统一展开，满足 OpenAI 兼容流的配对顺序）。
    [教学简化] 不覆盖 compaction/error 等旁注投影；这些事件不进消息历史。
    """
    messages: list[dict] = []
    tool_calls: list[dict] = []
    tool_results: list[dict] = []

    def flush_tool_batch():
        nonlocal tool_calls, tool_results
        if tool_calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": list(tool_calls)})
        messages.extend(tool_results)
        tool_calls = []
        tool_results = []

    for ev in events:
        # M4 显式分层：跳过审计面事件（turn/start、turn/end、session/title、approval/*）
        if not getattr(ev, "surface", True):
            continue
        t = ev.type
        p = ev.payload
        if t == "user-message":
            flush_tool_batch()
            messages.append({"role": "user", "content": p.get("text", "")})
        elif t == "assistant-message":
            flush_tool_batch()
            messages.append({"role": "assistant", "content": p.get("content", "")})
        elif t == "tool-call":
            args = p.get("arguments", {})
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            tool_calls.append({
                "id": p.get("call_id", f"call-{len(tool_calls)}"),
                "type": "function",
                "function": {"name": p.get("name", ""), "arguments": args},
            })
        elif t == "tool-result":
            tool_results.append({
                "role": "tool",
                "tool_call_id": p.get("call_id", f"call-{len(tool_results)}"),
                "content": p.get("result", ""),
            })
    flush_tool_batch()
    return messages


class ReactLoopAgent:
    """反应式循环驱动器（agent.ts:64）。

    [教学简化] 省略 phase 状态机（idle/running）与 wake_requested 重入处理——
    asyncio.run 下的串行调用天然单次激活；消息历史 ``self.messages`` 在 loop 内
    持有（不走事件反投影）。
    """

    def __init__(self, ctx, session: Session, options: dict | None = None):
        self.ctx = ctx
        self.session = session
        self.options = options or {}
        self.inbox = Inbox()
        self.messages: list[dict] = []  # 模型侧对话历史（user/assistant/tool）
        # M4：turn 边界计数与结果（turn/start / turn/end 配对）
        self._turn_no = 0
        self._turn_reason = "completed"
        # 桥接技能加载：ctx.skills.load 会广播 skills/change(op=load) →
        # 此处转成会话事件 skill-loaded（跨层桥接，见 T9/T10 分层契约）。
        ctx.on("skills/change", self._on_skill_change)

    def _on_skill_change(self, event: dict):
        if event.get("op") == "load":
            self.session.append("skill-loaded", {"name": event["name"]})

    # ---------- 入队 ----------

    def send(self, message) -> "ReactLoopAgent":
        """入队一条用户消息（字符串或 ``{"role","content"}``）。"""
        if isinstance(message, str):
            message = {"role": "user", "content": message}
        self.inbox.enqueue(message)
        return self

    # ---------- 驱动 ----------

    async def run(self):
        """处理 inbox 中全部消息，直到清空。运行期间把当前 agent 作为 ctx.agents 发起者
        （withInitiator），供 subagent 委派桥接「父会话」定位（M9 官方机制，替换 _session_stack）。"""
        agents = getattr(self.ctx, "agents", None)
        if agents is not None:
            with agents.with_initiator(getattr(self, "_public", None) or self):
                while self.inbox.has_pending:
                    await self.turn()
            return
        # 回退：无 agents 服务（headless 测试）用旧 _session_stack
        stack = getattr(self.ctx, "_session_stack", None)
        if stack is None:
            stack = []
            self.ctx._session_stack = stack
        stack.append(self.session)
        try:
            while self.inbox.has_pending:
                await self.turn()
        finally:
            stack.pop()

    async def turn(self):
        """一个 turn：取消息 → 记录 user-message → react 循环（M4 产 turn 边界事件）。"""
        self._turn_no += 1
        turn_no = self._turn_no
        self.session.append("turn/start", {"turn": turn_no})
        for message in self.inbox.claim():
            content = message.get("content", "")
            self.session.append("user-message", {"text": content})
            self.messages.append({"role": "user", "content": content})
            # M7：首条 user-message 产确定性 session title fallback（不连 LLM）
            if self._turn_no == 1:
                title = fallback_session_title(content)
                if title:
                    self.session.append("session/title", {"title": title})
        await self._react()
        self.session.append(
            "turn/end", {"turn": turn_no, "reason": {"kind": self._turn_reason}}
        )
        self._turn_reason = "completed"

    async def _react(self):
        """react 主循环：模型调用 → 有工具调用则执行继续，无则收尾。"""
        system_text = self.ctx.systemPrompt.render()
        tools = self.ctx.tools.openai_schemas()

        # token 压力触发的压缩（若 compaction 服务已提供）：只在文本收尾前做一次检查，
        # 避免在工具往返中间打断 react 连续性。
        compaction = getattr(self.ctx, "compaction", None)
        if compaction is not None:
            await compaction.maybe_compact(self)

        for _ in range(_MAX_REACT_STEPS):
            tool_calls: list[Chunk] = []
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            chunk_seqs: list[int] = []
            stop_reason: str | None = None

            async for chunk in self.ctx.llm.stream(
                self.messages, system_prompt=system_text, tools=tools
            ):
                if chunk.kind == "reasoning-delta":
                    ev = self.session.append("reasoning-chunk", {"text": chunk.reasoning})
                    reasoning_parts.append(chunk.reasoning)
                elif chunk.kind == "text-delta":
                    ev = self.session.append("assistant-chunk", {"text": chunk.text})
                    chunk_seqs.append(ev.seq)
                    text_parts.append(chunk.text)
                elif chunk.kind == "tool-call":
                    tool_calls.append(chunk)
                elif chunk.kind == "finish":
                    stop_reason = chunk.stop_reason

            # 工具调用轮：assistant 消息按需带 reasoning_content 回传（软映射层判
            # requires_reasoning_history → 保留；否则 strip）。见 _execute_tools。
            reasoning = "".join(reasoning_parts)
            if tool_calls:
                await self._execute_tools(tool_calls, reasoning=reasoning)
                continue  # 下一模型 turn：工具结果已进消息历史

            # 无工具调用 → 文本收尾，产出聚合回复（= 持久化 flush 边界）
            content = "".join(text_parts)
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}

            # 纯文本轮：仅当模型要求回传时才把 reasoning 放进旁路字段
            if reasoning and softmap.requires_reasoning_history(self.ctx.llm.model):
                assistant_msg["reasoning_content"] = reasoning
            self.messages.append(assistant_msg)
            self.session.append(
                "assistant-message",
                {
                    "content": content,
                    "stop_reason": stop_reason,
                    "reasoning": reasoning,
                    "chunk_seqs": chunk_seqs,
                },
            )
            return

        # 步数耗尽（异常态）：显式报错，不让会话静默悬挂
        self._turn_reason = "error"
        self.session.append("error", {"message": f"max react steps ({_MAX_REACT_STEPS}) exceeded"})

    async def _execute_tools(self, tool_calls: list[Chunk], reasoning: str = ""):
        """执行一批工具调用，回填消息历史与事件流。"""
        # 1) assistant 消息体（tool_calls 形式）进历史；reasoning 按需回传
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": c.id or f"call-{i}",
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments or "{}"},
                }
                for i, c in enumerate(tool_calls)
            ],
        }
        if reasoning and softmap.requires_reasoning_history(self.ctx.llm.model):
            assistant_msg["reasoning_content"] = reasoning
        self.messages.append(assistant_msg)
        # 2) 逐个执行，产 tool-call / tool-result 会话事件 + tool 角色消息
        for i, chunk in enumerate(tool_calls):
            call_id = chunk.id or f"call-{i}"
            args = _parse_arguments(chunk.arguments)
            self.session.append("tool-call", {"name": chunk.name, "arguments": args, "call_id": call_id})

            result = await self.ctx.tools.execute(
                ToolExecution(call_id=call_id, name=chunk.name or "", arguments=args)
            )
            tool_result_payload = {
                "name": chunk.name,
                "result": result.content,
                "is_error": result.is_error,
                "call_id": call_id,
            }
            # M5：展示元数据随事件落盘（仅当工具产出，避免引入空字段）
            if result.meta is not None:
                tool_result_payload["meta"] = result.meta
            self.session.append("tool-result", tool_result_payload)
            self.messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": result.content}
            )


class AgentLoop(CapabilityProvider):
    """agent-loop 服务（index.ts:296）：被容器装配，create 产出 agent。

    inject 对齐 static inject（index.ts:296-297）：sessions/llm/systemPrompt/tools
    全提供后才加载。经 ctx.agents.setFactory 注册为唯一 AgentFactory——消费方用
    ctx.agents，不依赖本具体包（loop 可替换，M2/M9 官方机制）。

    [教学简化] create 保持同步（内核同步；官方 createAgent 是 async），返回
    ReactLoopAgent；登记到 ctx.agents（若已装配），否则退回自身 dict（无 agents 能力时）。
    """

    inject = ["sessions", "llm", "systemPrompt", "tools"]
    service_name = "agent_loop"

    def _init(self, ctx):
        self.agents = {}
        self._register_factory()

    def _register_factory(self):
        """向 ctx.agents 注册本 loop 为 AgentFactory（若 agents 服务已装配）。

        loop 是唯一工厂实现：消费方调 ctx.agents.create/resume 时经本工厂真正建
        ReactLoopAgent。无 agents 服务（headless 测试装配）则跳过——create 仍走自身。
        """
        ctx = self.ctx
        if not ctx.has("agents"):
            return
        from ..agents import AgentFactory, AgentHandle, Agent as PublicAgent

        loop = self

        class LoopAgentFactory(AgentFactory):
            async def create_agent(self, owner_ctx, options):
                owner = owner_ctx if owner_ctx is not None else loop.ctx
                session = owner.sessions.create()
                agent = ReactLoopAgent(owner, session, options)
                loop.agents[session.id] = agent
                return AgentHandle(PublicAgent(agent_id=session.id, session=session,
                                               options=agent.options), lambda: None)

            async def resume_agent(self, owner_ctx, options):
                owner = owner_ctx if owner_ctx is not None else loop.ctx
                session_id = options.get("resume_session_id")
                events = options.get("events")
                agent = loop.resume(session_id, events=events)
                return AgentHandle(PublicAgent(agent_id=agent.id, session=agent.session,
                                               options=agent.options), lambda: None)

        ctx.agents.set_factory(LoopAgentFactory())

    def create(self, **options) -> ReactLoopAgent:
        """create：建 Session → 建 ReactLoopAgent → 登记 → 广播 agent/session-start。"""
        session = self.ctx.sessions.create()
        agent = ReactLoopAgent(self.ctx, session, options)
        self.agents[session.id] = agent
        self._publish_agent(agent)
        self.ctx.emit("agent/session-start", {"session_id": session.id, "agent": agent})
        return agent

    def resume(self, session_id: str, events: list | None = None) -> ReactLoopAgent:
        """resume：恢复一个持久会话（session_id + 已落盘事件），agent 接着聊。

        对应官方 AgentRegistry.resume + loop 的 ResumeAgentOptions(resumeSessionId)。
        [教学简化] 事件由调用方从持久化后端 load 后传入；无持久化后端时 events=None
        → 建空会话（等同 create 但沿用给定 id）。消息历史经 ``derive_messages`` 反投影。
        """
        session = self.ctx.sessions.resume(session_id, events=events)
        agent = ReactLoopAgent(self.ctx, session)
        agent.messages = derive_messages(session.events())
        # M4：恢复 turn 计数——从历史 turn/start 的最大 turn 号续接，避免续聊重头
        agent._turn_no = max(
            (e.payload.get("turn", 0) for e in session.events() if e.type == "turn/start"),
            default=0,
        )
        self.agents[session.id] = agent
        self._publish_agent(agent)
        self.ctx.emit("agent/session-start", {"session_id": session.id, "agent": agent, "resumed": True})
        return agent

    def _publish_agent(self, agent):
        """登记到 ctx.agents（若已装配），使 agent 经官方注册表可见。"""
        if self.ctx.has("agents"):
            from ..agents import Agent as PublicAgent

            pub = PublicAgent(agent_id=agent.session.id, session=agent.session,
                              options=agent.options, scoped_ctx=None)
            self.ctx.agents._publish(pub)
            agent._public = pub

    def get(self, session_id: str) -> ReactLoopAgent | None:
        return self.agents.get(session_id)