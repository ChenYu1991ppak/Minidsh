"""web 能力：检索 seam（seam 预留）。

v1 为 no-op：search/fetch 均返回不可用标记，为未来接真实检索/抓取 provider 预留。
"""
from __future__ import annotations

from .definition import WebService, NoopWebService

__all__ = ['WebService', 'NoopWebService']
