"""Tests for the Runtime class."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock

from aurelia.core.events import EventLog
from aurelia.core.runtime import Runtime
from aurelia.sandbox.docker import ContainerResult, DockerClient


def _mock_docker_client() -> DockerClient:
    """Create a mock DockerClient for runtime tests."""
    mock_stdout = "\n".join([
        json.dumps({"type": "init", "session_id": "s1", "model": "gemini-2.5-pro"}),
        json.dumps({"type": "result", "response": "Mock done.", "stats": {}}),
    ])
    docker = AsyncMock(spec=DockerClient)
    docker.check_available = AsyncMock()
    docker.image_exists = AsyncMock(return_value=True)
    docker.build_image = AsyncMock()
    docker.run_container = AsyncMock(
        return_value=ContainerResult(exit_code=0, stdout=mock_stdout, stderr="")
    )
    return docker


def _init_project(tmp_path):
    """Create a minimal project directory with git repo for runtime tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "README.md").write_text("Test problem description")

    aurelia_dir = project_dir / ".aurelia"
    for subdir in ["state", "logs", "cache", "reports", "config"]:
        (aurelia_dir / subdir).mkdir(parents=True)

    # Write workflow config with fast heartbeat under the 'runtime' key
    (aurelia_dir / "config" / "workflow.yaml").write_text(
        "runtime:\n  heartbeat_interval_s: 1\n"
    )

    # Create evaluate.py so the evaluator can succeed
    (project_dir / "evaluate.py").write_text(
        'import json\nprint(json.dumps({"accuracy": 0.95, "speed_ms": 5.0}))\n'
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


class TestRuntimeStartStop:
    async def test_runtime_start_stop(self, tmp_path):
        project_dir = _init_project(tmp_path)
        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_soon():
            await asyncio.sleep(0.5)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_soon())
        await runtime.start()
        await stop_task

        event_log = EventLog(project_dir / ".aurelia" / "logs" / "events.jsonl")
        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "runtime.started" in event_types
        assert "runtime.stopped" in event_types


class TestRuntimePidFile:
    async def test_runtime_creates_pid_file(self, tmp_path):
        project_dir = _init_project(tmp_path)
        pid_path = project_dir / ".aurelia" / "state" / "pid"
        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        pid_existed_during_run = False

        async def check_and_stop():
            nonlocal pid_existed_during_run
            await asyncio.sleep(0.5)
            pid_existed_during_run = pid_path.exists()
            await runtime.stop()

        stop_task = asyncio.create_task(check_and_stop())
        await runtime.start()
        await stop_task

        assert pid_existed_during_run, "PID file should exist while runtime is running"
        assert not pid_path.exists(), "PID file should be removed after stop"


class TestRuntimeStatePersistence:
    async def test_runtime_state_persistence(self, tmp_path):
        project_dir = _init_project(tmp_path)
        state_dir = project_dir / ".aurelia" / "state"
        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_after_cycle():
            # Wait long enough for at least one heartbeat cycle
            await asyncio.sleep(1.5)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_after_cycle())
        await runtime.start()
        await stop_task

        # State files should exist and contain valid data
        runtime_json = state_dir / "runtime.json"
        assert runtime_json.exists(), "runtime.json should be persisted"

        import json

        data = json.loads(runtime_json.read_text())
        assert data["status"] == "stopped"
        assert data["heartbeat_count"] >= 1
