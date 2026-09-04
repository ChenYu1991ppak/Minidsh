"""T11 验收测试：openai 假 client 集成闭环「一条进一条出」+ 持久化写路径接线。

装配完整能力图：cordis + session + llm(openai 假 client) + prompt + tools + loop +
持久化协调器，跑一条用户消息，断言：
1. 一条回复（assistant-message）产出，退出即完成；
2. 事件序列覆盖契约所列全部类型（含工具调用往返）；
3. 事件流经 session/event → persistence 写路径落盘（jsonl），load 回来与原日志等价。

对应 spec S1 / S5 / S2 的模块级验证（端到端 CLI 冒烟在 T18）。
"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.llm import OpenAILlm
from minidsh.packages.services.loop import AgentLoop
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.persistence import PersistenceCoordinator
from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from minidsh.packages.tools import bash as tool_bash
from minidsh.packages.tools import read_file as tool_read
from tests.helpers.world import plug_execution_world

from tests.helpers.fake_llm import make_fake_llm


def _assemble(tmp_path, script):
    """完整装配（含持久化），返回 (ctx, loop, coord)。script 按轮次回放。"""
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.plugin(make_fake_llm(script))
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    ctx.plugin(tool_read)

    ctx.provide("agent_loop", AgentLoop(ctx))

    coord = PersistenceCoordinator(ctx, JsonlSessionPersistence(tmp_path))
    ctx.provide("sessionPersistence", coord)
    return ctx, ctx.agent_loop, coord


async def test_one_in_one_out_with_persistence(tmp_path):
    script = [
        {"tool_calls": [("bash", '{"cmd":"echo hi"}', "call-0")]},
        {"text": "完成"},
    ]
    ctx, loop, coord = _assemble(tmp_path, script)
    agent = loop.create()

    agent.send("读一下然后执行")
    await agent.run()

    events = agent.session.events()

    # 1) 一条回复产出
    replies = [e for e in events if e.type == "assistant-message"]
    assert len(replies) == 1
    assert replies[0].payload["content"] == "完成"

    # 2) 事件序列覆盖契约类型：turn/start → user → session/title → tool-call → tool-result
    #    → assistant-* → turn/end（M4 turn 边界 + M7 title）
    types = [e.type for e in events]
    assert types == [
        "turn/start",
        "user-message",
        "session/title",
        "tool-call",
        "tool-result",
        "assistant-chunk",
        "assistant-message",
        "turn/end",
    ]

    # 3) 持久化：assistant-message 是 flush 边界，落盘后 load 回来与原日志等价
    ctx.emit("session/flush", agent.session.id)
    loaded = coord.load(agent.session.id)
    assert loaded == events  # 事件逐条相等（含 seq/type/payload）


async def test_closed_loop_emits_contract_event_types(tmp_path):
    """事件类型枚举契约：极简会话也至少覆盖核心类型白名单。"""
    ctx, loop, coord = _assemble(tmp_path, [{"text": "就绪"}])
    agent = loop.create()
    agent.send("在吗")
    await agent.run()

    types = {e.type for e in agent.session}
    assert {"user-message", "assistant-chunk", "assistant-message"} <= types