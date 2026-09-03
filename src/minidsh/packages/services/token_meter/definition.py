"""token-meter：独立回放 token 计量 seam（ctx.tokenMeter）。

源码对应：packages/llm/token-meter/src/index.ts + types.ts。

产生一次请求压力与表层定价的**不可变回放快照**（TokenMeasurement），包含：
- ``logRevision``：消费的持久事件数
- ``baseline``：usage 锚点（最近一次同路由 provider 调用的完整计数）或 heuristic 估算
- ``surfaceDeltaTokens``：相对锚点的有符号差异
- ``totalTokens``：请求+响应压力
- ``surfaceTokens``：表层路由定价总量
- ``nodes``：当前位置顺序的表层节点

[教学简化] 不连 LLM 实际 provider 的 usage 回传做精确锚点（那是 llm provider 侧的改动），
但数据结构完整、锚点预留 usage 槽位。compaction 改为消费 ctx.tokenMeter 而非 chars/4 粗估。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from minidsh.cordis import CapabilityProvider

__all__ = [
    "TokenMeasurementBaseline",
    "TokenMeasurement",
    "TokenSurfaceNode",
    "TokenMeterService",
    "estimate_message",
    "estimate_tokens",
]

# 固定文本密度估算（与官方 estimate.ts 一致）
CHARS_PER_TOKEN = 4
ROLE_OVERHEAD = 4
BLOCK_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    """固定密度 token 粗估：chars/4。"""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_message(message: dict) -> int:
    """按官方 estimateMessage 估算一条消息的 token 数（含 role 开销）。"""
    tokens = ROLE_OVERHEAD
    content = message.get("content", "")
    if content and isinstance(content, str):
        tokens += estimate_tokens(content)
    # tool_calls 额外开销
    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            tokens += estimate_tokens(fn.get("name", "")) + estimate_tokens(fn.get("arguments", "")) + BLOCK_OVERHEAD
    return tokens


@dataclass(frozen=True)
class TokenSurfaceNode:
    """一条表层事件的位置 token 定价节点（官方 TokenSurfaceNode）。"""

    seq: int
    tokens: int                # 该消息的请求压力 token
    heuristic_tokens: int      # 固定启发式定价（独立于路由）


@dataclass(frozen=True)
class TokenMeasurementBaseline:
    """计量锚点（官方 TokenMeasurementBaseline）。"""

    kind: str          # "none" | "estimated" | "usage"
    tokens: int = 0
    usage: dict | None = None   # usage 锚点附带的完整 TokenUsage（kind=usage 时）


@dataclass(frozen=True)
class TokenMeasurement:
    """一次不可变请求压力与表层回放快照（官方 TokenMeasurement）。"""

    log_revision: int
    baseline: TokenMeasurementBaseline
    surface_delta_tokens: int
    total_tokens: int
    surface_tokens: int
    nodes: list[TokenSurfaceNode] = field(default_factory=list)


class TokenMeterService(CapabilityProvider):
    """ctx.tokenMeter：独立 token 计量服务。"""

    service_name = "tokenMeter"

    def _init(self, ctx):
        self._usage_anchor: tuple[str, int, dict] | None = None  # (model, totalTokens, usage)
        self._log_revision_base: int = 0

    def measure(self, session, messages: list[dict] | None = None) -> TokenMeasurement:
        """从 session 事件流 + 当前 messages 产生一次计量快照。

        ``messages`` 可选（缺省从 session 投影推导；compaction 直接传入 agent.messages）。
        """
        # logRevision = 已持久化事件数（消费的 seq）
        log_revision = session.seq

        # 表层节点：按事件流中对应的模型可见消息位置
        nodes = self._build_nodes(session, messages or [])
        surface_tokens = sum(n.tokens for n in nodes)

        # 锚点：优先 usage（最近一次同路由成功调用），否则 heuristic
        baseline = self._resolve_baseline(surface_tokens, nodes)

        total_tokens = baseline.tokens + surface_tokens
        surface_delta = surface_tokens - baseline.tokens

        return TokenMeasurement(
            log_revision=log_revision,
            baseline=baseline,
            surface_delta_tokens=surface_delta,
            total_tokens=total_tokens,
            surface_tokens=surface_tokens,
            nodes=nodes,
        )

    def _build_nodes(self, session, messages: list[dict]) -> list[TokenSurfaceNode]:
        """从当前消息列表构建表层节点（按 seq 位置对齐）。"""
        nodes: list[TokenSurfaceNode] = []
        events = session.events()
        # 按模型消息投影：每个 user/assistant/tool 消息对应一个 node
        msg_idx = 0
        for ev in events:
            t = ev.type
            if t in ("user-message", "assistant-message"):
                # 取对应消息（如果 tokens 超出列表则 break）
                if msg_idx >= len(messages):
                    break
                msg = messages[msg_idx]
                msg_idx += 1
                tokens = estimate_message(msg)
                nodes.append(TokenSurfaceNode(
                    seq=ev.seq,
                    tokens=tokens,
                    heuristic_tokens=tokens,
                ))
        return nodes

    def _resolve_baseline(self, surface_tokens: int, nodes: list[TokenSurfaceNode]) -> TokenMeasurementBaseline:
        """解析锚点：usage 优先，否则 heuristic。"""
        # [教学简化] 当前无 provider usage 回传 → 永远走 heuristic
        if self._usage_anchor is not None:
            _, anchor_tokens, usage = self._usage_anchor
            return TokenMeasurementBaseline(kind="usage", tokens=anchor_tokens, usage=usage)
        if surface_tokens == 0:
            return TokenMeasurementBaseline(kind="none", tokens=0)
        return TokenMeasurementBaseline(kind="estimated", tokens=surface_tokens)

    def record_usage(self, model: str, total_tokens: int, usage: dict | None = None) -> None:
        """记录一次成功的 provider 调用用量（供后续计量当锚点）。"""
        self._usage_anchor = (model, total_tokens, usage or {})