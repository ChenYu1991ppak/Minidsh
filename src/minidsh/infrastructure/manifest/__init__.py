"""manifest 模块：装配清单（替代 loader 硬编码）。"""
from __future__ import annotations

from .schema import ManifestEntry, parse_manifest, load_manifest, merge_manifests, load_manifest_file, apply_removes
from .build import build_context

__all__ = [
    "ManifestEntry",
    "parse_manifest",
    "load_manifest",
    "merge_manifests",
    "load_manifest_file",
    "apply_removes",
    "build_context",
]