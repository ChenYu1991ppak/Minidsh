"""事件派发混入：on / emit / serial / waterfall。

源码对应：vendor/cordis/src/events.ts:288（on）/:194（emit）/:204（serial）/:234（waterfall）。

派发是同步的（spec §11-5：内核同步）。`on` 自身是一笔 effect——注册监听器的
清理函数（移除监听）交给宿主 fiber 或根级 effect 管理，卸载时自动注销。
"""
from __future__ import annotations

from .symbols import Symbols

__all__ = ["EventMethods"]


class EventMethods:
    """提供事件注册与派发能力的混入基类。

    依赖宿主（`Context`）提供：存储表（`Symbols.events`）与 `effect()`。
    """

    def on(self, event, listener):
        """注册监听器，返回 off disposer（events.ts:288-302）。

        注册本身是 effect：宿主 fiber 卸载时自动注销（events.ts:254 register → fiber.effect）。
        """
        listeners = getattr(self, Symbols.events).setdefault(event, [])

        def setup():
            listeners.append(listener)

            def off():
                if listener in listeners:
                    listeners.remove(listener)

            return off

        return self.effect(setup, label=f"on:{event}")

    def emit(self, event, *args):
        """同步派发：按注册顺序调用，不等返回值（events.ts:194；:183 是 parallel）。"""
        for listener in list(getattr(self, Symbols.events).get(event, [])):
            listener(*args)

    def serial(self, event, *args):
        """顺序调用监听器，遇 bail 值立即返回（events.ts:204-209）。

        bail 判定：非 None 且非 False（isBailed，events.ts:13）。
        """
        for listener in list(getattr(self, Symbols.events).get(event, [])):
            result = listener(*args)
            if result is not None and result is not False:
                return result
        return None

    def waterfall(self, event, value):
        """把返回值穿下去：返回 None 视为放行，非 None 替换当前值（events.ts:234）。

        [教学决策 G4] 无监听器时原样返回初始 value。
        真实实现是中间件式（监听器包裹 next 续体、最外层优先）；教学版简化成顺序改写。
        """
        for listener in list(getattr(self, Symbols.events).get(event, [])):
            result = listener(value)
            if result is not None:
                value = result
        return value