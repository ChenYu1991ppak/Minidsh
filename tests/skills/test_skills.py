"""T12 验收测试：skills 注册表 + SKILL.md 加载 + catalog 工具。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.skills import (
    FilesystemSkillProvider,
    SkillRegistry,
    make_catalog_tool,
    parse_skill_file,
)
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution


def _write_skill(root, name, description="desc", body="**技能正文**"):
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8"
    )


def _ctx(tmp_path):
    ctx = Context()
    LocalSystemPromptService(ctx)
    skills = SkillRegistry(ctx)  # 构造即注册 ctx.skills
    ctx.provide("skills", skills)
    skills.register_provider(FilesystemSkillProvider(tmp_path))
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    tools.register(make_catalog_tool(skills))
    return ctx, skills, tools


# ---------- parse_skill_file ----------


def test_parse_skill_file():
    out = parse_skill_file("---\nname: relay\ndescription: 中继\n---\n正文")
    assert out == ("relay", "中继", "正文")


def test_parse_skill_file_no_frontmatter():
    assert parse_skill_file("无 frontmatter") is None


def test_parse_skill_file_missing_name():
    assert parse_skill_file("---\ndescription: 只有描述\n---\n正文") is None


# ---------- registry ----------


def test_list_merges_and_sorts(tmp_path):
    ctx, skills, _ = _ctx(tmp_path)
    _write_skill(tmp_path, "beta")
    _write_skill(tmp_path, "alpha")
    names = [s.name for s in skills.list()]
    assert names == ["alpha", "beta"]


def test_get_loads_full_definition(tmp_path):
    ctx, skills, _ = _ctx(tmp_path)
    _write_skill(tmp_path, "relay", body="**正文**")
    definition = skills.get("relay")
    assert definition is not None
    assert definition.content == "**正文**"
    assert skills.get("nope") is None


def test_load_injects_system_prompt(tmp_path):
    ctx, skills, _ = _ctx(tmp_path)
    _write_skill(tmp_path, "relay", body="技能专属指令")
    definition = skills.load("relay")
    assert definition is not None
    assert "技能专属指令" in ctx.systemPrompt.render()  # 惰性加载：load 后注入


def test_list_without_skills_is_empty(tmp_path):
    ctx, skills, _ = _ctx(tmp_path)
    assert skills.list() == []


# ---------- catalog 工具 ----------


async def test_catalog_list(tmp_path):
    ctx, skills, tools = _ctx(tmp_path)
    _write_skill(tmp_path, "relay", description="中继技能")
    result = await tools.execute(ToolExecution("c1", "skill-catalog", {"action": "list"}))
    assert "relay" in result.content
    assert "中继技能" in result.content


async def test_catalog_load(tmp_path):
    ctx, skills, tools = _ctx(tmp_path)
    _write_skill(tmp_path, "relay", description="中继技能", body="技能的正文内容")
    result = await tools.execute(
        ToolExecution("c1", "skill-catalog", {"action": "load", "name": "relay"})
    )
    assert "已加载技能 relay" in result.content
    assert "技能的正文内容" in ctx.systemPrompt.render()


async def test_catalog_load_missing(tmp_path):
    ctx, skills, tools = _ctx(tmp_path)
    result = await tools.execute(
        ToolExecution("c1", "skill-catalog", {"action": "load", "name": "ghost"})
    )
    assert result.is_error is False  # 返回错误文本，但非管线错误
    assert "未找到" in result.content


async def test_catalog_unknown_action(tmp_path):
    ctx, skills, tools = _ctx(tmp_path)
    result = await tools.execute(ToolExecution("c1", "skill-catalog", {"action": "nuke"}))
    assert "未知 action" in result.content