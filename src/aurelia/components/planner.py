"""PlannerComponent — runs Gemini CLI to produce an improvement plan.

Similar to CoderComponent but instead of modifying code, the Planner
examines repo state, evaluation history, and problem description to
produce a structured plan (plan.json) with actionable improvement items.
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

_PLAN_SCHEMA = {
    "type": "object",
    "required": ["summary", "items"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "High-level strategy description",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "description", "instruction"],
                "properties": {
                    "id": {"type": "string", "description": "Unique item ID, e.g. plan-0001"},
                    "description": {"type": "string", "description": "What this improvement does"},
                    "instruction": {
                        "type": "string",
                        "description": "Detailed instruction for the coder agent",
                    },
                    "parent_branch": {
                        "type": "string",
                        "description": (
                            'Branch to fork from: "main", an existing branch, '
                            'or "$plan-XXXX" to reference another plan item'
                        ),
                        "default": "main",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Lower numbers execute first",
                        "default": 0,
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Plan item IDs that must complete first",
                        "default": [],
                    },
                },
            },
        },
    },
}

logger = logging.getLogger(__name__)


class PlannerComponent(BaseComponent):
    """Component that runs Gemini CLI to produce a plan.json file."""

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

    async def execute(self, task: Task) -> TaskResult:
        """Run Gemini CLI to generate an improvement plan.

        1. Ensure Docker image exists.
        2. Write planning context and system prompt to worktree.
        3. Run Gemini CLI.
        4. Read plan.json from worktree.
        5. Return TaskResult with plan JSON.
        """
        sandbox = self._spec.sandbox
        if sandbox is None:
            msg = "PlannerComponent requires a SandboxConfig"
            raise RuntimeError(msg)

        worktree_path = Path(task.context.get("worktree_path", str(self._project_dir)))

        await self._emit_event("planner.started", {"task_id": task.id})

        # 1. Ensure Docker image
        await self._ensure_image(sandbox.image)

        # 2. Write context files
        planning_ctx = task.context.get("planning_context", {})
        problem_desc = task.context.get("problem_description", "")
        context_md = self._build_context_markdown(problem_desc, planning_ctx)
        context_file = worktree_path / "_planning_context.md"
        context_file.write_text(context_md)

        schema_file = worktree_path / "plan_schema.json"
        schema_file.write_text(json.dumps(_PLAN_SCHEMA, indent=2))

        # 3. Write system prompt
        system_prompt = self._build_system_prompt(task)
        system_prompt_file = worktree_path / ".gemini_system.md"
        system_prompt_file.write_text(system_prompt)

        try:
            # 4. Run Gemini CLI
            user_prompt = (
                "Read _planning_context.md and plan_schema.json. "
                "Analyze the repository code and evaluation results. "
                "Then write a plan.json file with concrete improvement items."
            )
            command = [
                "gemini",
                "-y",
                "-p",
                user_prompt,
                "--output-format",
                "stream-json",
            ]
            env = {
                "GEMINI_SYSTEM_MD": "/workspace/.gemini_system.md",
            }
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

            if result.exit_code != 0:
                error_msg = (
                    f"Planner Gemini CLI exited with code {result.exit_code}: {result.stderr[:500]}"
                )
                await self._emit_event(
                    "planner.failed",
                    {"task_id": task.id, "error": error_msg},
                )
                return TaskResult(
                    id=self._id_gen.next_id("result"),
                    summary=error_msg,
                    artifacts=[str(transcript_path)],
                    error=error_msg,
                )

            # 6. Read plan.json from worktree
            plan_file = worktree_path / "plan.json"
            if plan_file.exists():
                plan_json = plan_file.read_text()
                summary = f"Plan generated: {plan_json[:200]}"
            else:
                plan_json = ""
                summary = "Planner did not produce plan.json"

            await self._emit_event(
                "planner.completed",
                {
                    "task_id": task.id,
                    "has_plan": bool(plan_json),
                },
            )

            return TaskResult(
                id=self._id_gen.next_id("result"),
                summary=plan_json if plan_json else summary,
                artifacts=[str(transcript_path)],
                error=None if plan_json else summary,
            )

        finally:
            # Clean up temp files
            for f in (context_file, schema_file, system_prompt_file):
                f.unlink(missing_ok=True)

    def _build_system_prompt(self, task: Task) -> str:
        """Load planner system prompt template and fill variables."""
        template = (_PROMPT_DIR / "planner_system.txt").read_text()
        planning_ctx = task.context.get("planning_context", {})
        problem_desc = task.context.get("problem_description", "")
        return template.format(
            problem_description=problem_desc,
            planning_context=self._build_context_markdown(problem_desc, planning_ctx),
            plan_schema=json.dumps(_PLAN_SCHEMA, indent=2),
        )

    @staticmethod
    def _build_context_markdown(
        problem_description: str,
        planning_ctx: dict,
    ) -> str:
        """Build a markdown document with all planning context."""
        sections = [f"# Problem\n\n{problem_description}\n"]

        if evals := planning_ctx.get("evaluation_history"):
            sections.append("# Evaluation History\n")
            for ev in evals:
                status = "PASS" if ev.get("passed") else "FAIL"
                sections.append(
                    f"- {ev.get('candidate_branch', '?')}: "
                    f"{status} — {json.dumps(ev.get('metrics', {}))}"
                )
            sections.append("")

        if plan_state := planning_ctx.get("current_plan"):
            sections.append("# Current Plan State\n")
            for item in plan_state.get("items", []):
                sections.append(
                    f"- [{item.get('status', '?')}] {item.get('id')}: {item.get('description', '')}"
                )
            sections.append("")

        if knowledge := planning_ctx.get("knowledge_entries"):
            sections.append("# Knowledge Base\n")
            for entry in knowledge:
                sections.append(f"- {entry.get('content', '')[:200]}")
            sections.append("")

        return "\n".join(sections)

    async def _ensure_image(self, image: str) -> None:
        """Build the Docker image if it doesn't exist locally."""
        await self._docker.check_available()
        if await self._docker.image_exists(image):
            return
        await self._emit_event("planner.image_build.started", {"image": image})
        logger.info("Building Docker image %s (first run)...", image)
        await self._docker.build_image(_DOCKERFILE_PATH, image)
        await self._emit_event("planner.image_build.completed", {"image": image})

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
