"""settings 模块。"""
from pydsh.packages.services.settings.definition import (
    SettingsNamespace,
    SettingsRegisterOptions,
    SettingsScope,
    SettingsService,
    deep_merge,
    validate_namespace,
)

__all__ = [
    "SettingsNamespace",
    "SettingsRegisterOptions",
    "SettingsScope",
    "SettingsService",
    "deep_merge",
    "validate_namespace",
]