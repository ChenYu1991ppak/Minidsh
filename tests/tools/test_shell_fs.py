"""CT1 验收测试：shell/fs 定义（类型与契约）。"""
from __future__ import annotations

import inspect

from minidsh.packages.services.shell import ShellRequest, ShellResult, ShellService
from minidsh.packages.services.fs import FsRequest, FsResult, FsService

import pytest


def test_shell_types():
    req = ShellRequest(cmd="echo hi")
    assert req.cmd == "echo hi"
    assert req.timeout_seconds == 30.0

    result = ShellResult(stdout="hi\n", stderr="", exit_code=0)
    assert result.exit_code == 0


def test_shell_service_is_async_abstract():
    assert inspect.iscoroutinefunction(ShellService.execute)
    # execute 是未实现的抽象（子类必须覆写），直接调用应抛 NotImplementedError
    from minidsh.cordis import Context

    class S(ShellService):
        pass

    ctx = Context()
    s = S.__new__(S)  # 绕过构造器（构造器需要 name 注册），仅测抽象 execute
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.run(s.execute(ShellRequest("x")))


def test_fs_types():
    req = FsRequest(path="/tmp/a.txt")
    assert req.path == "/tmp/a.txt"
    result = FsResult(content="hello")
    assert result.content == "hello"


def test_fs_service_is_async_abstract():
    assert inspect.iscoroutinefunction(FsService.execute)


def test_definitions_are_capability_definitions():
    """两个定义都是 CapabilityDefinition 子类（纯接口，非 Service）。"""
    from minidsh.cordis import CapabilityDefinition, Service

    assert issubclass(ShellService, CapabilityDefinition)
    assert issubclass(FsService, CapabilityDefinition)
    # 定义不是 Service：不自注册（注册是 provider 的职责）
    assert not issubclass(ShellService, Service)
    assert not issubclass(FsService, Service)


def test_definitions_not_provided_by_import():
    """定义模块不自行注册服务：provider 才 provide（三角色职责分离）。"""
    from minidsh.cordis import Context

    ctx = Context()
    # 仅 import 定义，不激活任何插件 → 无 shell/fs 服务
    assert not ctx.has("shell")
    assert not ctx.has("fs")