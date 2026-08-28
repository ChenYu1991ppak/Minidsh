"""workspace 模块：项目加载 + CLI 装配。

- ``loader.py``：解析被加载项目目录（AGENTS.md / .minidsh/ models.json + settings.json /
  skills/ / agents/），装配完整插件图成一个 ``Context``。
- ``cli.py``：argparse 入口（``minidsh run`` / ``minidsh replay``）。

项目目录布局见 spec §6.2：
    <project>/
    ├── AGENTS.md                 # 全局指令 → systemPrompt 节
    ├── .minidsh/
    │   ├── models.json           # 模型配置（对齐 CodeBuddy，内嵌 apiKey）
    │   └── settings.json         # harness 设置（storage/compaction/tools）
    ├── skills/<name>/SKILL.md    # 技能 → FilesystemSkillProvider
    ├── agents/<name>.md          # 子 agent 定义 → SubagentRegistry.define_agent
    └── ...
"""
from __future__ import annotations

from .loader import load_project

__all__ = ["load_project"]