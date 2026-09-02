"""BT7 验收测试：entry-point 发现 + resolver。"""
from __future__ import annotations

import types

import pytest

from minidsh.infrastructure.packaging import discover_plugins, entry_point_resolver
from minidsh.infrastructure.packaging.discover import _load_entry_point


class _FakeEntryPoint:
    def __init__(self, name, value):
        self.name = name
        self.value = value


def test_load_entry_point_imports_module(monkeypatch):
    called = {}

    def fake_import(name):
        called["name"] = name
        mod = types.ModuleType(name)
        mod.name = "imported-plugin"
        mod.inject = ["tools"]
        mod.apply = lambda ctx: None
        return mod

    monkeypatch.setattr("minidsh.infrastructure.packaging.discover.importlib.import_module", fake_import)
    plugin = _load_entry_point(_FakeEntryPoint("my-plugin", "my_pkg.mod"))
    assert plugin.name == "imported-plugin"
    assert plugin.inject == ["tools"]
    assert called["name"] == "my_pkg.mod"


def test_load_entry_point_import_failure_returns_none(monkeypatch):
    def boom(name):
        raise ImportError(name)

    monkeypatch.setattr("minidsh.infrastructure.packaging.discover.importlib.import_module", boom)
    assert _load_entry_point(_FakeEntryPoint("x", "missing.mod")) is None


def test_discover_plugins_enumerates_group(monkeypatch):
    eps = [
        _FakeEntryPoint("plugin-a", "pkg.a"),
        _FakeEntryPoint("plugin-b", "pkg.b"),
    ]

    def fake_import(name):
        mod = types.ModuleType(name)
        mod.name = "ep-" + name.rsplit(".", 1)[-1]
        mod.apply = lambda ctx: None
        return mod

    import minidsh.infrastructure.packaging.discover as d

    monkeypatch.setattr("minidsh.infrastructure.packaging.discover.importlib.import_module", fake_import)
    monkeypatch.setattr(d, "_metadata", types.SimpleNamespace(entry_points=lambda group=None: eps))
    found = discover_plugins()
    assert set(found) == {"plugin-a", "plugin-b"}
    assert found["plugin-a"].name == "ep-a"


def test_resolver_returns_plugin_and_caches():
    calls = {"n": 0}

    def fake_discover():
        calls["n"] += 1
        mod = types.ModuleType("x")
        mod.name = "cached"
        mod.apply = lambda ctx: None
        return {"known": mod}

    import minidsh.infrastructure.packaging.discover as d

    original = d.discover_plugins
    d.discover_plugins = fake_discover
    try:
        resolver = entry_point_resolver()
        assert resolver("known").name == "cached"
        assert resolver("ghost") is None
        assert calls["n"] == 1  # 只发现一次（缓存）
    finally:
        d.discover_plugins = original