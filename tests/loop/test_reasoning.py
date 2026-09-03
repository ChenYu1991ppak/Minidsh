"""M3 验收测试：reasoning-chunk 事件 + 按需回传协议。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.loop import AgentLoop
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from minidsh.packages.services.llm.providers.openai import OpenAILlm
from minidsh.packages.services.llm import Chunk, softmap
from tests.helpers.openai_fake import make_scripted_client
from tests.helpers.world import plug_execution_world
from minidsh.packages.tools import bash as tool_bash


def _assemble(script, model="fake-llm"):
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    client = make_scripted_client(script)
    OpenAILlm(ctx, client=client, model=model)
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)
    return ctx, loop


# ---------- 推理流只走 reasoning-delta ----------


async def test_reasoning_chunk_event_emitted_and_kept_out_of_content():
    ctx, loop = _assemble([{"reasoning": "让我想想", "text": "答案是 42"}], model="fake-llm")
    agent = loop.create()
    agent.send("问题")

    await agent.run()

    types = [e.type for e in agent.session]
    assert "reasoning-chunk" in types          # 思考进了会话事件流
    reasoning = "".join(e.payload["text"] for e in agent.session if e.type == "reasoning-chunk")
    assert reasoning == "让我想想"

    am = [e for e in agent.session if e.type == "assistant-message"][0]
    assert am.payload["content"] == "答案是 42"      # 文本回复不含思考
    assert am.payload["reasoning"] == "让我想想"     # 思考旁路聚合进事件

    # fake-llm 不要求回传 → 历史消息不保留 reasoning_content
    assert "reasoning_content" not in agent.messages[1]


# ---------- 回传协议 ----------


async def test_requires_history_family_echoes_reasoning():
    # 用 deepseek-v4 家族：软映射判 requires_reasoning_history
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    client = make_scripted_client([{"text": "无工具回复"}])
    OpenAILlm(ctx, client=client, model="deepseek-v4-pro")
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    ctx.provide("tools", ToolRuntime(ctx))
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)

    # 预置一条带 reasoning 的历史消息（模拟上一轮）
    agent = loop.create()
    agent.messages = [
        {"role": "user", "content": "上轮问题"},
        {"role": "assistant", "content": "上轮答案", "reasoning_content": "上轮思考"},
    ]
    agent.send("继续")
    await agent.run()

    # 纯文本轮，deepseek-v4 要求回传：新一轮 assistant 也带 reasoning_content
    # 关键断言：模型是 deepseek-v4-pro，软映射判真
    assert softmap.requires_reasoning_history("deepseek-v4-pro")


async def test_non_requires_history_family_strips_reasoning():
    assert not softmap.requires_reasoning_history("gpt-4o")
    assert not softmap.requires_reasoning_history("fake-llm")