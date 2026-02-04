"""CoderComponent — runs Gemini CLI inside a Docker container.

Overrides BaseComponent.execute() to shell out to Gemini CLI rather than
using the in-process LLM tool-use loop.  The full session transcript
(stream-json JSONL) is captured and stored for later analysis.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

from aurelia.components.base import BaseComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import ComponentSpec, Event, Task, TaskResult
from aurelia.llm.client import LLMClient
from aurelia.sandbox.docker import DockerClient
from aurelia.tools.registry import ToolRegistry

_PROMPT_DIR = Path(__file__).parent / "prompts"
_DOCKERFILE_PATH = Path(__file__).parent.parent / "sandbox" / "Dockerfile"

logger = logging.getLogger(__name__)


class CoderComponent(BaseComponent):
    """Component that runs Gemini CLI in a Docker container to modify code."""

    def __init__(
        self,
        spec: ComponentSpec,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        event_log: EventLog,
        id_generator: IdGenerator,
        project_dir: Path,
        docker_client: DockerClient | None = None,
    ) -> None:
        super().__init__(spec, llm_client, tool_registry, event_log, id_generator)
        self._project_dir = project_dir
        self._docker = docker_client or DockerClient()

    # ------------------------------------------------------------------
    # Override execute — bypass the LLM tool-use loop entirely
    # ------------------------------------------------------------------

    async def execute(self, task: Task) -> TaskResult:
        """Run Gemini CLI in a Docker container to implement the task.

        Steps:
        1. Ensure the Docker image exists (lazy build).
        2. Write a system prompt file into the worktree.
        3. Run ``gemini -y -p "..." --output-format stream-json`` in a container.
        4. Save stdout as a transcript JSONL file.
        5. Parse the final ``result`` event for summary and stats.
        6. Clean up the system prompt file.
        7. Return a TaskResult with summary and transcript path.
        """
        sandbox = self._spec.sandbox
        if sandbox is None:
            msg = "CoderComponent requires a SandboxConfig on its ComponentSpec"
            raise RuntimeError(msg)

        worktree_path = Path(task.context.get("worktree_path", str(self._project_dir)))

        await self._emit_event("coder.started", {"task_id": task.id})

        # 1. Ensure Docker image exists (lazy build)
        await self._ensure_image(sandbox.image)

        # 2. Write system prompt to worktree
        system_prompt = self._build_system_prompt(task)
        system_prompt_file = worktree_path / ".gemini_system.md"
        system_prompt_file.write_text(system_prompt)

        try:
            # 3. Build user prompt
            user_prompt = self._build_user_prompt(task)

            # 4. Run Gemini CLI in Docker
            command = [
                "gemini",
                "-y",
                "-p",
                user_prompt,
                "--output-format",
                "stream-json",
            ]

            # Build env dict: system prompt path + forwarded host vars
            env = {"GEMINI_SYSTEM_MD": "/workspace/.gemini_system.md"}
            for key in sandbox.env_forward:
                if value := os.environ.get(key):
                    env[key] = value

            result = await self._docker.run_container(
                image=sandbox.image,
                command=command,
                sandbox_config=sandbox,
                workdir="/workspace",
                env=env,
                mounts=[
                    (str(worktree_path), "/workspace", False),
                ],
                timeout_s=sandbox.timeout_s,
            )

            # 5. Save transcript
            transcript_dir = self._project_dir / ".aurelia" / "logs" / "transcripts"
            transcript_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = transcript_dir / f"{task.id}.jsonl"
            transcript_path.write_text(result.stdout)

            # 6. Parse result
            summary, stats = self._parse_transcript(result.stdout)

            if result.exit_code != 0:
                error_msg = (
                    f"Gemini CLI exited with code {result.exit_code}: "
                    f"{result.stderr[:500]}"
                )
                await self._emit_event(
                    "coder.failed",
                    {
                        "task_id": task.id,
                        "exit_code": result.exit_code,
                        "error": error_msg,
                    },
                )
                return TaskResult(
                    id=self._id_gen.next_id("result"),
                    summary=summary or error_msg,
                    artifacts=[str(transcript_path)],
                    error=error_msg,
                )

            # Emit transcript event with stats
            await self._emit_event(
                "coder.transcript",
                {
                    "task_id": task.id,
                    "transcript_path": str(transcript_path),
                    "stats": stats,
                },
            )
            await self._emit_event(
                "coder.completed",
                {"task_id": task.id, "summary": summary[:200] if summary else ""},
            )

            return TaskResult(
                id=self._id_gen.next_id("result"),
                summary=summary or "Coder completed (no response text)",
                artifacts=[str(transcript_path)],
            )

        finally:
            # 7. Clean up system prompt file
            system_prompt_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Prompt building (reuses template)
    # ------------------------------------------------------------------

    def _build_system_prompt(self, task: Task) -> str:
        """Load coder_system.txt and fill in variables from task.context."""
        template = (_PROMPT_DIR / "coder_system.txt").read_text()

        feedback = task.context.get("feedback", "")
        attempt = task.context.get("attempt_number", 1)
        if feedback:
            previous_attempts = (
                f"This is attempt #{attempt}. "
                f"Learn from previous attempts:\n\n{feedback}"
            )
        else:
            previous_attempts = "This is the first attempt."

        return template.format(
            problem_description=task.context.get("problem_description", ""),
            branch=task.branch,
            worktree_path="/workspace",
            instruction=task.instruction,
            previous_attempts=previous_attempts,
        )

    def _build_user_prompt(self, task: Task) -> str:
        """Build the prompt string passed to ``gemini -p``."""
        msg = task.instruction
        if task.context.get("additional_context"):
            msg += f"\n\nAdditional context:\n{task.context['additional_context']}"
        return msg

    # ------------------------------------------------------------------
    # Docker image management
    # ------------------------------------------------------------------

    async def _ensure_image(self, image: str) -> None:
        """Build the Docker image if it doesn't exist locally."""
        await self._docker.check_available()

        if await self._docker.image_exists(image):
            return

        await self._emit_event(
            "coder.image_build.started", {"image": image}
        )
        logger.info("Building Docker image %s (first run)...", image)
        await self._docker.build_image(_DOCKERFILE_PATH, image)
        await self._emit_event(
            "coder.image_build.completed", {"image": image}
        )

    # ------------------------------------------------------------------
    # Transcript parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_transcript(stdout: str) -> tuple[str, dict]:
        """Parse Gemini CLI stream-json output.

        Returns (response_text, stats_dict).  Extracts the ``result``
        event for the final response and aggregated stats.  Falls back
        to concatenating ``message`` events if no ``result`` is found.
        """
        response_text = ""
        stats: dict = {}
        messages: list[str] = []

        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "result":
                response_text = event.get("response", "")
                stats = event.get("stats", {})
            elif event_type == "message":
                role = event.get("role", "")
                content = event.get("content", "")
                if role == "assistant" and content:
                    messages.append(content)

        if not response_text and messages:
            response_text = messages[-1]

        return response_text, stats

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    async def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit an event to the event log."""
        await self._event_log.append(
            Event(
                seq=self._id_gen.next_event_seq(),
                type=event_type,
                timestamp=datetime.datetime.now(datetime.UTC),
                data=data,
            )
        )
