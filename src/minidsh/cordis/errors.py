"""容器错误类型。

源码对应：无直接对应；教学版自定义（notes §35「未给定错误类型」的落地）。
"""


class ServiceNotFoundError(AttributeError):
    """读取未提供的服务时抛出。

    [教学决策 G1] 继承 AttributeError，使 `getattr(ctx, name, default)` 的缺省值
    写法仍然可用（缺省值写法依赖「属性未定义」的语义，而非普通异常）。
    """

    def __init__(self, name: str):
        super().__init__(f"service '{name}' is not provided")
        self.service_name = name