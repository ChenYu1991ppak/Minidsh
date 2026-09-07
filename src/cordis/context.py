"""Context：插件执行环境——服务解析、依赖注入、事件派发、生命周期注册四合一。

源码对应：vendor/cordis/src/context.ts:42。属性读取对应 TS 的 Proxy get 陷阱：
普通查找失败后路由到服务表（context.ts:16/42 → reflect.ts:133/136）。

[教学决策 G6] TS Proxy 同时拦截 get/set；Python 的 __getattr__ 只拦截缺失属性读取，
因此服务注册一律走显式 provide()，不用 __setattr__ 魔法，避免内部字段误伤。
"""
from __future__ import annotations

from . import fiber as _fiber
from .events import EventMethods
from .fiber import Fiber
from .plugin import normalize_plugin
from .errors import ServiceNotFoundError
from .symbols import Symbols

__all__ = ["Context"]


class Context(EventMethods):
    """插件执行环境。内核同步、单线程（spec §11-5）。

    ``parent`` 形参开启**子容器**（对应真实 Cordis 的 ctx.extend/fork）：子容器
    的读取沿 parent 链回退（服务继承看得见祖先），写入（provide/effect/plugin）
    只落自己——这是 scope 库原语的根基（packages/core/scope）。父为 None 时行为
    与旧版完全一致。
    """

    def __init__(self, parent: "Context | None" = None):
        self._parent = parent
        setattr(self, Symbols.services, {})    # 服务表：name → 实例
        setattr(self, Symbols.events, {})      # 监听器表：事件名 → [listener]
        setattr(self, Symbols.dispose, False)  # dispose 标记
        self._fibers = []      # 全部 fiber（按注册顺序）
        self._pending = []     # 依赖未满足、等待加载的 fiber
        self._disposers = []   # 根级 effect 的清理函数

    def extend(self, **extensions) -> "Context":
        """铸造一个继承读、孤立写的子容器；``extensions`` 作为标签属性直接挂上。

        对应真实 Cordis 的 ``ctx.extend({...})``（scope/index.ts 用它打 scope 标签）。
        """
        child = Context(parent=self)
        for key, value in extensions.items():
            setattr(child, key, value)
        return child

    # ---------- 服务解析 ----------

    def __getattr__(self, name):
        """普通属性查找失败时才调用：一切非内部属性都按服务读取。

        自身的服务表查不到则沿 parent 链向上读（子容器继承祖先服务）。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        services = getattr(self, Symbols.services)
        if name in services:
            return services[name]
        if self._parent is not None:
            return getattr(self._parent, name)   # 祖先或更上级含该服务时命中；否则抛 ServiceNotFoundError
        raise ServiceNotFoundError(name)

    def provide(self, name, value):
        """注册服务，返回「注销」disposer（reflect.ts:237-243）。

        注册后触发 service/provide，并结算等待依赖的 fiber。
        """
        services = getattr(self, Symbols.services)
        services[name] = value
        self.emit("service/provide", {"name": name})
        self._settle_pending()

        def dispose():
            if services.get(name) is value:
                del services[name]
                self.emit("service/dispose", {"name": name})

        return dispose

    # ---------- 依赖注入：inject 依赖检查 ----------

    def _lookup(self, name):
        """沿自己 → parent 链查找服务名，返回 (found, value)；用于 probe/has/inject。

        子容器读继承祖先服务（scope 的可见性根基）；写入始终只落自己的服务表。
        """
        services = getattr(self, Symbols.services)
        if name in services:
            return True, services[name]
        if self._parent is not None:
            return self._parent._lookup(name)
        return False, None

    def probe(self, name):
        """显式按名查服务，任意名字（含 `tools/bash`、`llm/openai` 等非标识符）可查。

        `ctx.<ident>` 属性路由仅覆盖合法标识符名；非标识符名一律经 ``probe`` 显式读取。
        找不到抛 ``ServiceNotFoundError``。子容器沿 parent 链回退。
        """
        found, value = self._lookup(name)
        if found:
            return value
        raise ServiceNotFoundError(name)

    def service(self, name):
        """``probe`` 的语义别名：更贴近「从服务表取服务」的读法。

        当前代码统一走 ``probe``；此别名作为公共 API 保留，便于调用侧按语义选择。
        """
        return self.probe(name)

    def has(self, name):
        """服务表是否存在该名（不发异常）。子容器沿 parent 链回退。"""
        return self._lookup(name)[0]

    def inject(self, names, callback):
        """严格解析依赖后执行 callback；任一依赖缺失即抛 ``ServiceNotFoundError``。

        与插件化 deferral（Fiber PENDING→ACTIVE）互补：前者「齐备才加载」，这里
        是「现在就要」的消费方写法——解析出的服务按声明顺序作为位置参数传入。
        子容器未持有的名字沿 parent 链解析（继承语义）。
        抛出的错误信息内含缺失的依赖名（可能多个）。
        """
        missing = [n for n in names if not self.has(n)]
        if missing:
            raise ServiceNotFoundError(", ".join(missing))
        return callback(*[self.probe(n) for n in names])

    def _settle_pending(self):
        """新服务到达后逐个复查 PENDING fiber：满足才加载。

        fiber.ts:249-251 的反面：PENDING + deps_satisfied() 不满足 → 不加载而等待。
        循环经 remove 前判存在：activate 里可能再次 provide → 递归 settle，此时
        外层循环剩余的 fiber 已被里层 settle 移除并激活，需跳过而非二次 remove。
        """
        while True:
            ready = [f for f in self._pending if f.deps_satisfied()]
            if not ready:
                return
            for fiber in ready:
                if fiber not in self._pending:
                    continue  # 已被递归 settle 移除并激活
                self._pending.remove(fiber)
                fiber.activate()

    # ---------- 生命周期注册 ----------

    def effect(self, execute, label="anonymous"):
        """注册 effect：立即执行 execute，收集其返回的清理函数。

        清理函数在卸载时逆序执行（fiber.ts:415/418/431）——后注册的先清理。
        label 参数对齐真实 API，教学版不消费它。
        """
        disposer = execute()
        if disposer is None:
            disposer = lambda: None  # noqa: E731  无清理函数时用 no-op 占位
        if _fiber._current_fiber is not None:
            _fiber._current_fiber.disposers.append(disposer)
        else:
            self._disposers.append(disposer)
        return disposer

    def plugin(self, callback, config=None):
        """注册插件：module / class / 带 apply 的对象 / 函数 / Plugin 归一后产出激活 Fiber。

        归一化经 ``normalize_plugin``；显式重名抛 ValueError（SPEC §9 决议 1），
        推导名可能重复，由名字唯一性在此把关（仅拦截显式重名）。
        """
        plugin = normalize_plugin(callback)
        for fiber in self._fibers:
            if fiber.name == plugin.name:
                if plugin.explicit_name:
                    # 显式 name 重复 → 抛错（SPEC §9 决议 1）
                    raise ValueError(f"插件名重复：{plugin.name!r}")
                # 推导名重复 → 只告警不阻断
        return Fiber(self, plugin, config)

    def dispose(self):
        """销毁容器：按注册逆序卸载全部 fiber，再逆序执行根级 effect。

        [教学简化] 真实代码 dispose 异步且带 settle 超时。
        """
        if getattr(self, Symbols.dispose):
            return
        setattr(self, Symbols.dispose, True)
        for fiber in reversed(self._fibers):
            fiber.dispose()
        for disposer in reversed(self._disposers):
            disposer()