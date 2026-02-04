"""Evaluator component — runs evaluation scripts via subprocess."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurelia.core.events import EventLog
    from aurelia.core.ids import IdGenerator

from aurelia.core.models import Event, Task, TaskResult

logger = logging.getLogger(__name__)

_TIMEOUT_S = 120


_DEFAULT_EVAL_COMMAND = "pixi run evaluate"


class EvaluatorComponent:
    """Runs the evaluation command in a candidate worktree and collects metrics."""

    def __init__(self, event_log: EventLog, id_generator: IdGenerator) -> None:
        self._event_log = event_log
        self._id_gen = id_generator

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit(self, event_type: str, data: dict[str, object]) -> None:
        event = Event(
            seq=self._id_gen.next_event_seq(),
            type=event_type,
            timestamp=datetime.datetime.now(datetime.UTC),
            data=data,
        )
        await self._event_log.append(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, task: Task) -> TaskResult:
        """Run evaluation in the worktree via subprocess.

        Runs the evaluation command (default ``pixi run evaluate``) in the
        worktree directory specified by ``task.context["worktree_path"]``.
        Override the command by setting ``task.context["eval_command"]``.
        Parses JSON output from stdout into metrics.  Returns a
        :class:`TaskResult` with metrics on success, or an error description
        on failure.
        """
        worktree_path = task.context["worktree_path"]
        eval_command = task.context.get("eval_command", _DEFAULT_EVAL_COMMAND)
        result_id = self._id_gen.next_id("result")

        await self._emit(
            "eval.started",
            {"task_id": task.id, "worktree": worktree_path, "command": eval_command},
        )

        try:
            proc = await asyncio.create_subprocess_shell(
                eval_command,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT_S
            )
        except TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            await proc.wait()  # type: ignore[union-attr]
            result = TaskResult(
                id=result_id,
                summary="Evaluation timed out",
                error=f"Timed out after {_TIMEOUT_S}s",
                metrics={},
            )
            await self._emit("eval.failed", {"task_id": task.id, "error": result.error})
            return result

        stdout = stdout_bytes.decode()
        stderr = stderr_bytes.decode()

        if proc.returncode != 0:
            error_msg = stderr or stdout
            result = TaskResult(
                id=result_id,
                summary="Evaluation failed",
                error=error_msg,
                metrics={},
            )
            await self._emit("eval.failed", {"task_id": task.id, "error": error_msg})
            return result

        try:
            metrics: dict[str, float] = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            result = TaskResult(
                id=result_id,
                summary="Evaluation output not valid JSON",
                error=stdout,
                metrics={},
            )
            await self._emit("eval.failed", {"task_id": task.id, "error": "invalid JSON output"})
            return result

        result = TaskResult(
            id=result_id,
            summary="Evaluation completed",
            metrics=metrics,
        )
        await self._emit("eval.completed", {"task_id": task.id, "metrics": metrics})
        return result
