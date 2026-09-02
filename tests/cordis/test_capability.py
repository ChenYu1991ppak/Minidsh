"""cordis 三基类验收测试。"""
from __future__ import annotations

import pytest

from minidsh.cordis import (
    Context,
    CapabilityDefinition,
    CapabilityProvider,
    CapabilityConsumer,
)


class ShellDef(CapabilityDefinition):
    service_name = "shell"

    async def execute(self, request):  # 纯接口
        raise NotImplementedError


class LocalShell(ShellDef, CapabilityProvider):
    def _init(self, ctx, *, tag=""):
        self.tag = tag

    async def execute(self, request):
        return f"exec:{self.tag}"


# ---------- Definition：不自注册 ----------


def test_definition_does_not_register():
    ctx = Context()
    d = ShellDef()  # 纯接口，无注册副作用
    assert d.service_name == "shell"
    assert not ctx.has("shell")


# ---------- Provider：构造即注册到 service_name ----------


def test_provider_registers_on_construction():
    ctx = Context()
    p = LocalShell(ctx, tag="x")
    assert ctx.has("shell")
    assert ctx.shell is p
    assert ctx.shell.service_name == "shell"


def test_provider_init_extra_kwargs():
    ctx = Context()
    p = LocalShell(ctx, tag="extra")
    assert p.tag == "extra"


# ---------- Consumer：非 Service；校验 ----------


def test_consumer_assert_valid():
    CapabilityConsumer.assert_valid(["tools", "shell"], "shell")  # 不抛


def test_consumer_assert_missing_tools():
    with pytest.raises(ValueError):
        CapabilityConsumer.assert_valid(["shell"], "shell")


def test_consumer_assert_missing_service():
    with pytest.raises(ValueError):
        CapabilityConsumer.assert_valid(["tools"], "shell")


def test_consumer_is_not_service():
    from minidsh.cordis import Service

    assert not issubclass(CapabilityConsumer, Service)