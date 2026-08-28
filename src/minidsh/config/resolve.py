"""配置合并：models.json（模型，含 apiKey）+ settings.json（harness）。

对齐 CodeBuddy 的 models.json 结构：
    {
      "models": [ {"id","name","vendor","url","apiKey","supportsToolCall",...}, ... ],
      "availableModels": ["id1","id2",...],
      "currentModel": "id1"      // 可选；缺省取 availableModels 首位
    }

harness 设置独立在 settings.json：
    {
      "storage": "jsonl",
      "compaction": {"contextWindow": 8000, "thresholdRatio": 0.8},
      "tools": {"allow": ["read_file","bash"]}
    }

优先级：项目级（<project>/.minidsh/models.json）覆盖用户级（~/.minidsh/models.json）。
模型列表**拼接**（同名 id 项目级赢），settings 按键**项目级覆盖用户级**。

无 provider 抽象：每个模型自带 vendor/url/apiKey。当前模型由 currentModel / availableModels 定位。
"""
from __future__ import annotations

from pathlib import Path

from .config import Config, ModelSpec
from .files import user_models_path, user_settings_path, project_dir, load_json

__all__ = ["resolve_config"]


def resolve_config(project_dir_path: str | Path | None = None) -> Config:
    cfg = Config()

    # 第 3 层：用户级
    user_models = load_json(user_models_path())
    user_settings = load_json(user_settings_path())
    _merge_models(cfg, user_models)
    _merge_settings(cfg, user_settings)

    # 第 2 层：项目级（覆盖用户级）
    if project_dir_path is not None:
        pdir = project_dir(project_dir_path)
        proj_models = load_json(pdir / "models.json")
        proj_settings = load_json(pdir / "settings.json")
        _merge_models(cfg, proj_models, override=True)
        _merge_settings(cfg, proj_settings)

    return cfg


def _merge_models(cfg: Config, data: dict, override: bool = False) -> None:
    """合并模型列表：拼接（override=True 时同 id 覆盖），更新 availableModels/currentModel。"""
    if not data:
        return
    raw_models = data.get("models", [])
    incoming: dict[str, ModelSpec] = {}
    for item in raw_models:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        spec = ModelSpec(
            id=item["id"],
            name=item.get("name", ""),
            vendor=item.get("vendor", ""),
            url=item.get("url", ""),
            api_key=item.get("apiKey", ""),
            supports_tool_call=item.get("supportsToolCall", True),
            supports_reasoning=item.get("supportsReasoning", False),
            supports_images=item.get("supportsImages", False),
            temperature=item.get("temperature"),
        )
        incoming[spec.id] = spec

    if override:
        # 同 id 覆盖；不存在则追加
        idx = {m.id: i for i, m in enumerate(cfg.models)}
        for mid, spec in incoming.items():
            if mid in idx:
                cfg.models[idx[mid]] = spec
            else:
                cfg.models.append(spec)
    else:
        existing = {m.id for m in cfg.models}
        for spec in incoming.values():
            if spec.id not in existing:
                cfg.models.append(spec)

    if data.get("availableModels"):
        cfg.available_models = list(data["availableModels"])
    if data.get("currentModel"):
        cfg.current_model = data["currentModel"]


def _merge_settings(cfg: Config, data: dict) -> None:
    """合并 harness 设置：storage / compaction / tools。存在即覆盖。"""
    if not data:
        return
    if "storage" in data and data["storage"]:
        cfg.storage = data["storage"]
    comp = data.get("compaction", {})
    if isinstance(comp, dict):
        if "contextWindow" in comp:
            cfg.context_window = int(comp["contextWindow"])
        if "thresholdRatio" in comp:
            cfg.compaction_threshold_ratio = float(comp["thresholdRatio"])
    tools = data.get("tools", {})
    if isinstance(tools, dict) and isinstance(tools.get("allow"), list):
        cfg.allowed_tools = [str(x) for x in tools["allow"]]