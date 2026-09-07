"""base 插件：agents-md（AGENTS.md 注入 systemPrompt）。"""
from __future__ import annotations

name = "minidsh.agents-md"
inject = ["systemPrompt", "root"]


def apply(ctx):
    agents_md = ctx.root / "AGENTS.md"
    if agents_md.is_file():
        ctx.systemPrompt.section("workspace", agents_md.read_text(encoding="utf-8"), order=0)
