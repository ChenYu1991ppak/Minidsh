"""subagent 模块：委派 seam——in-process 派生子 loop。

源码对应（ch11 教学版，逐机制对齐）：
- ``SubagentProvider`` 契约 {name, inherits_parent_context, run} ↔ types.ts:285
- ``SubagentRegistry``（provider 注册表，绑定 ctx.subagents）↔ index.ts:172
- ``SubagentResult`` ↔ subagent-in-process-driver/src/index.ts:208
- ``SubagentError`` / depth 校验 ↔ error.ts:10 / child-agent.ts:54 / depth.ts:42
- fork/spawn 差异 ↔ subagent-fork-in-process / subagent-spawn-in-process

seam 形态：**provider 注册表型**（同 ch12 skill）——多个传输 provider 并存注册，
读取时按名选定一个。v1 实现 ``in-process``（spawn）与 ``fork`` 两个传输；
真实版还有独立进程 / ACP / codex 等传输，缝在 provider 接口后面。

v1 简化（相对 ch11）：
- 异步 ``run`` 用 asyncio 协程（内核同步、loop 层 asyncio，spec §11-5）。
- fork 继承父上下文 = 复制父 ``messages`` 前缀；实现为两个命名 provider（同传输、
  ``inherits_parent_context`` 不同）。
- agent 指令注入：子 agent 的定义正文（agents/<name>.md）在驱动期间作为**临时
  systemPrompt 节**注册，run 结束即移除——不污染其它 agent 的作用域。
- depth：委派链深度，超过 max_depth 抛 SubagentError("MAX_DEPTH")。
"""
from __future__ import annotations

from ..cordis import Service

__all__ = [
    "SubagentError",
    "SubagentResult",
    "SubagentProvider",
    "SubagentRegistry",
    "InProcessSubagentProvider",
]


class SubagentError(Exception):
    """subagent seam 的统一错误，带机器可读 code（error.ts:10）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SubagentResult:
    """一次运行的结算结果：子 agent 最终输出（readResult，in-process-driver :208）。"""

    def __init__(self, text: str, stop_reason: str = "end-turn"):
        self.text = text
        self.stop_reason = stop_reason


class SubagentProvider:
    """传输 provider 契约（types.ts:285）。

    inherits_parent_context：子 agent 是否继承父上下文（spawn=False，fork=True）。
    """

    name: str = ""
    inherits_parent_context: bool = False

    async def run(self, ctx, agent_def: dict, task: str, depth: int) -> SubagentResult:
        """派生子 agent、执行 task、返回结算结果。"""
        raise NotImplementedError


class InProcessSubagentProvider(SubagentProvider):
    """in-process 传输：用父容器建子 agent 并驱动。

    子 agent 复用父 ctx 的能力（llm/tools/skills/prompt），但拥有独立 Session
    （独立 session_id，可独立持久化），origin 记为委派链。

    fork（inherits_parent_context=True）时复制父 messages 前缀；spawn 从零开始。
    agent 定义正文（agent_def["content"]）作为临时 systemPrompt 节注入子 agent。
    """

    def __init__(self, name: str = "in-process", inherits_parent_context: bool = False):
        self.name = name
        self.inherits_parent_context = inherits_parent_context

    async def run(self, ctx, agent_def: dict, task: str, depth: int) -> SubagentResult:
        from ..loop import ReactLoopAgent

        # 独立会话 + origin 元数据
        child_session = ctx.sessions.create()
        child_session.origin = {"agent": agent_def.get("name", ""), "depth": depth}
        child_session.append("subagent-spawn", {
            "agent": agent_def.get("name", ""),
            "task": task,
            "origin": child_session.origin,
        })

        # 子 agent 复用父容器能力，独立 Session
        child = ReactLoopAgent(ctx, child_session)
        if self.inherits_parent_context and agent_def.get("parent_messages"):
            child.messages = list(agent_def["parent_messages"])

        # agent 定义正文：驱动的临时 systemPrompt 节（结束即移除，不污染其它 agent）
        content = agent_def.get("content", "")
        section = ctx.systemPrompt.section(
            f"agent:{agent_def.get('name', '')}", content, order=5
        ) if content else None
        try:
            child.send(task)
            await child.run()
        finally:
            if section is not None:
                section()

        # 最终输出 = 最后一条 assistant-message 文本
        final = ""
        for ev in reversed(child_session.events()):
            if ev.type == "assistant-message":
                final = ev.payload.get("content", "")
                break
        child_session.append("subagent-result", {"agent": agent_def.get("name", ""), "result": final})

        return SubagentResult(text=final)


class SubagentRegistry(Service):
    """ctx.subagents：provider 注册表 + agent 定义注册表（index.ts:172 + agents）。"""

    def __init__(self, ctx):
        super().__init__(ctx, "subagents")
        self._providers: dict[str, SubagentProvider] = {}
        self._agents: dict[str, dict] = {}  # agent 名 → 定义（name/description/content）
        self._run_seq = 0

    def register_provider(self, provider: SubagentProvider):
        """按名注册，重名拒绝，返回注销 disposer（registerProvider，index.ts:369）。"""
        if provider.name in self._providers:
            raise SubagentError("DUPLICATE_PROVIDER", f"provider 重名: {provider.name}")
        self._providers[provider.name] = provider

        def dispose():
            self._providers.pop(provider.name, None)

        return self.ctx.effect(lambda: dispose, label=f"subagent-provider:{provider.name}")

    def list_providers(self) -> list[str]:
        return sorted(self._providers)

    def expect_provider(self, name: str) -> SubagentProvider:
        if name not in self._providers:
            raise SubagentError("UNKNOWN_PROVIDER", f"未注册的 provider: {name}")
        return self._providers[name]

    def define_agent(self, name: str, definition: dict):
        """登记一个可委派的 agent 定义（agents/<name>.md 解析结果）。"""
        self._agents[name] = definition

    def list_agents(self) -> list[str]:
        return sorted(self._agents)

    async def task(self, execution_args: dict) -> SubagentResult:
        """`task` 工具的执行体（消费方）：派生 subagent 执行任务。

        execution_args 含：provider、agent（agent 名）、task、parent_messages、max_depth。
        默认 provider="in-process"、max_depth=3；agent 名会从 agent 定义注册表解析出
        完整定义（含 instructions 正文）。

        委派深度从「当前父会话的 origin.depth」推算（parent_depth + 1），
        不信任调用方传入的深度字段；超过 max_depth 抛 SubagentError("MAX_DEPTH")。
        """
        provider = self.expect_provider(execution_args.get("provider", "in-process"))
        agent_ref = execution_args.get("agent", {})
        agent_name = agent_ref if isinstance(agent_ref, str) else agent_ref.get("name", "")
        agent_def = dict(self._agents.get(agent_name, {"name": agent_name}))

        task_text = execution_args.get("task", "")
        max_depth = int(execution_args.get("max_depth", 3))

        # 父会话 origin.depth 是深度真相源（父 loop 运行时压栈，见 ReactLoopAgent.run）
        stack = getattr(self.ctx, "_session_stack", None) or []
        parent_origin = getattr(stack[-1], "origin", None) if stack else None
        parent_depth = (parent_origin or {}).get("depth", 0)
        child_depth = parent_depth + 1
        if child_depth > max_depth:
            raise SubagentError(
                "MAX_DEPTH", f"委派深度 {child_depth} 超过上限 max_depth={max_depth}"
            )

        agent_def["parent_messages"] = execution_args.get("parent_messages", [])
        return await provider.run(self.ctx, agent_def, task_text, child_depth)