"""T2 验收测试：inject 依赖检查（严格解析 + 插件化 deferral）。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context, Service, ServiceNotFoundError


# ---------- ctx.inject：严格解析 ----------


def test_inject_with_satisfied_deps():
    ctx = Context()
    ctx.provide("a", "A")
    ctx.provide("b", "B")

    seen = ctx.inject(["a", "b"], lambda a, b: (a, b))
    assert seen == ("A", "B")


def test_inject_missing_dep_raises_with_names():
    ctx = Context()
    ctx.provide("a", "A")

    with pytest.raises(ServiceNotFoundError) as exc:
        ctx.inject(["a", "b", "c"], lambda *_: None)

    msg = str(exc.value)
    assert "b" in msg and "c" in msg  # 错误信息含缺失依赖名（可能多个）


# ---------- 插件化 deferral：Fiber 齐备才加载 ----------


def test_fiber_deferred_until_deps_satisfied():
    ctx = Context()
    loaded = []

    def consumer(ctx):
        # 此处依赖 "dep" 已就绪（deps_satisfied 保证）
        loaded.append(ctx.dep)

    consumer.inject = ["dep"]

    fiber = ctx.plugin(consumer)
    assert fiber.state == fiber.PENDING  # 依赖未齐备，不加载
    assert fiber.missing_deps() == ["dep"]

    ctx.provide("dep", "ready")  # 补齐依赖 → 结算
    assert fiber.state == fiber.ACTIVE
    assert loaded == ["ready"]
    assert fiber.missing_deps() == []


def test_fiber_events_is_not_external_dep():
    ctx = Context()
    loaded = []

    def consumer(ctx):
        loaded.append(True)

    consumer.inject = ["events"]  # events 是容器内置，不算外部依赖

    fiber = ctx.plugin(consumer)
    assert fiber.state == fiber.ACTIVE
    assert loaded == [True]


def test_fiber_multiple_pending_settles_in_order():
    ctx = Context()
    order = []

    def mk(name):
        def body(ctx):
            order.append(name)

        body.inject = ["dep"]
        return body

    ctx.plugin(mk("first"))
    ctx.plugin(mk("second"))

    assert order == []  # 都还在 PENDING
    ctx.provide("dep", "D")
    assert order == ["first", "second"]  # 按注册顺序结算


def test_service_registers_even_when_fiber_pending():
    """Service 构造即注册不依赖 fiber 状态：服务表写出立即可读。"""
    ctx = Context()

    class Tac(Service):
        pass

    Tac(ctx, "tac")
    assert ctx.tac is not None