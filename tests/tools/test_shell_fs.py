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


# ---------- FsService write_text / edit_text ----------


async def test_fs_write_text_creates_file(tmp_path):
    """write_text 创建文件，内容正确。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "out.txt"
    await svc.write_text(str(f), "hello world")
    assert f.read_text() == "hello world"


async def test_fs_write_text_overwrites_existing(tmp_path):
    """write_text 覆盖已有文件。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "out.txt"
    f.write_text("old")
    await svc.write_text(str(f), "new")
    assert f.read_text() == "new"


async def test_fs_edit_text_single_replace(tmp_path):
    """edit_text 替换第一个匹配（replace_all=False）。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "out.txt"
    f.write_text("hello hello world")
    result = await svc.edit_text(str(f), "hello", "hi", replace_all=False)
    assert result == "hi hello world"
    assert f.read_text() == "hi hello world"


async def test_fs_edit_text_replace_all(tmp_path):
    """edit_text 替换所有匹配（replace_all=True）。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "out.txt"
    f.write_text("hello hello world")
    result = await svc.edit_text(str(f), "hello", "hi", replace_all=True)
    assert result == "hi hi world"
    assert f.read_text() == "hi hi world"


async def test_fs_edit_text_no_match_unchanged(tmp_path):
    """edit_text 无匹配时文本不变。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "out.txt"
    f.write_text("hello world")
    result = await svc.edit_text(str(f), "xyz", "abc", replace_all=False)
    assert result == "hello world"  # 无替换，原文不变
    assert f.read_text() == "hello world"


async def test_fs_write_text_creates_parent_dirs(tmp_path):
    """write_text 自动创建父目录。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "deep" / "nested" / "out.txt"
    await svc.write_text(str(f), "hello")
    assert f.read_text() == "hello"


async def test_fs_edit_text_creates_file_if_not_exists(tmp_path):
    """edit_text 对不存在的文件：创建并写入 new_string。"""
    from minidsh.cordis import Context
    from minidsh.packages.services.fs.providers.local import LocalFsService

    ctx = Context()
    svc = LocalFsService(ctx)
    f = tmp_path / "new" / "file.txt"
    result = await svc.edit_text(str(f), "old", "new", replace_all=False)
    assert result == "new"
    assert f.read_text() == "new"