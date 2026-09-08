"""prompt 模块：system-prompt 分节注册 / 组装 / 渲染。

源码对应：packages/core/system-prompt/src/index.ts:338（SystemPromptService）、
:381（section）、:467（assemble）、:212-217（renderPrompt）。

一个「节」是一段按序拼接的文本；能力的消费方（tools / skills / workspace 的 AGENTS.md）
各自注册自己的节，loop 在每次调用前 assemble + render。注册即效应：卸载时移除该节。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptSection:
    """提示词片段（index.ts:53）。"""

    name: str
    order: int
    text: str


@dataclass
class PromptAssembly:
    """组装快照（index.ts:115）。

    [教学简化] 真实快照还含 variables/tools/contexts；此处只含 sections。
    """

    sections: list[PromptSection] = field(default_factory=list)


def render_prompt(assembly: PromptAssembly) -> str:
    """sections → 过滤空 → ``\\n\\n`` 拼接（renderPrompt，index.ts:212-217）。"""
    return "\n\n".join(s.text for s in assembly.sections if s.text)


class SystemPromptService(CapabilityDefinition):
    """ctx.systemPrompt：分节注册与组装（index.ts:338）。

    纯接口：子类（provider）实现 section/assemble，并负责初始化 _sections 与 ctx。
    """

    service_name = "systemPrompt"

    def section(self, name: str, text: str, order: int = 0):
        """注册一个片段（index.ts:381）。注册即效应：卸载时自动移除。"""
        raise NotImplementedError

    def assemble(self) -> PromptAssembly:
        """按 order 升序组装（assemble，index.ts:467）。"""
        raise NotImplementedError

    def render(self) -> str:
        """便捷：assemble + render 一步到位（renderPrompt，index.ts:212-217）。"""
        return render_prompt(self.assemble())


__all__ = [
    "PromptAssembly",
    "PromptSection",
    "SystemPromptService",
    "render_prompt",
]