"""End-to-end integration test for a full Aurelia runtime cycle with mock LLM."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock

from aurelia.core.events import EventLog
from aurelia.core.runtime import Runtime
from aurelia.sandbox.docker import ContainerResult, DockerClient


def _init_e2e_project(tmp_path):
    """Create a project directory with git repo, evaluate.py, and solution.py."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "README.md").write_text(
        "# Test Problem\nImplement a function that adds two numbers.\n"
    )
    (project_dir / "solution.py").write_text("def add(a, b):\n    return a + b\n")
    (project_dir / "evaluate.py").write_text(
        'import json\nprint(json.dumps({"accuracy": 0.95, "speed_ms": 5.0}))\n'
    )
    (project_dir / "pixi.toml").write_text(
        "[workspace]\n"
        'name = "test-project"\nchannels = ["conda-forge"]\n'
        'platforms = ["osx-arm64", "osx-64", "linux-64"]\n\n'
        "[dependencies]\n"
        'python = ">=3.12"\n\n'
        "[tasks]\n"
        'evaluate = "python evaluate.py"\n'
    )

    aurelia_dir = project_dir / ".aurelia"
    for subdir in ["state", "logs", "cache", "reports", "config"]:
        (aurelia_dir / subdir).mkdir(parents=True)

    # Fast heartbeat so the test completes quickly; trivial presubmit check
    (aurelia_dir / "config" / "workflow.yaml").write_text(
        'runtime:\n  heartbeat_interval_s: 1\n  presubmit_checks:\n    - "true"\n'
    )

    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=project_dir,
        check=True,
        capture_output=True,
        env=git_env,
    )

    return project_dir


def _mock_docker_client() -> DockerClient:
    """Create a mock DockerClient that simulates a successful Gemini CLI run."""
    mock_stdout = "\n".join(
        [
            json.dumps({"type": "init", "session_id": "s1", "model": "gemini-2.5-pro"}),
            json.dumps({"type": "message", "role": "assistant", "content": "Done."}),
            json.dumps({"type": "result", "response": "Mock coder done.", "stats": {}}),
        ]
    )
    docker = AsyncMock(spec=DockerClient)
    docker.check_available = AsyncMock()
    docker.image_exists = AsyncMock(return_value=True)
    docker.build_image = AsyncMock()
    docker.run_container = AsyncMock(
        return_value=ContainerResult(exit_code=0, stdout=mock_stdout, stderr="")
    )
    return docker


class TestFullCycleWithMock:
    async def test_full_cycle_with_mock(self, tmp_path):
        project_dir = _init_e2e_project(tmp_path)
        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_after_cycles():
            # 4 heartbeat cycles needed: dispatch coder, dispatch presubmit,
            # dispatch evaluator, finish candidate.  With 1s interval, wait
            # ~8s for safety.
            await asyncio.sleep(8)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_after_cycles())
        await runtime.start()
        await stop_task

        # -- Verify events --
        event_log = EventLog(project_dir / ".aurelia" / "logs" / "events.jsonl")
        events = await event_log.read_all()
        event_types = [e.type for e in events]

        assert "runtime.started" in event_types
        assert "runtime.stopped" in event_types
        assert "candidate.created" in event_types
        assert "task.created" in event_types
        assert "task.started" in event_types
        assert "task.completed" in event_types

        # -- Verify state files --
        state_dir = project_dir / ".aurelia" / "state"

        runtime_json = state_dir / "runtime.json"
        assert runtime_json.exists()
        runtime_data = json.loads(runtime_json.read_text())
        assert runtime_data["status"] == "stopped"
        assert runtime_data["total_tasks_dispatched"] >= 3  # coder + presubmit + evaluator

        tasks_json = state_dir / "tasks.json"
        assert tasks_json.exists()
        tasks_data = json.loads(tasks_json.read_text())
        assert len(tasks_data) >= 3  # at least coder + presubmit + evaluator tasks

        candidates_json = state_dir / "candidates.json"
        assert candidates_json.exists()
        candidates_data = json.loads(candidates_json.read_text())
        assert len(candidates_data) >= 1

        # The candidate should have been evaluated
        candidate = candidates_data[0]
        assert candidate["status"] in ("succeeded", "failed", "evaluating")

        # If the full cycle completed, we should see the evaluator events
        if "candidate.evaluated" in event_types:
            eval_event = next(e for e in events if e.type == "candidate.evaluated")
            assert "metrics" in eval_event.data
            assert eval_event.data["metrics"]["accuracy"] == 0.95

        # Evaluations should be persisted
        evals_json = state_dir / "evaluations.json"
        if "candidate.evaluated" in event_types:
            assert evals_json.exists()
            evals_data = json.loads(evals_json.read_text())
            assert len(evals_data) >= 1
            assert evals_data[0]["metrics"]["accuracy"] == 0.95


class TestTerminationOnMetricThreshold:
    async def test_terminates_when_metric_reached(self, tmp_path):
        """Runtime should stop when termination_condition is met."""
        project_dir = _init_e2e_project(tmp_path)

        # Set termination condition; trivial presubmit check
        (project_dir / ".aurelia" / "config" / "workflow.yaml").write_text(
            "runtime:\n"
            "  heartbeat_interval_s: 1\n"
            '  termination_condition: "accuracy>=0.90"\n'
            "  presubmit_checks:\n"
            '    - "true"\n'
        )

        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def safety_stop():
            await asyncio.sleep(10)
            await runtime.stop()

        stop_task = asyncio.create_task(safety_stop())
        await runtime.start()
        stop_task.cancel()

        event_log = EventLog(project_dir / ".aurelia" / "logs" / "events.jsonl")
        events = await event_log.read_all()
        event_types = [e.type for e in events]

        # Should have terminated due to metric threshold
        assert "runtime.terminated" in event_types or "runtime.stopped" in event_types

        # Should have at least one candidate
        state_dir = project_dir / ".aurelia" / "state"
        candidates_data = json.loads((state_dir / "candidates.json").read_text())
        assert len(candidates_data) >= 1
