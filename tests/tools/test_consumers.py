"""CT4 验收测试：tool-bash / tool-read / tool-write / tool-edit / glob / grep / todo_write / ask_user_question consumer（经 provider 服务）。"""
from __future__ import annotations

from pydsh.cordis import Context
from pydsh.infrastructure.config import Config
from pydsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from pydsh.packages.tools import bash as tool_bash
from pydsh.packages.tools import read_file as tool_read
from pydsh.packages.tools import write_file as tool_write
from pydsh.packages.tools import edit_file as tool_edit
from pydsh.packages.tools import glob as tool_glob
from pydsh.packages.tools import grep as tool_grep
from pydsh.packages.tools import todo_write as tool_todo_write
from pydsh.packages.tools import ask_user_question as tool_ask_user
from tests.helpers.world import plug_execution_world


def _assemble(allowed=None, with_bash=True, with_read=True):
    """装配：config + tools(空运行时) + 执行世界(subprocess→shell→fs) + 需要的 consumer。"""
    ctx = Context()
    ctx.provide("config", Config(allowed_tools=allowed))
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    if with_bash:
        ctx.plugin(tool_bash)
    if with_read:
        ctx.plugin(tool_read)
    return ctx, tools


async def test_bash_consumer_registers_and_executes():
    ctx, tools = _assemble()
    assert tools.get("bash") is not None
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo hi"}))
    assert result.is_error is False
    assert "hi" in result.content


async def test_read_consumer_registers_and_executes(tmp_path):
    ctx, tools = _assemble()
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    result = await tools.execute(ToolExecution("c1", "read_file", {"path": str(f)}))
    assert result.content == "hello"


async def test_read_consumer_nonzero_stderr():
    ctx, tools = _assemble()
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo err >&2; exit 2"}))
    assert "[exit 2]" in result.content


async def test_whitelist_filters_bash():
    """白名单不含 bash → consumer 不注册 bash；但 read_file 仍注册。"""
    ctx, tools = _assemble(allowed=["read_file"])
    assert tools.get("bash") is None
    assert tools.get("read_file") is not None


async def test_whitelist_none_registers_all():
    ctx, tools = _assemble(allowed=None)
    assert tools.get("bash") is not None
    assert tools.get("read_file") is not None


# ---------- write_file consumer ----------


async def test_write_consumer_registers_and_executes(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_write)
    f = tmp_path / "out.txt"
    result = await tools.execute(ToolExecution("c1", "write_file",
                                {"file_path": str(f), "content": "hello"}))
    assert result.is_error is False
    assert "Wrote" in result.content
    assert f.read_text() == "hello"


# ---------- edit_file consumer ----------


async def test_edit_consumer_single_replace(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_edit)
    f = tmp_path / "out.txt"
    f.write_text("hello world")
    result = await tools.execute(ToolExecution("c1", "edit_file",
                                {"file_path": str(f), "old_string": "hello", "new_string": "hi"}))
    assert result.is_error is False
    assert f.read_text() == "hi world"


async def test_edit_consumer_replace_all(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_edit)
    f = tmp_path / "out.txt"
    f.write_text("hello hello world")
    result = await tools.execute(ToolExecution("c1", "edit_file",
                                {"file_path": str(f), "old_string": "hello",
                                 "new_string": "hi", "replace_all": True}))
    assert result.is_error is False
    assert f.read_text() == "hi hi world"


# ---------- glob consumer ----------


async def test_glob_consumer_finds_files(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_glob)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = await tools.execute(ToolExecution("c1", "glob",
                                {"pattern": "*.py", "path": str(tmp_path)}))
    assert result.is_error is False
    assert "a.py" in result.content
    assert "b.py" in result.content
    assert "c.txt" not in result.content


async def test_glob_consumer_no_match(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_glob)
    result = await tools.execute(ToolExecution("c1", "glob",
                                {"pattern": "*.xyz", "path": str(tmp_path)}))
    assert result.is_error is False
    assert "No files found" in result.content


# ---------- grep consumer ----------


