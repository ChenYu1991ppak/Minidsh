"""BT3 验收测试：ToolOutput/ToolDefinition 契约 + 轻量校验器。"""
from __future__ import annotations

import pytest

from minidsh.packages.services.tool_runtime import ToolOutput, ToolDefinition
from minidsh.packages.services.tool_runtime.validate import validate_schema, SchemaError


# ---------- 轻量校验器 ----------


def test_validate_string_ok():
    validate_schema("hello", {"type": "string"})


def test_validate_string_mismatch():
    with pytest.raises(SchemaError) as exc:
        validate_schema(42, {"type": "string"})
    assert "期望 type=string" in str(exc.value)
    assert "int" in str(exc.value)


def test_validate_integer_vs_boolean():
    # bool 是 int 子类，但不该算 integer
    with pytest.raises(SchemaError):
        validate_schema(True, {"type": "integer"})


def test_validate_object_properties_recursive():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    }
    validate_schema({"a": 1}, schema)
    with pytest.raises(SchemaError):
        validate_schema({"a": "x"}, schema)
    with pytest.raises(SchemaError) as exc:
        validate_schema({}, schema)
    assert "必需字段" in str(exc.value)


def test_validate_array_items():
    validate_schema([1, 2, 3], {"type": "array", "items": {"type": "integer"}})
    with pytest.raises(SchemaError):
        validate_schema([1, "x"], {"type": "array", "items": {"type": "integer"}})


def test_validate_unknown_type_loose():
    validate_schema(object(), {"type": "custom-unknown"})  # 未知类型不报


def test_type_alias_mapping():
    validate_schema(1, {"type": "int"})
    validate_schema("x", {"type": "str"})
    validate_schema([], {"type": "list"})
    validate_schema({}, {"type": "dict"})


# ---------- ToolOutput / ToolDefinition 契约 ----------


def test_tool_output_contract():
    out = ToolOutput(schema={"type": "string"}, render=lambda args, value: value)
    assert out.schema == {"type": "string"}
    assert out.render({}, "hi") == "hi"


def test_tool_definition_has_async_execute_and_output():
    async def handler(args):
        return f"got {args}"

    definition = ToolDefinition(
        name="echo",
        description="desc",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=handler,
        output=ToolOutput(schema={"type": "string"}, render=lambda a, v: v),
    )
    assert definition.name == "echo"
    # execute 是 async 可调用，返回 coroutine
    import inspect

    assert inspect.iscoroutinefunction(definition.execute)
    assert definition.output.schema == {"type": "string"}