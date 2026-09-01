"""能力三角色抽象基类（对齐官方 capability 三层拆分的「定义/提供方/消费方」）。

- ``CapabilityDefinition``：定义（纯契约，不自注册）。子类声明 ``service_name`` + 覆写接口方法。
- ``CapabilityProvider``：提供方（继承 Definition + Service，构造即注册到 service_name）。
- ``CapabilityConsumer``：消费方（非 Service、不被继承；只做「消费方契约」校验）。
"""
from __future__ import annotations

from .service import Service

__all__ = ["CapabilityDefinition", "CapabilityProvider", "CapabilityConsumer"]


class CapabilityDefinition:
    """能力定义：纯契约，不注册服务。

    子类必须声明类属性 ``service_name``（能力服务名，如 "shell"/"llm"/"session"），
    并覆写接口方法（如 ``execute(...)``）。不自注册——注册是 Provider 的职责。
    """

    service_name: str = ""


class CapabilityProvider(CapabilityDefinition, Service):
    """提供方：实现能力定义，构造即注册到 ``service_name``。

    子类常量：
    - ``service_name``（继承自 Definition）：注册与注入用的服务名。
    子类覆写 ``_init(ctx, *args, **kwargs)`` 做额外初始化（替代手工 super().__init__）。
    构造 ::
        LocalShellService(ctx)   # → auto-register ctx.<service_name>
    """

    def __init__(self, ctx, *args, **kwargs):
        Service.__init__(self, ctx, self.service_name)
        self._init(ctx, *args, **kwargs)

    def _init(self, ctx, *args, **kwargs):
        """子类覆写以做额外初始化；默认无操作。"""


class CapabilityConsumer:
    """消费方：向 tools 注册表写入工具（官方机制），不提供新服务。

    不被继承——官方 consumer 是 module 形态（module 级 name/inject/apply）。
    本类只提供「消费方契约」的校验：
    - ``inject`` 必须含 ``tools``（往注册表写工具的入口）；
    - ``inject`` 必须含所消费能力的 ``service_name``。
    """

    @staticmethod
    def assert_valid(inject: list[str], service_name: str) -> None:
        """校验一个 consumer 的依赖声明是否符合契约；不符抛 ValueError。"""
        if "tools" not in inject:
            raise ValueError(f"consumer 必须 inject 'tools'（实际 {inject!r}）")
        if service_name and service_name not in inject:
            raise ValueError(
                f"consumer 必须 inject 所消费能力服务名 {service_name!r}（实际 {inject!r}）"
            )