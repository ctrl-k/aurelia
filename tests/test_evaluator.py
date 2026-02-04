"""Tests for the EvaluatorComponent."""

from __future__ import annotations

import datetime
import textwrap

from aurelia.components.evaluator import EvaluatorComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import RuntimeState, Task, TaskStatus


def _make_eval_task(worktree_path: str) -> Task:
    return Task(
        id="task-0001",
        thread_id="thread-0001",
        component="evaluator",
        branch="aurelia/cand-0001",
        instruction="Run evaluation",
        status=TaskStatus.pending,
        context={
            "worktree_path": worktree_path,
            "eval_command": "python evaluate.py",
        },
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _write_evaluate_py(directory, script_body: str) -> None:
    """Write an evaluate.py script into the given directory."""
    evaluate_py = directory / "evaluate.py"
    evaluate_py.write_text(textwrap.dedent(script_body))


class TestEvaluateSuccess:
    async def test_evaluate_success(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _write_evaluate_py(
            worktree,
            """\
            import json
            print(json.dumps({"accuracy": 0.95, "speed_ms": 10.0}))
            """,
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        evaluator = EvaluatorComponent(event_log, id_gen)

        task = _make_eval_task(str(worktree))
        result = await evaluator.execute(task)

        assert result.error is None
        assert result.summary == "Evaluation completed"
        assert result.metrics["accuracy"] == 0.95
        assert result.metrics["speed_ms"] == 10.0


class TestEvaluateScriptFailure:
    async def test_evaluate_script_failure(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _write_evaluate_py(
            worktree,
            """\
            import sys
            print("something went wrong", file=sys.stderr)
            sys.exit(1)
            """,
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        evaluator = EvaluatorComponent(event_log, id_gen)

        task = _make_eval_task(str(worktree))
        result = await evaluator.execute(task)

        assert result.error is not None
        assert result.summary == "Evaluation failed"


class TestEvaluateInvalidJSON:
    async def test_evaluate_invalid_json(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _write_evaluate_py(
            worktree,
            """\
            print("not json at all")
            """,
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        evaluator = EvaluatorComponent(event_log, id_gen)

        task = _make_eval_task(str(worktree))
        result = await evaluator.execute(task)

        assert result.error is not None
        assert result.summary == "Evaluation output not valid JSON"


class TestEvaluateEventsEmitted:
    async def test_evaluate_events_emitted(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        _write_evaluate_py(
            worktree,
            """\
            import json
            print(json.dumps({"accuracy": 0.9}))
            """,
        )

        event_log = EventLog(tmp_path / "events.jsonl")
        id_gen = IdGenerator(RuntimeState())
        evaluator = EvaluatorComponent(event_log, id_gen)

        task = _make_eval_task(str(worktree))
        await evaluator.execute(task)

        events = await event_log.read_all()
        event_types = [e.type for e in events]
        assert "eval.started" in event_types
        assert "eval.completed" in event_types

        started = next(e for e in events if e.type == "eval.started")
        assert started.data["task_id"] == "task-0001"

        completed = next(e for e in events if e.type == "eval.completed")
        assert completed.data["metrics"]["accuracy"] == 0.9
