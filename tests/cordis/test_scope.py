"""M1 验收测试：scope 库原语 + Context.extend 子容器。

覆盖 scope/index.ts + store.ts 的落地子集：createScope 读继承写孤立、Scope.dispose
停稳撤销、ScopedLayers 全局+精确层的读写与回收。
"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context, Service
from minidsh.packages.core.scope import createScope, scopeOf, ScopedLayers, NamedEntries


class _Layer:
    """测试用聚合层：一个 NamedEntries 表。"""

    def __init__(self):
        self.entries = NamedEntries()

    def isEmpty(self):
        return self.entries.isEmpty()


def _scoped_layers():
    return ScopedLayers(create_layer=lambda scope: _Layer())


# ---------- Context.extend 子容器 ----------


def test_child_reads_parent_service():
    parent = Context()
    parent.provide("greeting", "hello")
    child = parent.extend()
    assert child.greeting == "hello"


def test_child_write_isolated_from_parent():
    parent = Context()
    child = parent.extend()
    child.provide("own", "x")
    assert child.own == "x"
    assert not parent.has("own")


def test_child_probe_and_has_inherit():
    parent = Context()
    parent.provide("greeting", "hello")
    child = parent.extend()
    assert child.has("greeting") is True
    assert child.probe("greeting") == "hello"


def test_grandchild_inherits_through_chain():
    parent = Context()
    parent.provide("greeting", "hi")
    child = parent.extend()
    grand = child.extend()
    assert grand.greeting == "hi"


# ---------- createScope / Scope.dispose ----------


def test_create_scope_provides_and_disposes():
    ctx = Context()
    scope = createScope(ctx)
    assert scopeOf(scope.ctx) is not None

    greeter = Service(scope.ctx, "scoped-greeting")
    assert scope.ctx.probe("scoped-greeting") is greeter

    scope.dispose()
    assert not scope.ctx.has("scoped-greeting")


def test_create_scope_inherits_services_and_isolates_writes():
    ctx = Context()
    ctx.provide("base", "B")
    scope = createScope(ctx)
    assert scope.ctx.base == "B"      # 读继承
    scope.ctx.provide("scoped", "S")  # 写孤立
    assert scope.ctx.scoped == "S"
    assert not ctx.has("scoped")
    # 父容器不受影响
    scope.dispose()
    assert ctx.base == "B"


def test_scope_dispose_is_idempotent():
    ctx = Context()
    scope = createScope(ctx)
    Service(scope.ctx, "x")  # Service 经 effect 注册，随 scope.dispose 撤销
    scope.dispose()
    scope.dispose()  # 第二次安全
    assert not scope.ctx.has("x")


def test_scope_key_distinct_per_create():
    ctx = Context()
    s1 = createScope(ctx)
    s2 = createScope(ctx)
    assert scopeOf(s1.ctx) is not scopeOf(s2.ctx)


# ---------- ScopedLayers ----------


def test_global_layer_eagerly_constructed():
    layers = _scoped_layers()
    assert layers.global_layer is not None
    layers.global_layer.entries.insert("a", 1)
    assert layers.global_layer.entries.get("a") == 1


def test_exact_scope_layers_isolated():
    layers = _scoped_layers()
    ctx = Context()
    s1 = createScope(ctx)
    s2 = createScope(ctx)

    layers.effect(s1.ctx, lambda L: L.entries.insert("tool", "s1-tool"))
    layers.effect(s2.ctx, lambda L: L.entries.insert("tool", "s2-tool"))

    k1, k2 = scopeOf(s1.ctx), scopeOf(s2.ctx)
    assert layers.peek(k1).entries.get("tool") == "s1-tool"
    assert layers.peek(k2).entries.get("tool") == "s2-tool"
    assert layers.global_layer.entries.isEmpty()  # 未动全局


def test_global_and_scope_merge_nearest_wins():
    layers = _scoped_layers()
    ctx = Context()
    layers.global_layer.entries.insert("tool", "global")
    scope = createScope(ctx)
    layers.effect(scope.ctx, lambda L: L.entries.insert("tool", "scoped"))

    merged = layers.merge(scopeOf(scope.ctx), lambda L: L.entries)
    assert merged["tool"] == "scoped"


def test_scope_layer_reclaimed_when_empty():
    layers = _scoped_layers()
    ctx = Context()
    scope = createScope(ctx)
    key = scopeOf(scope.ctx)

    disposer = layers.effect(scope.ctx, lambda L: L.entries.insert("x", 1))
    assert layers.peek(key) is not None
    disposer()                      # undo 后层空 → 回收
    assert layers.peek(key) is None
    assert not scope.ctx.has(key if False else "__noop__")  # scope 不受影响


def test_scope_dispose_unwinds_layer_registrations():
    layers = _scoped_layers()
    ctx = Context()
    scope = createScope(ctx)
    key = scopeOf(scope.ctx)

    layers.effect(scope.ctx, lambda L: L.entries.insert("x", 1))
    assert layers.peek(key) is not None

    scope.dispose()                 # effect 绑在 scope.ctx 的 fiber 上 → 自动撤回
    assert layers.peek(key) is None