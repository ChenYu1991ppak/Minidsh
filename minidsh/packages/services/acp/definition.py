"""ACP server 定义：Agent Client Protocol JSON-RPC stdio server（教学版）。

对齐官方 ``dsh-acp``（packages/acp/acp/src/index.ts）的 ACP v1 子集。
传输层是 ndjson（每行一个 JSON-RPC 2.0 对象，stdin/stdout）。

[教学简化] 不实现完整的 ACP v1：无 session/list、session/resume、session/close；
无 authenticate negotiation；无 capabilities 动态枚举；无 MCP 挂载；无 image prompts。
只做「单会话创建 + prompt + cancel + 流式 update」核心闭环。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition

__all__ = ["AcpServer", "SESSION_UPDATE", "USAGE_UPDATE", "TOOL_CALL", "TOOL_CALL_UPDATE",
           "AGENT_MESSAGE_CHUNK", "AGENT_THOUGHT_CHUNK"]

# ACP session/update 类型常量（对齐官方 updates.ts）
AGENT_MESSAGE_CHUNK = "agent_message_chunk"
AGENT_THOUGHT_CHUNK = "agent_thought_chunk"
TOOL_CALL = "tool_call"
TOOL_CALL_UPDATE = "tool_call_update"
USAGE_UPDATE = "usage_update"

# 自定义扩展（非标准 ACP）：模型/思考强度切换
SESSION_UPDATE = "session_update"


class AcpServer(CapabilityDefinition):
    """ACP JSON-RPC stdio server 接口（定义层）。

    ``start()`` 阻塞当前线程，处理 stdin JSON-RPC 请求并写入 stdout 响应，
    直到客户端断开（stdin EOF）或主动 ``stop()`` 被调用。
    """

    service_name = "acp"

    async def start(self) -> None:
        """启动 ACP server：读取 stdin，处理 JSON-RPC，写入 stdout。阻塞直到 EOF。"""
        raise NotImplementedError

    async def stop(self) -> None:
        """关闭 ACP server。"""
        raise NotImplementedError