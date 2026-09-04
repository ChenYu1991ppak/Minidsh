"""approval 能力定义：审批 seam（ctx.approval）。

源码对应：
- ``ApprovalService`` ↔ packages/interaction/user-approval/src/index.ts
- ``ApprovalOutcome`` / ``ApprovalPolicy`` ↔ packages/interaction/user-approval/src/types.ts

审批能力决定一次敏感操作是否放行。策略（ask/never）在 waterfall 分发应答者**之前**
强制执行；应答者通过 ``approval/request`` 瀑布事件提供决策。

``ApprovalService`` 是定义（纯契约 + 决策逻辑）；`self.ctx` 由 Service 基类构造时写入，
``self._default_policy`` 由 provider 的 ``_init`` 写入。

[教学简化] 无 TUI 人类应答者（应答者链默认空 → ``unavailable`` fail-closed）；
``ask`` 策略在无应答者时等价于 ``never``。审计事件 ``approval/asked`` / ``approval/decided``
仅写入会话日志，不进模型 transcript。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from minidsh.cordis import CapabilityDefinition

__all__ = [
    "ApprovalOutcome",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalService",
    "APPROVAL_POLICIES",
]

# 闭合审批结果（fail-closed）
ApprovalOutcome = Literal["allowed-once", "rejected", "cancelled", "unavailable"]

# 审批策略
ApprovalPolicy = Literal["ask", "never"]
APPROVAL_POLICIES: tuple[ApprovalPolicy, ...] = ("ask", "never")


@dataclass(frozen=True)
class ApprovalRequest:
    """一次审批请求：包含 agent、工具名、可选 call_id 和拒绝原因。"""

    agent: object  # ReactLoopAgent（避免循环依赖，用 object + 文档标注）
    tool_name: str
    call_id: str | None = None
    reason: str | None = None


class ApprovalService(CapabilityDefinition):
    """ctx.approval：审批服务定义。

    策略 + 应答者 waterfall 两层决策：
    1. ``never`` 策略 → 直接返回 ``rejected``（不分发应答者）
    2. ``ask`` 策略 → 分发 ``approval/request`` 瀑布事件，无应答者 → ``unavailable``

    既是定义（seam 契约）也是决策逻辑载体；provider 经 CapabilityProvider
    构造即注册到 ``ctx.approval``。
    """

    service_name = "approval"

    def register_answerer(self, answerer) -> "Callable[[], None]":
        """注册一个审批应答者到 ``approval/request`` 瀑布（M6）。

        ``answerer`` 签名 ``async def answerer(req, next) -> ApprovalOutcome | None``：
        返回 outcome 占据决策槽位；调 ``next()`` 委托下一应答者；返回 ``None`` 亦委托。
        无应答者时 ``_decide`` 落 ``unavailable``（fail-closed 不变）。返回 off disposer。

        [教学简化] 直接封装 ``ctx.on("approval/request", ...)``；不做官方 scope 过滤
        （per-agent 应答者路由）。
        """
        return self.ctx.on("approval/request", answerer)

    def effective_policy(self, session) -> ApprovalPolicy:
        """读取会话当前生效的审批策略（先查 session 覆盖，否则用默认）。"""
        # [教学简化] 无 session-level approval/policy 事件覆盖，一律用默认
        return self._default_policy

    def set_policy(self, policy: ApprovalPolicy) -> None:
        """切换默认审批策略。"""
        if policy not in APPROVAL_POLICIES:
            raise ValueError(f"审批策略必须为 'ask' 或 'never'，实际 {policy!r}")
        self._default_policy = policy

    async def request(self, req: ApprovalRequest) -> ApprovalOutcome:
        """请求审批：先检查策略，再分发应答者瀑布。

        ``never`` 策略 → 直接返回 ``rejected``（不经过应答者）。
        ``ask`` 策略 → 分发 ``approval/request`` 瀑布事件给应答者链；
        无应答者 → ``unavailable``（fail-closed）。

        审计事件 ``approval/asked`` / ``approval/decided`` 写入 session 日志。
        """
        session = getattr(req.agent, "session", None)
        policy = self.effective_policy(session)

        # 审计：asked
        import uuid
        request_id = str(uuid.uuid4())
        if session is not None:
            session.append("approval/asked", {
                "id": request_id,
                "tool_name": req.tool_name,
                "call_id": req.call_id,
                "reason": req.reason,
            })

        # 策略层：never 直接拒绝，不经过应答者
        if policy == "never":
            outcome: ApprovalOutcome = "rejected"
        else:
            outcome = await self._decide(req)

        # 审计：decided
        if session is not None:
            session.append("approval/decided", {
                "id": request_id,
                "outcome": outcome,
            })

        return outcome

    async def _decide(self, req: ApprovalRequest) -> ApprovalOutcome:
        """分发 ``approval/request`` 瀑布事件给应答者链。

        中间件式瀑布：每个应答者返回 outcome 或调 ``next()`` 委托下一应答者。
        第一个非 None 结果占据决策槽位；全部委托 → ``unavailable``。
        """
        from minidsh.cordis.symbols import Symbols

        listeners = list(getattr(self.ctx, Symbols.events).get("approval/request", []))

        async def invoke(index: int) -> ApprovalOutcome:
            if index >= len(listeners):
                return "unavailable"  # 无应答者 → fail-closed

            async def next_():
                return await invoke(index + 1)

            result = listeners[index](req, next_)
            import inspect
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                return result
            return await next_()

        return await invoke(0)