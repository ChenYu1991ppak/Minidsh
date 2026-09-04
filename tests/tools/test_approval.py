"""M3 验收测试：approval 替换 permission（ctx.approval + ask/never + waterfall）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.approval import (
    ApprovalRequest,
    ApprovalProvider,
    APPROVAL_POLICIES,
)
from minidsh.packages.services.session import SessionStore


def _fake_agent(session=None):
    """造一个带 session 的 agent 对象（供 ApprovalRequest 用）。"""
    if session is None:
        ctx = Context()
        store = SessionStore(ctx)
        session = store.create()
    return type("MockAgent", (), {"session": session})()


def _svc(ctx, policy="ask"):
    """装配 approval provider 并设策略，返回注册好的 ctx.approval。"""
    ApprovalProvider(ctx)
    svc = ctx.approval
    svc.set_policy(policy)
    return svc


def _ctx():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    return ctx


# ---------- 策略 ----------


async def test_never_policy_always_rejects():
    ctx = _ctx()
    svc = _svc(ctx, policy="never")
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "rejected"


async def test_ask_policy_no_answerers_unavailable():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "unavailable"  # 无应答者 → fail-closed


async def test_set_policy_rejects_invalid():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")
    try:
        svc.set_policy("invalid")  # type: ignore
        assert False, "应该抛 ValueError"
    except ValueError:
        pass


async def test_set_policy_switches_behavior():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")
    svc.set_policy("never")
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "rejected"


# ---------- 应答者 waterfall ----------


async def test_answerer_allows_once():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def answerer(req, next_):
        return "allowed-once"

    ctx.on("approval/request", answerer)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "allowed-once"


async def test_answerer_rejects():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def answerer(req, next_):
        return "rejected"

    ctx.on("approval/request", answerer)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "rejected"


async def test_answerer_waterfall_delegates_with_next():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def first(req, next_):
        return await next_()  # 委托

    async def second(req, next_):
        return "allowed-once"

    ctx.on("approval/request", first)
    ctx.on("approval/request", second)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "allowed-once"


async def test_answerer_waterfall_first_claims_slot():
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    calls = []

    async def first(req, next_):
        calls.append("first")
        return "rejected"  # 占据决策槽位，不委托

    async def second(req, next_):
        calls.append("second")
        return "allowed-once"

    ctx.on("approval/request", first)
    ctx.on("approval/request", second)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "rejected"
    assert calls == ["first"]  # second 没被调用


# ---------- 审计事件 ----------


async def test_audit_events_written_to_session():
    ctx = _ctx()
    store = ctx.sessions
    session = store.create()
    agent = _fake_agent(session=session)
    svc = _svc(ctx, policy="never")

    req = ApprovalRequest(agent=agent, tool_name="bash", call_id="call-1", reason="test")
    await svc.request(req)

    events = session.events()
    asked = [e for e in events if e.type == "approval/asked"]
    decided = [e for e in events if e.type == "approval/decided"]
    assert len(asked) == 1
    assert asked[0].payload["tool_name"] == "bash"
    assert asked[0].payload["call_id"] == "call-1"
    assert asked[0].payload["reason"] == "test"
    assert len(decided) == 1
    assert decided[0].payload["outcome"] == "rejected"


# ---------- provider ----------


def test_approval_provider_registers():
    ctx = Context()
    ApprovalProvider(ctx)  # 构造即注册 ctx.approval
    assert ctx.has("approval")


async def test_approval_provider_default_ask():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ApprovalProvider(ctx)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await ctx.approval.request(req)
    assert outcome == "unavailable"  # ask 策略 + 无应答者 → fail-closed


# ---------- 常量 ----------


def test_approval_policies_constant():
    assert "ask" in APPROVAL_POLICIES
    assert "never" in APPROVAL_POLICIES
    assert len(APPROVAL_POLICIES) == 2


# ---------- M6 register_answerer ----------


async def test_register_answerer_routes_request():
    """register_answerer 注册的应答者接收 request（对齐官方 user-approval 应答者）。"""
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def answerer(req, next_):
        return "allowed-once"

    dispose = svc.register_answerer(answerer)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "allowed-once"
    dispose()


async def test_register_answerer_disposer_removes():
    """注销应答者后回到无应答者 → unavailable（fail-closed 不变）。"""
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def answerer(req, next_):
        return "allowed-once"

    dispose = svc.register_answerer(answerer)
    dispose()
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "unavailable"


async def test_register_answerer_waterfall_delegates():
    """register_answerer 的应答者返回 None / 调 next 委托下一应答者。"""
    ctx = _ctx()
    svc = _svc(ctx, policy="ask")

    async def first(req, next_):
        return await next_()  # 委托

    async def second(req, next_):
        return "rejected"

    svc.register_answerer(first)
    svc.register_answerer(second)
    req = ApprovalRequest(agent=_fake_agent(), tool_name="bash")
    outcome = await svc.request(req)
    assert outcome == "rejected"