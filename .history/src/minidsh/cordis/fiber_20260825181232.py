"""Fiber：插件的一次激活。

源码对应：vendor/cordis/src/fiber.ts:184。

状态机：[教学简化] PENDING/ACTIVE/DISPOSED 三态 + UNLOADING（重载中间态）；
真实代码为 PENDING/LOADING/ACTIVE/FAILED/DISPOSED/UNLOADING 六态。

「变化即重载」：fiber 依赖的服务被重新提供（service/provide）或移除
（service/dispose）时，已激活的 fiber 先 _unload（逆序执行 disposer）再按
依赖是否仍满足决定 _reload（重新激活）或退回 PENDING 等待。对应
fiber.ts:588-609（_unload）、646-696（_reload）。

订阅机制说明：fiber 对 service/provide、service/dispose 的订阅**不走 ctx.effect**，
而是直接写入监听器表——否则卸载（unload）时会把订阅自身当 disposer 撤销，
导致之后无法再重载。订阅只在最终 dispose() 时移除。
"""
from __future__ import annotations

from .symbols import Symbols

__all__ = ["Fiber"]

# [教学简化] 真实 cordis 用 AsyncLocalStorage 找到宿主 fiber；
# 教学版同步单线程，用模块级变量标记「当前正在激活的 fiber」即可。
_current_fiber: "Fiber | None" = None

_SERVICE_EVENTS = ("service/provide", "service/dispose")


class Fiber:
    """插件的一次激活，跟踪生命周期与全部 effect 清理函数。"""

    PENDING = "pending"
    ACTIVE = "active"
    UNLOADING = "unloading"  # 变化即重载的中间态
    DISPOSED = "disposed"

    def __init__(self, ctx, callback, config=None):
        self.ctx = ctx
        self.config = config
        self.state = self.PENDING
        self.disposers = []
        self.inject = list(getattr(callback, "inject", None) or [])
        self._body = self._normalize(callback, config)
        self._in_reload = False
        self._service_subs: list[tuple[list, object]] = []
        ctx._fibers.append(self)
        self._subscribe_service_events()
        if self.deps_satisfied():  # 满足才加载（fiber.ts:249-251）
            self.activate()
        else:
            ctx._pending.append(self)

    @staticmethod
    def _normalize(callback, config):
        """三形态归一：

        类 → 实例化 cls(ctx, config)；apply 对象 → 取其 apply(ctx)；函数 → 原样调用 fn(ctx)。
        """
        if isinstance(callback, type):
            return lambda ctx: callback(ctx, config)
        apply_ = getattr(callback, "apply", None)
        if callable(apply_):
            return lambda ctx: apply_(ctx)
        return callback

    # ---------- 服务变更订阅（变化即重载） ----------

    def _subscribe_service_events(self):
        """直接订阅 service/provide 与 service/dispose，不经 effect（见模块 docstring）。"""
        events = getattr(self.ctx, Symbols.events)

        for event in _SERVICE_EVENTS:
            slots = events.setdefault(event, [])
            handler = self._make_change_handler()
            slots.append(handler)
            self._service_subs.append((slots, handler))

    def _make_change_handler(self):
        def handler(data):
            name = data.get("name") if isinstance(data, dict) else None
            # 只对「我依赖的服务」重载；PENDING 交给 Context._settle_pending，
            # 重载过程中（_in_reload）或非 ACTIVE 态不响应（防重入）。
            if name in self.inject and self.state == self.ACTIVE and not self._in_reload:
                self._apply_change(name)
        return handler

    def _apply_change(self, name: str):
        """依赖变化：卸载，再按 service/provide vs service/dispose 决定重载或等待。

        [教学简化] 事件类型不影响卸载动作，只影响卸载后的去向：
        - provide 后依赖仍满足 → 重载（reload）
        - dispose 或 provide 后仍缺其它依赖 → 退回 PENDING 等待
        """
        self._in_reload = True
        try:
            self._unload()
            if self.deps_satisfied():
                self.activate()
            else:
                self.state = self.PENDING
                if self not in self.ctx._pending:
                    self.ctx._pending.append(self)
        finally:
            self._in_reload = False

    # ---------- 生命周期 ----------

    def deps_satisfied(self):
        """inject「满足才加载」检查：声明的服务全部已提供才加载。

        events 是容器内置能力，不计入外部依赖。
        """
        return not self.missing_deps()

    def missing_deps(self):
        """返回尚未提供的依赖名列表（诊断用）。

        声明依赖经 ``inject``；events 为内置能力，不计入外部依赖。
        事件派发/持久化等模块可用它诊断「插件为何停在 PENDING」。
        """
        services = getattr(self.ctx, Symbols.services)
        return [name for name in self.inject if name != "events" and name not in services]

    def activate(self):
        """执行插件体；执行期间的宿主 fiber 指向 self（effect 的收集目标）。"""
        global _current_fiber
        self.state = self.ACTIVE
        parent = _current_fiber
        _current_fiber = self
        try:
            self._body(self.ctx)
        finally:
            _current_fiber = parent

    def _unload(self):
        """逆序执行清理函数，回到未加载态（fiber.ts:588-609 的 _unload）。

        只清理 effect，不撤销服务订阅、不清 inject——以便之后 reload。
        对已 PENDING 的空 disposers 调用是无害 no-op。
        """
        self.state = self.UNLOADING
        for disposer in reversed(self.disposers):
            disposer()
        self.disposers.clear()

    def _unsubscribe_service_events(self):
        for slots, handler in self._service_subs:
            if handler in slots:
                slots.remove(handler)
        self._service_subs.clear()

    def dispose(self):
        """最终销毁：先卸载（若仍激活），再移除服务订阅（fiber.ts:431）。"""
        if self.state == self.DISPOSED:
            return
        if self.state == self.ACTIVE:
            self._unload()
        self._unsubscribe_service_events()
        self.state = self.DISPOSED