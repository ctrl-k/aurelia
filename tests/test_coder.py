"""Tests for the Docker-based CoderComponent."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock

from aurelia.components.coder import CoderComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import (
    ComponentSpec,
    ModelConfig,
    RuntimeState,
    SandboxConfig,
    Task,
    TaskStatus,
)
from aurelia.llm.client import MockLLMClient
from aurelia.sandbox.docker import ContainerResult, DockerClient
from aurelia.tools.registry import ToolRegistry


def _make_sandbox() -> SandboxConfig:
    return SandboxConfig(image="aurelia-coder:latest", network=True, timeout_s=60)


def _make_spec(sandbox: SandboxConfig | None = None) -> ComponentSpec:
    return ComponentSpec(
        id="coder",
        name="Coder",
        role="Write and modify code",
        model=ModelConfig(),
        tools=[],
        sandbox=sandbox or _make_sandbox(),
    )


def _make_task(worktree_path: str) -> Task:
    return Task(
        id="task-0001",
        thread_id="thread-0001",
        component="coder",
        branch="aurelia/cand-0001",
        instruction="Fix the bug in solution.py",
        status=TaskStatus.pending,
        context={
            "worktree_path": worktree_path,
            "problem_description": "Implement a square root function.",
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _mock_docker(
    image_exists: bool = True,
    container_result: ContainerResult | None = None,
) -> DockerClient:
    """Create a mock DockerClient."""
    docker = AsyncMock(spec=DockerClient)
    docker.check_available = AsyncMock()
    docker.image_exists = AsyncMock(return_value=image_exists)
    docker.build_image = AsyncMock()
    docker.run_container = AsyncMock(
        return_value=container_result or ContainerResult(exit_code=0, stdout="", stderr="")
    )
    return docker


def _stream_json_output(response: str = "I fixed the bug.", stats: dict | None = None) -> str:
    """Build a realistic stream-json JSONL output from Gemini CLI."""
    lines = [
        json.dumps({"type": "init", "session_id": "sess-1", "model": "gemini-2.5-pro"}),
        json.dumps({"type": "message", "role": "user", "content": "Fix the bug"}),
        json.dumps(
            {
                "type": "tool_use",
                "name": "read_file",
                "parameters": {"path": "/workspace/solution.py"},
            }
        ),
        json.dumps(
            {
                "type": "tool_result",
                "name": "read_file",
                "result": "def sqrt(n):\n    return n**0.5\n",
            }
        ),
        json.dumps({"type": "message", "role": "assistant", "content": response}),
        json.dumps(
            {
                "type": "result",
                "response": response,
                "stats": stats or {"models": {"total_tokens": 100}},
            }
        ),
    ]
    return "\n".join(lines)


class TestCoderSuccess:
    async def test_successful_execution(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        aurelia_dir = tmp_path / ".aurelia" / "logs" / "transcripts"
        aurelia_dir.mkdir(parents=True)

        stdout = _stream_json_output("Bug fixed successfully.")
        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=stdout, stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        registry = ToolRegistry()
        mock_llm = MockLLMClient()

        component = CoderComponent(
            spec=_make_spec(),
            llm_client=mock_llm,
            tool_registry=registry,
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        result = await component.execute(task)

        assert result.error is None
        assert result.summary == "Bug fixed successfully."
        assert len(result.artifacts) == 1
        assert result.artifacts[0].endswith("task-0001.jsonl")

        # Transcript file should exist
        transcript = Path(result.artifacts[0])
        assert transcript.exists()
        assert "Bug fixed successfully." in transcript.read_text()

        # System prompt file should have been cleaned up
        assert not (worktree / ".gemini_system.md").exists()

        # Docker was called correctly
        docker.run_container.assert_called_once()
        call_kwargs = docker.run_container.call_args.kwargs
        assert call_kwargs["image"] == "aurelia-coder:latest"
        assert call_kwargs["workdir"] == "/workspace"
        assert "GEMINI_SYSTEM_MD" in call_kwargs["env"]


class TestCoderContainerFailure:
    async def test_container_nonzero_exit(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=1, stdout="", stderr="API key not set")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        result = await component.execute(task)

        assert result.error is not None
        assert "exited with code 1" in result.error
        assert "API key not set" in result.error


class TestCoderTranscriptSaved:
    async def test_transcript_saved_to_disk(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        stdout = _stream_json_output()
        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=stdout, stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        result = await component.execute(task)

        transcript_path = Path(result.artifacts[0])
        assert transcript_path.exists()

        # Each line should be valid JSON
        for line in transcript_path.read_text().strip().splitlines():
            json.loads(line)  # should not raise


class TestCoderSystemPromptCleanup:
    async def test_system_prompt_cleaned_up_on_success(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        assert not (worktree / ".gemini_system.md").exists()

    async def test_system_prompt_cleaned_up_on_failure(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=1, stdout="", stderr="fail")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        assert not (worktree / ".gemini_system.md").exists()


class TestCoderLazyImageBuild:
    async def test_builds_image_when_missing(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            image_exists=False,
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr=""),
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        docker.build_image.assert_called_once()

        # Check events include image build
        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "coder.image_build.started" in event_types
        assert "coder.image_build.completed" in event_types

    async def test_skips_build_when_image_exists(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            image_exists=True,
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr=""),
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        docker.build_image.assert_not_called()


class TestCoderEventsEmitted:
    async def test_events_emitted_on_success(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]

        assert "coder.started" in event_types
        assert "coder.transcript" in event_types
        assert "coder.completed" in event_types

        # Verify transcript event data
        transcript_event = next(e for e in events if e.type == "coder.transcript")
        assert transcript_event.data["task_id"] == "task-0001"
        assert "transcript_path" in transcript_event.data
        assert "stats" in transcript_event.data


class TestCoderNoSandboxConfig:
    async def test_raises_without_sandbox(self, tmp_path):
        """CoderComponent should raise if spec has no SandboxConfig."""
        import pytest

        spec = ComponentSpec(id="coder", name="Coder", role="test", sandbox=None)

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=spec,
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
        )

        task = _make_task(str(tmp_path))
        with pytest.raises(RuntimeError, match="SandboxConfig"):
            await component.execute(task)


class TestParseTranscript:
    def test_parse_with_result_event(self):
        stdout = _stream_json_output("Done!", {"models": {"tokens": 50}})
        text, stats = CoderComponent._parse_transcript(stdout)
        assert text == "Done!"
        assert stats == {"models": {"tokens": 50}}

    def test_parse_with_no_result_falls_back_to_messages(self):
        lines = [
            json.dumps({"type": "message", "role": "assistant", "content": "first"}),
            json.dumps({"type": "message", "role": "assistant", "content": "second"}),
        ]
        text, stats = CoderComponent._parse_transcript("\n".join(lines))
        assert text == "second"
        assert stats == {}

    def test_parse_empty_output(self):
        text, stats = CoderComponent._parse_transcript("")
        assert text == ""
        assert stats == {}

    def test_parse_invalid_json_lines_skipped(self):
        lines = [
            "not json at all",
            json.dumps({"type": "result", "response": "ok", "stats": {}}),
        ]
        text, stats = CoderComponent._parse_transcript("\n".join(lines))
        assert text == "ok"


class TestCoderForwardsApiKeys:
    async def test_forwards_env_vars_to_container(self, tmp_path, monkeypatch):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")

        sandbox = SandboxConfig(
            image="aurelia-coder:latest",
            network=True,
            env_forward=["GEMINI_API_KEY", "MISSING_KEY"],
        )

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(sandbox),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        await component.execute(task)

        call_kwargs = docker.run_container.call_args.kwargs
        env = call_kwargs["env"]
        assert env["GEMINI_API_KEY"] == "test-key-123"
        assert env["GEMINI_SYSTEM_MD"] == "/workspace/.gemini_system.md"
        # MISSING_KEY should not be in env since it's not set on host
        assert "MISSING_KEY" not in env


class TestCoderFeedbackInPrompt:
    async def test_feedback_included_in_system_prompt(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (tmp_path / ".aurelia" / "logs" / "transcripts").mkdir(parents=True)

        docker = _mock_docker(
            container_result=ContainerResult(exit_code=0, stdout=_stream_json_output(), stderr="")
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_task(str(worktree))
        task.context["feedback"] = "### Attempt 1\n- Status: FAILED\n- Metrics: {}"
        task.context["attempt_number"] = 2

        # Call _build_system_prompt directly to inspect
        prompt = component._build_system_prompt(task)
        assert "attempt #2" in prompt.lower()
        assert "Attempt 1" in prompt
        assert "FAILED" in prompt

    async def test_first_attempt_message(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = CoderComponent(
            spec=_make_spec(),
            llm_client=MockLLMClient(),
            tool_registry=ToolRegistry(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
        )

        task = _make_task(str(worktree))
        # No feedback in context
        prompt = component._build_system_prompt(task)
        assert "first attempt" in prompt.lower()
