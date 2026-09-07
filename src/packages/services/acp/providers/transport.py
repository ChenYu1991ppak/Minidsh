"""ACP transport：ndjson（每行一个 JSON 对象）JSON-RPC 2.0 stdio 传输。

对齐官方 ``dsh-acp`` 的 ``ndJsonStream``（packages/acp/acp/src/index.ts:373-376）。
stdin/stdout 用纯文本逐行解析，不做二进制分帧；stdout 只走协议流量，日志走 stderr。
"""
from __future__ import annotations

import json
import sys
from typing import Any

__all__ = ["read_request", "write_response", "write_notification", "JsonRpcError"]


class JsonRpcError(Exception):
    """JSON-RPC 2.0 错误：code + message。"""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict:
        d: dict = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def read_request(line: str) -> dict | None:
    """解析一行 JSON-RPC 请求；空行/非法 JSON 返回 None（跳过）。"""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def write_response(message_id: Any, result: Any = None, stream=None) -> None:
    """写一个 JSON-RPC 成功响应。``stream`` 缺省 stdout。"""
    out = stream if stream is not None else sys.stdout
    payload = {"jsonrpc": "2.0", "id": message_id, "result": result}
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()


def write_notification(method: str, params: Any = None, stream=None) -> None:
    """写一个 JSON-RPC 通知（无 id）。"""
    out = stream if stream is not None else sys.stdout
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()


def write_error(message_id: Any, error: JsonRpcError, stream=None) -> None:
    """写一个 JSON-RPC 错误响应。"""
    out = stream if stream is not None else sys.stdout
    payload = {"jsonrpc": "2.0", "id": message_id, "error": error.to_dict()}
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()