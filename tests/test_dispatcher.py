"""Tests for Dispatcher implementations."""

from __future__ import annotations

import datetime

from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    Evaluation,
    Plan,
    PlanItem,
    PlanItemStatus,
    RuntimeConfig,
)
from aurelia.dispatch.base import DefaultDispatcher, DispatchContext


def _make_dispatch_context(
    instruction: str = "Solve the problem",
    candidates: list[Candidate] | None = None,
    evaluations: list[Evaluation] | None = None,
) -> DispatchContext:
    return DispatchContext(
        project_dir="/fake/project",
        instruction=instruction,
        candidates=candidates or [],
        evaluations=evaluations or [],
        config=RuntimeConfig(),
    )


class TestDefaultDispatcherSelectNext:
    async def test_select_next_from_main(self):
        dispatcher = DefaultDispatcher()
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is not None
        assert request.parent_branch == "main"
        assert "Improve the solution" in request.instruction

    async def test_select_next_from_best_candidate(self):
        succeeded_cand = Candidate(
            id="cand-0001",
            branch="aurelia/cand-0001",
            status=CandidateStatus.succeeded,
            created_at=datetime.datetime.now(datetime.UTC),
            evaluations=["eval-0001"],
        )
        passed_eval = Evaluation(
            id="eval-0001",
            task_id="task-0001",
            candidate_branch="aurelia/cand-0001",
            commit_sha="abc123",
            metrics={"accuracy": 0.9},
            raw_output="",
            timestamp=datetime.datetime.now(datetime.UTC),
            passed=True,
        )

        dispatcher = DefaultDispatcher()
        ctx = _make_dispatch_context(
            candidates=[succeeded_cand],
            evaluations=[passed_eval],
        )
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is not None
        assert request.parent_branch == "aurelia/cand-0001"


class TestDefaultDispatcherNeedsPlanning:
    async def test_needs_planning_always_false(self):
        dispatcher = DefaultDispatcher()
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        assert dispatcher.needs_planning() is False


class TestPlannerDispatcherSelectNext:
    async def test_select_next_returns_todo_item(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test plan",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="First improvement",
                    instruction="Do thing 1",
                    parent_branch="main",
                    status=PlanItemStatus.todo,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is not None
        assert request.parent_branch == "main"
        assert request.instruction == "Do thing 1"
        assert request.plan_item_id == "plan-0001"

    async def test_select_next_respects_dependencies(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test plan",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="First",
                    instruction="First task",
                    status=PlanItemStatus.todo,
                ),
                PlanItem(
                    id="plan-0002",
                    description="Second (depends on first)",
                    instruction="Second task",
                    depends_on=["plan-0001"],
                    status=PlanItemStatus.todo,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        # Should get plan-0001 since plan-0002 is blocked
        assert request is not None
        assert request.plan_item_id == "plan-0001"

    async def test_select_next_respects_priority(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test plan",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Low priority",
                    instruction="Low",
                    priority=10,
                    status=PlanItemStatus.todo,
                ),
                PlanItem(
                    id="plan-0002",
                    description="High priority",
                    instruction="High",
                    priority=1,
                    status=PlanItemStatus.todo,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        # Should get plan-0002 (lower priority number = higher priority)
        assert request is not None
        assert request.plan_item_id == "plan-0002"

    async def test_select_next_resolves_branch_ref(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test plan",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="First",
                    instruction="First",
                    status=PlanItemStatus.complete,
                    assigned_branch="aurelia/cand-0001",
                ),
                PlanItem(
                    id="plan-0002",
                    description="Second",
                    instruction="Second",
                    parent_branch="$plan-0001",
                    depends_on=["plan-0001"],
                    status=PlanItemStatus.todo,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is not None
        assert request.plan_item_id == "plan-0002"
        # $plan-0001 resolves to aurelia/cand-0001
        assert request.parent_branch == "aurelia/cand-0001"

    async def test_select_next_returns_none_when_empty(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Empty plan",
            items=[],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is None

    async def test_select_next_returns_none_when_all_assigned(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="All assigned",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Already assigned",
                    instruction="In progress",
                    status=PlanItemStatus.assigned,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        request = dispatcher.select_next()

        assert request is None


class TestPlannerDispatcherOnCandidateCompleted:
    async def test_marks_complete_on_success(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Item",
                    instruction="Do it",
                    status=PlanItemStatus.assigned,
                    assigned_candidate_id="cand-0001",
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        candidate = Candidate(
            id="cand-0001",
            branch="aurelia/cand-0001",
            status=CandidateStatus.succeeded,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        evaluation = Evaluation(
            id="eval-0001",
            task_id="task-0001",
            candidate_branch="aurelia/cand-0001",
            commit_sha="abc",
            metrics={"accuracy": 0.95},
            raw_output="",
            timestamp=datetime.datetime.now(datetime.UTC),
            passed=True,
        )

        dispatcher.on_candidate_completed(candidate, evaluation)

        assert plan.items[0].status == PlanItemStatus.complete

    async def test_marks_failed_on_failure(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="Test",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Item",
                    instruction="Do it",
                    status=PlanItemStatus.assigned,
                    assigned_candidate_id="cand-0001",
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        candidate = Candidate(
            id="cand-0001",
            branch="aurelia/cand-0001",
            status=CandidateStatus.failed,
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher.on_candidate_completed(candidate, None)

        assert plan.items[0].status == PlanItemStatus.failed


class TestPlannerDispatcherNeedsPlanning:
    async def test_needs_planning_when_no_plan(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        dispatcher = PlannerDispatcher(plan=None)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        assert dispatcher.needs_planning() is True

    async def test_needs_planning_when_todos_exhausted(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="All done",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Done",
                    instruction="Already done",
                    status=PlanItemStatus.complete,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        assert dispatcher.needs_planning() is True

    async def test_does_not_need_planning_when_todos_exist(self):
        from aurelia.dispatch.planner import PlannerDispatcher

        plan = Plan(
            id="plan-0000",
            summary="In progress",
            items=[
                PlanItem(
                    id="plan-0001",
                    description="Todo",
                    instruction="Do this",
                    status=PlanItemStatus.todo,
                ),
            ],
            created_at=datetime.datetime.now(datetime.UTC),
        )

        dispatcher = PlannerDispatcher(plan=plan)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        assert dispatcher.needs_planning() is False


class TestPlannerDispatcherOnPlanningCompleted:
    async def test_parses_plan_json(self, tmp_path):
        from aurelia.dispatch.planner import PlannerDispatcher

        dispatcher = PlannerDispatcher(plan=None)
        ctx = _make_dispatch_context()
        await dispatcher.initialize(ctx)

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        plan_data = {
            "summary": "New plan",
            "items": [
                {
                    "id": "plan-0001",
                    "description": "First task",
                    "instruction": "Do the first thing",
                    "parent_branch": "main",
                    "priority": 0,
                },
            ],
        }
        (worktree / "plan.json").write_text(
            __import__("json").dumps(plan_data)
        )

        from aurelia.core.models import TaskResult
        result = TaskResult(
            id="result-0001",
            summary="Plan complete",
        )
        dispatcher.on_planning_completed(result, str(worktree))

        assert dispatcher.plan is not None
        assert dispatcher.plan.summary == "New plan"
        assert len(dispatcher.plan.items) == 1
        assert dispatcher.plan.items[0].id == "plan-0001"
        assert dispatcher.plan.items[0].status == PlanItemStatus.todo
