"""base 插件：skills（SkillRegistry + FilesystemSkillProvider + catalog 工具）。"""
from __future__ import annotations

from minidsh.packages.services.skills import FilesystemSkillProvider, SkillRegistry, make_catalog_tool

name = "minidsh.skills"
inject = ["tools", "root"]


def apply(ctx):
    tools = ctx.tools
    skills = SkillRegistry(ctx)
    skills.register_provider(FilesystemSkillProvider(ctx.root))
    tools.register(make_catalog_tool(skills))
