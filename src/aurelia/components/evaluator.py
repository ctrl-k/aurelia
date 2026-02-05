"""Evaluator component — runs evaluation scripts via subprocess or Docker."""

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
_DOCKERFILE_PATH = Path(__file__).parent.parent / "sandbox" / "Dockerfile.evaluator"
_DEFAULT_IMAGE = "aurelia-evaluator:latest"


_DEFAULT_EVAL_COMMAND = "pixi run evaluate"


class EvaluatorComponent:
    """Runs the evaluation command in a candidate worktree and collects metrics.

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
        """Run evaluation in the worktree.

        Runs the evaluation command (default ``pixi run evaluate``) in the
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
        result_id = self._id_gen.next_id("result")

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

        # Parse JSON metrics
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

    async def _execute_subprocess(
        self, worktree_path: str, eval_command: str
    ) -> tuple[int, str, str]:
        """Execute evaluation via direct subprocess.

        Uses process groups to ensure all child processes are cleaned up
        on timeout or cancellation.
        """
        proc = await asyncio.create_subprocess_shell(
            eval_command,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # Create new process group for cleanup
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT_S
            )
            return proc.returncode or 0, stdout_bytes.decode(), stderr_bytes.decode()
        except (TimeoutError, asyncio.CancelledError):
            # Kill the entire process group to clean up all children
            self._kill_process_group(proc.pid)
            await proc.wait()
            return -1, "", "Evaluation timed out or cancelled"

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
