"""Presubmit component — runs lint/test checks before evaluation."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurelia.core.events import EventLog
    from aurelia.core.ids import IdGenerator

from aurelia.core.models import Event, Task, TaskResult

logger = logging.getLogger(__name__)

_TIMEOUT_S = 120


class PresubmitComponent:
    """Runs a sequence of shell commands to validate code before evaluation.

    Each check (e.g. ``pixi run test``) is executed in the candidate worktree.
    If any check fails, execution stops immediately and the task is marked as
    failed.  This saves time by catching obvious errors before the more
    expensive evaluation step.
    """

    def __init__(
        self,
        event_log: EventLog,
        id_generator: IdGenerator,
    ) -> None:
        self._event_log = event_log
        self._id_gen = id_generator

    async def _emit(self, event_type: str, data: dict[str, object]) -> None:
        event = Event(
            seq=self._id_gen.next_event_seq(),
            type=event_type,
            timestamp=datetime.datetime.now(datetime.UTC),
            data=data,
        )
        await self._event_log.append(event)

    def _kill_process_group(self, pid: int) -> None:
        """Kill a process group, first with SIGTERM then SIGKILL."""
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        # Give processes a moment to terminate gracefully
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    async def execute(self, task: Task) -> TaskResult:
        """Run presubmit checks in the candidate worktree.

        Checks are taken from ``task.context["checks"]`` (a list of shell
        command strings).  Each is run sequentially; if any returns a non-zero
        exit code, the remaining checks are skipped and a failed
        :class:`TaskResult` is returned.
        """
        worktree_path = task.context["worktree_path"]
        checks: list[str] = task.context.get("checks", ["pixi run test"])
        result_id = self._id_gen.next_id("result")

        await self._emit(
            "presubmit.started",
            {
                "task_id": task.id,
                "worktree": worktree_path,
                "checks": checks,
            },
        )

        outputs: list[str] = []

        for check in checks:
            proc = await asyncio.create_subprocess_shell(
                check,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # Create new process group for cleanup
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=_TIMEOUT_S
                )
            except (TimeoutError, asyncio.CancelledError):
                # Kill the entire process group to clean up all children
                self._kill_process_group(proc.pid)
                await proc.wait()
                error_msg = f"Check '{check}' timed out after {_TIMEOUT_S}s"
                result = TaskResult(
                    id=result_id,
                    summary=error_msg,
                    error=error_msg,
                )
                await self._emit(
                    "presubmit.failed",
                    {
                        "task_id": task.id,
                        "check": check,
                        "error": error_msg,
                    },
                )
                return result

            stdout = stdout_bytes.decode()
            stderr = stderr_bytes.decode()

            if proc.returncode != 0:
                error_msg = f"Check '{check}' failed (exit {proc.returncode})"
                detail = stderr or stdout
                if detail:
                    error_msg += f": {detail[:500]}"
                result = TaskResult(
                    id=result_id,
                    summary=error_msg,
                    error=error_msg,
                )
                await self._emit(
                    "presubmit.failed",
                    {
                        "task_id": task.id,
                        "check": check,
                        "error": error_msg,
                    },
                )
                return result

            outputs.append(f"{check}: OK")

        summary = "All presubmit checks passed" if outputs else "No checks configured"
        result = TaskResult(
            id=result_id,
            summary=summary,
        )
        await self._emit(
            "presubmit.completed",
            {"task_id": task.id, "checks_passed": len(checks)},
        )
        return result
