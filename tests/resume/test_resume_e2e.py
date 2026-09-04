"""resume 端到端回归：恢复后新事件 append 不 seq 断裂（协调器游标采纳）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.loop import AgentLoop
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.persistence import PersistenceCoordinator
from minidsh.packages.services.persistence.providers.jsonl import JsonlSessionPersistence
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from tests.helpers.fake_llm import make_fake_llm


def _assemble(tmp_path, script):
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.plugin(make_fake_llm(script))
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    ctx.provide("tools", ToolRuntime(ctx))
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)
    coord = PersistenceCoordinator(ctx, JsonlSessionPersistence(tmp_path))
    ctx.provide("sessionPersistence", coord)
    return ctx, loop, coord


async def test_resume_then_append_no_seq_break(tmp_path):
    """复现生产 bug：默认接上次会话后，恢复 agent 写游标须采纳到已落盘 seq。"""
    ctx, loop, coord = _assemble(tmp_path, [{"text": "新的回复"}])

    old_agent = loop.create()
    old_agent.send("旧问题")
    await old_agent.run()
    ctx.emit("session/flush", old_agent.session.id)

    events = coord.load(old_agent.session.id)   # 生产 _resume_agent 走的这条路
    agent = loop.resume(old_agent.session.id, events=events)

    agent.send("新问题")
    await agent.run()   # 之前这里抛 ValueError: append seq 断裂

    assert agent.session.events()[-1].type == "turn/end"   # M4：末事件为 turn/end
    assert agent.session.events()[-1].seq == len(agent.session) - 1
