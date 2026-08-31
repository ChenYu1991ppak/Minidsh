"""profile 模块：bundle 选择 + 直接覆盖（覆盖链）。"""
from __future__ import annotations

from .profile import resolve_profile, profile_path, DEFAULT_BUNDLES

__all__ = ["resolve_profile", "profile_path", "DEFAULT_BUNDLES"]