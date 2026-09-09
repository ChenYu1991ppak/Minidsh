"""workspace 能力：Workspace entity（提供 ctx.root 的运行时值），对齐官方 packages/workspace。"""
from .providers.root import apply, SET

__all__ = ["apply", "SET"]
