"""T8 验收测试：prompt 分节注册 / 组装 / 渲染。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.prompt import PromptAssembly, PromptSection, SystemPromptService, render_prompt
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService


def _ctx() -> tuple[Context, SystemPromptService]:
    ctx = Context()
    svc = LocalSystemPromptService(ctx)  # 构造即注册（ctx.systemPrompt）
    return ctx, svc


def test_sections_render_in_order():
    ctx, svc = _ctx()
    svc.section("base", "A", order=20)
    svc.section("head", "B", order=10)
    assert svc.render() == "B\n\nA"  # order 升序


def test_same_name_sections_coexist_in_order():
    ctx, svc = _ctx()
    svc.section("x", "first", order=0)
    svc.section("x", "second", order=0)
    # 同名节允许并存（对齐 dsh：不同插件各注册各的节，name 只是 label），按 order 排序
    assert len(svc.assemble().sections) == 2


def test_render_is_stable():
    ctx, svc = _ctx()
    svc.section("a", "1")
    svc.section("b", "2")
    assert svc.render() == svc.render()  # 同输入同输出


def test_render_filters_empty():
    ctx, svc = _ctx()
    svc.section("empty", "", order=0)
    svc.section("full", "hello", order=1)
    assert svc.render() == "hello"


def test_section_unregisters_on_dispose():
    ctx, svc = _ctx()
    off = svc.section("temp", "T")
    assert svc.render() == "T"
    off()
    assert svc.render() == ""


def test_standalone_render_prompt():
    secs = [PromptSection("a", 0, "x"), PromptSection("b", 1, "y")]
    assert render_prompt(PromptAssembly(secs)) == "x\n\ny"


def test_assembly_default_has_no_sections():
    assert render_prompt(PromptAssembly()) == ""