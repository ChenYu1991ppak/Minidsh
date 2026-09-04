"""profile：bundle 选择 + 直接覆盖（覆盖链）。

profile 文件可同时含三键：
    bundles:            # 选 bundle（覆盖：本层 bundles 整体替换「前面的 bundle 组合」中的非 base 部分）
    plugins:            # 直接覆盖（累加：同名替换、不同名追加）
    remove:             # 全局删

覆盖链（后覆盖前）：默认 [minidsh.base] < 命名 profile < 项目 < 用户 < argv。
``--profile``：文件存在 → 当路径（argv 覆盖）；否则 → 当命名 profile 名（~/.minidsh/profiles/<n>.yaml）。
"""
from __future__ import annotations

from pathlib import Path

from ...infrastructure.bundle import (
    PluginRef,
    merge_plugins,
    apply_removes,
    load_bundle,
    BUILTIN_BUNDLE_NAME,
)

__all__ = ["resolve_profile", "profile_path", "DEFAULT_BUNDLES"]

DEFAULT_BUNDLES = [BUILTIN_BUNDLE_NAME]


def profile_path(name: str, home: str | Path | None = None) -> Path:
    from ...infrastructure.config.files import user_config_dir

    base = Path(home) if home else user_config_dir()
    return base / "profiles" / f"{name}.yaml"


def _parse_profile_file(path: Path) -> dict:
    """读一个 profile 文件 → {bundles, plugins, remove}。缺失返回空 dict。"""
    if not path.is_file():
        return {}
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"profile 必须是 mapping：{path}")
    return data


def _read_plugins(data: dict) -> tuple[list[PluginRef], list[str]]:
    """从 profile 数据里单独解析 plugins/remove（复用 bundle 的 parse 逻辑）。"""
    raw = data.get("plugins") or []
    plugins: list[PluginRef] = []
    for item in raw:
        if isinstance(item, str):
            plugins.append(PluginRef(name=item))
        elif isinstance(item, dict):
            nm = item.get("name")
            cfg = item.get("config")
            plugins.append(PluginRef(name=nm, config=cfg if isinstance(cfg, dict) else None))
        else:
            raise ValueError(f"plugin 条目类型非法：{item!r}")
    removes = data.get("remove") or []
    return plugins, removes


def resolve_profile(
    profile: str | None = None,
    project_dir: str | Path | None = None,
    user_home: str | Path | None = None,
    argv_path: str | Path | None = None,
    extra_bundles: list[str] | None = None,
) -> list[PluginRef]:
    """解析覆盖链，返回最终 plugins 名单（累加 + remove 已应用）。

    覆盖链：
      1. 默认 bundles=[minidsh.base]
      2. 命名 profile（若 profile 给的是「名字」）
      3. 项目 <project>/.minidsh/profile.yaml
      4. 用户 ~/.minidsh/profile.yaml
      5. argv（--profile 给「路径」时，作为最高覆盖层）

    - bundles 覆盖：取「最后写 bundles 的那层」的非 base 部分 + [minidsh.base]。
    - plugins 累加：跨层同名替换、不同名追加。
    - remove 全局删。
    - ``extra_bundles``：额外 bundle 名，追加到 base 之后（如 ``tui-textual`` 前端 bundle）。
    """
    from ...infrastructure.config.files import user_config_dir

    layers: list[dict] = []
    # 命名 profile
    if profile is not None and not Path(profile).exists():
        layers.append(_parse_profile_file(profile_path(profile)))
    # 项目
    if project_dir is not None:
        layers.append(_parse_profile_file(Path(project_dir) / ".minidsh" / "profile.yaml"))
    # 用户
    home = Path(user_home) if user_home else user_config_dir()
    layers.append(_parse_profile_file(home / "profile.yaml"))
    # argv
    if argv_path is not None:
        layers.append(_parse_profile_file(Path(argv_path)))

    # bundles 覆盖：取最后写 bundles 的层
    bundles = DEFAULT_BUNDLES
    for layer in layers:
        if "bundles" in layer:
            bs = layer["bundles"]
            if isinstance(bs, list) and all(isinstance(b, str) for b in bs):
                bundles = [BUILTIN_BUNDLE_NAME] + [b for b in bs if b != BUILTIN_BUNDLE_NAME]

    # extra_bundles 追加到 base 之后（launcher 的 --profile <bundle> 落点）
    if extra_bundles:
        bundles = bundles + [b for b in extra_bundles if b not in bundles]

    # 展开 bundles 的 plugins（base + 选定 bundles，按序 merge）
    plugin_layers: list[list[PluginRef]] = []
    removes: list[str] = []
    for bname in bundles:
        bundle = load_bundle(bname)
        if bundle is not None:
            plugin_layers.append(bundle.plugins)
            removes.extend(bundle.remove)
        else:
            print(f"[minidsh] 警告：未知 bundle {bname!r}，跳过", file=__import__("sys").stderr)

    # 叠加各层 profile 的 plugins/remove
    for layer in layers:
        plugins, layer_removes = _read_plugins(layer)
        plugin_layers.append(plugins)
        removes.extend(layer_removes)

    merged = merge_plugins(plugin_layers)
    return apply_removes(merged, removes)