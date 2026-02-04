from __future__ import annotations

from pathlib import Path

from google.genai import types

from aurelia.components.base import BaseComponent
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import ComponentSpec, Task, TaskResult
from aurelia.llm.client import LLMClient
from aurelia.tools.registry import ToolRegistry

_PROMPT_DIR = Path(__file__).parent / "prompts"


class CoderComponent(BaseComponent):
    """Component that acts as a software engineer to implement code changes."""

    def __init__(
        self,
        spec: ComponentSpec,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        event_log: EventLog,
        id_generator: IdGenerator,
        project_dir: Path,
    ) -> None:
        super().__init__(spec, llm_client, tool_registry, event_log, id_generator)
        self._project_dir = project_dir

    def _build_system_prompt(self, task: Task) -> str:
        """Load coder_system.txt and fill in variables from task.context."""
        template = (_PROMPT_DIR / "coder_system.txt").read_text()
        return template.format(
            problem_description=task.context.get("problem_description", ""),
            branch=task.branch,
            worktree_path=task.context.get("worktree_path", str(self._project_dir)),
            instruction=task.instruction,
        )

    def _build_contents(self, task: Task) -> list[types.Content]:
        """Build user message with task instruction and optional additional context."""
        msg = task.instruction
        if task.context.get("additional_context"):
            msg += f"\n\nAdditional context:\n{task.context['additional_context']}"
        return [types.Content(parts=[types.Part(text=msg)], role="user")]

    def _parse_result(self, task: Task, final_content: types.Content) -> TaskResult:
        """Extract summary from the model's final text response."""
        text_parts = [p.text for p in (final_content.parts or []) if p.text]
        summary = "\n".join(text_parts) if text_parts else "No response from coder"
        return TaskResult(id=self._id_gen.next_id("result"), summary=summary)
