"""M6 验收测试：settings seam（按 namespace 分层解析 + validate 拒绝写入）。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.settings import (
    SettingsService,
    SettingsRegisterOptions,
    deep_merge,
    validate_namespace,
)
from minidsh.packages.services.settings.providers.file import FileSettingsService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path / "minidsh-home"))
    ctx = Context()
    service = FileSettingsService(ctx, path=tmp_path / "settings.json")
    return ctx, service


# ---------- namespace 校验 ----------


def test_namespace_syntax():
    with pytest.raises(ValueError):
        validate_namespace("Bad-Name")
    validate_namespace("ok-name")


# ---------- 分层解析 ----------


def test_resolve_defaults_base_user_layers(svc):
    ctx, service = svc
    scope = service.register("app", {"a": 1, "b": 2},
                             options=SettingsRegisterOptions(base={"a": 10}))
    assert scope.get() == {"a": 10, "b": 2}   # base 覆盖默认，用户层无

    scope.update({"a": 99})
    assert scope.get() == {"a": 99, "b": 2}   # 用户层最高


def test_resolve_via_service(svc):
    ctx, service = svc
    service.register("app", {"x": 0})
    assert service.resolve("app") == {"x": 0}


def test_unregistered_namespace_raises(svc):
    ctx, service = svc
    with pytest.raises(KeyError):
        service.resolve("nope")


def test_duplicate_register_rejected(svc):
    ctx, service = svc
    service.register("app", {})
    with pytest.raises(KeyError):
        service.register("app", {})


# ---------- validate 拒绝写入 ----------


def test_validate_rejects_bad_write(svc):
    ctx, service = svc

    def validator(value):
        if value.get("storage") == "unknown":
            raise ValueError("storage 不支持")

    scope = service.register("storage", {"storage": "jsonl"},
                             options=SettingsRegisterOptions(validate=validator))
    with pytest.raises(ValueError):
        scope.update({"storage": "unknown"})
    # 拒绝后解析值不变
    assert scope.get() == {"storage": "jsonl"}


# ---------- update / replace / watch ----------


def test_replace_resets_to_defaults(svc):
    ctx, service = svc
    scope = service.register("app", {"a": 1, "b": 2})
    scope.update({"a": 100})
    assert scope.get()["a"] == 100
    scope.replace({})
    assert scope.get() == {"a": 1, "b": 2}   # 全部回到默认


def test_watch_fires_on_commit(svc):
    ctx, service = svc
    scope = service.register("app", {"n": 0})
    seen = []
    scope.watch(lambda nxt, prev: seen.append((nxt["n"], prev["n"])))
    scope.update({"n": 5})
    assert seen == [(5, 0)]


def test_watch_disposer_stops(svc):
    ctx, service = svc
    scope = service.register("app", {"n": 0})
    seen = []
    off = scope.watch(lambda nxt, prev: seen.append(nxt["n"]))
    off()
    scope.update({"n": 7})
    assert seen == []


def test_persisted_to_disk(svc):
    ctx, service = svc
    scope = service.register("app", {"v": 0})
    scope.update({"v": 42})
    # 重新读文档确认已落盘
    from minidsh.infrastructure.config.files import load_json
    assert load_json(service._path)["app"]["v"] == 42


# ---------- deep_merge 纯函数 ----------


def test_deep_merge_nested():
    assert deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 20}}) == {"a": {"x": 1, "y": 20}}


def test_deep_merge_scalar_overwrites():
    assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}