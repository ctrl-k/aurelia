"""Tests for the PresubmitComponent."""

from __future__ import annotations

import datetime
import sys

from aurelia.components.presubmit import PresubmitComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import RuntimeState, Task, TaskStatus


def _make_presubmit_task(worktree_path: str, checks: list[str]) -> Task:
    return Task(
        id="task-0001",
        thread_id="thread-0001",
        component="presubmit",
        branch="aurelia/cand-0001",
        instruction="Run presubmit checks",
        status=TaskStatus.pending,
        context={
            "worktree_path": worktree_path,
            "checks": checks,
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )


class TestAllChecksPass:
    async def test_all_checks_pass(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        checks = [
            f"{sys.executable} -c \"print('lint ok')\"",
            f"{sys.executable} -c \"print('test ok')\"",
        ]

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = PresubmitComponent(event_log, id_gen)

        task = _make_presubmit_task(str(worktree), checks)
        result = await component.execute(task)

        assert result.error is None
        assert "passed" in result.summary.lower()


class TestFirstCheckFails:
    async def test_first_check_fails(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        checks = [
            f'{sys.executable} -c "import sys; sys.exit(1)"',
            f"{sys.executable} -c \"print('should not run')\"",
        ]

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = PresubmitComponent(event_log, id_gen)

        task = _make_presubmit_task(str(worktree), checks)
        result = await component.execute(task)

        assert result.error is not None
        assert "failed" in result.error.lower()


class TestEventsEmitted:
    async def test_events_emitted(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        checks = [f"{sys.executable} -c \"print('ok')\""]

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = PresubmitComponent(event_log, id_gen)

        task = _make_presubmit_task(str(worktree), checks)
        await component.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "presubmit.started" in event_types
        assert "presubmit.completed" in event_types

        started = next(e for e in events if e.type == "presubmit.started")
        assert started.data["task_id"] == "task-0001"


class TestFailedEventsEmitted:
    async def test_failed_events_emitted(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        checks = [f'{sys.executable} -c "import sys; sys.exit(1)"']

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = PresubmitComponent(event_log, id_gen)

        task = _make_presubmit_task(str(worktree), checks)
        await component.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "presubmit.started" in event_types
        assert "presubmit.failed" in event_types


class TestTimeout:
    async def test_timeout(self, tmp_path, monkeypatch):
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        # Patch timeout to 1s so the test completes quickly
        import aurelia.components.presubmit as mod

        monkeypatch.setattr(mod, "_TIMEOUT_S", 1)

        checks = [f'{sys.executable} -c "import time; time.sleep(60)"']

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        component = PresubmitComponent(event_log, id_gen)

        task = _make_presubmit_task(str(worktree), checks)
        result = await component.execute(task)

        assert result.error is not None
        assert "timed out" in result.error.lower()
