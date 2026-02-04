"""Base component engine with LLM tool-use loop.

Provides the core generate-then-act loop shared by all Aurelia components.
Subclasses override hooks to customise prompt building and result parsing.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import time
from typing import Any

from google.genai import types

from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import (
    ComponentSpec,
    Event,
    Task,
    TaskResult,
)
from aurelia.llm.client import LLMClient
from aurelia.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class BaseComponent:
    """Component that executes a task via an LLM tool-use loop.

    Subclasses may override the ``_build_system_prompt``,
    ``_build_contents``, and ``_parse_result`` hooks to customise
    behaviour without replacing the core loop.
    """

    def __init__(
        self,
        spec: ComponentSpec,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        event_log: EventLog,
        id_generator: IdGenerator,
    ) -> None:
        self._spec = spec
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._event_log = event_log
        self._id_gen = id_generator

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute(self, task: Task) -> TaskResult:
        """Run the component logic for *task*.

        1. Build system prompt and user contents via subclass hooks.
        2. Construct ``GenerateContentConfig`` with tools.
        3. Run the tool-use loop until a text-only response.
        4. Parse the final content into a ``TaskResult``.
        """
        system_prompt = self._build_system_prompt(task)
        contents = self._build_contents(task)

        # -- tool declarations --
        decls = self._tool_registry.get_declarations(self._spec.tools)
        tools: list[types.Tool] | None = None
        if decls:
            tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(**d) for d in decls
                    ]
                )
            ]

        config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            temperature=self._spec.model.temperature,
            max_output_tokens=self._spec.model.max_output_tokens,
            tools=tools,
        )

        final_content = await self._tool_use_loop(
            task, contents, config
        )
        return self._parse_result(task, final_content)

    # ------------------------------------------------------------------
    # Tool-use loop
    # ------------------------------------------------------------------

    async def _tool_use_loop(
        self,
        task: Task,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
        max_rounds: int = 20,
    ) -> types.Content:
        """Run the generate / tool-call / respond loop.

        Returns the final ``Content`` once the model produces a
        text-only response or *max_rounds* is exhausted.
        """
        for _round in range(max_rounds):
            response = await self._call_llm(task, contents, config)
            content = response.candidates[0].content
            contents.append(content)

            # Collect function calls from the response parts.
            function_calls: list[types.FunctionCall] = []
            for part in content.parts or []:
                if part.function_call:
                    function_calls.append(part.function_call)

            if not function_calls:
                return content

            # Execute each tool and build function-response parts.
            response_parts: list[types.Part] = []
            for fc in function_calls:
                logger.debug(
                    "Tool call: %s(%s)", fc.name, fc.args
                )
                result = await self._execute_tool(
                    fc.name, dict(fc.args) if fc.args else {}
                )
                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response=result,
                        )
                    )
                )

            contents.append(
                types.Content(parts=response_parts, role="user")
            )

        logger.warning(
            "Max tool-use rounds (%d) reached for task %s",
            max_rounds,
            task.id,
        )
        return content  # type: ignore[possibly-undefined]

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        task: Task,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        """Call the LLM with exponential-backoff retry (3 attempts).

        Emits ``llm.request`` and ``llm.response`` events.
        """
        max_attempts = 3
        backoff_seconds = [1, 2, 4]
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            try:
                # -- emit request event --
                req_seq = self._id_gen.next_event_seq()
                request_hash = self._hash_contents(contents)
                await self._event_log.append(
                    Event(
                        seq=req_seq,
                        type="llm.request",
                        timestamp=datetime.datetime.now(
                            datetime.UTC
                        ),
                        data={
                            "task_id": task.id,
                            "component": self._spec.id,
                            "model": self._spec.model.model,
                            "request_hash": request_hash,
                            "attempt": attempt + 1,
                        },
                    )
                )

                start = time.monotonic()
                response = await self._llm_client.generate(
                    self._spec.model.model, contents, config
                )
                latency_ms = int(
                    (time.monotonic() - start) * 1000
                )

                # -- extract token counts when available --
                input_tokens = 0
                output_tokens = 0
                if response.usage_metadata:
                    input_tokens = (
                        response.usage_metadata.prompt_token_count
                        or 0
                    )
                    output_tokens = (
                        response.usage_metadata
                        .candidates_token_count
                        or 0
                    )

                # -- emit response event --
                resp_seq = self._id_gen.next_event_seq()
                await self._event_log.append(
                    Event(
                        seq=resp_seq,
                        type="llm.response",
                        timestamp=datetime.datetime.now(
                            datetime.UTC
                        ),
                        data={
                            "task_id": task.id,
                            "component": self._spec.id,
                            "model": self._spec.model.model,
                            "request_hash": request_hash,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "latency_ms": latency_ms,
                        },
                    )
                )

                return response

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts - 1:
                    await asyncio.sleep(
                        backoff_seconds[attempt]
                    )

        raise RuntimeError(
            f"LLM call failed after {max_attempts} attempts"
        ) from last_exc

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool via the registry.

        On error, returns an error dict instead of raising so that
        the model can observe and react to the failure.
        """
        try:
            return await self._tool_registry.execute(name, args)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Tool '%s' raised: %s", name, exc
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    def _build_system_prompt(self, task: Task) -> str:
        """Return the system instruction for the LLM call."""
        return self._spec.model.system_instruction or ""

    def _build_contents(
        self, task: Task
    ) -> list[types.Content]:
        """Return the initial conversation contents."""
        return [
            types.Content(
                parts=[types.Part(text=task.instruction)],
                role="user",
            )
        ]

    def _parse_result(
        self, task: Task, final_content: types.Content
    ) -> TaskResult:
        """Convert the final LLM content into a ``TaskResult``."""
        text_parts = [
            p.text
            for p in (final_content.parts or [])
            if p.text
        ]
        summary = (
            "\n".join(text_parts) if text_parts else "No response"
        )
        return TaskResult(
            id=self._id_gen.next_id("result"), summary=summary
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_contents(
        contents: list[types.Content],
    ) -> str:
        """Produce a stable SHA-256 hex digest of *contents*."""
        raw = json.dumps(
            [c.model_dump() for c in contents],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()
