"""Tests for BaseComponent and its tool-use loop with MockLLMClient."""

from __future__ import annotations

import datetime

from google.genai import types

from aurelia.components.base import BaseComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import (
    ComponentSpec,
    RuntimeState,
    Task,
    TaskStatus,
    ToolRegistration,
)
from aurelia.llm.client import MockLLMClient
from aurelia.tools.registry import ToolRegistry


def _make_task(instruction: str = "Do something") -> Task:
    return Task(
        id="task-0001",
        thread_id="thread-0001",
        component="test",
        branch="main",
        instruction=instruction,
        status=TaskStatus.pending,
        context={},
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _text_content(text: str) -> types.Content:
    return types.Content(parts=[types.Part(text=text)], role="model")


def _fc_content(name: str, args: dict) -> types.Content:
    return types.Content(
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
        role="model",
    )


def _make_registry_with_tools() -> ToolRegistry:
    """Build a ToolRegistry with builtin tools registered synchronously.

    Works around the fact that ``register_builtin`` uses ``await`` on a
    synchronous ``list_tools()`` call in some MCP versions.
    """
    from aurelia.tools.builtin import mcp as builtin_mcp

    registry = ToolRegistry()
    tools = builtin_mcp._tool_manager.list_tools()
    for tool in tools:
        registration = ToolRegistration(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.parameters,
            requires_sandbox=False,
            handler="builtin",
        )
        registry._tools[tool.name] = registration
    return registry


class TestExecuteSimpleTextResponse:
    async def test_execute_simple_text_response(self, tmp_path):
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = _make_registry_with_tools()

        mock_llm = MockLLMClient(responses=[_text_content("Hello from the model")])
        spec = ComponentSpec(id="test", name="Test", role="test", tools=["read_file"])
        component = BaseComponent(spec, mock_llm, registry, event_log, id_gen)

        task = _make_task("Say hello")
        result = await component.execute(task)

        assert result.summary == "Hello from the model"
        assert result.id.startswith("result-")
        assert result.error is None


class TestToolUseSingleCall:
    async def test_tool_use_loop_single_tool_call(self, tmp_path):
        # Create a file the tool can read
        test_file = tmp_path / "test.txt"
        test_file.write_text("file contents here")

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = _make_registry_with_tools()

        # First response: function call, second response: text
        responses = [
            _fc_content("read_file", {"path": str(test_file)}),
            _text_content("I read the file successfully"),
        ]
        mock_llm = MockLLMClient(responses=responses)
        spec = ComponentSpec(id="test", name="Test", role="test", tools=["read_file"])
        component = BaseComponent(spec, mock_llm, registry, event_log, id_gen)

        task = _make_task("Read the file")
        result = await component.execute(task)

        assert result.summary == "I read the file successfully"
        assert len(mock_llm.calls) == 2


class TestToolUseMaxRounds:
    async def test_tool_use_loop_max_rounds(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = _make_registry_with_tools()

        # Always returns a function call — loop should exit after max_rounds
        mock_llm = MockLLMClient(
            responses=[_fc_content("read_file", {"path": str(test_file)})]
        )
        spec = ComponentSpec(id="test", name="Test", role="test", tools=["read_file"])
        component = BaseComponent(spec, mock_llm, registry, event_log, id_gen)

        task = _make_task("Loop forever")
        contents = component._build_contents(task)
        config = types.GenerateContentConfig(temperature=0.0)

        final = await component._tool_use_loop(task, contents, config, max_rounds=2)

        # Should have called LLM exactly 2 times (max_rounds=2)
        assert len(mock_llm.calls) == 2
        # Final content should still be a function call (loop exhausted)
        fc_parts = [p for p in (final.parts or []) if p.function_call]
        assert len(fc_parts) > 0


class TestToolErrorReturnsDict:
    async def test_tool_error_returns_error_dict(self, tmp_path):
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = _make_registry_with_tools()

        spec = ComponentSpec(id="test", name="Test", role="test", tools=["read_file"])
        component = BaseComponent(
            spec, None, registry, event_log, id_gen  # type: ignore[arg-type]
        )

        # Call a tool that doesn't exist — should return error dict, not raise
        result = await component._execute_tool("nonexistent_tool", {})
        assert "error" in result
        assert isinstance(result["error"], str)


class TestLLMEventsEmitted:
    async def test_llm_events_emitted(self, tmp_path):
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = _make_registry_with_tools()

        mock_llm = MockLLMClient(responses=[_text_content("done")])
        spec = ComponentSpec(id="test", name="Test", role="test", tools=["read_file"])
        component = BaseComponent(spec, mock_llm, registry, event_log, id_gen)

        task = _make_task("Test events")
        await component.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "llm.request" in event_types
        assert "llm.response" in event_types

        # Verify event data contains expected fields
        req_event = next(e for e in events if e.type == "llm.request")
        assert req_event.data["task_id"] == "task-0001"
        assert req_event.data["component"] == "test"

        resp_event = next(e for e in events if e.type == "llm.response")
        assert resp_event.data["task_id"] == "task-0001"
        assert "latency_ms" in resp_event.data
