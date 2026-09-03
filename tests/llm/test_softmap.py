"""M2 验收测试：softmap 软映射层（四家思考强度/推理模型判别）。"""
from __future__ import annotations

from minidsh.packages.services.llm import softmap


# ---------- is_reasoning_model ----------


def test_reasoning_models_detected():
    assert softmap.is_reasoning_model("o3-mini")
    assert softmap.is_reasoning_model("deepseek-v4-pro")
    assert softmap.is_reasoning_model("deepseek-reasoner")
    assert softmap.is_reasoning_model("kimi-k3")
    assert softmap.is_reasoning_model("kimi-k2.6")
    assert softmap.is_reasoning_model("qwq-32b")
    assert softmap.is_reasoning_model("qwen3-30b-a3b-thinking")


def test_non_reasoning_models():
    assert not softmap.is_reasoning_model("gpt-4o")
    assert not softmap.is_reasoning_model("deepseek-chat")
    assert not softmap.is_reasoning_model("kimi-moonshot")


def test_routing_prefix_stripped():
    assert softmap.is_reasoning_model("openai/deepseek-v4-pro")
    assert softmap.is_reasoning_model("dashscope/qwen3-30b-a3b-thinking")


# ---------- requires_reasoning_history ----------


def test_requires_history_families():
    assert softmap.requires_reasoning_history("deepseek-v4-pro")
    assert softmap.requires_reasoning_history("deepseek-reasoner")
    assert softmap.requires_reasoning_history("kimi-k3")
    assert softmap.requires_reasoning_history("kimi-k2.7")
    assert not softmap.requires_reasoning_history("kimi-k2.6")
    assert not softmap.requires_reasoning_history("gpt-4o")


# ---------- reasoning_effort_map（§2 软映射表） ----------


def test_reasoning_effort_map_gpt():
    assert softmap.reasoning_effort_map("o3-mini", "medium") == "medium"
    assert softmap.reasoning_effort_map("o3-mini", "high") == "high"
    assert softmap.reasoning_effort_map("o3-mini", "minimal") == "minimal"
    assert softmap.reasoning_effort_map("o3-mini", "off") is None


def test_reasoning_effort_map_deepseek():
    # minimal/low→low；medium/high→high；off→None
    assert softmap.reasoning_effort_map("deepseek-v4-pro", "low") == "low"
    assert softmap.reasoning_effort_map("deepseek-v4-pro", "medium") == "high"
    assert softmap.reasoning_effort_map("deepseek-v4-pro", "high") == "high"
    assert softmap.reasoning_effort_map("deepseek-v4-pro", "off") is None


def test_reasoning_effort_map_kimi_k3():
    # minimal/low→low; medium→high; high→max
    assert softmap.reasoning_effort_map("kimi-k3", "low") == "low"
    assert softmap.reasoning_effort_map("kimi-k3", "medium") == "high"
    assert softmap.reasoning_effort_map("kimi-k3", "high") == "max"


# ---------- thinking_optin ----------


def test_thinking_optin_deepseek():
    assert softmap.thinking_optin("deepseek-v4-pro", "high") == {"thinking": {"type": "enabled"}}
    assert softmap.thinking_optin("deepseek-v4-pro", "off") == {"thinking": {"type": "disabled"}}


def test_thinking_optin_qwen():
    assert softmap.thinking_optin("qwq-32b", "high") == {"enable_thinking": True}
    assert softmap.thinking_optin("qwq-32b", "off") == {"enable_thinking": False}


def test_thinking_optin_kimi_k26():
    assert softmap.thinking_optin("kimi-k2.6", "off") == {"thinking": {"type": "disabled"}}


def test_thinking_optin_none_for_gpt():
    assert softmap.thinking_optin("o3-mini", "high") is None