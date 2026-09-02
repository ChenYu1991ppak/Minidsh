"""M3 验收测试：subprocess seam（完全显式 spawn + collect + DSH_* 环境清除）。"""
from __future__ import annotations

import asyncio
import os

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.subprocess import (
    CollectedOutput,
    SubprocessOutcome,
    SubprocessService,
    SubprocessSpawnSpec,
    SubprocessStdio,
)
from minidsh.packages.services.subprocess.providers.local import LocalSubprocessService


def _ctx() -> tuple[Context, SubprocessService]:
    ctx = Context()
    svc = LocalSubprocessService(ctx)  # 构造即注册 ctx.subprocess
    return ctx, svc


def _echo_spec(*args, stdin="ignore", env=None, cwd=None) -> SubprocessSpawnSpec:
    return SubprocessSpawnSpec(
        argv=list(args),
        cwd=cwd or os.getcwd(),
        stdio=SubprocessStdio(stdin=stdin),
        env=env,
    )


# ---------- 基础执行 ----------


async def test_spawn_collects_stdout():
    ctx, svc = _ctx()
    handle = await svc.spawn(_echo_spec("python", "-c", "print('hello')"))
    outcome = await handle.done
    assert isinstance(outcome, SubprocessOutcome)
    assert outcome.exit_code == 0
    await asyncio.sleep(0)
    assert "hello" in handle.collected["stdout"].text


async def test_spawn_nonzero_exit_code():
    ctx, svc = _ctx()
    handle = await svc.spawn(_echo_spec("python", "-c", "import sys; sys.exit(3)"))
    outcome = await handle.done
    assert outcome.exit_code == 3


# ---------- stdin 三种处置 ----------


async def test_stdin_ignore():
    ctx, svc = _ctx()
    handle = await svc.spawn(_echo_spec("cat"))  # 无输入，ignore：立即 EOF
    outcome = await handle.done
    assert outcome.exit_code == 0


async def test_stdin_data_batch():
    ctx, svc = _ctx()
    spec = _echo_spec("cat", stdin={"data": "payload"})
    handle = await svc.spawn(spec)
    await handle.done
    assert "payload" in handle.collected["stdout"].text


# ---------- DSH_* 环境清除 ----------


async def test_dsh_env_scrubbed_and_explicit_merged(monkeypatch):
    ctx, svc = _ctx()
    monkeypatch.setenv("DSH_LEFTOVER", "stale")
    monkeypatch.setenv("DSH_KEEP", "old-value")
    monkeypatch.setenv("NEUTRAL", "kept")
    code = "import os; print(os.environ.get('DSH_LEFTOVER'), os.environ.get('DSH_KEEP'), os.environ.get('NEUTRAL'))"
    spec = _echo_spec("python", "-c", code, env={"DSH_KEEP": "fresh", "NEUTRAL": None})
    handle = await svc.spawn(spec)
    await handle.done
    out = handle.collected["stdout"].text
    # DSH_LEFTOVER 被 scrub；DSH_KEEP 被显式覆盖；NEUTRAL 被 tombstone 删除
    assert out.startswith("None fresh None")


# ---------- collect 截断 + spill ----------


async def test_collect_truncates_keeps_tail():
    ctx, svc = _ctx()
    spec = _echo_spec("python", "-c", "print('x' * 100)")
    spec = SubprocessSpawnSpec(
        argv=spec.argv, cwd=spec.cwd,
        stdio=SubprocessStdio(stdout={"maxBytes": 10}, stderr="collect"),
    )
    handle = await svc.spawn(spec)
    await handle.done
    co = handle.collected["stdout"]
    assert co.truncated is True
    assert co.text == "x" * 9 + "\n"  # 保留尾部（print 补 \n，共 101 字节，取后 10）


async def test_collect_spill_writes_full_stream():
    ctx, svc = _ctx()
    spec = SubprocessSpawnSpec(
        argv=["python", "-c", "print('y' * 100)"], cwd=os.getcwd(),
        stdio=SubprocessStdio(stdout={"maxBytes": 10, "spill": {"maxBytes": 1024}}, stderr="collect"),
    )
    handle = await svc.spawn(spec)
    await handle.done
    co = handle.collected["stdout"]
    assert co.spill_path is not None
    with open(co.spill_path, encoding="utf-8") as f:
        assert f.read() == "y" * 100 + "\n"
    os.remove(co.spill_path)


# ---------- resolve_executable ----------


async def test_resolve_executable_absolute():
    ctx, svc = _ctx()
    import sys
    assert await svc.resolve_executable(sys.executable) == sys.executable


async def test_resolve_executable_bare_name_unknown_returns_name():
    ctx, svc = _ctx()
    assert await svc.resolve_executable("definitely-not-a-cmd-xyz") == "definitely-not-a-cmd-xyz"