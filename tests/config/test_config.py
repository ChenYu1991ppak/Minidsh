"""config 配置链测试：models.json（模型）+ settings.json（harness），项目覆盖用户。"""
from __future__ import annotations

import pytest

from minidsh.infrastructure.config import Config, ModelSpec, resolve_config
from minidsh.infrastructure.config.config import _validate_effort
from minidsh.infrastructure.config.files import load_json, save_json, user_models_path, user_settings_path, project_dir


# ---------- 默认值 ----------


def test_defaults_empty():
    cfg = resolve_config()
    assert cfg.models == []
    assert cfg.available_models == []
    assert cfg.current_model is None
    assert cfg.storage == "jsonl"
    assert cfg.allowed_tools is None


# ---------- 模型解析与当前模型定位 ----------


def _write_user(models=None, settings=None, tmp_path=None, monkeypatch=None):
    if tmp_path is not None:
        monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    if models is not None:
        save_json(user_models_path(), models, secure=True)
    if settings is not None:
        save_json(user_settings_path(), settings)


def test_parse_models_from_user(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "m1", "name": "M1", "vendor": "V", "url": "https://x", "apiKey": "k1"}],
        "availableModels": ["m1"],
        "currentModel": "m1",
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    cfg = resolve_config()
    assert len(cfg.models) == 1
    assert cfg.models[0].id == "m1"
    assert cfg.current_model_id == "m1"
    assert cfg.current.id == "m1"
    assert cfg.current.api_key == "k1"


def test_current_model_falls_back_to_first_available(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "a", "url": "u"}, {"id": "b", "url": "u"}],
        "availableModels": ["b", "a"],
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    # 无 currentModel → 取 availableModels 首位 "b"
    assert resolve_config().current_model_id == "b"


def test_current_model_prefers_currentModel_field(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "a", "url": "u"}, {"id": "b", "url": "u"}],
        "availableModels": ["a"],
        "currentModel": "b",
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert resolve_config().current_model_id == "b"


# ---------- settings 解析 ----------


def test_parse_settings(tmp_path, monkeypatch):
    _write_user(settings={
        "storage": "sqlite",
        "compaction": {"contextWindow": 2000, "thresholdRatio": 0.4},
        "tools": {"allow": ["read_file"]},
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    cfg = resolve_config()
    assert cfg.storage == "sqlite"
    assert cfg.context_window == 2000
    assert cfg.compaction_threshold_ratio == 0.4
    assert cfg.allowed_tools == ["read_file"]


# ---------- 项目覆盖用户 + 拼接 ----------


def test_project_merges_models_with_override(tmp_path, monkeypatch):
    """模型拼接：同 id 项目级覆盖；项目只出现过的模型追加。"""
    user_home = tmp_path / "home"
    monkeypatch.setenv("MINIDSH_HOME", str(user_home))
    _write_user(models={
        "models": [
            {"id": "shared", "url": "user-url", "apiKey": "user-key"},
            {"id": "only-user", "url": "u2"},
        ],
        "availableModels": ["shared"],
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    proj = tmp_path / "proj"
    proj.mkdir()
    save_json(project_dir(proj) / "models.json", {
        "models": [
            {"id": "shared", "url": "proj-url", "apiKey": "proj-key"},
            {"id": "only-proj", "url": "p2"},
        ],
        "currentModel": "only-proj",
    }, secure=True)

    cfg = resolve_config(proj)
    ids = {m.id for m in cfg.models}
    assert ids == {"shared", "only-user", "only-proj"}
    # 同 id 覆盖：shared 的 url/apiKey 来自项目级
    assert cfg.find("shared").url == "proj-url"
    assert cfg.find("shared").api_key == "proj-key"
    assert cfg.find("only-user").url == "u2"
    assert cfg.current_model_id == "only-proj"


def test_project_settings_override(tmp_path, monkeypatch):
    user_home = tmp_path / "home"
    monkeypatch.setenv("MINIDSH_HOME", str(user_home))
    _write_user(settings={"storage": "jsonl"}, tmp_path=tmp_path, monkeypatch=monkeypatch)

    proj = tmp_path / "proj"
    proj.mkdir()
    save_json(project_dir(proj) / "settings.json", {"storage": "sqlite"})

    assert resolve_config(proj).storage == "sqlite"


def test_missing_files_return_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    cfg = resolve_config(tmp_path / "nonexistent")
    assert cfg.models == []
    assert cfg.storage == "jsonl"


# ---------- 思考强度（M1） ----------


def test_reasoning_effort_parsed(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "m", "url": "u", "reasoningEffort": "high"}],
        "availableModels": ["m"],
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert resolve_config().current.reasoning_effort == "high"


def test_reasoning_effort_defaults_to_medium(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "m", "url": "u"}],
        "availableModels": ["m"],
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert resolve_config().current.reasoning_effort == "medium"


def test_reasoning_effort_invalid_rejected(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _validate_effort("ultra")
    # 五档全合法
    for level in ("off", "minimal", "low", "medium", "high"):
        assert _validate_effort(level) == level


def test_temperature_parsed(tmp_path, monkeypatch):
    _write_user(models={
        "models": [{"id": "m", "url": "u", "temperature": 0.7}],
        "availableModels": ["m"],
    }, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert resolve_config().current.temperature == 0.7


# ---------- 文件读写 ----------


def test_save_and_load_models_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    path = save_json(user_models_path(), {"models": [{"id": "m", "apiKey": "k"}]}, secure=True)
    assert path.is_file()
    loaded = load_json(path)
    assert loaded["models"][0]["apiKey"] == "k"