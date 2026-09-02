"""pytest 全局隔离：默认把 MINIDSH_HOME 指向临时目录。

真实用户 ~/.minidsh 里可能有 apikey / 模型配置（运行时会用），若测试读它会
污染断言。故默认隔离；个别需要「测试用户级配置」的用例自行 monkeypatch 覆盖。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_minidsh_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path / "minidsh-home"))
    yield