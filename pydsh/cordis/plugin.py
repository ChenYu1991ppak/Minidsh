"""插件标准化：``Plugin`` 实体 + ``normalize_plugin`` 四形态归一。

对齐官方 <https://deepseek-harness.github.io/deepseek-harness/develop/basic/> 的插件三形态
（function / object / class），补一个 Python 便利形态（module），归一到轻量 ``Plugin``
实体（name / inject / factory 三要素）。

归一后的 ``Plugin`` 是 Fiber 唯一消费的形态：Fiber 不再直接读原始回调的 ``inject``
或拼 ``name``。四个形态的 name/inject/apply 来源见各 ``_from_*``。

name 缺省推导规则（SPEC-plugin-def §2.2）：
- 优先级：显式 ``name`` 字段 > 名字推导（``__name__`` / 模块短名）。
- 显式重名的拦截不在这里（归一不做全局唯一性），由 ``ctx.plugin``/Fiber 在注册时把关
  （SPEC §9 决议 1）。
"""
from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["Plugin", "normalize_plugin"]

# 执行体 = 单参 ctx 的可调用对象（apply 语义；config 不下发到 factory，见 SPEC §9 决议 3）
Factory = Callable[[Any], Any]


@dataclass(frozen=True)
class Plugin:
    """归一化的插件实体（身份 + 依赖 + 执行体）。

    ``explicit_name``：name 是否来自显式声明（``name`` 字段）而非名字推导。供
    ``ctx.plugin`` 做重名把关——显式重名抛错、推导重名只告警（SPEC §9 决议 1）。
    """

    name: str
    inject: list[str] = field(default_factory=list)
    factory: Factory | None = None
    explicit_name: bool = False


def normalize_plugin(obj: Any) -> Plugin:
    """把四形态任意一种（或已归一化的 Plugin）归一为 ``Plugin``。

    判定顺序（有先后）：
    1. 已是 Plugin → 原样返回（幂等）
    2. module（`types.ModuleType`）→ 模块级 name/inject/apply
    3. class（`type`）→ 类属性 name/inject + 类本身当 factory（`cls(ctx)`）
    4. 有 ``apply`` 可调用对象 → `obj.name`/`obj.inject` + `obj.apply`
    5. 可调用对象（函数）→ `fn.name`/`fn.inject` + `fn` 本身

    都不是则抛 ``TypeError``，报出对象类型。
    """
    if isinstance(obj, Plugin):
        return obj
    if isinstance(obj, types.ModuleType):
        return _from_module(obj)
    if isinstance(obj, type):
        return _from_class(obj)
    apply_fn = getattr(obj, "apply", None)
    if callable(apply_fn):
        return _from_object(obj, apply_fn)
    if callable(obj):
        return _from_function(obj)
    raise TypeError(
        f"无法把 {type(obj).__name__!r} 归一为插件：需是 module / class / 带 apply 的对象 / 函数之一"
    )


def _inject_of(obj: Any) -> list[str]:
    raw = getattr(obj, "inject", None)
    if raw is None:
        return []
    return list(raw)


def _explicit_name_of(obj: Any) -> bool:
    return getattr(obj, "name", None) is not None


def _from_module(mod: types.ModuleType) -> Plugin:
    explicit = _explicit_name_of(mod)
    name = getattr(mod, "name", None) or mod.__name__.rsplit(".", 1)[-1]
    apply = getattr(mod, "apply", None)
    if not callable(apply):
        raise TypeError(
            f"模块插件 {mod.__name__!r} 缺少 apply(ctx) 函数（module 形态需导出 apply）"
        )
    return Plugin(name=name, inject=_inject_of(mod), factory=apply, explicit_name=explicit)


def _from_class(cls: type) -> Plugin:
    explicit = _explicit_name_of(cls)
    name = getattr(cls, "name", None) or cls.__name__
    return Plugin(name=name, inject=_inject_of(cls), factory=cls, explicit_name=explicit)


def _from_object(obj: Any, apply_fn: Callable) -> Plugin:
    explicit = _explicit_name_of(obj)
    name = getattr(obj, "name", None) or type(obj).__name__
    return Plugin(name=name, inject=_inject_of(obj), factory=apply_fn, explicit_name=explicit)


def _from_function(fn: Callable) -> Plugin:
    explicit = _explicit_name_of(fn)
    name = getattr(fn, "name", None) or fn.__name__
    return Plugin(name=name, inject=_inject_of(fn), factory=fn, explicit_name=explicit)