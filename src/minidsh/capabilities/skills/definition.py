"""skills 模块：skill 加载——provider 注册表型 seam。

源码对应（ch12 教学版，逐机制对齐）：
- ``SkillSummary`` / ``SkillDefinition`` ↔ packages/skill/skill/src/index.ts:56 / :86
- ``SkillProvider`` 契约 {name, list(), get()} ↔ index.ts:248
- ``SkillRegistry``（Service，绑定 ctx.skills）↔ index.ts:357
- ``FilesystemSkillProvider`` ↔ packages/skill/skill-filesystem/src/index.ts:146
- parseSkillFile / parseFrontmatter ↔ skill-filesystem/src/index.ts:793 / :909

seam 形态（ch12 [教学决策 1]）：**provider 注册表型**——多个 provider 并存注册，
读取时合并去重；与第 5 章 shell 的「组合期二选一」方法调用式 seam 相对。

v1 简化（相对 ch12）：
- **单作用域**（无 ScopedLayers / scope chain）——scope 是 seam 预留，ch09 机制不进 v1；
  分层 shadowing 规则留注释，实现退化为单一 provider 表。
- 项目目录布局对齐 spec §6.2：``skills/<name>/SKILL.md``（嵌套目录），
  而非 ch12 的平铺 ``*.md``。
- 无 watch（变更订阅）；靠重新 list() 真实扫盘。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...cordis import CapabilityProvider

__all__ = [
    "SkillSummary",
    "SkillDefinition",
    "SkillProvider",
    "FilesystemSkillProvider",
    "SkillRegistry",
    "parse_skill_file",
]


# ---------- 词汇类型 ----------


@dataclass(frozen=True)
class SkillSummary:
    """目录条目：渲染用元数据，无正文（index.ts:56）。list() 返回它。"""

    name: str
    description: str
    source: str = "project"


@dataclass(frozen=True)
class SkillDefinition:
    """完整定义：带正文，按需加载（index.ts:86）。provider.get() 返回它。"""

    name: str
    description: str
    content: str
    source: str = "project"


class SkillProvider:
    """skill provider 契约（index.ts:248）：list() 出摘要、get() 按名加载正文。

    这是「provider 注册表」型 seam 的实现侧接口：多个实现并存注册，
    注册表读取时合并去重（同层同名后注册遮蔽先注册，v1 简化）。
    """

    name: str = ""

    def list(self) -> list[SkillSummary]:
        """列出本 provider 的候选摘要（元数据，无正文）（index.ts:252）。"""
        raise NotImplementedError

    def get(self, name: str) -> SkillDefinition | None:
        """按名加载完整定义（含正文）（index.ts:258）。"""
        raise NotImplementedError


# ---------- SKILL.md 解析 ----------


def parse_skill_file(text: str) -> tuple[str, str, str] | None:
    """解析一段 SKILL.md 文本：frontmatter（name/description）+ 正文。

    返回 (name, description, content)；无 frontmatter 或缺 name 返回 None。
    [教学简化] 真实 parseFrontmatter 支持任意字段 + invocation policy；此处只取 name/description。
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    frontmatter = text[3:end].strip()
    content = text[end + 4:].strip() if end + 4 < len(text) else ""
    fields = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    name = fields.get("name")
    if not name:
        return None
    return name, fields.get("description", ""), content


# ---------- provider：目录扫描 ----------


class FilesystemSkillProvider(SkillProvider):
    """目录扫描 provider（skill-filesystem/src/index.ts:146）。

    扫 ``root/skills/<name>/SKILL.md``（spec §6.2 布局）。
    """

    name = "filesystem"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _skill_dirs(self) -> list[Path]:
        skills_root = self.root / "skills"
        if not skills_root.is_dir():
            return []
        return sorted(p for p in skills_root.iterdir() if p.is_dir())

    def _load_definition(self, name: str) -> SkillDefinition | None:
        for d in self._skill_dirs():
            skill_file = d / "SKILL.md"
            if not skill_file.is_file():
                continue
            parsed = parse_skill_file(skill_file.read_text(encoding="utf-8"))
            if parsed is None:
                continue
            skill_name, description, content = parsed
            if skill_name == name:
                return SkillDefinition(
                    name=skill_name, description=description, content=content, source="project"
                )
        return None

    def list(self) -> list[SkillSummary]:
        summaries: list[SkillSummary] = []
        for d in self._skill_dirs():
            skill_file = d / "SKILL.md"
            if not skill_file.is_file():
                continue
            parsed = parse_skill_file(skill_file.read_text(encoding="utf-8"))
            if parsed is None:
                continue
            name, description, _content = parsed
            summaries.append(SkillSummary(name=name, description=description, source="project"))
        return summaries

    def get(self, name: str) -> SkillDefinition | None:
        return self._load_definition(name)


# ---------- 注册表 ----------


class SkillRegistry(CapabilityProvider):
    """ctx.skills：skill provider 注册表（index.ts:357）。

    [教学简化] 单作用域：一个 provider 表，无 scope 链分层；同层同名后注册遮蔽先注册。

    注册表型 seam：SkillRegistry 是「能力边界」的 provider（提供 ctx.skills 服务），
    它内部再维护一张「子 provider 注册表」——里层 SkillProvider 不套三角色基类，
    是 registry 的内部类型。
    """

    service_name = "skills"

    def _init(self, ctx):
        self._providers: dict[str, SkillProvider] = {}

    # ---- 注册侧 ----

    def register_provider(self, provider: SkillProvider):
        """把一个 provider 注册进 registry（index.ts:391）。注册是 effect：返回 disposer。"""
        self._providers[provider.name] = provider

        def dispose():
            self._providers.pop(provider.name, None)

        return self.ctx.effect(lambda: dispose, label=f"skill-provider:{provider.name}")

    # ---- 读取侧 ----

    def list(self) -> list[SkillSummary]:
        """合并所有 provider 的目录，按名排序（index.ts:471）。

        [教学简化] 无 rank/shadowing：同名合并去重（后注册 provider 先其贡献），按名排序。
        """
        merged: dict[str, SkillSummary] = {}
        for provider in self._providers.values():
            for summary in provider.list():
                merged[summary.name] = summary
        return [merged[k] for k in sorted(merged)]

    def get(self, name: str) -> SkillDefinition | None:
        """按名加载完整定义（index.ts:501）。"""
        for provider in self._providers.values():
            definition = provider.get(name)
            if definition is not None:
                return definition
        return None

    def load(self, name: str) -> SkillDefinition | None:
        """加载一个技能并注入 system-prompt；返回定义，未找到返回 None。

        注入即效应：注册 ``systemPrompt`` 节，卸载时移除。消费方是 loop——
        每次调用前 ``systemPrompt.render()`` 会带上已加载技能正文。
        """
        definition = self.get(name)
        if definition is None:
            return None
        # 注入 prompt（惰性加载：只有被显式 load 才注入，见 spec §6.2「正文在被加载时才注入」）
        self.ctx.systemPrompt.section(
            f"skill:{definition.name}",
            definition.content,
            order=50,
        )
        self.ctx.emit("skills/change", {"name": definition.name, "op": "load"})
        return definition