async def test_grep_consumer_finds_matches(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_grep)
    f = tmp_path / "a.py"
    f.write_text("hello world\nfoo bar\nhello again")
    result = await tools.execute(ToolExecution("c1", "grep",
                                {"pattern": "hello", "path": str(tmp_path)}))
    assert result.is_error is False
    assert "hello" in result.content


async def test_grep_consumer_no_match(tmp_path):
    ctx, tools = _assemble()
    ctx.plugin(tool_grep)
    result = await tools.execute(ToolExecution("c1", "grep",
                                {"pattern": "xyz_nonexistent", "path": str(tmp_path)}))
    assert result.is_error is False
    assert "No matches found" in result.content


# ---------- todo_write consumer ----------


async def test_todo_write_consumer():
    ctx, tools = _assemble()
    ctx.plugin(tool_todo_write)
    # 模拟 session 上下文（tool 需要 _session_stack）
    ctx._session_stack = [type("FakeSession", (), {"append": lambda self, t, p: None})()]
    result = await tools.execute(ToolExecution("c1", "todo_write",
                                {"todos": [
                                    {"content": "task 1", "status": "pending"},
                                    {"content": "task 2", "status": "in_progress",
                                     "activeForm": "Doing task 2"},
                                    {"content": "task 3", "status": "completed"},
                                ]}))
    assert result.is_error is False
    assert "[ ] task 1" in result.content
    assert "[>] Doing task 2" in result.content
    assert "[x] task 3" in result.content


async def test_todo_write_writes_session_event():
    """todo_write 调用 append session 事件。"""
    ctx, tools = _assemble()
    ctx.plugin(tool_todo_write)
    events = []
    fake_session = type("FakeSession", (), {
        "append": lambda self, t, p: events.append((t, p)),
    })()
    ctx._session_stack = [fake_session]
    await tools.execute(ToolExecution("c1", "todo_write",
                     {"todos": [{"content": "do it", "status": "pending"}]}))
    assert len(events) == 1
    assert events[0][0] == "todo-update"
    assert events[0][1]["todos"][0]["content"] == "do it"


# ---------- ask_user_question consumer ----------


async def test_ask_user_question_consumer():
    ctx, tools = _assemble()
    ctx.plugin(tool_ask_user)
    ctx._session_stack = [type("FakeSession", (), {"append": lambda self, t, p: None})()]
    result = await tools.execute(ToolExecution("c1", "ask_user_question",
                                {"questions": [{
                                    "question": "What color?",
                                    "header": "Color",
                                    "options": [
                                        {"label": "Red", "description": "The color red"},
                                        {"label": "Blue", "description": "The color blue"},
                                    ],
                                    "multiSelect": False,
                                }]}))
    assert result.is_error is False
    assert "What color?" in result.content
    assert "Red" in result.content
    assert "Blue" in result.content


async def test_ask_user_question_writes_session_event():
    """ask_user_question 调用 append session 事件。"""
    ctx, tools = _assemble()
    ctx.plugin(tool_ask_user)
    events = []
    fake_session = type("FakeSession", (), {
        "append": lambda self, t, p: events.append((t, p)),
    })()
    ctx._session_stack = [fake_session]
    await tools.execute(ToolExecution("c1", "ask_user_question",
                     {"questions": [{"question": "Q?", "header": "H",
                                     "options": [{"label": "A", "description": "desc"}]}]}))
    assert len(events) == 1
    assert events[0][0] == "user-question"
    assert events[0][1]["questions"][0]["question"] == "Q?"


# ---------- whitelist（新工具） ----------


async def test_whitelist_filters_new_tools():
    """白名单不含新工具 → consumer 不注册；但 read_file 仍注册。"""
    ctx, tools = _assemble(allowed=["read_file"])
    ctx.plugin(tool_write)
    ctx.plugin(tool_edit)
    ctx.plugin(tool_glob)
    ctx.plugin(tool_grep)
    ctx.plugin(tool_todo_write)
    ctx.plugin(tool_ask_user)
    assert tools.get("write_file") is None
    assert tools.get("edit_file") is None
    assert tools.get("glob") is None
    assert tools.get("grep") is None
    assert tools.get("todo_write") is None
    assert tools.get("ask_user_question") is None
    assert tools.get("read_file") is not None