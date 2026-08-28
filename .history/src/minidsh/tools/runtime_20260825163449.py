"""tools 模块：工具注册面 + 展示面 + 守卫执行管线。

源码对应（ch04 教学版，逐机制对齐）：
- ``ToolDefinition``  ↔ packages/core/tools/index.ts:222（名字/描述/参数 schema/执行体）
- ``ToolRuntime``    ↔ index.ts:787（ctx.tools：定义/展示/执行三合一）
- register           ↔ index.ts:1037；guard ↔ :1110；presentAs ↔ :946
- wireSchemas        ↔ index.ts:980（{schemas, knownNames}）
- 执行管线           ↔ execute :1342 → prepare :1463 → dispatchScheduledExecution :1569
- 三段守卫           ↔ packages/guard（pre-execute / execute 环绕 / post-execute）

三种面：
- **定义面**：register 写入作用域层 → 触发 ``tools/change``；返回注销 disposer。
- **展示面**：view() 按模式过滤 → wire_schemas() 投影白名单 → render_schemas() 注入 prompt。
- **执行面**：execute() 跑三段守卫瀑布 + 单调 guard，产 ToolResult 并广播 ``tools/result``。

[教学简化] 单作用域层（真实版是 ScopedLayers 全局层 + agent 作用域层，见 ch09 scope）；
execute 同步（内核同步）。产出会话事件 ``tool-call`` / ``tool-result`` 由 loop 层负责
（本模块只管 cordis 内的事件与返回值），二者分属不同层：这里广播的是进程内事件
``tools/result``，落盘观测的是会话事件 ``tool-result``——loop（T10）做桥接。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..cordis import Service
import inspect

__all__ = [
    "ToolDefinition",
    "ToolResult",
    "ToolExecution",
    "ToolRuntime",
    "PreToolDecision",
    "PostToolDecision",
]


def waterfall_wrap(listeners, args, fallback):
    """中间件式瀑布：监听器从外到内包裹，fallback 最内层兜底。

    监听器签名 ``listener(*args, next)``；调 ``next()`` 才交控制权给内层，不调则短路。
    （补全 cordis 简化掉的真实中间件语义，events.ts:234。）
    """

    def invoke(index):
        if index >= len(listeners):
            return fallback()
        return listeners[index](*args, lambda: invoke(index + 1))

    return invoke(0)


# ---------------------------------------------------------------------------
# 契约对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDefinition:
    """一条工具契约（index.ts:222）：名字 + 描述 + 参数 JSON schema + 执行体。

    [教学简化] execute 签名退化为 ``execute(args: dict) -> str``（真实版是 (args, exec)
    且返回值经 snapshot/validate/render）；output 契约省略。
    """

    name: str
    description: str
    parameters: dict
    execute: Callable[[dict], str]
    timeout_ms: int | None = None


@dataclass(frozen=True)
class ToolResult:
    """工具最终结果（对应 ToolExecutionResult）。"""

    content: str
    is_error: bool = False


@dataclass
class ToolExecution:
    """一次工具调用对象，贯穿三段管线（对应 ToolExecution / ToolRunContext）。"""

    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class PreToolDecision:
    """调用前决策：allow / deny / ask（index.ts:588-597）。"""

    kind: str
    reason: str | None = None

    @staticmethod
    def allow():
        return PreToolDecision("allow")

    @staticmethod
    def deny(reason):
        return PreToolDecision("deny", reason)


@dataclass(frozen=True)
class PostToolDecision:
    """调用后决策：accept / block（index.ts:588-597）。"""

    kind: str
    feedback: str | None = None

    @staticmethod
    def accept():
        return PostToolDecision("accept")

    @staticmethod
    def block(feedback):
        return PostToolDecision("block", feedback)


@dataclass
class ToolLayer:
    """作用域层（index.ts:714）：工具 + 单调守卫 + 展示模式。"""

    tools: dict = field(default_factory=dict)
    guards: list = field(default_factory=list)
    modes: dict = field(default_factory=dict)  # name -> "native" | "code" | "both"

    def guard_reason(self, exec_: ToolExecution):
        """单调守卫：顺序跑，返回第一个非 None 的拒绝理由（index.ts:1119-1127）。"""
        for guard in self.guards:
            reason = guard(exec_)
            if reason is not None:
                return reason
        return None


# ---------------------------------------------------------------------------
# 运行时
# ---------------------------------------------------------------------------


class ToolRuntime(Service):
    """ctx.tools：注册面 + 展示面 + 执行面三合一（index.ts:787）。"""

    def __init__(self, ctx, config=None):
        super().__init__(ctx, "tools")
        self._layer = ToolLayer()
        self._pre_execute = []
        self._execute = []
        self._post_execute = []
        self._seq = 0

    # ---------- 定义面 ----------

    def register(self, definition: ToolDefinition):
        """把工具写入作用域层并触发 tools/change，返回注销 disposer（index.ts:1037）。"""
        name = definition.name
        self._layer.tools[name] = definition
        self.ctx.emit("tools/change", {"name": name, "op": "add"})

        def dispose():
            self._layer.tools.pop(name, None)
            self.ctx.emit("tools/change", {"name": name, "op": "remove"})

        return self.ctx.effect(lambda: dispose, label=f"tool:{name}")

    def guard(self, guard_fn):
        """注册单调守卫：只能拒绝、不能放行（index.ts:1110）。"""
        self._layer.guards.append(guard_fn)

    def present_as(self, name, mode):
        """设置工具的展示/执行模式 native/code/both（index.ts:946）。"""
        self._layer.modes[name] = mode

    def mode_for(self, name):
        return self._layer.modes.get(name, "native")

    def get(self, name):
        return self._layer.tools.get(name)

    # ---------- 展示面 ----------

    def view(self):
        """可见工具集：模式非 code 的工具才向模型暴露 schema。"""
        return [d for d in self._layer.tools.values() if self.mode_for(d.name) != "code"]

    def schema_of(self, definition: ToolDefinition):
        """投影成给模型看的白名单：{name, description, parameters}。"""
        return {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        }

    def wire_schemas(self):
        """汇总可见工具 schema 与已知名字（index.ts:980）。"""
        visible = self.view()
        return {
            "schemas": [self.schema_of(d) for d in visible],
            "knownNames": [d.name for d in visible],
        }

    def openai_schemas(self):
        """转成 OpenAI 兼容工具 schema 列表（{type:"function", function:{...}}）。"""
        return [
            {"type": "function", "function": s}
            for s in self.wire_schemas()["schemas"]
        ]

    def render_schemas(self):
        """渲染成 prompt 文本，供 system-prompt section 注入。"""
        lines = ["可用工具："]
        for s in self.wire_schemas()["schemas"]:
            lines.append(f"- {s['name']}: {s['description']}")
            lines.append(f"  参数 {s['parameters']}")
        return "\n".join(lines)

    # ---------- 执行面 ----------

    def on_pre_execute(self, listener):
        self._pre_execute.append(listener)

    def on_execute(self, wrapper):
        self._execute.append(wrapper)

    def on_post_execute(self, listener):
        self._post_execute.append(listener)

    def execute(self, exec_: ToolExecution) -> ToolResult:
        """跑完整守卫管线：prepare → dispatch → post（index.ts:1342）。"""
        gate = self._prepare(exec_)
        if gate.kind != "allow":
            return ToolResult(content=gate.reason or f"{gate.kind}", is_error=True)

        result = self._dispatch(exec_)
        decision = self._post(exec_, result)
        if decision.kind == "block":
            result = ToolResult(content=decision.feedback or "blocked", is_error=True)

        self.ctx.emit("tools/result", exec_, result)  # 通知观察者（只读，index.ts:1657）
        return result

    def _prepare(self, exec_: ToolExecution):
        """调用前：pre-execute 瀑布 + 单调守卫（prepareExecution，index.ts:1463）。"""
        if self.mode_for(exec_.name) == "code":
            return PreToolDecision.deny("code 态工具只能经 run_code 传输调用")
        gate = waterfall_wrap(self._pre_execute, (exec_,), fallback=PreToolDecision.allow)
        if gate.kind == "allow":
            reason = self._layer.guard_reason(exec_)
            if reason is not None:
                return PreToolDecision.deny(reason)
        return gate

    def _dispatch(self, exec_: ToolExecution):
        """调用中：execute 环绕瀑布，兜底直接调函数体（index.ts:1569-1595）。"""
        return waterfall_wrap(self._execute, (exec_,), fallback=lambda: self._dispatch_body(exec_))

    def _dispatch_body(self, exec_: ToolExecution):
        """真正调用工具 execute，包装成 ToolResult（index.ts:1532-1560）。"""
        tool = self._layer.tools.get(exec_.name)
        if tool is None:
            return ToolResult(content=f"unknown tool: {exec_.name}", is_error=True)
        return ToolResult(content=str(tool.execute(exec_.arguments)))

    def _post(self, exec_: ToolExecution, result: ToolResult):
        """调用后：post-execute 瀑布，兜底 accept（index.ts:1742-1781）。"""
        return waterfall_wrap(self._post_execute, (exec_, result), fallback=PostToolDecision.accept)

    async def execute_async(self, exec_: ToolExecution) -> ToolResult:
        """异步执行变体：供 loop 层（asyncio）调用，支持异步 executor（如 subagent 委派）。

        与同步 ``execute`` 同一守卫语义（pre 守卫 + post 守卫），区别仅两点：
        1. 执行体若返回 coroutine（``async def execute``）则 await 之；
        2. [教学简化] 跳过同步的 ``on_execute`` 中间件瀑布——把异步续体穿进同步
        ``next()`` 链会破坏守卫语义，v1 让异步 executor 直连守卫管线（不含中间件）。
        """
        gate = self._prepare(exec_)
        if gate.kind != "allow":
            return ToolResult(content=gate.reason or f"{gate.kind}", is_error=True)

        tool = self._layer.tools.get(exec_.name)
        if tool is None:
            result = ToolResult(content=f"unknown tool: {exec_.name}", is_error=True)
        else:
            raw = tool.execute(exec_.arguments)
            if inspect.isawaitable(raw):
                raw = await raw
            result = ToolResult(content=str(raw))

        decision = self._post(exec_, result)
        if decision.kind == "block":
            result = ToolResult(content=decision.feedback or "blocked", is_error=True)

        self.ctx.emit("tools/result", exec_, result)
        return result