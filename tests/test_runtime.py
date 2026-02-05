"""Tests for the Runtime class."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock

import pytest

from aurelia.core.events import EventLog
from aurelia.core.runtime import Runtime
from aurelia.sandbox.docker import ContainerResult, DockerClient


def _mock_docker_client() -> DockerClient:
    """Create a mock DockerClient for runtime tests."""
    mock_stdout = "\n".join(
        [
            json.dumps({"type": "init", "session_id": "s1", "model": "gemini-2.5-pro"}),
            json.dumps({"type": "result", "response": "Mock done.", "stats": {}}),
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


def _init_project(tmp_path):
    """Create a minimal project directory with git repo for runtime tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "README.md").write_text("Test problem description")

    aurelia_dir = project_dir / ".aurelia"
    for subdir in ["state", "logs", "cache", "reports", "config"]:
        (aurelia_dir / subdir).mkdir(parents=True)

    # Write workflow config with fast heartbeat under the 'runtime' key
    (aurelia_dir / "config" / "workflow.yaml").write_text("runtime:\n  heartbeat_interval_s: 1\n")

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


class TestParallelCandidates:
    async def test_multiple_candidates_created(self, tmp_path):
        """With max_concurrent_tasks=2, multiple candidates should be created."""
        project_dir = _init_project(tmp_path)

        # Configure for 2 concurrent tasks
        (project_dir / ".aurelia" / "config" / "workflow.yaml").write_text(
            "runtime:\n"
            "  heartbeat_interval_s: 1\n"
            "  max_concurrent_tasks: 2\n"
            "  candidate_abandon_threshold: 10\n"
        )

        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_after_cycles():
            await asyncio.sleep(4)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_after_cycles())
        await runtime.start()
        await stop_task

        # Should have created multiple candidates
        candidates_data = json.loads(
            (project_dir / ".aurelia" / "state" / "candidates.json").read_text()
        )
        assert len(candidates_data) >= 2, (
            f"Expected >=2 candidates with max_concurrent_tasks=2, got {len(candidates_data)}"
        )


class TestCrashRecovery:
    async def test_stale_pid_cleaned_up(self, tmp_path):
        """A stale PID file from a dead process should be cleaned up on start."""
        project_dir = _init_project(tmp_path)
        pid_path = project_dir / ".aurelia" / "state" / "pid"

        # Write a PID for a process that doesn't exist
        pid_path.write_text("999999")

        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_soon():
            await asyncio.sleep(0.5)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_soon())
        await runtime.start()
        await stop_task

        # Should have started successfully
        event_log = EventLog(project_dir / ".aurelia" / "logs" / "events.jsonl")
        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "runtime.started" in event_types

    async def test_blocks_if_pid_alive(self, tmp_path):
        """If PID file points to a running process, start should raise."""
        project_dir = _init_project(tmp_path)
        pid_path = project_dir / ".aurelia" / "state" / "pid"

        # Write current process PID (definitely alive)
        pid_path.write_text(str(os.getpid()))

        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        with pytest.raises(RuntimeError, match="Another Aurelia instance"):
            await runtime.start()

    async def test_running_tasks_marked_failed(self, tmp_path):
        """Tasks left in 'running' state from a crash should be marked failed."""
        project_dir = _init_project(tmp_path)
        state_dir = project_dir / ".aurelia" / "state"

        # Write state with a task stuck in 'running'
        import datetime

        now = datetime.datetime.now(datetime.UTC).isoformat()
        tasks_data = [
            {
                "id": "task-0001",
                "thread_id": "thread-0001",
                "component": "coder",
                "branch": "aurelia/cand-0001",
                "instruction": "test",
                "status": "running",
                "context": {},
                "created_at": now,
                "started_at": now,
                "completed_at": None,
                "result": None,
                "parent_task_id": None,
                "last_heartbeat": None,
            }
        ]
        candidates_data = [
            {
                "id": "cand-0001",
                "branch": "aurelia/cand-0001",
                "parent_branch": "main",
                "status": "active",
                "evaluations": [],
                "created_at": now,
                "worktree_path": str(state_dir),
            }
        ]
        runtime_data = {
            "status": "running",
            "started_at": now,
            "stopped_at": None,
            "next_event_seq": 5,
            "next_seq": {"cand": 2, "task": 2, "thread": 2, "result": 1, "eval": 1},
            "heartbeat_count": 1,
            "total_tasks_dispatched": 1,
            "total_tasks_completed": 0,
            "total_tasks_failed": 0,
            "total_tokens_used": 0,
            "total_cost_usd": 0.0,
            "last_heartbeat_at": now,
            "last_instruction_hash": None,
        }

        (state_dir / "tasks.json").write_text(json.dumps(tasks_data))
        (state_dir / "candidates.json").write_text(json.dumps(candidates_data))
        (state_dir / "runtime.json").write_text(json.dumps(runtime_data))

        runtime = Runtime(project_dir, use_mock=True, docker_client=_mock_docker_client())

        async def stop_soon():
            await asyncio.sleep(0.5)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_soon())
        await runtime.start()
        await stop_task

        # Check that the interrupted task was marked failed
        tasks = json.loads((state_dir / "tasks.json").read_text())
        crashed_task = next(t for t in tasks if t["id"] == "task-0001")
        assert crashed_task["status"] == "failed"
        assert crashed_task["result"]["error"] == "runtime_crash_recovery"

        # Check that the candidate was also marked failed
        candidates = json.loads((state_dir / "candidates.json").read_text())
        crashed_cand = next(c for c in candidates if c["id"] == "cand-0001")
        assert crashed_cand["status"] == "failed"

        # Check recovery event was emitted
        event_log = EventLog(project_dir / ".aurelia" / "logs" / "events.jsonl")
        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "runtime.recovered" in event_types


class TestGracefulShutdown:
    async def test_running_tasks_cancelled_on_stop(self, tmp_path):
        """Tasks running when stop is called should be cancelled."""
        project_dir = _init_project(tmp_path)

        # Use a slow mock that takes a while to complete
        slow_docker = _mock_docker_client()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(60)
            return ContainerResult(exit_code=0, stdout="", stderr="")

        slow_docker.run_container = AsyncMock(side_effect=slow_run)

        runtime = Runtime(project_dir, use_mock=True, docker_client=slow_docker)

        async def stop_during_task():
            # Wait long enough for a task to be launched
            await asyncio.sleep(2)
            await runtime.stop()

        stop_task = asyncio.create_task(stop_during_task())
        await runtime.start()
        await stop_task

        # Check that tasks were cancelled
        state_dir = project_dir / ".aurelia" / "state"
        tasks = json.loads((state_dir / "tasks.json").read_text())
        for task in tasks:
            assert task["status"] in ("cancelled", "failed", "success"), (
                f"Task {task['id']} has unexpected status: {task['status']}"
            )
