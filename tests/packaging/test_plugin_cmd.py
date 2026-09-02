"""BT8 验收测试：minidsh plugin add/remove/ls 命令。"""
from __future__ import annotations

import subprocess
import types

import pytest

from minidsh.infrastructure.packaging.plugin_cmd import plugin_add, plugin_remove, plugin_list, USER_PROFILE, _write_user_plugins
from minidsh.infrastructure.config.files import user_config_dir


class _OK:
    returncode = 0
    stderr = ""


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path / "home"))
    yield user_config_dir()


def _fake_discover(monkeypatch, names):
    """替换 discover_plugins，返回 {name → 归一化 Plugin}。"""
    plugins = {}
    for n in names:
        mod = types.ModuleType(n)
        mod.name = n
        mod.apply = lambda ctx: None
        plugins[n] = mod
    import minidsh.infrastructure.packaging.plugin_cmd as pc
    monkeypatch.setattr(pc, "discover_plugins", lambda: plugins)


def test_add_writes_new_names_to_manifest(monkeypatch, isolated_home):
    _fake_discover(monkeypatch, ["my-plugin", "other-plugin"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _OK())
    code = plugin_add("./some-pkg")
    assert code == 0
    txt = USER_PROFILE.read_text(encoding="utf-8")
    assert "my-plugin" in txt
    assert "other-plugin" in txt


def test_add_no_new_plugins_message(monkeypatch, isolated_home, capsys):
    _fake_discover(monkeypatch, ["already"])
    from minidsh.infrastructure.packaging.plugin_cmd import _write_user_plugins
    _write_user_plugins(["already"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _OK())
    code = plugin_add("./pkg")
    assert code == 0
    assert "未发现新的" in capsys.readouterr().out


def test_remove_existing(monkeypatch, isolated_home, capsys):
    from minidsh.infrastructure.packaging.plugin_cmd import _write_user_plugins
    _write_user_plugins(["a", "b"])
    assert plugin_remove("a") == 0
    assert "a" not in USER_PROFILE.read_text(encoding="utf-8")
    assert "b" in USER_PROFILE.read_text(encoding="utf-8")


def test_remove_missing(monkeypatch, isolated_home, capsys):
    from minidsh.infrastructure.packaging.plugin_cmd import _write_user_plugins
    _write_user_plugins(["a"])
    assert plugin_remove("ghost") == 1
    assert "不在用户 profile" in capsys.readouterr().err


def test_list_marks_active(monkeypatch, isolated_home, capsys):
    from minidsh.infrastructure.packaging.plugin_cmd import _write_user_plugins
    _write_user_plugins(["active-one"])
    _fake_discover(monkeypatch, ["active-one", "inactive-two"])
    assert plugin_list() == 0
    out = capsys.readouterr().out
    assert "active-one" in out and "已激活" in out
    assert "inactive-two" in out and "未声明" in out