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
import inspect
from typing import Any, Awaitable, Callable

from minidsh.cordis import CapabilityProvider
from minidsh.packages.core.scope import ScopedLayers
from .validate import validate_schema, SchemaError
from .guard import GuardRegistry

__all__ = [
    "ToolDefinition",
    "ToolOutput",
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


def waterfall_wrap_async(listeners, args, fallback):
    """异步版中间件瀑布：监听器签名 ``async def listener(*args, next)``。

    ``await next()`` 把控制权交给内层；不调用则短路。fallback 可为 async 或 sync。
    """

    async def invoke(index):
        if index >= len(listeners):
            result = fallback()
            if inspect.isawaitable(result):
                return await result
            return result
        return await listeners[index](*args, lambda: invoke(index + 1))

    return invoke(0)


# ---------------------------------------------------------------------------
# 契约对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolOutput:
    """工具输出契约（对齐官方 defineTool 的 output）。

    - ``schema``：规范值类型声明 + 运行时校验依据（{type: ...}）。
    - ``render``：``(args, value) -> str`` 把规范值转成给模型的内容。
    - ``presentation_meta``：（M5 双通道）``(args, value) -> dict | None`` 产出结构化
      展示元数据（never model-visible），随 tool-result 事件落盘供 UI 复现卡片。
      可选；缺省 ``None`` 表示该工具不产展示元数据。
    """

    schema: dict
    render: Callable[[dict, Any], str]
    presentation_meta: Callable[[dict, Any], dict | None] | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """一条工具契约（index.ts:222）：名字 + 描述 + 参数 schema + 异步执行体 + 输出契约。

    ``execute`` 为 async，接收 args（dict），返回 ``output.schema`` 声明的**规范值**。
    """

    name: str
    description: str
    parameters: dict
    execute: Callable[[dict], Awaitable[Any]]
    output: ToolOutput
    timeout_ms: int | None = None


@dataclass(frozen=True)
class ToolResult:
    """工具最终结果（对应 ToolExecutionResult）。

    ``meta``：（M5 双通道）结构化展示元数据快照，由 ``output.presentation_meta`` 产出；
    随 tool-result 事件落盘供 UI 复现卡片，never model-visible。缺省 ``None``。
    """

    content: str
    is_error: bool = False
    meta: dict | None = None


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
    """调用后决策：accept / block（index.ts:588-597）。

    ``additional_contexts`` 是下游监听器注入的附加上下文（如 repeat-tool-reminder
    的提醒文本），始终追加不替换；缺省为空 tuple。
    """

    kind: str
    feedback: str | None = None
    additional_contexts: tuple = ()

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
    guards: GuardRegistry = field(default_factory=GuardRegistry)
    modes: dict = field(default_factory=dict)  # name -> "native" | "code" | "both"

    def guard_reason(self, exec_: ToolExecution):
        """单调守卫：顺序跑，返回第一个非 None 的拒绝理由（index.ts:1119-1127）。"""
        return self.guards.evaluate(exec_)

    def isEmpty(self):
        """聚合层判空（ScopedLayers 回收依据）：工具 + 守卫 + 模式全空才算空。"""
        return not self.tools and not self.guards and not self.modes


# ---------------------------------------------------------------------------
# 运行时
# ---------------------------------------------------------------------------


class ToolRuntime(CapabilityProvider):
    """ctx.tools：注册面 + 展示面 + 执行面三合一（index.ts:787）。

    [教学简化 → 对齐 ch09] 工具/守卫/模式存进 ``ScopedLayers``（全局层 + 各 scope 精确层）。
    默认（无显式 scope）时注册到全局层，行为与旧单层完全一致；per-agent 隔离经
    ``scoped_register(scope_ctx, ...)`` 或传入 ``scope_key`` 落到精确层。
    """

    service_name = "tools"

    def _init(self, ctx):
        self._layers = ScopedLayers(create_layer=lambda scope: ToolLayer())
        self._pre_execute = []
        self._execute = []
        self._post_execute = []
        self._seq = 0

    # ---------- 定义面 ----------

    def register(self, definition: ToolDefinition, scope_key=None):
        """把工具写入作用域层并触发 tools/change，返回注销 disposer（index.ts:1037）。

        ``scope_key`` 缺省 → 全局层（对齐旧行为）；显式 key → 该 scope 精确层（per-agent 隔离）。
        """
        name = definition.name

        def add(layer: ToolLayer):
            layer.tools[name] = definition
            self.ctx.emit("tools/change", {"name": name, "op": "add"})

            def undo():
                layer.tools.pop(name, None)
                self.ctx.emit("tools/change", {"name": name, "op": "remove"})

            return undo

        return self._layers.effect(self.ctx, add, label=f"tool:{name}", scope=scope_key)

    def scoped_register(self, scope_ctx, definition: ToolDefinition):
        """在某个 scope ctx 的精确层注册工具（per-agent；M7/M9 用）。

        effect 归属 scope_ctx 的 fiber（scope.dispose 时自动撤回），层由
        ``scopeOf(scope_ctx)`` 选定。
        """
        from minidsh.packages.core.scope import scopeOf

        name = definition.name

        def add(layer: ToolLayer):
            layer.tools[name] = definition
            self.ctx.emit("tools/change", {"name": name, "op": "add"})

            def undo():
                layer.tools.pop(name, None)
                self.ctx.emit("tools/change", {"name": name, "op": "remove"})

            return undo

        return self._layers.effect(scope_ctx, add, label=f"tool:{name}", scope=scopeOf(scope_ctx))

    def guard(self, guard_fn, scope_key=None):
        """注册单调守卫：只能拒绝、不能放行（index.ts:1110）。

        底层走 GuardRegistry.register(guard_fn)，返回 disposer。
        """
        def add(layer: ToolLayer):
            return layer.guards.register(guard_fn)

        return self._layers.effect(self.ctx, add, label="tool-guard", scope=scope_key)

    def present_as(self, name, mode, scope_key=None):
        """设置工具的展示/执行模式 native/code/both（index.ts:946）。"""
        def add(layer: ToolLayer):
            prev = layer.modes.get(name, "native")
            layer.modes[name] = mode

            def undo():
                layer.modes[name] = prev

            return undo

        return self._layers.effect(self.ctx, add, label=f"tool-mode:{name}", scope=scope_key)

    def mode_for(self, name, scope_key=None):
        layer = self._effective_layer(scope_key)
        return layer.modes.get(name, "native")

    def get(self, name, scope_key=None):
        layer = self._effective_layer(scope_key)
        return layer.tools.get(name)

    def _effective_layer(self, scope_key=None):
        """合成可见层：全局层 + scope 链遮蔽（最近者赢名字）。返回一个只读视图对象。"""
        global_layer = self._layers.global_layer
        tools = dict(global_layer.tools)
        modes = dict(global_layer.modes)
        merged_guards = GuardRegistry()
        for guard in global_layer.guards:
            merged_guards.register(guard)
        for layer in self._layers.chain_layers(scope_key):
            tools.update(layer.tools)
            modes.update(layer.modes)
            for guard in layer.guards:
                merged_guards.register(guard)
        view = ToolLayer(tools=tools, guards=merged_guards, modes=modes)
        return view

    # ---------- 展示面 ----------

    def view(self):
        """可见工具集：模式非 code 的工具才向模型暴露 schema（全局层，无 scope 视图）。"""
        return self._view_for(None)

    def _view_for(self, scope_key):
        view = self._effective_layer(scope_key)
        return [
            d for d in view.tools.values() if view.modes.get(d.name, "native") != "code"
        ]

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

    # ---------- 执行面（async 统一路径） ----------

    def on_pre_execute(self, listener):
        self._pre_execute.append(listener)

    def on_execute(self, wrapper):
        self._execute.append(wrapper)

    def on_post_execute(self, listener):
        self._post_execute.append(listener)

    async def execute(self, exec_: ToolExecution) -> ToolResult:
        """跑完整异步守卫管线：prepare → dispatch → post（index.ts:1342 async 化）。"""
        gate = await self._prepare(exec_)
        if gate.kind != "allow":
            return ToolResult(content=gate.reason or f"{gate.kind}", is_error=True)

        result = await self._dispatch(exec_)
        decision = await self._post(exec_, result)
        if decision.kind == "block":
            result = ToolResult(content=decision.feedback or "blocked", is_error=True)
        elif decision.additional_contexts:
            # [教学简化] 官方把 additionalContexts 前置到下一次请求上下文；此处
            # 追加到工具结果内容，让提醒文本随 tool-result 回到模型可见面。
            suffix = "\n\n".join(decision.additional_contexts)
            result = ToolResult(content=f"{result.content}\n\n{suffix}", is_error=result.is_error)

        self.ctx.emit("tools/result", exec_, result)  # 通知观察者（只读，index.ts:1657）
        return result

    async def _prepare(self, exec_: ToolExecution):
        """调用前：pre-execute 异步瀑布 + 单调守卫（prepareExecution，index.ts:1463）。"""
        if self.mode_for(exec_.name) == "code":
            return PreToolDecision.deny("code 态工具只能经 run_code 传输调用")
        gate = await waterfall_wrap_async(
            self._pre_execute, (exec_,), fallback=PreToolDecision.allow
        )
        if gate.kind == "allow":
            view = self._effective_layer()
            reason = view.guard_reason(exec_)
            if reason is not None:
                return PreToolDecision.deny(reason)
        return gate

    async def _dispatch(self, exec_: ToolExecution):
        """调用中：execute 异步环绕瀑布，兜底直接调异步工具体（index.ts:1569-1595）。"""
        return await waterfall_wrap_async(
            self._execute, (exec_,), fallback=lambda: self._dispatch_body(exec_)
        )

    async def _dispatch_body(self, exec_: ToolExecution):
        """真正调用工具 execute → 校验规范值 → output.render 包装成 ToolResult。"""
        view = self._effective_layer()
        tool = view.tools.get(exec_.name)
        if tool is None:
            return ToolResult(content=f"unknown tool: {exec_.name}", is_error=True)

        value = tool.execute(exec_.arguments)
        if inspect.isawaitable(value):
            value = await value

        # 校验：规范值须符合 output.schema（不符 → 错误结果）
        try:
            validate_schema(value, tool.output.schema)
        except SchemaError as exc:
            return ToolResult(content=f"输出校验失败：{exc}", is_error=True)

        # M5 双通道：产展示元数据（可选）；失败不阻断主路径，降级无 meta
        meta = None
        if tool.output.presentation_meta is not None:
            try:
                meta = tool.output.presentation_meta(exec_.arguments, value)
            except Exception:
                meta = None

        content = tool.output.render(exec_.arguments, value)
        return ToolResult(content=str(content), meta=meta)

    async def _post(self, exec_: ToolExecution, result: ToolResult):
        """调用后：post-execute 异步瀑布，兜底 accept（index.ts:1742-1781）。"""
        return await waterfall_wrap_async(
            self._post_execute, (exec_, result), fallback=PostToolDecision.accept
        )

