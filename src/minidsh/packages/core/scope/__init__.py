"""scope 库原语：铸造带身份标签的 Cordis 子容器，并为该身份建路由。

源码对应：packages/core/scope/src/index.ts。这不是 cordis 服务，是库原语——
同一个注册上下文同时表达「每个 agent 的可见性」与「共享生命周期所有权」。

关键语义（index.ts 顶部注释）：
- 注册视图**沿链向下继承**：子 scope 看得见祖先层（``ScopedLayers``）；
- 事件准入**沿链向上扩展**：挂在祖先上的监听器收到后代 key 派发的事件。

mini-dsh 落地子集（相对官方，见 [教学简化]）：
- ``createScope`` = ``ctx.extend`` 一个带 scope 标签的子容器（读继承、写孤立），
  ``Scope.dispose()`` 停稳撤销其拥有的一切注册；
- 不落地 scope parent 链 / rebind / scopeTarget（M9 之前用不到），只保留
  createScope / scopeOf / ScopedLayers 三件套，供 tool_runtime（M7）与
  subagent（M9）使用。
"""
from __future__ import annotations

from minidsh.cordis import Context

from .layers import ScopedLayers, NamedEntries, AnonymousEntries

__all__ = [
    "Scope",
    "createScope",
    "scopeOf",
    "ScopedLayers",
    "NamedEntries",
    "AnonymousEntries",
]

# 不透明身份（官方 ScopeKey = object）。identity 比较，从不检视内容。
ScopeKey = object

# scope 标签属性名（对应官方 kScope Symbol）。
_SCOPE_TAG = "__minidsh_scope__"


class Scope:
    """一次铸造的注册作用域与其停稳边界（官方 Scope）。

    - ``ctx``：作用域拥有的子容器（写归它、读回退父）。
    - ``dispose()``：撤销 scope 拥有的一切注册；竞态安全（幂等）。
    """

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self._disposed = False

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.ctx.dispose()


def createScope(ctx: Context, key: object = None) -> Scope:
    """在 ``ctx`` 下铸造一个作用域（官方 createScope）。

    [教学简化] 官方经 backing fiber 把 scope 生命周期绑到铸造它的插件；mini-dsh
    直接 ``extend`` 一个子容器，``Scope.dispose()`` 撤销子容器拥有的全部注册。
    """
    key = key if key is not None else object()
    scoped = ctx.extend(**{_SCOPE_TAG: key})
    return Scope(scoped)


def scopeOf(ctx: Context) -> object | None:
    """读最近一次继承到的 scope 标签（官方 scopeOf）；无 scope 返回 None。"""
    return getattr(ctx, _SCOPE_TAG, None)