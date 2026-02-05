"""Dispatcher abstraction for candidate selection and evolution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    DispatchRequest,
    Evaluation,
    RuntimeConfig,
    TaskResult,
)

logger = logging.getLogger(__name__)


@dataclass
class DispatchContext:
    """Context provided to a Dispatcher during initialization."""

    project_dir: Path
    instruction: str
    candidates: list[Candidate] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    config: RuntimeConfig = field(default_factory=RuntimeConfig)


class Dispatcher(Protocol):
    """Protocol for pluggable candidate dispatch strategies.

    A Dispatcher decides *what* to work on next: which branch to fork from,
    what instruction to give the coder, and when to trigger replanning.
    """

    async def initialize(self, ctx: DispatchContext) -> None:
        """Called once at runtime start with current state."""
        ...

    def select_next(self) -> DispatchRequest | None:
        """Return the next work item, or None if nothing to dispatch."""
        ...

    def on_candidate_completed(
        self, candidate: Candidate, evaluation: Evaluation | None,
    ) -> None:
        """Called when a candidate finishes (success or failure)."""
        ...

    def needs_planning(self) -> bool:
        """Return True if the dispatcher needs a planning phase."""
        ...

    def get_planning_context(self) -> dict[str, Any]:
        """Return context for the planner component."""
        ...

    def on_planning_completed(
        self, result: TaskResult, worktree_path: str,
    ) -> None:
        """Called when a planning task finishes."""
        ...


class DefaultDispatcher:
    """Simple dispatcher that branches from the best candidate.

    Preserves the original Aurelia behavior: always branch from the
    best succeeded candidate (or main), using the README instruction.
    """

    def __init__(self) -> None:
        self._ctx: DispatchContext | None = None

    async def initialize(self, ctx: DispatchContext) -> None:
        self._ctx = ctx

    def select_next(self) -> DispatchRequest | None:
        assert self._ctx is not None
        best = self._get_best_candidate()
        parent_branch = best.branch if best else "main"
        feedback = self._build_feedback_text()
        return DispatchRequest(
            parent_branch=parent_branch,
            instruction=f"Improve the solution. {self._ctx.instruction}",
            context={
                "problem_description": self._ctx.instruction,
                "feedback": feedback,
                "attempt_number": len(self._ctx.candidates) + 1,
            },
        )

    def on_candidate_completed(
        self, candidate: Candidate, evaluation: Evaluation | None,
    ) -> None:
        # DefaultDispatcher has no internal state to update.
        pass

    def needs_planning(self) -> bool:
        return False

    def get_planning_context(self) -> dict[str, Any]:
        return {}

    def on_planning_completed(
        self, result: TaskResult, worktree_path: str,
    ) -> None:
        pass

    # -- Internal helpers ------------------------------------------------

    def _get_best_candidate(self) -> Candidate | None:
        """Find the succeeded candidate with the highest average metric."""
        assert self._ctx is not None
        eval_by_id = {e.id: e for e in self._ctx.evaluations}
        best: Candidate | None = None
        best_score = -1.0

        for cand in self._ctx.candidates:
            if cand.status != CandidateStatus.succeeded:
                continue
            for eval_id in cand.evaluations:
                ev = eval_by_id.get(eval_id)
                if ev is None or not ev.passed:
                    continue
                nums = [
                    v for v in ev.metrics.values()
                    if isinstance(v, (int, float))
                ]
                if not nums:
                    continue
                score = sum(nums) / len(nums)
                if score > best_score:
                    best_score = score
                    best = cand

        return best

    def _build_feedback_text(self) -> str:
        """Format previous attempts into feedback for the coder."""
        assert self._ctx is not None
        if not self._ctx.evaluations:
            return ""

        eval_by_id = {e.id: e for e in self._ctx.evaluations}
        lines: list[str] = []

        for i, cand in enumerate(self._ctx.candidates, 1):
            for eval_id in cand.evaluations:
                ev = eval_by_id.get(eval_id)
                if ev is None:
                    continue
                lines.append(f"### Attempt {i}")
                lines.append(
                    f"- Status: {'PASSED' if ev.passed else 'FAILED'}"
                )
                lines.append(
                    f"- Metrics: {json.dumps(ev.metrics)}"
                )
                if ev.raw_output:
                    lines.append(
                        f"- Output: {ev.raw_output[:200]}"
                    )
                lines.append("")

        return "\n".join(lines)
