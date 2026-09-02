"""BT1 验收测试：Plugin 实体 + normalize_plugin 四形态归一。"""
from __future__ import annotations

import types

import pytest

from minidsh.cordis import Plugin, normalize_plugin


def _mk_module(name="mymod", inject=None, has_apply=True, module_name="fake_mod"):
    mod = types.ModuleType(module_name)
    mod.name = name
    if inject is not None:
        mod.inject = inject
    if has_apply:
        def apply(ctx):
            return "applied"

        mod.apply = apply
    return mod


# ---------- Plugin 幂等 ----------


def test_plugin_is_idempotent():
    p = Plugin(name="x", inject=["a"], factory=lambda ctx: None)
    assert normalize_plugin(p) is p


# ---------- module 形态 ----------


def test_module_form_extracts_name_inject_apply():
    mod = _mk_module(name="my-tool-plugin", inject=["tools"])
    p = normalize_plugin(mod)
    assert p.name == "my-tool-plugin"
    assert p.inject == ["tools"]
    assert callable(p.factory)
    assert p.factory(None) == "applied"


def test_module_form_falls_back_to_module_short_name():
    mod = _mk_module(name=None, module_name="pkg.my_tool_plugin")
    assert normalize_plugin(mod).name == "my_tool_plugin"


def test_module_form_missing_apply_raises():
    mod = _mk_module(has_apply=False)
    with pytest.raises(TypeError):
        normalize_plugin(mod)


# ---------- class 形态 ----------


def test_class_form():
    class P:
        inject = ["tools"]

        def __init__(self, ctx):
            self.ctx = ctx

    p = normalize_plugin(P)
    assert p.name == "P"
    assert p.inject == ["tools"]
    # factory 是类本身，调用即实例化（官方 constructor(ctx) 语义）
    inst = p.factory("ctx-value")
    assert isinstance(inst, P)
    assert inst.ctx == "ctx-value"


def test_class_form_explicit_name_wins():
    class P:
        name = "my-svc"
        inject = []

    assert normalize_plugin(P).name == "my-svc"


# ---------- object 形态（带 apply） ----------


def test_object_form():
    class O:
        name = "obj-plugin"
        inject = ["llm"]

        def apply(self, ctx):
            return "obj-applied"

    p = normalize_plugin(O())
    assert p.name == "obj-plugin"
    assert p.inject == ["llm"]
    assert p.factory(None) == "obj-applied"


# ---------- function 形态 ----------


def test_function_form_default_name():
    def my_plugin(ctx):
        return "fn-applied"

    p = normalize_plugin(my_plugin)
    assert p.name == "my_plugin"  # 缺省用 __name__
    assert p.inject == []
    assert p.factory(None) == "fn-applied"


def test_function_form_with_inject_attr():
    def f(ctx):
        pass

    f.inject = ["tools"]  # noqa: B010 便利写法：函数对象挂 inject
    p = normalize_plugin(f)
    assert p.inject == ["tools"]


# ---------- 拒绝非法形态 ----------


def test_rejects_unrecognized():
    with pytest.raises(TypeError):
        normalize_plugin(42)