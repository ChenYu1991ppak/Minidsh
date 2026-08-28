"""轻量 JSON Schema 校验器：只支持 ``type`` 与最小 ``properties``/``required`` 子集。

用途：校验工具 ``execute`` 返回的规范值是否符合 ``output.schema`` 声明（SPEC-tool-def
§2.2）。**标准库手写，不引入 jsonschema**。

支持的类型：string / number / integer / boolean / object / array / null。
object 支持 ```properties```（递归）与 ``required``（数组）；array 支持 ``items``（可选）。
"""
from __future__ import annotations

from typing import Any

__all__ = ["validate_schema", "SchemaError"]

_TYPE_ALIASES = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "str": "string",
    "list": "array",
    "dict": "object",
    "none": "null",
}


class SchemaError(ValueError):
    """规范值不符合 output.schema。"""


def _check_type(value: Any, expected: str) -> bool:
    expected = _TYPE_ALIASES.get(expected, expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return True  # 未知类型：不报（放宽，避免自定义类型误伤）


def validate_schema(value: Any, schema: dict, path: str = "$") -> None:
    """校验 ``value`` 是否符合 ``schema``；不符合抛 ``SchemaError``（带路径）。

    仅执行 schema 里出现且被支持的约束；不认得的约束键忽略（向前兼容）。
    """
    if not isinstance(schema, dict):
        return
    expected = schema.get("type")
    if expected is not None:
        expected = _TYPE_ALIASES.get(expected, expected)
        if not _check_type(value, expected):
            got = type(value).__name__
            raise SchemaError(f"{path}: 期望 type={expected}，实际 {got}")

    if _check_type(value, "object") and "properties" in schema:
        props = schema["properties"]
        if isinstance(props, dict):
            for key, subschema in props.items():
                if key in value:
                    validate_schema(value[key], subschema, f"{path}.{key}")
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    raise SchemaError(f"{path}: 缺少必需字段 {key!r}")

    if _check_type(value, "array") and "items" in schema:
        items = schema["items"]
        if isinstance(items, dict):
            for i, item in enumerate(value):
                validate_schema(item, items, f"{path}[{i}]")