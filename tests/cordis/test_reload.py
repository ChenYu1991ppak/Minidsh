"""cordis「变化即重载」测试：依赖服务被替换/移除时，激活中的 fiber 先卸载再重载。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context


def _plugin(events, default_value="?"):
    """一个依赖 ``dep`` 服务的插件，记录 activate/cleanup 序列。"""

    class P:
        inject = ["dep"]

        def __init__(self, ctx):
            value = ctx.probe("dep") if ctx.has("dep") else default_value
            events.append(f"activate:{value}")

            def cleanup():
                events.append("cleanup")

            ctx.effect(lambda: cleanup)

    return P


# ---------- 提供即激活 ----------


def test_plugin_activates_after_dep_provided():
    ctx = Context()
    events = []
    ctx.plugin(_plugin(events), config=None)
    assert events == []  # 依赖未满足，停在 PENDING

    ctx.provide("dep", "v1")
    assert events == ["activate:v1"]


# ---------- 重载：依赖被替换 ----------


def test_reload_on_service_replace():
    ctx = Context()
    events = []
    ctx.provide("dep", "v1")
    ctx.plugin(_plugin(events))
    assert events == ["activate:v1"]

    ctx.provide("dep", "v2")  # 替换 → 卸载（cleanup）+ 重新激活
    assert events == ["activate:v1", "cleanup", "activate:v2"]


def test_reload_rebinds_injected_reference():
    ctx = Context()
    seen = {}

    class P:
        inject = ["dep"]

        def __init__(self, ctx):
            ctx.effect(lambda: seen.update(dep=ctx.probe("dep")))

    ctx.provide("dep", "v1")
    ctx.plugin(P)
    assert seen["dep"] == "v1"

    ctx.provide("dep", "v2")
    assert seen["dep"] == "v2"  # 重载后注入的是新引用


# ---------- 移除：依赖消失 ----------


def test_remove_dependency_unloads_to_pending():
    ctx = Context()
    events = []
    ctx.provide("dep", "v1")
    ctx.plugin(_plugin(events))
    assert events == ["activate:v1"]

    ctx.probe("dep")  # 占位；下面直接移除服务并广播 dispose

    # 拿到「移除+广播 service/dispose」的路径：provide 返回的 disposer 即此路径
    off = ctx.provide("dep", "v2")  # 替换（重载一次）
    assert events == ["activate:v1", "cleanup", "activate:v2"]

    off()  # 移除 dep → 卸载回 PENDING
    assert events == ["activate:v1", "cleanup", "activate:v2", "cleanup"]
    assert not ctx.has("dep")
    assert ctx._pending  # 回到等待列表


# ---------- 多依赖：局部重载 ----------


def test_multiple_deps_partial_reload():
    ctx = Context()
    events = []

    class P:
        inject = ["a", "b"]

        def __init__(self, ctx):
            events.append("activate")

            def cleanup():
                events.append("cleanup")

            ctx.effect(lambda: cleanup)

    ctx.provide("a", 1)
    ctx.provide("b", 2)
    ctx.plugin(P)
    assert events == ["activate"]

    off_b = ctx.provide("b", 3)  # 替换 b（a、b 仍在）→ 重载
    assert events == ["activate", "cleanup", "activate"]

    off_b()  # 移除 b → 仅剩 a，仍缺 b → 卸载回 PENDING
    assert events == ["activate", "cleanup", "activate", "cleanup"]


def test_unrelated_service_change_does_not_reload():
    ctx = Context()
    events = []
    ctx.provide("dep", "v1")
    ctx.provide("other", "x")
    ctx.plugin(_plugin(events))
    assert events == ["activate:v1"]

    ctx.provide("other", "y")  # 非依赖服务变化 → 不重载
    assert events == ["activate:v1"]


# ---------- 卸载幂等 ----------


def test_dispose_does_not_double_unload():
    ctx = Context()
    events = []
    ctx.provide("dep", "v1")
    ctx.plugin(_plugin(events))
    assert events == ["activate:v1"]

    ctx.dispose()
    assert events == ["activate:v1", "cleanup"]
    ctx.dispose()  # 幂等
    assert events == ["activate:v1", "cleanup"]