from __future__ import annotations

from typing import Protocol

from google.genai import types


class LLMClient(Protocol):
    """Protocol defining the interface for LLM clients."""

    async def generate(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig | None = None,
    ) -> types.GenerateContentResponse: ...


class MockLLMClient:
    """Returns configurable canned responses. Records all calls for test assertions."""

    def __init__(self, responses: list[types.Content] | None = None) -> None:
        self._responses = responses or [
            types.Content(parts=[types.Part(text="Mock response")], role="model")
        ]
        self._call_index = 0
        self._calls: list[dict] = []

    async def generate(
        self,
        model: str,
        contents: list[types.Content],
        config: types.GenerateContentConfig | None = None,
    ) -> types.GenerateContentResponse:
        self._calls.append({"model": model, "contents": contents, "config": config})
        content = self._responses[self._call_index % len(self._responses)]
        self._call_index += 1
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=content)]
        )

    @property
    def calls(self) -> list[dict]:
        return self._calls
