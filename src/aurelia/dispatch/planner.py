"""PlannerDispatcher — dispatches work items from a structured plan."""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    DispatchRequest,
    Evaluation,
    Plan,
    PlanItem,
    PlanItemStatus,
    TaskResult,
)
from aurelia.dispatch.base import DispatchContext

logger = logging.getLogger(__name__)


class PlannerDispatcher:
    """Dispatcher that works from a structured Plan.

    Each plan item maps 1:1 to a candidate branch. Items progress through:
    TODO → ASSIGNED → COMPLETE/FAILED
    """

    def __init__(self, plan: Plan | None = None) -> None:
        self._plan = plan
        self._ctx: DispatchContext | None = None

    async def initialize(self, ctx: DispatchContext) -> None:
        self._ctx = ctx

    @property
    def plan(self) -> Plan | None:
        return self._plan

    def select_next(self) -> DispatchRequest | None:
        """Select the next eligible plan item to dispatch.

        Returns None if:
        - No plan exists yet (needs planning)
        - No TODO items remain
        - All TODO items are blocked by dependencies
        """
        if self._plan is None:
            return None

        eligible = self._get_eligible_items()
        if not eligible:
            return None

        # Sort by priority (lower = higher priority)
        eligible.sort(key=lambda it: it.priority)
        item = eligible[0]

        # Resolve parent_branch
        parent_branch = self._resolve_branch(item.parent_branch)
        if parent_branch is None:
            # Referenced branch not ready yet
            return None

        return DispatchRequest(
            parent_branch=parent_branch,
            instruction=item.instruction,
            context={
                "plan_item_id": item.id,
                "plan_item_description": item.description,
            },
            plan_item_id=item.id,
        )

    def mark_assigned(
        self,
        plan_item_id: str,
        candidate: Candidate,
    ) -> None:
        """Mark a plan item as assigned to a candidate."""
        if self._plan is None:
            return
        item = self._find_item(plan_item_id)
        if item:
            item.status = PlanItemStatus.assigned
            item.assigned_candidate_id = candidate.id
            item.assigned_branch = candidate.branch

    def on_candidate_completed(
        self,
        candidate: Candidate,
        evaluation: Evaluation | None,
    ) -> None:
        """Update plan item status based on candidate result."""
        if self._plan is None:
            return

        item = self._find_item_by_candidate(candidate.id)
        if item is None:
            return

        if candidate.status == CandidateStatus.succeeded:
            item.status = PlanItemStatus.complete
        else:
            item.status = PlanItemStatus.failed

    def needs_planning(self) -> bool:
        """Return True if we need to run the planner.

        Needs planning when:
        - No plan exists
        - All TODO items are exhausted (none remain selectable)
        """
        if self._plan is None:
            return True

        # Check if any TODO items exist
        todo_items = [it for it in self._plan.items if it.status == PlanItemStatus.todo]
        if not todo_items:
            return True

        # Check if any TODO items are actually selectable
        eligible = self._get_eligible_items()
        if not eligible:
            # All TODO items are blocked — check if anything is still in progress
            assigned = [it for it in self._plan.items if it.status == PlanItemStatus.assigned]
            # If nothing assigned, we're deadlocked → need replan
            if not assigned:
                return True

        return False

    def get_planning_context(self) -> dict[str, Any]:
        """Return context for the planner component."""
        assert self._ctx is not None

        result: dict[str, Any] = {
            "problem_description": self._ctx.instruction,
        }

        # Add evaluation history
        if self._ctx.evaluations:
            result["evaluation_history"] = [
                {
                    "candidate_branch": ev.candidate_branch,
                    "metrics": ev.metrics,
                    "passed": ev.passed,
                }
                for ev in self._ctx.evaluations
            ]

        # Add current plan state if we have one
        if self._plan:
            result["current_plan"] = {
                "summary": self._plan.summary,
                "revision": self._plan.revision,
                "items": [
                    {
                        "id": it.id,
                        "description": it.description,
                        "status": it.status,
                        "assigned_branch": it.assigned_branch,
                    }
                    for it in self._plan.items
                ],
            }

        return result

    def on_planning_completed(
        self,
        result: TaskResult | None,
        worktree_path: str,
    ) -> None:
        """Parse the plan.json written by the planner."""
        if result is None or result.error:
            logger.warning(
                "Planning failed: %s",
                result.error if result else "no result",
            )
            return

        plan_file = Path(worktree_path) / "plan.json"
        if not plan_file.exists():
            logger.warning("Planner did not produce plan.json")
            return

        try:
            plan_data = json.loads(plan_file.read_text())
        except json.JSONDecodeError as e:
            logger.warning("Invalid plan.json: %s", e)
            return

        # Merge with existing plan: keep completed/assigned items
        if self._plan is not None:
            existing_items = {
                it.id: it
                for it in self._plan.items
                if it.status
                in (
                    PlanItemStatus.assigned,
                    PlanItemStatus.complete,
                    PlanItemStatus.failed,
                )
            }
            new_revision = self._plan.revision + 1
        else:
            existing_items = {}
            new_revision = 0

        # Parse new items
        new_items: list[PlanItem] = []
        for item_data in plan_data.get("items", []):
            item_id = item_data.get("id", "")
            if item_id in existing_items:
                # Keep existing item with its status
                new_items.append(existing_items[item_id])
            else:
                # Create new TODO item
                new_items.append(
                    PlanItem(
                        id=item_id,
                        description=item_data.get("description", ""),
                        instruction=item_data.get("instruction", ""),
                        parent_branch=item_data.get("parent_branch", "main"),
                        priority=item_data.get("priority", 0),
                        depends_on=item_data.get("depends_on", []),
                        status=PlanItemStatus.todo,
                    )
                )

        self._plan = Plan(
            id=f"plan-{new_revision:04d}",
            summary=plan_data.get("summary", ""),
            items=new_items,
            created_at=datetime.datetime.now(datetime.UTC),
            revision=new_revision,
        )
        logger.info(
            "Loaded plan revision %d with %d items",
            new_revision,
            len(new_items),
        )

    # -- Internal helpers ------------------------------------------------

    def _get_eligible_items(self) -> list[PlanItem]:
        """Return TODO items with all dependencies satisfied."""
        if self._plan is None:
            return []

        completed_ids = {it.id for it in self._plan.items if it.status == PlanItemStatus.complete}

        eligible: list[PlanItem] = []
        for item in self._plan.items:
            if item.status != PlanItemStatus.todo:
                continue

            # Check dependencies
            deps_satisfied = all(dep_id in completed_ids for dep_id in item.depends_on)
            if not deps_satisfied:
                continue

            # Check branch resolution
            if item.parent_branch.startswith("$plan-"):
                ref_id = item.parent_branch[1:]  # remove $
                ref_item = self._find_item(ref_id)
                if ref_item is None or ref_item.status != PlanItemStatus.complete:
                    continue
                if not ref_item.assigned_branch:
                    continue

            eligible.append(item)

        return eligible

    def _resolve_branch(self, parent_branch: str) -> str | None:
        """Resolve $plan-XXXX references to actual branch names."""
        if not parent_branch.startswith("$plan-"):
            return parent_branch

        ref_id = parent_branch[1:]  # remove $
        ref_item = self._find_item(ref_id)
        if ref_item is None:
            logger.warning("Plan item reference %s not found", ref_id)
            return None

        if ref_item.status != PlanItemStatus.complete:
            return None

        return ref_item.assigned_branch

    def _find_item(self, item_id: str) -> PlanItem | None:
        """Find a plan item by ID."""
        if self._plan is None:
            return None
        for item in self._plan.items:
            if item.id == item_id:
                return item
        return None

    def _find_item_by_candidate(
        self,
        candidate_id: str,
    ) -> PlanItem | None:
        """Find the plan item assigned to a candidate."""
        if self._plan is None:
            return None
        for item in self._plan.items:
            if item.assigned_candidate_id == candidate_id:
                return item
        return None
