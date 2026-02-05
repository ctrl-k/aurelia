"""Tests for the PlannerComponent."""

from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock

from aurelia.components.planner import PlannerComponent
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
from aurelia.sandbox.docker import ContainerResult, DockerClient


def _make_planner_spec() -> ComponentSpec:
    return ComponentSpec(
        id="planner",
        name="Planner",
        role="Generate improvement plan",
        model=ModelConfig(),
        sandbox=SandboxConfig(
            image="test-image:latest",
            timeout_s=60,
            env_forward=["GEMINI_API_KEY"],
        ),
    )


def _make_planner_task(
    worktree_path: str,
    planning_context: dict | None = None,
) -> Task:
    return Task(
        id="task-0001",
        thread_id="thread-0001",
        component="planner",
        branch="__planner__",
        instruction="Generate improvement plan",
        status=TaskStatus.pending,
        context={
            "worktree_path": worktree_path,
            "planning_context": planning_context or {},
            "problem_description": "Test problem description",
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _mock_docker_client(
    plan_json: str | None = None,
    exit_code: int = 0,
) -> DockerClient:
    stdout = json.dumps({"type": "result", "response": "Done"})
    docker = AsyncMock(spec=DockerClient)
    docker.check_available = AsyncMock()
    docker.image_exists = AsyncMock(return_value=True)
    docker.build_image = AsyncMock()

    async def mock_run_container(**kwargs):
        # If plan_json provided, write it to the worktree
        if plan_json is not None:
            mounts = kwargs.get("mounts", [])
            if mounts:
                worktree_path = mounts[0][0]
                import pathlib

                (pathlib.Path(worktree_path) / "plan.json").write_text(plan_json)
        return ContainerResult(exit_code=exit_code, stdout=stdout, stderr="")

    docker.run_container = mock_run_container
    return docker


class TestPlannerWritesContextAndReadsPlan:
    async def test_writes_context_and_reads_plan(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        plan_content = {
            "summary": "Improve accuracy",
            "items": [
                {
                    "id": "plan-0001",
                    "description": "Tune parameters",
                    "instruction": "Adjust learning rate",
                },
            ],
        }

        docker = _mock_docker_client(plan_json=json.dumps(plan_content))
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())

        component = PlannerComponent(
            spec=_make_planner_spec(),
            llm_client=AsyncMock(),
            tool_registry=AsyncMock(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_planner_task(
            str(worktree),
            planning_context={"evaluation_history": []},
        )
        result = await component.execute(task)

        assert result.error is None
        assert "plan-0001" in result.summary or "Improve accuracy" in result.summary


class TestPlannerHandlesInvalidPlanJson:
    async def test_handles_invalid_plan_json(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        # No plan.json written
        docker = _mock_docker_client(plan_json=None)
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())

        component = PlannerComponent(
            spec=_make_planner_spec(),
            llm_client=AsyncMock(),
            tool_registry=AsyncMock(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_planner_task(str(worktree))
        result = await component.execute(task)

        assert result.error is not None
        assert "plan.json" in result.error.lower()


class TestPlannerEventsEmitted:
    async def test_events_emitted(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        plan_content = {"summary": "Plan", "items": []}
        docker = _mock_docker_client(plan_json=json.dumps(plan_content))
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())

        component = PlannerComponent(
            spec=_make_planner_spec(),
            llm_client=AsyncMock(),
            tool_registry=AsyncMock(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_planner_task(str(worktree))
        await component.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]

        assert "planner.started" in event_types
        assert "planner.completed" in event_types


class TestPlannerHandlesGeminiCliFailure:
    async def test_handles_gemini_cli_failure(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        docker = _mock_docker_client(plan_json=None, exit_code=1)
        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())

        component = PlannerComponent(
            spec=_make_planner_spec(),
            llm_client=AsyncMock(),
            tool_registry=AsyncMock(),
            event_log=event_log,
            id_generator=id_gen,
            project_dir=tmp_path,
            docker_client=docker,
        )

        task = _make_planner_task(str(worktree))
        result = await component.execute(task)

        assert result.error is not None
        assert "exit" in result.error.lower() or "Planner" in result.error

        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "planner.failed" in event_types
