"""测试用假 llm provider 插件（对齐官方「provider 即插件」）。

假 llm 是一个 module 形态 provider；``apply(ctx)`` 里构造 ``OpenAILlm(ctx, client=...)``，
构造即注册到 ``ctx.llm``（自注册，无需外层 provide）。测试 ``ctx.plugin(make_fake_llm(script))``。

复用 OpenAILlm 的 chunk 映射逻辑（client 注入），保证与真实 provider 的映射语义一致。
"""
from __future__ import annotations

import types

from minidsh.packages.services.llm.providers.openai import OpenAILlm
from .openai_fake import make_scripted_client

__all__ = ["make_fake_llm"]

FAKE_PLUGIN_NAME = "test.llm-fake"


def make_fake_llm(script: list[dict] | None = None):
    """造一个 module 形态假 llm 插件（name=test.llm-fake）。"""
    client = make_scripted_client(script or [])

    mod = types.ModuleType("tests.helpers.fake_llm")
    mod.name = FAKE_PLUGIN_NAME
    mod.inject = []

    def apply(ctx):
        OpenAILlm(ctx, client=client, model="fake-llm")  # 构造即注册 ctx.llm

    mod.apply = apply
    return mod