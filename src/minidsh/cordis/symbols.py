"""容器内部符号表。

源码对应：vendor/cordis/src/utils.ts:50-73（源码无独立 symbols.ts；notes §6）。

[教学决策] Symbol.for('cordis:...') → 双下划线字符串常量（notes §6 符号映射）。
存储用这些「双下划线」属性名，普通名称则留给服务表路由（`Context.__getattr__`）。
"""


class Symbols:
    """cordis 内部键名：符号 → 字符串常量映射。"""

    invoke = "__cordis_invoke__"
    dispose = "__cordis_dispose__"
    events = "__cordis_events__"
    fiber = "__cordis_fiber__"
    inject = "__cordis_inject__"
    intercept = "__cordis_intercept__"
    parent = "__cordis_parent__"
    provider = "__cordis_provider__"
    root = "__cordis_root__"
    services = "__cordis_services__"
    setup = "__cordis_setup__"