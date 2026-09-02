"""settings 的 file 提供方：存原始用户文档 + 分层解析（构造即注册 ctx.settings）。

源码对应：packages/settings/settings-file。三角色的「提供方」。

用户文档位置：``~/.minidsh/settings.json`` 的顶层（复用现有 settings.json 形态），
每个已注册 namespace 对应一个键。用户分节缺失 = 未覆盖，解析回退 base/schema 默认。

分层：schema 默认 → 注册方 base → 用户分节。validate 在 schema 接纳后运行，
拒绝的是**写入**；写盘失败时保留 last-good 并告警（settings.zh.md）。
"""
from __future__ import annotations

from ..definition import (
    SettingsService,
    SettingsNamespace,
    SettingsRegisterOptions,
    SettingsScope,
    deep_merge,
)
from minidsh.cordis import CapabilityProvider
from minidsh.infrastructure.config.files import user_settings_path, load_json, save_json

__all__ = ["FileSettingsService"]

name = "minidsh.settings"
inject = []


class FileSettingsService(SettingsService, CapabilityProvider):
    """文件后端 settings：用户文档持久化在 user_settings_path。"""

    def __init__(self, ctx, path=None):
        super().__init__(ctx)
        self._path = path or user_settings_path()
        self._registrations: dict[SettingsNamespace, SettingsScope] = {}
        self._validators: dict[SettingsNamespace, object] = {}

    # ---------- 文档访问 ----------

    def _document(self) -> dict:
        return load_json(self._path)

    def _user_section(self, namespace: SettingsNamespace) -> dict:
        section = self._document().get(namespace)
        return section if isinstance(section, dict) else {}

    def _write_user_section(self, namespace: SettingsNamespace, section: dict) -> None:
        doc = self._document()
        doc[namespace] = section
        save_json(self._path, doc)

    # ---------- 解析 ----------

    def resolve(self, namespace: str) -> dict:
        ns = SettingsNamespace(namespace)
        if ns not in self._registrations:
            raise KeyError(f"settings namespace 未注册：{namespace!r}")
        return self._registrations[ns].get()

    def _resolve(self, namespace: SettingsNamespace, schema: dict, base: dict) -> dict:
        return deep_merge(schema, base, self._user_section(namespace))

    # ---------- 注册 ----------

    def register(self, namespace: str, schema: dict,
                 options: SettingsRegisterOptions | None = None) -> SettingsScope:
        ns = SettingsNamespace(namespace)
        if ns in self._registrations:
            raise KeyError(f"settings namespace 重复注册：{namespace!r}")
        options = options or SettingsRegisterOptions()
        scope = SettingsScope(self, ns, schema, options.base)
        scope._validate = options.validate
        self._registrations[ns] = scope

        def dispose():
            self._registrations.pop(ns, None)

        self.ctx.effect(lambda: dispose, label=f"settings:{namespace}")
        return scope

    # ---------- 提交（SettingsScope 调 update/replace） ----------

    def _commit(self, scope: SettingsScope, next_section: dict) -> None:
        ns = scope._namespace
        proposed = deep_merge(scope._schema, next_section)  # 结构接纳：叶子补默认
        validate_hook = getattr(scope, "_validate", None)
        if validate_hook is not None:
            validate_hook(proposed)   # 抛错 = 拒绝写入（不落盘）

        prev = scope.get()
        try:
            self._write_user_section(ns, next_section)
        except Exception as exc:      # 写盘失败：保留 last-good，不触发观察
            print(f"[minidsh] settings: 写入 namespace {ns!r} 失败，保留旧值：{exc}")
            return
        for watcher in list(scope._watchers):
            try:
                watcher(scope.get(), prev)
            except Exception as exc:
                print(f"[minidsh] settings: watcher 异常：{exc}")