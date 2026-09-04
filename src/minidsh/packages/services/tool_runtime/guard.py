"""guard 模块：独立 GuardRegistry 类 + ToolGuard 接口 + repeat-tool-reminder。

源码对应：
- ``ToolGuard`` ↔ packages/guard 的 guard 函数签名（``(exec) -> str | None``）
- ``GuardRegistry`` ↔ 从 ToolRuntime 内部 ``_layers.guards`` 抽出的独立注册表
- ``repeat-tool-reminder`` ↔ packages/guard/repeat-tool-reminder/src/index.ts

ToolGuard 是**单调的**（monotonic）：只能 upsert 拒绝不能 upsert 放行——返回 ``None``
保留 waterfall 决策，返回 ``str`` 裁定拒绝。GuardRegistry 管理注册/注销/求值；
ToolRuntime 内部每个作用域层改持 GuardRegistry（见 runtime.py 的 ``ToolLayer``）。

[教学简化] repeat-tool-reminder 不拆成独立包，并进本模块；chain key 按 ``session.id``
（官方用 Agent 弱引用 WeakMap），不实现 include/exclude 通配过滤。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator

__all__ = [
    "ToolGuard",
    "GuardRegistry",
    "RepeatedToolReminder",
    "DEFAULT_REPEAT_THRESHOLDS",
    "GENTLE_REMINDER",
]

# ToolGuard 签名：返回 str = 拒绝理由，返回 None = 保留 waterfall 决策。
# exec 的类型是 ToolExecution（此处避免 import runtime 引发循环依赖，用 Any + 文档标注）。
ToolGuard = Callable[[Any], str | None]

# 默认阈值（对齐官方 repeat-tool-reminder Config.thresholds 默认值 [3, 5, 8]）
DEFAULT_REPEAT_THRESHOLDS = [3, 5, 8]


class GuardRegistry:
    """独立守卫注册表：管理 Guard 的注册、注销与求值。

    从 ToolRuntime 内部抽出，ToolRuntime.guard() 的公开 API 不变，
    但底存（每个 ToolLayer.guards）改持 GuardRegistry 实例。
    """

    def __init__(self):
        self._guards: list[ToolGuard] = []

    def register(self, guard: ToolGuard):
        """注册一条守卫，返回 disposer；卸载后该 guard 不再生效。"""
        self._guards.append(guard)

        def dispose():
            if guard in self._guards:
                self._guards.remove(guard)

        return dispose

    def evaluate(self, exec_) -> str | None:
        """顺序求值所有守卫，返回第一个非 None 的拒绝理由（单调语义）。

        无守卫拒绝时返回 None，保留 waterfall 决策。
        """
        for guard in self._guards:
            reason = guard(exec_)
            if reason is not None:
                return reason
        return None

    def remove(self, guard: ToolGuard) -> None:
        """直接移除一条守卫（与 disposer 等价）。"""
        if guard in self._guards:
            self._guards.remove(guard)

    def __iter__(self) -> Iterator[ToolGuard]:
        return iter(self._guards)

    def __len__(self) -> int:
        return len(self._guards)

    def __bool__(self) -> bool:
        return bool(self._guards)


# ---------------------------------------------------------------------------
# repeat-tool-reminder
# ---------------------------------------------------------------------------


def _canonicalize(arguments: dict) -> str:
    """深度 key-sort 后序列化为规范字符串（对齐官方 canonicalize）。

    两个参数对象仅属性顺序不同时，规范形式相同，使重复识别不因 key 顺序误判。
    """
    import json

    def _sort(value):
        if isinstance(value, dict):
            return {k: _sort(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [_sort(v) for v in value]
        return value

    return json.dumps(_sort(arguments), ensure_ascii=False, sort_keys=True)


def _preview_arguments(canonical: str, cap: int) -> str:
    """截断规范参数串用于展示（对齐官方 previewArguments）。"""
    if len(canonical) <= cap:
        return canonical
    return f"{canonical[:cap]}… (+{len(canonical) - cap} more chars)"


GENTLE_REMINDER = (
    "You are repeating the exact same tool call with identical arguments. "
    "Carefully analyze the previous result before calling again: if the task is "
    "not complete, try a different approach or different arguments instead of "
    "repeating the call."
)


def _detailed_reminder(tool_name: str, count: int, canonical_args: str) -> str:
    return (
        f"Repeated tool call detected:\n"
        f"- tool: {tool_name}\n"
        f"- consecutive_calls: {count}\n"
        f"- arguments: {canonical_args}\n"
        "The repeated calls are not making progress. Do not call this tool with "
        "these exact arguments again. Inspect the latest result and choose a "
        "different action, different arguments, or finish the task if enough "
        "evidence has been gathered."
    )


@dataclass
class _Chain:
    """一个追踪上下文的连续重复链：上次调用的 identity key 与当前 run length。"""

    key: str
    count: int


class RepeatedToolReminder:
    """重复工具调用提醒器（对齐官方 repeat-tool-reminder）。

    观测工具调用，追踪「同一工具名 + 规范参数」的连续重复次数；达到阈值时返回
    提醒文本（调用方负责注入到后续决策的 additional contexts）。

    [教学简化] chain key 按 ``session.id``（经 ``exec.agent.session``），不实现
    include/exclude 通配过滤。
    """

    def __init__(self, thresholds: list[int] | None = None,
                 arguments_preview_chars: int = 500):
        self._thresholds = sorted(thresholds or DEFAULT_REPEAT_THRESHOLDS)
        self._threshold_set = set(self._thresholds)
        self._arguments_preview_chars = arguments_preview_chars
        self._chains: dict[str, _Chain] = {}

    def _chain_key(self, exec_) -> str:
        """从 ToolExecution 推导 chain 身份键（对齐官方 exec.agent 弱引用键）。"""
        agent = getattr(exec_, "agent", None)
        session = getattr(agent, "session", None) if agent is not None else None
        return getattr(session, "id", "default")

    def observe(self, exec_) -> str | None:
        """观测一次工具调用；若达到阈值则返回提醒文本，否则返回 None。"""
        chain_key = self._chain_key(exec_)
        canonical = _canonicalize(exec_.arguments)
        call_key = f"{exec_.name}:{canonical}"

        chain = self._chains.get(chain_key)
        if chain is not None and chain.key == call_key:
            count = chain.count + 1
        else:
            count = 1
        self._chains[chain_key] = _Chain(key=call_key, count=count)

        if count not in self._threshold_set:
            return None

        if count == self._thresholds[0]:
            return GENTLE_REMINDER
        return _detailed_reminder(
            exec_.name, count,
            _preview_arguments(canonical, self._arguments_preview_chars),
        )

    def reset(self, chain_key: str) -> None:
        """重置某个 chain 的追踪状态（用户新消息到达时调用）。"""
        self._chains.pop(chain_key, None)

    def reset_all(self) -> None:
        """清空所有 chain（用户新输入 → 上下文变化 → 重复链断裂）。"""
        self._chains.clear()