"""settings seam：按 namespace 分节的用户设置（Service Definition）

源码对应：packages/settings/settings/src/index.ts。

三角色：
- ``SettingsService``（定义，``ctx.settings``）——按 namespace 注册 + 分层解析；
- ``settings-file``（provider）——存原始文档并推送外部编辑；
- Consumer：各插件注册 schema 后读现象或观察解析值。

分层（settings.zh.md）：**schema 默认值 → 注册方 base → 用户分节**；validate 在 schema
接纳后运行，拒绝的是**写入**（不产出静默失效值）。

[教学简化] 相对官方：
- schema 用「叶子即默认值」的纯 dict（不引 schemastery）；
- 砍掉 revision CAS / redactSecrets / SettingsPathOp，保留 get/watch/update/replace 四法；
- 无深冻结快照（教学版 dict 直接返回）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from minidsh.cordis import CapabilityDefinition

__all__ = [
    "SettingsNamespace",
    "SettingsRegisterOptions",
    "SettingsScope",
    "SettingsService",
    "deep_merge",
]

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def validate_namespace(identifier: str) -> None:
    """校验小写 kebab-case 语法（settings.zh.md 构造期校验）。"""
    if not _NAMESPACE_RE.match(identifier):
        raise ValueError(f"settings namespace 须为小写 kebab-case：{identifier!r}")


class SettingsNamespace(str):
    """命名用户文档中归插件所有的分节（branded，构造期校验）。"""

    def __new__(cls, value: str):
        validate_namespace(value)
        return super().__new__(cls, value)


@dataclass(frozen=True)
class SettingsRegisterOptions:
    """注册选项：组合 base 层 + 跨字段 validate 钩子（settings.zh.md 子集）。"""

    base: dict | None = None
    validate: Callable[[dict], None] | None = None


def deep_merge(base: dict, *overlays: dict) -> dict:
    """深合并：后层覆盖前层；键缺席保留前层。返回新 dict。"""
    result: dict[str, Any] = dict(base or {})
    for overlay in overlays:
        if not overlay:
            continue
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
    return result


class SettingsScope:
    """owner 面向的句柄（settings.zh.md SettingsScope）：get/watch/update/replace。"""

    def __init__(self, service, namespace: SettingsNamespace,
                 schema: dict, base: dict | None):
        self._service = service
        self._namespace = namespace
        self._schema = schema          # 叶子即默认值
        self._base = base or {}
        self._watchers: list[Callable[[dict, dict], Any]] = []
        self._validate: Callable[[dict], None] | None = None  # provider 填 validate 钩子

    def get(self) -> dict:
        """当前解析值：schema 默认 → base → 用户分节。"""
        return self._service._resolve(self._namespace, self._schema, self._base)

    def watch(self, callback: Callable[[dict, dict], Any]) -> Callable[[], None]:
        """观察已提交变更；返回移除观察者的 disposer。"""
        self._watchers.append(callback)

        def dispose():
            if callback in self._watchers:
                self._watchers.remove(callback)

        return dispose

    def update(self, patch: dict) -> None:
        """把稀疏 patch 合并进用户分节并持久化（绝不进 base）。"""
        self._service._commit(self, deep_merge(self._service._user_section(self._namespace), patch))

    def replace(self, section: dict) -> None:
        """整体替换用户分节；缺席键重新继承 base 与默认值。"""
        self._service._commit(self, section)


class SettingsService(CapabilityDefinition):
    """ctx.settings：用户设置 seam。"""

    service_name = "settings"

    def register(self, namespace: str, schema: dict,
                 options: SettingsRegisterOptions | None = None) -> SettingsScope:
        raise NotImplementedError

    def resolve(self, namespace: str) -> dict:
        raise NotImplementedError