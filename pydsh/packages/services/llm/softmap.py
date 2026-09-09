"""softmap：按 model id 家族判别的软映射层（四家思考强度/推理模型差异收敛）。

对齐 claw-code ``openai_compat.rs`` 的做法（纯函数，只依赖 model id 前缀，无视 vendor 字段）：

- ``is_reasoning_model(id)``：推理/思维链模型 → 请求剥离 temperature/top_p/penalties
  （固定采样，传了会被部分模型 400 拒收）。
- ``requires_reasoning_history(id)``：工具调用/多轮里必须把上一轮 assistant 的
  ``reasoning_content`` 原样回传的家族（deepseek-v4 / kimi-k3 / kimi-k2.7）。
- ``reasoning_effort_map(id, effort)``：五档 → 各家真实取值（nearby 归并）。
- ``thinking_optin(id, effort)``：需要 ``thinking`` / ``enable_thinking`` 开关的家族。
- ``strip_tuning(id)``：reasoning 模型剥离 temperature 等参数。

判别依据（官方文档 + claw-code）：
- DeepSeek：`deepseek-v4*` / `deepseek-reasoner` → thinking.type 开关 + reasoning_effort(low/high)
- Kimi K3：`kimi-k3*` 始终推理 + reasoning_effort(low/high/max)
- Kimi K2.6：`kimi-k2.6*` thinking.type 二态（enabled/disabled）
- Kimi K2.7：`kimi-k2.7*` 始终思考（无法关）
- Qwen：`qwq*` / `qwen*-thinking` → enable_thinking 二态
- GPT o-series：`o1*`/`o3*`/`o4*` → reasoning_effort(minimal/low/medium/high)

[教学简化] 不做 grok/其他厂商；前缀朴素匹配，不做精确型号表（可扩展，不追求穷尽）。
"""
from __future__ import annotations

__all__ = [
    "is_reasoning_model",
    "requires_reasoning_history",
    "reasoning_effort_map",
    "thinking_optin",
    "strip_tuning",
]


def _canonical(model_id: str) -> str:
    """剥掉 'provider/prefix' 路由前缀，取裸 model id（对齐 claw-code strip_routing_prefix）。"""
    return model_id.lower().rsplit("/", 1)[-1]


def is_reasoning_model(model_id: str) -> bool:
    """推理/思维链模型（固定采样，需剥离 temperature 等调参）。"""
    c = _canonical(model_id)
    return (
        c.startswith("o1")
        or c.startswith("o3")
        or c.startswith("o4")
        or c.startswith("deepseek-v4")
        or c == "deepseek-reasoner"
        or c.startswith("kimi-k2")
        or c.startswith("kimi-k3")
        or c.startswith("qwq")
        or c.startswith("qwen-qwq")
        or c.startswith("qwen3") and "-thinking" in c
    )


def requires_reasoning_history(model_id: str) -> bool:
    """必须在多轮/工具调用里回传 assistant 上一轮 reasoning_content 的家族。"""
    c = _canonical(model_id)
    return (
        c.startswith("deepseek-v4")
        or c == "deepseek-reasoner"
        or c.startswith("kimi-k3")
        or c.startswith("kimi-k2.7")
    )


def reasoning_effort_map(model_id: str, effort: str) -> str | None:
    """五档 → 各家 reasoning_effort 真实取值；None = 该家族不支持 reasoning_effort。"""
    c = _canonical(model_id)
    # GPT o-series：原生 minimal/low/medium/high
    if c.startswith("o1") or c.startswith("o3") or c.startswith("o4"):
        return None if effort == "off" else effort
    # DeepSeek：low/high 二档（medium→high；minimal→low）
    if c.startswith("deepseek-v4") or c == "deepseek-reasoner":
        if effort == "off":
            return None
        return "low" if effort in ("minimal", "low") else "high"
    # Kimi K3：low/high/max（minimal/low→low；medium→high；high→max）
    if c.startswith("kimi-k3"):
        if effort == "off":
            return None
        return {"minimal": "low", "low": "low", "medium": "high", "high": "max"}[effort]
    return None  # 其余不支持 reasoning_effort（on/off 由 thinking_optin 管）


def thinking_optin(model_id: str, effort: str) -> dict | None:
    """需要 ``thinking`` / ``enable_thinking`` 开关的家族；None = 无需。"""
    c = _canonical(model_id)
    enabled = effort != "off"
    # DeepSeek：thinking.type
    if c.startswith("deepseek-v4") or c == "deepseek-reasoner":
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    # Kimi K2.6：thinking.type 二态
    if c.startswith("kimi-k2.6"):
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    # Qwen：enable_thinking
    if c.startswith("qwq") or c.startswith("qwen-qwq") or ("qwen3" in c and "-thinking" in c):
        return {"enable_thinking": enabled}
    return None


def strip_tuning(model_id: str) -> bool:
    """是否剥离 temperature/top_p/penalties（reasoning 模型固定采样）。"""
    return is_reasoning_model(model_id)