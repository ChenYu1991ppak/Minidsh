"""boot：启动装配（loader + CLI 入口），对齐官方 packages/boot 的职责。"""
from .loader import load_project
from .cli import main

__all__ = ["load_project", "main"]
