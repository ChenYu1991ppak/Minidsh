"""Phase F 验收测试：bundle（一等概念）+ profile（覆盖链）。"""
from __future__ import annotations

import pytest

from minidsh.infrastructure.bundle import Bundle, load_bundle, BUILTIN_BUNDLE_NAME, PluginRef
from minidsh.infrastructure.profile import resolve_profile, profile_path


# ---------- bundle ----------


def test_load_builtin_base_bundle():
    bundle = load_bundle(BUILTIN_BUNDLE_NAME)
    assert bundle is not None
    assert bundle.name == "minidsh.base"
    assert len(bundle.plugins) == 23  # 内置 base 有 23 个插件
    names = [r.name for r in bundle.plugins]
    assert names[0] == "minidsh.config"
    assert "minidsh.persistence-jsonl" in names
    assert "minidsh.tool-bash" in names
    assert "minidsh.subprocess" in names


def test_load_unknown_bundle_returns_none():
    assert load_bundle("nope") is None


def test_bundle_is_frozen_entity():
    b = Bundle(name="x", plugins=[PluginRef("a")])
    assert b.name == "x"
    assert b.plugins == [PluginRef("a")]


# ---------- profile ----------


def test_default_profile_is_base():
    merged = resolve_profile(None)
    assert len(merged) == 23
    assert merged[0].name == "minidsh.config"


def test_profile_path_location(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    p = profile_path("demo")
    assert p == tmp_path / "profiles" / "demo.yaml"


def test_custom_profile_with_base_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "demo.yaml").write_text(
        "bundles:\n  - minidsh.base\n", encoding="utf-8"
    )
    merged = resolve_profile(profile="demo")
    assert len(merged) == 23


def test_custom_profile_unknown_bundle_warns_and_continues(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "demo.yaml").write_text(
        "bundles:\n  - minidsh.base\n  - ghost-bundle\n", encoding="utf-8"
    )
    merged = resolve_profile(profile="demo")
    assert len(merged) == 23
    assert "ghost-bundle" in capsys.readouterr().err


def test_missing_profile_returns_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    merged = resolve_profile(profile="nonexistent")
    assert len(merged) == 23


def test_profile_plugins_accumulate(tmp_path, monkeypatch):
    """profile 自己写 plugins → 追加到 base（累加语义，非覆盖）。"""
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    (tmp_path / "profile.yaml").write_text(
        "plugins:\n  - my-extra\n", encoding="utf-8"
    )
    merged = resolve_profile(None)
    names = [r.name for r in merged]
    assert len(merged) == 24  # 23 + my-extra
    assert names[-1] == "my-extra"


# ---------- loader 统一路径（无 _bundles 特殊 import） ----------


def test_loader_uses_profile_not_bundles_import():
    import minidsh.infrastructure.boot.loader as loader

    src = open(loader.__file__, encoding="utf-8").read()
    assert "_bundles" not in src
    assert "resolve_profile" in src
    entries = loader._profile_plugins(None, None, None, quiet=False)
    assert len(entries) == 23


def test_loader_quiet_removes_trace_render():
    import minidsh.infrastructure.boot.loader as loader

    entries = loader._profile_plugins(None, None, None, quiet=True)
    names = [r.name for r in entries]
    assert "minidsh.trace-render" not in names
    assert len(entries) == 22