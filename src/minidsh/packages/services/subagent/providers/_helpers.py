"""base 静态插件的公共辅助（_load_agents / _parse_agent_md）。"""
from __future__ import annotations

from pathlib import Path


def _parse_agent_md(text: str) -> tuple[str, str, str] | None:
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
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    if fields.get("name"):
        return fields["name"], fields.get("description", ""), content
    return None


def _load_agents(root: Path, subagents):
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    for path in sorted(agents_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed = _parse_agent_md(text)
        if parsed is not None:
            name, description, content = parsed
        else:
            name, description, content = path.stem, "", text
        subagents.define_agent(name, {"name": name, "description": description, "content": content})
