"""App 插件接口：「一切皆插件」——app 形态（TUI / ACP / headless）由 profile/插件决定。

App 插件是 module 形态（同现有插件三形态之一）：``name`` + ``inject`` + ``apply(ctx, args)``。
``apply`` 接管进程生命周期：自建 agent（``ctx.agent_loop.create()`` / ``resume``）、启动前端、
等待退出、返回进程退出码。launcher 只负责装配 Context 并找到第一个 app 插件，不碰 agent 创建
（对齐官方「TUI 等待 root agent 就绪」的职责边界）。

发现约定：plugins 名单中 ``name`` 以 ``minidsh.app-`` 开头者为 app 插件，取第一个。

[教学简化] 无插件卸载/热重载的 app 生命周期管理；apply 返回退出码即进程退出。
"""
from __future__ import annotations

from typing import Any, Callable

__all__ = ["AppPlugin", "APP_PREFIX", "find_app_plugin"]

APP_PREFIX = "minidsh.app-"


class AppPlugin:
    """App 插件契约校验（同 CapabilityConsumer 只做校验，不做基类被继承）。"""

    @staticmethod
    def assert_valid(plugin: Any) -> None:
        """校验一个 app 插件：name 以 ``minidsh.app-`` 开头，inject 含 ``agent_loop``。"""
        name = getattr(plugin, "name", None)
        if not name or not name.startswith(APP_PREFIX):
            raise ValueError(f"app 插件名须以 {APP_PREFIX!r} 开头：{name!r}")
        inject = list(getattr(plugin, "inject", None) or [])
        if "agent_loop" not in inject:
            raise ValueError(f"app 插件须 inject 'agent_loop'：{inject!r}")


def find_app_plugin(ctx: Any, entries: list) -> Callable | None:
    """从已展开的 plugins 名单里找到第一个 app 插件的 ``apply`` 函数。

    ``entries`` 为 ``PluginRef`` 序列（name/config）；按名单顺序取第一个名字命中
    ``minidsh.app-`` 前缀且已在 ctx 装配激活的插件。无 app 插件返回 ``None``。

    [教学简化] ctx 不保留「已激活插件表」的显式索引，这里直接从 entry-point resolver
    取插件模块的 ``apply``（app 插件都是内置 module，未激活即退回 resolver 取值会拿到
    apply 但可能未装配——此处仅按名字命中返回 ``apply``，装配正确性由 inject 约束保证）。
    """
    for ref in entries:
        if ref.name.startswith(APP_PREFIX):
            from ..packaging import entry_point_resolver

            plugin = entry_point_resolver()(ref.name)
            if plugin is None:
                continue
            apply_fn = getattr(plugin, "apply", None) or getattr(plugin, "factory", None)
            if callable(apply_fn):
                return apply_fn
    return None