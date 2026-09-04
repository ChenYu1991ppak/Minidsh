"""base 插件：fake llm（测试用脚本 LLM，不连真实 API）。

[教学简化] 脚本由环境变量 ``MINIDSH_FAKE_SCRIPT`` 提供（JSON 数组，格式同
``tests.helpers.openai_fake.make_scripted_client``）。缺省脚本回复固定文本 "你好！"。
"""
from __future__ import annotations

import json
import os

from ..definition import LlmRuntime
from minidsh.cordis import CapabilityProvider

name = "minidsh.llm-fake"
inject = ["config"]


class FakeLlm(LlmRuntime, CapabilityProvider):
    """脚本化假 LLM：不连真实 API，按预置脚本回放 chunk。"""

    service_name = "llm"

    def __init__(self, ctx, script=None):
        super().__init__(ctx)
        self.model = "fake"
        self.reasoning_effort = "medium"
        self._calls = 0
        if script is None:
            raw = os.environ.get("MINIDSH_FAKE_SCRIPT")
            script = json.loads(raw) if raw else [{"text": "你好！"}]
        self._script = script

    def reconfigure(self, spec):
        self.model = getattr(spec, "id", self.model)
        self.reasoning_effort = getattr(spec, "reasoning_effort", self.reasoning_effort)

    async def stream(self, messages, system_prompt="", tools=None):
        from ..definition import Chunk

        idx = min(self._calls, len(self._script) - 1) if self._script else 0
        self._calls += 1
        row = self._script[idx] if self._script else {"text": "你好！"}

        if "tool_calls" in row:
            for j, (name, arguments, tid) in enumerate(row["tool_calls"]):
                yield Chunk(kind="tool-call", id=tid or f"call-{j}", name=name, arguments=arguments)
            yield Chunk(kind="finish", stop_reason="tool-use")
        else:
            if row.get("reasoning"):
                yield Chunk(kind="reasoning-delta", reasoning=row["reasoning"])
            text = row.get("text", "")
            yield Chunk(kind="text-delta", text=text)
            yield Chunk(kind="finish", stop_reason="end-turn")


def apply(ctx):
    FakeLlm(ctx)  # 构造即注册 ctx.llm