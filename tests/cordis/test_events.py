"""T2 验收测试：on / emit / serial / waterfall 语义与生命周期绑定。"""
from __future__ import annotations

from minidsh.cordis import Context


# ---------- on / off ----------


def test_on_then_emit_in_order():
    ctx = Context()
    calls = []

    ctx.on("greet", lambda n: calls.append(f"a:{n}"))
    ctx.on("greet", lambda n: calls.append(f"b:{n}"))

    ctx.emit("greet", "x")
    assert calls == ["a:x", "b:x"]


def test_off_stops_delivery():
    ctx = Context()
    calls = []

    off = ctx.on("greet", lambda n: calls.append(n))
    ctx.emit("greet", "1")
    off()
    ctx.emit("greet", "2")

    assert calls == ["1"]


def test_on_with_no_listener_is_noop():
    ctx = Context()
    ctx.emit("nobody-home", 1)  # 不抛错


# ---------- serial ----------


def test_serial_bails_on_first_truthy():
    ctx = Context()
    ctx.on("gate", lambda v: None)             # 放行
    ctx.on("gate", lambda v: v + ":ok")        # 命中
    ctx.on("gate", lambda v: v + ":never")     # 不再调用

    assert ctx.serial("gate", "v") == "v:ok"


def test_serial_false_does_not_bail():
    ctx = Context()
    ctx.on("gate", lambda v: False)            # False 不是 bail
    ctx.on("gate", lambda v: True)

    assert ctx.serial("gate", "v") is True


def test_serial_no_hit_returns_none():
    ctx = Context()
    assert ctx.serial("gate", "v") is None


# ---------- waterfall ----------


def test_waterfall_passes_value_through():
    ctx = Context()

    ctx.on("transform", lambda v: v + 1)
    ctx.on("transform", lambda v: v * 2)

    assert ctx.waterfall("transform", 1) == 4  # (1 + 1) * 2


def test_waterfall_none_is_passthrough():
    ctx = Context()
    ctx.on("transform", lambda v: None)  # 放行不动
    ctx.on("transform", lambda v: v + 3)

    assert ctx.waterfall("transform", 10) == 13


def test_waterfall_no_listener_returns_initial():
    ctx = Context()
    assert ctx.waterfall("nobody", "原样") == "原样"


# ---------- 生命周期绑定：on 是 effect，随 fiber 卸载自动注销 ----------


def test_on_is_disposed_with_fiber():
    ctx = Context()
    calls = []

    def listener_plugin(ctx):
        ctx.on("ping", lambda: calls.append("hit"))

    ctx.plugin(listener_plugin)
    ctx.emit("ping")
    assert calls == ["hit"]

    ctx.dispose()
    ctx.emit("ping")  # fiber 已卸载，监听注销，不再投递
    assert calls == ["hit"]