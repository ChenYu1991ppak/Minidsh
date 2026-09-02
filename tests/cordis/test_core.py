"""T1 验收测试：cordis 内核基线——容器四合一语义。

覆盖：provide/probe、Service 构造即注册、effect 可逆注册与逆序回收、dispose 回滚、
plugin 三形态归一化、ServiceNotFoundError 语义。
"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context, Fiber, Service, ServiceNotFoundError


# ---------- provide / 服务解析 ----------


def test_provide_then_read():
    ctx = Context()
    ctx.provide("greeting", "hello")
    assert ctx.greeting == "hello"


def test_missing_service_raises_service_not_found():
    ctx = Context()
    with pytest.raises(ServiceNotFoundError) as exc:
        ctx.nothing
    assert exc.value.service_name == "nothing"


def test_missing_service_is_an_attribute_error():
    # [教学决策 G1] 继承 AttributeError，缺省值写法可用
    ctx = Context()
    assert getattr(ctx, "nothing", "default") == "default"


def test_internal_attr_is_not_service():
    ctx = Context()
    # 下划线前缀走普通属性，不路由到服务表
    with pytest.raises(AttributeError):
        ctx._fibers_missing


def test_provide_disposer_removes_service():
    ctx = Context()
    dispose = ctx.provide("greeting", "hello")
    assert ctx.greeting == "hello"
    dispose()
    with pytest.raises(ServiceNotFoundError):
        ctx.greeting


# ---------- Service 构造即注册 ----------


def test_service_registers_on_construction():
    ctx = Context()

    class Greeter(Service):
        def greet(self):
            return "hi"

    # 直接实例化即可注册（不必经 plugin）
    g = Greeter(ctx, "greeting")
    assert ctx.greeting is g
    assert ctx.greeting.greet() == "hi"


# ---------- effect 可逆注册 + 逆序回收 ----------


def test_effect_collects_and_reverses_disposers():
    ctx = Context()
    order = []

    ctx.effect(lambda: order.append("setup-1") or (lambda: order.append("teardown-1")))
    ctx.effect(lambda: order.append("setup-2") or (lambda: order.append("teardown-2")))

    assert order == ["setup-1", "setup-2"]
    ctx.dispose()
    # 后注册的先清理
    assert order == ["setup-1", "setup-2", "teardown-2", "teardown-1"]


def test_effect_with_no_disposer_is_noop():
    ctx = Context()
    ctx.effect(lambda: None)  # 无清理函数，不抛错
    ctx.dispose()  # 正常回收


# ---------- plugin 三形态归一化 ----------


def test_plugin_with_class():
    ctx = Context()

    class P:
        inject = []

        def __init__(self, ctx):
            ctx.provide("from-class", "constructed")

    fiber = ctx.plugin(P, config="cfg")
    assert ctx.probe("from-class") == "constructed"
    # config 不透传给 class 构造器（SPEC §9 决议 2/3），而是存到 Fiber.config
    assert fiber.config == "cfg"


def test_plugin_with_function():
    ctx = Context()

    def p(ctx):
        ctx.provide("from-func", "f")

    ctx.plugin(p)
    assert ctx.probe("from-func") == "f"


def test_plugin_with_apply_object():
    ctx = Context()

    class P:
        def apply(self, ctx):
            ctx.provide("from-apply", "a")

    ctx.plugin(P())
    assert ctx.probe("from-apply") == "a"


def test_plugin_returns_fiber():
    ctx = Context()
    fiber = ctx.plugin(lambda ctx: None)
    assert isinstance(fiber, Fiber)
    assert fiber.state == Fiber.ACTIVE


# ---------- dispose 回滚 ----------


def test_dispose_rolls_back_services():
    ctx = Context()

    class Greeter(Service):
        """经基类 name 注册的服务：卸载时随 effect 回收。"""

    Greeter(ctx, "greeting")
    assert ctx.greeting is not None

    ctx.dispose()
    with pytest.raises(ServiceNotFoundError):
        ctx.greeting


def test_dispose_is_idempotent():
    ctx = Context()
    calls = []
    ctx.effect(lambda: (lambda: calls.append("t")))
    ctx.dispose()
    ctx.dispose()  # 第二次不重复执行
    assert calls == ["t"]