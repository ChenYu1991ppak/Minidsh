"""profile：有序 bundle 组合（对齐官方 profile）。

profile 文件 ``~/.minidsh/profiles/<name>.yaml``，内容 ``bundles: [minidsh.base, ...]``。
默认（无 --profile）：``[minidsh.base]``。组合 = 依序把每个 bundle 的 manifest 作为一层，
用 ``merge_manifests`` 合并（后层 win per row）。
"""
from __future__ import annotations

from pathlib import Path

from ...infrastructure.bundle import Bundle, load_bundle, BUILTIN_BUNDLE_NAME
from ...infrastructure.manifest import ManifestEntry, merge_manifests, load_manifest_file

__all__ = ["resolve_profile_manifest", "profile_path", "DEFAULT_PROFILE_BUNDLES"]

DEFAULT_PROFILE_BUNDLES = [BUILTIN_BUNDLE_NAME]


def profile_path(name: str, home: str | Path | None = None) -> Path:
    """profile 文件路径：~/.minidsh/profiles/<name>.yaml。"""
    from ...infrastructure.config.files import user_config_dir

    base = Path(home) if home else user_config_dir()
    return base / "profiles" / f"{name}.yaml"


def resolve_profile_manifest(profile: str | None = None) -> list[ManifestEntry]:
    """解析 profile 得到「profile 层」的合并 manifest。

    - ``profile`` 为 None → 默认 bundles = [minidsh.base]。
    - 否则读 ~/.minidsh/profiles/<profile>.yaml 的 ``bundles:`` 列表。
    - 依序 load_bundle 每个名字，把各 bundle manifest 作为一层 merge（后层 win）。
    """
    bundles = DEFAULT_PROFILE_BUNDLES
    if profile is not None:
        entries, _removes = load_manifest_file(profile_path(profile))
        # profile 文件里 bundles: 是字符串列表，不是 manifest.yml 的 plugins 条目；
        # 需从原始 yaml 里单独读 bundles 键，而非复用 load_manifest_file 的 plugins 解析。
        names = _read_profile_bundles(profile_path(profile))
        if names:
            bundles = names

    layers: list[list[ManifestEntry]] = []
    for name in bundles:
        bundle = load_bundle(name)
        if bundle is not None:
            layers.append(bundle.manifest)
        else:
            # 未知 bundle：告警跳过（对齐「未知插件告警跳过」的容错语义）
            import sys
            print(f"[minidsh] 警告：profile 引用了未知 bundle {name!r}，跳过", file=sys.stderr)
    return merge_manifests(layers)


def _read_profile_bundles(path: Path) -> list[str]:
    """从 profile.yaml 读顶层 ``bundles:`` 键（字符串列表）。"""
    if not path.is_file():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    bundles = data.get("bundles", [])
    if not isinstance(bundles, list):
        return []
    return [b for b in bundles if isinstance(b, str)]