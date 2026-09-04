"""TUI 命令注册表：把斜杠命令抽成声明式注册表（对齐官方 interaction/commands）。

官方 ``dsh-commands``（packages/interaction/commands）用 ``CommandRegistry`` +
作用域层管理人类命令；教学版保持最小形态：``Command { name, description, handler }`` +
``CommandRegistry``（register / dispatch）。命令名合法集对齐官方 ``COMMAND_NAME``
（``[a-z][a-z0-9_-]*``，不含前导斜杠）。

dispatch 语义：按首词匹配；匹配成功调 handler 并返回 ``True``；未匹配返回 ``False``，
由调用方（TUI ``on_input_submitted``）降级为普通用户消息入队——不抛异常、不吞输入。

[教学简化] 不做官方 ``CommandInvocation``（agent/commandId/attachments/signal）、
不做 ``command/run``/``command/done`` 生命周期事件、不做 ScopedLayers per-agent 层、
不做 input.hint/images。只做「注册 + 首词分发」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

__all__ = ["Command", "CommandRegistry", "COMMAND_NAME_RE"]

# 命令名合法集（对齐官方 COMMAND_NAME，不含前导斜杠）
COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class Command:
    """一条斜杠命令：名字 + 描述 + handler。

    ``handler`` 签名 ``async def handler(app, arg: str | None)``；``arg`` 是命令名
    之后的剩余文本（剥首词），无则 ``None``。
    """

    name: str                                  # 小写命令名（无前导斜杠）
    description: str
    handler: Callable[..., Awaitable[None]]


class CommandRegistry:
    """斜杠命令注册表。``register`` 返回 disposer；``dispatch`` 按首词分发（异步）。"""

    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, cmd: Command) -> Callable[[], None]:
        """注册一条命令，返回注销 disposer。名字非法或重复抛 ValueError。"""
        if not COMMAND_NAME_RE.match(cmd.name):
            raise ValueError(f"非法命令名 {cmd.name!r}（须匹配 {COMMAND_NAME_RE.pattern}）")
        if cmd.name in self._commands:
            raise ValueError(f"命令 {cmd.name!r} 已注册")
        self._commands[cmd.name] = cmd

        def dispose():
            if self._commands.get(cmd.name) is cmd:
                del self._commands[cmd.name]

        return dispose

    async def dispatch(self, app, line: str) -> bool:
        """尝试把一行当命令分发；返回是否作为命令处理（未匹配返回 False）。

        命令行须以 ``/`` 开头；剥前导斜杠后取首词匹配注册命令，剩余作 ``arg``。
        匹配成功 ``await`` handler 后返回 ``True``；未匹配返回 ``False``（调用方
        降级为普通消息）。异步，调用方须在 async 上下文 ``await``。
        """
        if not line.startswith("/"):
            return False
        body = line[1:]
        name, _, rest = body.partition(" ")
        name = name.strip()
        arg = rest.strip() or None
        cmd = self._commands.get(name)
        if cmd is None:
            return False
        await cmd.handler(app, arg)
        return True

    def list_commands(self) -> list[Command]:
        """返回已注册命令（按名字序）。"""
        return [self._commands[k] for k in sorted(self._commands)]
