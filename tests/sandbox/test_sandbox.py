"""M4 验收测试：sandbox（bwrap 真 confining——workspace-write 可写、根下只读）。"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.sandbox.definition import (
    SandboxExecutionPolicy,
    SandboxService,
)
from minidsh.packages.services.sandbox.providers.bwrap import BwrapSandboxService
from minidsh.packages.services.subprocess.providers.local import LocalSubprocessService

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap 不可用")


def _ctx(tmp_path) -> tuple[Context, SandboxService, str]:
    ctx = Context()
    sp = LocalSubprocessService(ctx)
    ctx.provide("subprocess", sp)
    sandbox = BwrapSandboxService(ctx)
    ctx.provide("sandbox", sandbox)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello")
    return ctx, sandbox, str(ws)


async def test_workspace_writable_root_readonly(tmp_path):
    ctx, sandbox, ws = _ctx(tmp_path)
    policy = SandboxExecutionPolicy(mode="workspace-write", workspace_root=ws)
    handle = await sandbox.confine(
        ["sh", "-c", "echo -n \"$(cat a.txt)\"; touch new.txt && echo '|ws-ok'; touch /etc/_dsh_probe 2>/dev/null && echo '|etc-bad' || echo '|etc-blocked'"],
        cwd=ws, policy=policy,
    )
    outcome = await handle.done
    await asyncio.sleep(0)
    assert outcome.exit_code == 0
    text = handle.collected["stdout"].text
    assert text.startswith("hello")          # 读 workspace a.txt
    assert "ws-ok" in text                    # workspace 内可写
    assert "etc-blocked" in text              # 根下写入被拒
    assert "etc-bad" not in text


async def test_read_only_blocks_workspace_write(tmp_path):
    ctx, sandbox, ws = _ctx(tmp_path)
    policy = SandboxExecutionPolicy(mode="read-only", workspace_root=ws)
    handle = await sandbox.confine(
        ["sh", "-c", "touch new.txt 2>/dev/null && echo 'wrote' || echo 'blocked'"],
        cwd=ws, policy=policy,
    )
    await handle.done
    await asyncio.sleep(0)
    assert "blocked" in handle.collected["stdout"].text


async def test_enforcement_reports_full(tmp_path):
    ctx, sandbox, ws = _ctx(tmp_path)
    assert sandbox.enforcement == "full"


async def test_fail_closed_when_bwrap_missing(monkeypatch, tmp_path):
    ctx = Context()
    sp = LocalSubprocessService(ctx)
    ctx.provide("subprocess", sp)
    sandbox = BwrapSandboxService(ctx)
    ctx.provide("sandbox", sandbox)
    sandbox._bwrap = None  # 模拟无 bwrap
    policy = SandboxExecutionPolicy(mode="workspace-write", workspace_root="/tmp")
    with pytest.raises(RuntimeError):
        await sandbox.confine(["echo", "hi"], "/tmp", policy)
    assert sandbox.enforcement == "partial"