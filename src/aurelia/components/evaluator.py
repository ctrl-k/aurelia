"""Evaluator component — runs presubmit checks and evaluation scripts.

This component combines presubmit (tests) and evaluation into a single step.
It first runs any configured presubmit checks (e.g., tests), then runs the
evaluation script and collects metrics.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import signal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurelia.core.events import EventLog
    from aurelia.core.ids import IdGenerator
    from aurelia.sandbox.docker import DockerClient

from aurelia.core.models import Event, SandboxConfig, Task, TaskResult

logger = logging.getLogger(__name__)

_TIMEOUT_S = 120
_PRESUBMIT_TIMEOUT_S = 120
_DOCKERFILE_PATH = Path(__file__).parent.parent / "sandbox" / "Dockerfile.evaluator"
_DEFAULT_IMAGE = "aurelia-evaluator:latest"


_DEFAULT_EVAL_COMMAND = "pixi run evaluate"


class EvaluatorComponent:
    """Runs presubmit checks and evaluation in a candidate worktree.

    This component:
    1. First runs presubmit checks (e.g., tests) - if any fail, the task fails
    2. Then runs the evaluation command and parses JSON metrics

    Supports two modes:
    - Subprocess (default): Runs directly on host
    - Docker sandbox: Runs in isolated container (requires sandbox_config)
    """

    def __init__(
        self,
        event_log: EventLog,
        id_generator: IdGenerator,
        sandbox_config: SandboxConfig | None = None,
        docker_client: DockerClient | None = None,
    ) -> None:
        self._event_log = event_log
        self._id_gen = id_generator
        self._sandbox_config = sandbox_config
        self._docker = docker_client
        self._image_built = False

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

    async def _ensure_image(self) -> None:
        """Build Docker image if it doesn't exist."""
        if self._image_built or self._docker is None:
            return

        image = self._sandbox_config.image if self._sandbox_config else _DEFAULT_IMAGE
        if not await self._docker.image_exists(image):
            logger.info("Building Docker image %s (first run)...", image)
            await self._docker.build_image(_DOCKERFILE_PATH, image)
        self._image_built = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, task: Task) -> TaskResult:
        """Run presubmit checks and evaluation in the worktree.

        First runs any presubmit checks (e.g., tests) specified in
        ``task.context["presubmit_checks"]``. If any check fails, returns
        immediately with an error.

        Then runs the evaluation command (default ``pixi run evaluate``) in the
        worktree directory specified by ``task.context["worktree_path"]``.
        Override the command by setting ``task.context["eval_command"]``.
        Parses JSON output from stdout into metrics.  Returns a
        :class:`TaskResult` with metrics on success, or an error description
        on failure.

        If sandbox_config was provided, runs in Docker container; otherwise
        uses direct subprocess execution.
        """
        worktree_path = task.context["worktree_path"]
        eval_command = task.context.get("eval_command", _DEFAULT_EVAL_COMMAND)
        presubmit_checks: list[str] = task.context.get("presubmit_checks", [])
        result_id = self._id_gen.next_id("result")

        # Step 1: Run presubmit checks (tests)
        if presubmit_checks:
            await self._emit(
                "eval.presubmit_started",
                {
                    "task_id": task.id,
                    "worktree": worktree_path,
                    "checks": presubmit_checks,
                },
            )

            for check in presubmit_checks:
                exit_code, stdout, stderr = await self._execute_subprocess(
                    worktree_path, check, timeout_s=_PRESUBMIT_TIMEOUT_S
                )

                if exit_code == -1:
                    error_msg = f"Presubmit check '{check}' timed out"
                    await self._emit(
                        "eval.presubmit_failed",
                        {"task_id": task.id, "check": check, "error": error_msg},
                    )
                    return TaskResult(
                        id=result_id,
                        summary=error_msg,
                        error=error_msg,
                        metrics={},
                    )

                if exit_code != 0:
                    error_msg = f"Presubmit check '{check}' failed (exit {exit_code})"
                    detail = stderr or stdout
                    if detail:
                        error_msg += f": {detail[:500]}"
                    await self._emit(
                        "eval.presubmit_failed",
                        {"task_id": task.id, "check": check, "error": error_msg},
                    )
                    return TaskResult(
                        id=result_id,
                        summary=error_msg,
                        error=error_msg,
                        metrics={},
                    )

            await self._emit(
                "eval.presubmit_passed",
                {"task_id": task.id, "checks_passed": len(presubmit_checks)},
            )

        # Step 2: Run evaluation
        await self._emit(
            "eval.started",
            {
                "task_id": task.id,
                "worktree": worktree_path,
                "command": eval_command,
                "sandboxed": self._sandbox_config is not None,
            },
        )

        # Choose execution mode
        if self._sandbox_config and self._docker:
            exit_code, stdout, stderr = await self._execute_docker(worktree_path, eval_command)
        else:
            exit_code, stdout, stderr = await self._execute_subprocess(worktree_path, eval_command)

        # Handle timeout (indicated by special exit code)
        if exit_code == -1:
            result = TaskResult(
                id=result_id,
                summary="Evaluation timed out",
                error=f"Timed out after {_TIMEOUT_S}s",
                metrics={},
            )
            await self._emit("eval.failed", {"task_id": task.id, "error": result.error})
            return result

        # Handle non-zero exit
        if exit_code != 0:
            error_msg = stderr or stdout
            result = TaskResult(
                id=result_id,
                summary="Evaluation failed",
                error=error_msg,
                metrics={},
            )
            await self._emit("eval.failed", {"task_id": task.id, "error": error_msg})
            return result

        # Parse JSON metrics - try full output first, then last line
        # (evaluate.py may print human-readable summary before JSON)
        metrics: dict[str, float] = {}
        try:
            metrics = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            # Try parsing just the last non-empty line as JSON
            for line in reversed(stdout.strip().splitlines()):
                line = line.strip()
                if line:
                    try:
                        metrics = json.loads(line)
                        break
                    except (json.JSONDecodeError, ValueError):
                        continue

            if not metrics:
                result = TaskResult(
                    id=result_id,
                    summary="Evaluation output not valid JSON",
                    error=stdout[-500:] if len(stdout) > 500 else stdout,
                    metrics={},
                )
                await self._emit(
                    "eval.failed", {"task_id": task.id, "error": "invalid JSON output"}
                )
                return result

        result = TaskResult(
            id=result_id,
            summary="Evaluation completed",
            metrics=metrics,
        )
        await self._emit("eval.completed", {"task_id": task.id, "metrics": metrics})
        return result

    async def _execute_subprocess(
        self,
        worktree_path: str,
        command: str,
        timeout_s: int = _TIMEOUT_S,
    ) -> tuple[int, str, str]:
        """Execute a command via direct subprocess.

        Uses process groups to ensure all child processes are cleaned up
        on timeout or cancellation.
        """
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # Create new process group for cleanup
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
            return proc.returncode or 0, stdout_bytes.decode(), stderr_bytes.decode()
        except (TimeoutError, asyncio.CancelledError):
            # Kill the entire process group to clean up all children
            self._kill_process_group(proc.pid)
            await proc.wait()
            return -1, "", f"Command timed out after {timeout_s}s or cancelled"

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

    async def _execute_docker(self, worktree_path: str, eval_command: str) -> tuple[int, str, str]:
        """Execute evaluation in Docker container."""
        if self._docker is None or self._sandbox_config is None:
            raise RuntimeError("Docker execution requires docker_client and sandbox_config")

        await self._ensure_image()

        # Build command to run in container
        command = ["sh", "-c", eval_command]

        try:
            result = await self._docker.run_container(
                image=self._sandbox_config.image,
                command=command,
                sandbox_config=self._sandbox_config,
                workdir="/workspace",
                mounts=[(worktree_path, "/workspace", False)],
                timeout_s=self._sandbox_config.timeout_s or _TIMEOUT_S,
            )
            return result.exit_code, result.stdout, result.stderr
        except TimeoutError:
            return -1, "", "Evaluation timed out in container"
