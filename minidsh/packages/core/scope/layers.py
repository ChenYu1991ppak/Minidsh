"""注册表层：ScopedLayers + 具名/匿名条目表。

源码对应：packages/core/scope/src/store.ts。

ScopedLayers 拥有一个注册表的「全局层 + 各 scope 精确层」：
- 读不建层（peek / chainLayers / merge）；
- 注册的可见性与 effect 归属都由调用方传入的 Context 决定（``ctx.effect`` 绑定 fiber）；
- 只有**完全空**的聚合层才被回收，不丢兄弟表。

[教学简化] mini-dsh 的 Cordis ``ctx.effect`` 是同步的（不产 generator），故
``ScopedLayers.effect`` 直接同步执行 action 并包撤回，无 yield/notify。
"""
from __future__ import annotations

from collections.abc import Callable, Iterator

__all__ = ["NamedEntries", "AnonymousEntries", "ScopedLayers"]


class NamedEntries:
    """按插入序的具名条目表（store.ts NamedEntries）。重名抛错误、undo 幂等。"""

    def __init__(self, value_type=None):
        self._data: dict = {}
        self._value_type = value_type  # 供调用方做诊断/转换（可选）

    def insert(self, name, value):
        if name in self._data:
            raise KeyError(f"duplicate name: {name!r}")
        self._data[name] = value

        def undo():
            self._data.pop(name, None)

        return undo

    def get(self, name):
        return self._data.get(name)

    def has(self, name):
        return name in self._data

    def keys(self):
        return self._data.keys()

    def entries(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def isEmpty(self):
        return len(self._data) == 0


class AnonymousEntries:
    """按插入序的匿名条目表（store.ts AnonymousEntries）。等值仍是各自独立的注册。"""

    def __init__(self):
        self._data: dict = {}
        self._seq = 0

    def append(self, value):
        key = self._seq
        self._seq += 1
        self._data[key] = value

        def undo():
            self._data.pop(key, None)

        return undo

    def values(self):
        return self._data.values()

    def isEmpty(self):
        return len(self._data) == 0


class ScopedLayers:
    """一个注册表的全局层 + 各 scope 精确层（store.ts ScopedLayers）。

    ``create_layer(scope)`` 在首次需要时被调用来建某 scope 的层；
    ``on_change()`` 在层变更时被调用（供注册表广播变化）。
    """

    def __init__(self, create_layer: Callable[[object | None], object], on_change: Callable[[], None] = None):
        self._create_layer = create_layer
        self._on_change = on_change or (lambda: None)
        self.global_layer = create_layer(None)      # 全局层：eagerly 构造
        self._scoped: dict = {}               # ScopeKey → 层

    # ---------- 读（不建层） ----------

    def peek(self, scope):
        """读某 scope 的精确层；无则返回 None（不创建）。"""
        if scope is None:
            return None
        return self._scoped.get(scope)

    def chain_layers(self, scope):
        """某 scope 沿链的既有层，最近者最后（供分层叠加时最近的最后发言）。

        [教学简化] 无 parent 链，只返回该 scope 自身的层（有则一个），无则空表。
        """
        layer = self._scoped.get(scope) if scope is not None else None
        return [layer] if layer is not None else []

    def merge(self, scope, pick: Callable[[object], NamedEntries]) -> dict:
        """全局具名条目 + scope 链遮蔽，最近 scope 的条目赢名字（store.ts merge）。"""
        merged = dict(pick(self.global_layer).entries())
        for layer in self.chain_layers(scope):
            for name, value in pick(layer).entries():
                merged[name] = value
        return merged

    # ---------- 写（绑定到传入 ctx 的 effect） ----------

    def effect(self, ctx, action: Callable[[object], Callable[[], None]], label: str = "scope-layer", scope=None) -> Callable[[], None]:
        """把一次同步层变更绑到注册上下文（store.ts effect 的同步化）。

        ``action(layer)`` 返回该次插入的同步 undo；undo 执行后若层空则回收。
        注册的可见性与 effect 归属都由 ``ctx`` 决定——``scope`` 显式给定时选该层，
        否则 ``scopeOf(ctx)`` 选层；``ctx.effect`` 绑 fiber。返回 ``ctx.effect`` 产出
        的精确 disposer。
        """
        if scope is None:
            scope = scope_of_ctx(ctx)

        def setup():
            if scope is None:
                layer = self.global_layer
            elif scope in self._scoped:
                layer = self._scoped[scope]
            else:
                layer = self._create_layer(scope)
                self._scoped[scope] = layer

            undo = action(layer)

            def teardown():
                undo()
                if scope is not None and self._scoped.get(scope) is layer and layer.isEmpty():
                    self._scoped.pop(scope, None)
                self._on_change()

            return teardown

        return ctx.effect(setup, label=label)


def scope_of_ctx(ctx):
    """从 ctx 读 scope 标签（延迟 import 避免环：scope 的 scopeOf）。"""
    from . import scopeOf

    return scopeOf(ctx)