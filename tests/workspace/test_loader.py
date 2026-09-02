"""T17 验收测试：workspace 项目加载。"""
from __future__ import annotations

from minidsh.infrastructure.config.files import save_json, project_dir
from minidsh.infrastructure.boot import load_project
from minidsh.packages.services.session import SessionStore



def _make_project(tmp_path):
    """造一个规范 demo 项目目录：AGENTS.md + skills/ + agents/ + .minidsh/models.json + settings.json。"""
    (tmp_path / "AGENTS.md").write_text("全局指令：保持简短。\n", encoding="utf-8")

    # 项目级模型 + harness 设置（走 .minidsh/ 目录）
    save_json(project_dir(tmp_path) / "models.json", {
        "models": [{"id": "demo-model", "name": "Demo", "url": "https://api.example.com", "apiKey": "demo-key"}],
        "availableModels": ["demo-model"],
    }, secure=True)
    save_json(project_dir(tmp_path) / "settings.json", {
        "compaction": {"contextWindow": 1000, "thresholdRatio": 0.5},
    })

    skill_dir = tmp_path / "skills" / "relay"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: relay\ndescription: 回显\n---\n转述技能正文\n", encoding="utf-8"
    )
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: 审查\n---\n审查正文\n", encoding="utf-8"
    )
    return tmp_path


def _load(root, **kw):
    """加载项目，注入假 openai client（跳过真实 key 校验与网络）。"""
    return load_project(root, quiet=True, **kw)


def test_load_project_assembles_capabilities(tmp_path):
    ctx = _load(_make_project(tmp_path))

    for name in ("config", "sessions", "llm", "systemPrompt", "tools", "skills", "subagents",
                 "agent_loop", "compaction", "sessionPersistence"):
        assert ctx.has(name), f"缺服务 {name}"


def test_load_project_config_service(tmp_path):
    """minidsh.config 插件提供 ctx.config（Config 实例）。"""
    from minidsh.infrastructure.config import Config

    ctx = _load(_make_project(tmp_path))
    assert ctx.has("config")
    assert isinstance(ctx.config, Config)


def test_load_project_injects_agents_md(tmp_path):
    ctx = _load(_make_project(tmp_path))
    assert "全局指令" in ctx.systemPrompt.render()


def test_load_project_registers_skill(tmp_path):
    ctx = _load(_make_project(tmp_path))
    names = [s.name for s in ctx.skills.list()]
    assert names == ["relay"]


def test_load_project_defines_agent(tmp_path):
    ctx = _load(_make_project(tmp_path))
    assert "reviewer" in ctx.subagents.list_agents()


def test_load_project_tools_registered(tmp_path):
    ctx = _load(_make_project(tmp_path))
    known = ctx.tools.wire_schemas()["knownNames"]
    assert "read_file" in known
    assert "bash" in known
    assert "skill-catalog" in known
    assert "task" in known


def test_load_project_compaction_config(tmp_path):
    ctx = _load(_make_project(tmp_path))
    assert ctx.compaction.context_window == 1000
    assert ctx.compaction.threshold_ratio == 0.5


def test_load_project_tool_whitelist(tmp_path):
    root = _make_project(tmp_path)
    save_json(project_dir(root) / "settings.json", {
        "tools": {"allow": ["read_file"]},
    })
    ctx = _load(root)
    known = ctx.tools.wire_schemas()["knownNames"]
    assert "read_file" in known
    assert "bash" not in known


def test_load_project_storage_override(tmp_path):
    ctx = _load(_make_project(tmp_path), storage="sqlite")
    assert ctx._persistence_backend.__class__.__name__.startswith("Sqlite")


def test_load_project_llm_built_from_current_model(tmp_path):
    """llm 由 models.json 的当前模型构建（model id + base_url）。"""
    import json

    root = _make_project(tmp_path)
    ctx = _load(root)
    # 假 client 注入时 model 名 = 当前模型 id
    assert ctx.llm.model == "demo-model"


def test_load_project_missing_url_raises(tmp_path):
    """url 未配置的模型不可用：加载时报错。"""
    import pytest

    root = _make_project(tmp_path)
    save_json(project_dir(root) / "models.json", {
        "models": [{"id": "no-url"}],
        "availableModels": ["no-url"],
    }, secure=True)
    with pytest.raises(RuntimeError) as exc:
        _load(root)
    assert "url" in str(exc.value)


def test_load_project_plugins_explicit(tmp_path):
    """plugins 显式传入时跳过覆盖链（loader plugins 分支）。"""
    from minidsh.infrastructure.bundle import PluginRef

    ctx = load_project(
        _make_project(tmp_path),
        quiet=True,
        plugins=[PluginRef("minidsh.config"), PluginRef("minidsh.sessions")],
    )
    assert ctx.has("config")
    assert ctx.has("sessions")
    assert not ctx.has("agent_loop")


def test_load_project_extra_resolver(tmp_path):
    """extra_resolver 提供的第三方插件能被按名解析。"""
    import types

    mod = types.ModuleType("third_party_plugin")
    mod.name = "third-party"
    mod.inject = []
    mod.apply = lambda ctx: ctx.provide("third-party-marker", "ok")
    from minidsh.infrastructure.bundle import PluginRef

    ctx = load_project(
        _make_project(tmp_path),
        quiet=True,
        plugins=[
            PluginRef("minidsh.config"),
            PluginRef("minidsh.sessions"),
            PluginRef("third-party"),
        ],
        extra_resolver=lambda name: mod if name == "third-party" else None,
    )
    assert ctx.has("third-party-marker")


def test_parse_agent_md_without_frontmatter():
    from minidsh.packages.services.subagent.providers._helpers import _parse_agent_md

    assert _parse_agent_md("直接正文") is None  # 无 frontmatter → 返回 None（loader 用文件名兜底）


# ---------- 插件化装配：Fiber 真正接管 ----------


def test_load_project_produces_fibers(tmp_path):
    """装配后 ctx._fibers 非空：能力由 Fiber 驱动，而非写死构造函数调用。"""
    ctx = _load(_make_project(tmp_path))
    assert len(ctx._fibers) >= 5  # sessions/llm/systemPrompt/tools/loop/... 各自一个 fiber


def test_load_project_agent_loop_via_fiber(tmp_path):
    ctx = _load(_make_project(tmp_path))
    assert ctx.has("agent_loop")
    assert ctx.agent_loop is not None


def test_load_project_reload_agent_loop_on_session_replace(tmp_path):
    """变化即重载在真实装配里生效：替换 sessions 服务后 agent_loop fiber 重载。"""
    ctx = _load(_make_project(tmp_path))
    loop_before = ctx.agent_loop

    loop_before.create()  # 旧 store 上留一个会话
    ctx.provide("sessions", SessionStore(ctx))  # 触发 service/provide

    assert ctx.agent_loop is not None
    assert ctx.agent_loop is not loop_before
    assert len(ctx.agent_loop.agents) == 0