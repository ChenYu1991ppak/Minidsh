"""base 插件：prompt（LocalSystemPromptService，SystemPromptService 的唯一 provider）。"""
from __future__ import annotations

from minidsh.packages.services.prompt.definition import PromptAssembly, SystemPromptService
from minidsh.cordis import CapabilityProvider

name = "minidsh.prompt"
inject: list[str] = []


class LocalSystemPromptService(SystemPromptService, CapabilityProvider):
    """SystemPromptService 的本地实现：分节列表存内存，构造即注册 ctx.systemPrompt。"""

    def _init(self, ctx):
        self.ctx = ctx
        self._sections: list = []

    def section(self, name: str, text: str, order: int = 0):
        from minidsh.packages.services.prompt.definition import PromptSection

        entry = PromptSection(name, order, text)

        def setup():
            self._sections.append(entry)
            return lambda: self._sections.remove(entry)

        return self.ctx.effect(setup, label=f"section:{name}")

    def assemble(self) -> PromptAssembly:
        assembly = PromptAssembly()
        assembly.sections = sorted(self._sections, key=lambda s: s.order)
        return assembly


def apply(ctx):
    LocalSystemPromptService(ctx)  # 构造即注册 ctx.systemPrompt