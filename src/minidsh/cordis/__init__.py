"""cordis 内核：插件容器最小集（教学改写版，以 ch01/code/cordis.py 为基线）。

一切皆插件：Context 提供服务解析 / 依赖注入 / 事件派发 / 生命周期注册；
Fiber 是插件的一次激活；Service 构造即注册。内核同步、单线程（spec §11-5）。

源码对应：vendor/cordis/src/（context.ts / service.ts / fiber.ts / events.ts / reflect.ts）。
"""

from .symbols import Symbols
from .errors import ServiceNotFoundError
from .events import EventMethods
from .fiber import Fiber
from .plugin import Plugin, normalize_plugin
from .service import Service
from .capability import CapabilityDefinition, CapabilityProvider, CapabilityConsumer
from .context import Context

__all__ = [
    "Context",
    "Fiber",
    "Plugin",
    "normalize_plugin",
    "Service",
    "ServiceNotFoundError",
    "Symbols",
    "EventMethods",
    "CapabilityDefinition",
    "CapabilityProvider",
    "CapabilityConsumer",
]