"""Aurelia runtime orchestrator.

Manages the heartbeat loop, candidate lifecycle, task dispatch,
and graceful shutdown via signal handling.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from aurelia.components.coder import CoderComponent
from aurelia.components.evaluator import EvaluatorComponent
from aurelia.components.planner import PlannerComponent
from aurelia.components.presubmit import PresubmitComponent
from aurelia.core.config import (
    default_component_specs,
    load_workflow_config,
    make_runtime_config,
)
from aurelia.core.events import EventLog
from aurelia.core.ids import IdGenerator
from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    ComponentSpec,
    Evaluation,
    Event,
    RuntimeConfig,
    RuntimeState,
    Task,
    TaskResult,
    TaskStatus,
)
from aurelia.core.state import StateStore
from aurelia.dispatch.base import DefaultDispatcher, DispatchContext, Dispatcher
from aurelia.git.repo import GitRepo
from aurelia.git.worktree import WorktreeManager
from aurelia.llm.client import LLMClient, MockLLMClient
from aurelia.sandbox.docker import DockerClient
from aurelia.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Runtime:
    """Aurelia runtime orchestrator.

    Manages the heartbeat loop, candidate lifecycle, task dispatch,
    and graceful shutdown via signal handling.
    """

    def __init__(
        self,
        project_dir: Path,
        use_mock: bool = False,
        docker_client: DockerClient | None = None,
    ) -> None:
        self._project_dir = project_dir
        self._aurelia_dir = project_dir / ".aurelia"
        self._use_mock = use_mock
        self._docker_client = docker_client
        self._shutdown_event = asyncio.Event()
        self._running_asyncio_tasks: dict[str, asyncio.Task[TaskResult | None]] = {}

        # Initialized in start()
        self._state_store: StateStore
        self._event_log: EventLog
        self._runtime_state: RuntimeState
        self._id_gen: IdGenerator
        self._config: RuntimeConfig
        self._git: GitRepo
        self._worktrees: WorktreeManager
        self._tool_registry: ToolRegistry
        self._llm_client: LLMClient
        self._component_specs: dict[str, ComponentSpec]
        self._dispatcher: Dispatcher
        self._tasks: list[Task]
        self._candidates: list[Candidate]
        self._evaluations: list[Evaluation]

    # -- Public API -------------------------------------------------------

    async def start(self) -> None:
        """Initialize all infrastructure and run the heartbeat loop."""
        # 1. Load workflow config
        workflow = load_workflow_config(self._aurelia_dir)
        self._config = make_runtime_config(workflow)
        self._component_specs = default_component_specs()

        # 2. Initialize stores
        self._state_store = StateStore(self._aurelia_dir)
        await self._state_store.initialize(self._config)

        self._event_log = EventLog(self._aurelia_dir / "logs" / "events.jsonl")

        # 3. Load persisted state
        self._runtime_state = await self._state_store.load_runtime()
        self._id_gen = IdGenerator(self._runtime_state)
        self._tasks = await self._state_store.load_tasks()
        self._candidates = await self._state_store.load_candidates()
        self._evaluations = await self._state_store.load_evaluations()

        # 4. Git repo setup
        self._git = GitRepo(self._project_dir)
        self._worktrees = WorktreeManager(self._git, self._aurelia_dir / "worktrees")

        # 5. Tool registry
        self._tool_registry = ToolRegistry()
        await self._tool_registry.register_builtin()

        # 6. LLM client (used by planner; coder uses Gemini CLI directly)
        self._llm_client = MockLLMClient()
        if self._use_mock:
            logger.info("Running with mock LLM client")

        # 7. Initialize dispatcher
        self._dispatcher = await self._create_dispatcher()

        # 8. Crash recovery (before marking as running)
        await self._recover_from_crash()

        # 9. Update runtime state
        self._runtime_state.status = "running"
        self._runtime_state.started_at = datetime.datetime.now(datetime.UTC)

        # 10. Write PID file
        pid_path = self._aurelia_dir / "state" / "pid"
        pid_path.write_text(str(os.getpid()))

        # 9. Install signal handlers
        self._install_signal_handlers()

        # 10. Emit runtime.started event
        await self._emit("runtime.started", {"pid": os.getpid()})
        await self._persist_state()

        logger.info("Aurelia runtime started (pid=%d)", os.getpid())

        try:
            await self._heartbeat_loop()
        finally:
            # Cancel all background tasks
            for handle in self._running_asyncio_tasks.values():
                handle.cancel()
            if self._running_asyncio_tasks:
                await asyncio.gather(
                    *self._running_asyncio_tasks.values(),
                    return_exceptions=True,
                )
            for task in self._tasks:
                if task.status == TaskStatus.running:
                    task.status = TaskStatus.cancelled
                    task.completed_at = datetime.datetime.now(datetime.UTC)
            self._running_asyncio_tasks.clear()

            self._runtime_state.status = "stopped"
            self._runtime_state.stopped_at = datetime.datetime.now(datetime.UTC)
            await self._emit("runtime.stopped", {})
            await self._persist_state()

            pid_path.unlink(missing_ok=True)
            logger.info("Aurelia runtime stopped")

    async def stop(self) -> None:
        """Signal the runtime to shut down gracefully."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()

    # -- Dispatcher -------------------------------------------------------

    async def _create_dispatcher(self) -> Dispatcher:
        """Instantiate the configured dispatcher."""
        instruction = self._read_instruction()
        ctx = DispatchContext(
            project_dir=self._project_dir,
            instruction=instruction,
            candidates=self._candidates,
            evaluations=self._evaluations,
            config=self._config,
        )

        if self._config.dispatcher == "planner":
            from aurelia.dispatch.planner import (
                PlannerDispatcher,
            )

            plan = await self._state_store.load_plan()
            dispatcher: Dispatcher = PlannerDispatcher(plan=plan)
        else:
            dispatcher = DefaultDispatcher()

        await dispatcher.initialize(ctx)
        return dispatcher

    # -- Heartbeat loop ---------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Run heartbeat cycles until shutdown is signalled."""
        while not self._shutdown_event.is_set():
            try:
                await self._heartbeat_cycle()
            except Exception:
                logger.exception("Error in heartbeat cycle")

            await self._persist_state()

            # Wait for either the interval or shutdown
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._config.heartbeat_interval_s,
                )
                break  # Shutdown was signalled
            except TimeoutError:
                continue  # Interval elapsed, loop again

    async def _heartbeat_cycle(self) -> None:
        """Execute one heartbeat iteration.

        1. Emit heartbeat, read instruction
        2. Collect completed background tasks
        3. Advance pipeline for each active candidate
        4. Check termination conditions
        5. Launch new candidates up to concurrency limit
        """
        self._runtime_state.heartbeat_count += 1
        now = datetime.datetime.now(datetime.UTC)
        self._runtime_state.last_heartbeat_at = now

        await self._emit(
            "heartbeat",
            {"count": self._runtime_state.heartbeat_count},
        )

        # 1. Collect completed background tasks
        await self._collect_completed_tasks()

        # 3. Advance pipeline for each active candidate
        for candidate in self._get_active_candidates():
            await self._advance_candidate(candidate)

        # 4. Check termination
        term_reason = self._should_terminate()
        if term_reason is not None:
            logger.info("Termination: %s", term_reason)
            await self._emit(
                "runtime.terminated",
                {
                    "reason": term_reason,
                    "total_candidates": len(self._candidates),
                },
            )
            self._shutdown_event.set()
            return

        # 5. Handle planning if dispatcher needs it
        if self._dispatcher.needs_planning():
            await self._maybe_run_planner()

        # 6. Fill concurrency slots from dispatcher
        active = len(self._get_active_candidates())
        while (
            active < self._config.max_concurrent_tasks
            and len(self._running_asyncio_tasks) < self._config.max_concurrent_tasks
        ):
            request = self._dispatcher.select_next()
            if request is None:
                break
            candidate = await self._create_candidate(parent_branch=request.parent_branch)
            await self._dispatch_coder(
                candidate,
                request.instruction,
                extra_context=request.context,
            )
            if request.plan_item_id:
                self._dispatcher.mark_assigned(request.plan_item_id, candidate)
            active += 1

    async def _advance_candidate(
        self,
        candidate: Candidate,
    ) -> None:
        """Advance the task pipeline for a single candidate.

        Pipeline: coder → presubmit → evaluator → finish.
        """
        coder_task = self._find_task(candidate.branch, "coder")

        if coder_task is None:
            # Coder should have been dispatched when the candidate
            # was created.  If missing (e.g. after crash recovery),
            # skip this candidate — the dispatcher will re-evaluate.
            return

        if coder_task.status == TaskStatus.running:
            return

        if coder_task.status == TaskStatus.failed:
            await self._fail_candidate(candidate, coder_task)
            return

        if coder_task.status != TaskStatus.success:
            return

        # Coder succeeded — check presubmit
        presubmit_task = self._find_task(candidate.branch, "presubmit")

        if presubmit_task is None:
            if len(self._running_asyncio_tasks) < self._config.max_concurrent_tasks:
                await self._dispatch_presubmit(candidate)
            return

        if presubmit_task.status == TaskStatus.running:
            return

        if presubmit_task.status == TaskStatus.failed:
            await self._fail_candidate(candidate, presubmit_task)
            return

        if presubmit_task.status != TaskStatus.success:
            return

        # Presubmit succeeded — check evaluator
        eval_task = self._find_task(candidate.branch, "evaluator")

        if eval_task is None:
            if len(self._running_asyncio_tasks) < self._config.max_concurrent_tasks:
                await self._dispatch_evaluator(candidate)
            return

        if eval_task.status == TaskStatus.success:
            await self._finish_candidate(candidate, eval_task)
        elif eval_task.status == TaskStatus.failed:
            await self._fail_candidate(candidate, eval_task)

    async def _fail_candidate(self, candidate: Candidate, failed_task: Task) -> None:
        """Mark a candidate as failed due to a task failure."""
        candidate.status = CandidateStatus.failed
        error = failed_task.result.error if failed_task.result else "unknown"
        await self._emit(
            "candidate.failed",
            {
                "candidate_id": candidate.id,
                "branch": candidate.branch,
                "error": error,
            },
        )
        self._dispatcher.on_candidate_completed(candidate, None)

    # -- Helper methods --------------------------------------------------

    def _read_instruction(self) -> str:
        """Read the problem instruction from README.md."""
        readme = self._project_dir / "README.md"
        if readme.exists():
            return readme.read_text()
        return ""

    def _get_active_candidates(self) -> list[Candidate]:
        """Return all active or evaluating candidates."""
        return [
            c
            for c in self._candidates
            if c.status
            in (
                CandidateStatus.active,
                CandidateStatus.evaluating,
            )
        ]

    def _find_task(self, branch: str, component: str) -> Task | None:
        """Find the most recent task for a branch and component."""
        for task in reversed(self._tasks):
            if task.branch == branch and task.component == component:
                return task
        return None

    async def _create_candidate(
        self,
        parent_branch: str = "main",
    ) -> Candidate:
        """Create a new candidate branch and worktree."""
        cand_id = self._id_gen.next_id("cand")
        branch = f"aurelia/{cand_id}"

        logger.info(
            "Branching %s from %s",
            branch,
            parent_branch,
        )

        await self._git.create_branch(branch, from_branch=parent_branch)
        wt_path = await self._worktrees.create(branch)

        candidate = Candidate(
            id=cand_id,
            branch=branch,
            parent_branch=parent_branch,
            status=CandidateStatus.active,
            created_at=datetime.datetime.now(datetime.UTC),
            worktree_path=str(wt_path),
        )
        self._candidates.append(candidate)

        await self._emit(
            "candidate.created",
            {
                "candidate_id": cand_id,
                "branch": branch,
                "parent_branch": parent_branch,
            },
        )
        return candidate

    async def _dispatch_coder(
        self,
        candidate: Candidate,
        instruction: str,
        extra_context: dict[str, Any] | None = None,
    ) -> None:
        """Create and execute a coder task for the candidate."""
        context = {
            "worktree_path": candidate.worktree_path,
            "problem_description": self._read_instruction(),
        }
        if extra_context:
            context.update(extra_context)
        # Ensure feedback and attempt_number are set
        context.setdefault("feedback", self._build_feedback_text())
        context.setdefault("attempt_number", len(self._candidates))
        task = Task(
            id=self._id_gen.next_id("task"),
            thread_id=self._id_gen.next_id("thread"),
            component="coder",
            branch=candidate.branch,
            instruction=instruction,
            status=TaskStatus.pending,
            context=context,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._tasks.append(task)
        self._runtime_state.total_tasks_dispatched += 1

        await self._emit(
            "task.created",
            {"task_id": task.id, "component": "coder"},
        )
        await self._launch_task(task, "coder")

    async def _dispatch_presubmit(self, candidate: Candidate) -> None:
        """Create and launch a presubmit task in the background."""
        task = Task(
            id=self._id_gen.next_id("task"),
            thread_id=self._id_gen.next_id("thread"),
            component="presubmit",
            branch=candidate.branch,
            instruction="Run presubmit checks",
            status=TaskStatus.pending,
            context={
                "worktree_path": candidate.worktree_path,
                "checks": self._config.presubmit_checks,
            },
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._tasks.append(task)
        self._runtime_state.total_tasks_dispatched += 1

        await self._emit(
            "task.created",
            {
                "task_id": task.id,
                "component": "presubmit",
            },
        )
        await self._launch_task(task, "presubmit")

    async def _dispatch_evaluator(self, candidate: Candidate) -> None:
        """Create and launch an evaluator task in the background."""
        candidate.status = CandidateStatus.evaluating

        task = Task(
            id=self._id_gen.next_id("task"),
            thread_id=self._id_gen.next_id("thread"),
            component="evaluator",
            branch=candidate.branch,
            instruction="Run evaluation",
            status=TaskStatus.pending,
            context={
                "worktree_path": candidate.worktree_path,
            },
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._tasks.append(task)
        self._runtime_state.total_tasks_dispatched += 1

        await self._emit(
            "task.created",
            {"task_id": task.id, "component": "evaluator"},
        )
        await self._launch_task(task, "evaluator")

    async def _dispatch_planner(self) -> None:
        """Create and launch a planner task in the background."""
        # Create a temporary worktree from main for the planner
        planner_branch = "__planner__"
        try:
            await self._git.create_branch(planner_branch, from_branch="main")
        except Exception:
            pass  # branch may already exist
        wt_path = await self._worktrees.create(planner_branch)

        planning_ctx = self._dispatcher.get_planning_context()
        task = Task(
            id=self._id_gen.next_id("task"),
            thread_id=self._id_gen.next_id("thread"),
            component="planner",
            branch=planner_branch,
            instruction="Generate an improvement plan",
            status=TaskStatus.pending,
            context={
                "worktree_path": str(wt_path),
                "planning_context": planning_ctx,
                "problem_description": self._read_instruction(),
            },
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._tasks.append(task)
        self._runtime_state.total_tasks_dispatched += 1

        await self._emit(
            "task.created",
            {"task_id": task.id, "component": "planner"},
        )
        await self._launch_task(task, "planner")

    async def _maybe_run_planner(self) -> None:
        """Launch planner if needed and not already running."""
        planner_task = self._find_task("__planner__", "planner")

        if planner_task is not None:
            if planner_task.status in (
                TaskStatus.pending,
                TaskStatus.running,
            ):
                return  # already running

            if planner_task.status == TaskStatus.success:
                wt_path = planner_task.context.get("worktree_path", "")
                self._dispatcher.on_planning_completed(planner_task.result, wt_path)
                # Clear the planner task so future calls
                # can detect needs_planning() again
                self._tasks = [t for t in self._tasks if t.id != planner_task.id]
                return

        # No planner task or previous one failed — launch new
        if len(self._running_asyncio_tasks) < self._config.max_concurrent_tasks:
            await self._dispatch_planner()

    async def _launch_task(self, task: Task, component_name: str) -> None:
        """Launch a task as a background asyncio.Task."""
        task.status = TaskStatus.running
        task.started_at = datetime.datetime.now(datetime.UTC)
        await self._emit("task.started", {"task_id": task.id})

        coro = self._run_component(task, component_name)
        handle = asyncio.create_task(coro, name=f"aurelia-{task.id}")
        self._running_asyncio_tasks[task.id] = handle

    async def _collect_completed_tasks(self) -> None:
        """Poll background tasks and update state for any that finished."""
        completed_ids: list[str] = []
        for task_id, handle in self._running_asyncio_tasks.items():
            if not handle.done():
                continue
            completed_ids.append(task_id)

            task = next(t for t in self._tasks if t.id == task_id)
            try:
                result = handle.result()
                task.result = result
                task.status = TaskStatus.success
                task.completed_at = datetime.datetime.now(datetime.UTC)
                self._runtime_state.total_tasks_completed += 1

                # Aggregate token usage from coder tasks
                if result and result.metrics:
                    tokens = result.metrics.get("tokens_total", 0)
                    self._runtime_state.total_tokens_used += int(tokens)

                await self._emit(
                    "task.completed",
                    {
                        "task_id": task.id,
                        "summary": (result.summary if result else ""),
                    },
                )
            except Exception as exc:
                task.status = TaskStatus.failed
                task.completed_at = datetime.datetime.now(datetime.UTC)
                task.result = TaskResult(
                    id=self._id_gen.next_id("result"),
                    summary="Task execution failed",
                    error=str(exc),
                )
                self._runtime_state.total_tasks_failed += 1

                await self._emit(
                    "task.failed",
                    {
                        "task_id": task.id,
                        "error": str(exc),
                    },
                )
                logger.exception("Task %s failed", task.id)

        for task_id in completed_ids:
            del self._running_asyncio_tasks[task_id]

    async def _run_component(self, task: Task, component_name: str) -> TaskResult:
        """Instantiate and run the named component."""
        if component_name == "coder":
            spec = self._component_specs["coder"]
            component = CoderComponent(
                spec=spec,
                llm_client=self._llm_client,
                tool_registry=self._tool_registry,
                event_log=self._event_log,
                id_generator=self._id_gen,
                project_dir=self._project_dir,
                docker_client=self._docker_client,
            )
            return await component.execute(task)

        if component_name == "presubmit":
            presubmit = PresubmitComponent(self._event_log, self._id_gen)
            return await presubmit.execute(task)

        if component_name == "evaluator":
            evaluator = EvaluatorComponent(self._event_log, self._id_gen)
            return await evaluator.execute(task)

        if component_name == "planner":
            spec = self._component_specs["planner"]
            planner = PlannerComponent(
                spec=spec,
                llm_client=self._llm_client,
                tool_registry=self._tool_registry,
                event_log=self._event_log,
                id_generator=self._id_gen,
                project_dir=self._project_dir,
                docker_client=self._docker_client,
            )
            return await planner.execute(task)

        msg = f"Unknown component: {component_name}"
        raise ValueError(msg)

    async def _finish_candidate(
        self,
        candidate: Candidate,
        eval_task: Task,
    ) -> None:
        """Record evaluation result and update candidate status."""
        metrics: dict[str, Any] = eval_task.result.metrics if eval_task.result else {}
        passed = self._check_metrics_pass(metrics)

        # Try to retrieve the latest commit SHA
        try:
            commits = await self._git.log(candidate.branch, n=1)
            commit_sha: str = commits[0]["sha"] if commits else "unknown"
        except Exception:
            commit_sha = "unknown"

        evaluation = Evaluation(
            id=self._id_gen.next_id("eval"),
            task_id=eval_task.id,
            candidate_branch=candidate.branch,
            commit_sha=commit_sha,
            metrics=metrics,
            raw_output=(eval_task.result.summary if eval_task.result else ""),
            timestamp=datetime.datetime.now(datetime.UTC),
            passed=passed,
        )

        self._evaluations.append(evaluation)
        candidate.evaluations.append(evaluation.id)
        candidate.status = CandidateStatus.succeeded if passed else CandidateStatus.failed

        await self._emit(
            "candidate.evaluated",
            {
                "candidate_id": candidate.id,
                "branch": candidate.branch,
                "metrics": metrics,
                "passed": passed,
            },
        )
        self._dispatcher.on_candidate_completed(candidate, evaluation)

    # -- Feedback and evolution helpers ------------------------------------

    def _build_feedback_text(self) -> str:
        """Format previous attempts into feedback for the coder."""
        if not self._evaluations:
            return ""

        lines: list[str] = []
        eval_by_id = {e.id: e for e in self._evaluations}

        for i, cand in enumerate(self._candidates, 1):
            for eval_id in cand.evaluations:
                ev = eval_by_id.get(eval_id)
                if ev is None:
                    continue
                lines.append(f"### Attempt {i}")
                lines.append(f"- Status: {'PASSED' if ev.passed else 'FAILED'}")
                lines.append(f"- Metrics: {json.dumps(ev.metrics)}")
                if ev.raw_output:
                    lines.append(f"- Output: {ev.raw_output[:200]}")
                lines.append("")

        return "\n".join(lines)

    def _get_best_candidate(self) -> Candidate | None:
        """Find the succeeded candidate with the highest average metric."""
        eval_by_id = {e.id: e for e in self._evaluations}
        best: Candidate | None = None
        best_score = -1.0

        for cand in self._candidates:
            if cand.status != CandidateStatus.succeeded:
                continue
            for eval_id in cand.evaluations:
                ev = eval_by_id.get(eval_id)
                if ev is None or not ev.passed:
                    continue
                nums = [v for v in ev.metrics.values() if isinstance(v, (int, float))]
                if not nums:
                    continue
                score = sum(nums) / len(nums)
                if score > best_score:
                    best_score = score
                    best = cand

        return best

    def _check_metrics_pass(self, metrics: dict[str, Any]) -> bool:
        """Check if metrics satisfy the termination condition.

        If a termination condition is configured (e.g. 'accuracy>=0.95'),
        returns True only when all specified metrics meet their thresholds.
        If no termination condition is set, returns True (any completed
        evaluation is considered passing).
        """
        conditions = self._parse_termination_condition()
        if not conditions:
            return True
        for metric, threshold in conditions:
            val = metrics.get(metric)
            if val is None or not isinstance(val, (int, float)) or val < threshold:
                return False
        return True

    def _should_terminate(self) -> str | None:
        """Check if the runtime should stop creating candidates.

        Returns a reason string when termination is warranted,
        or None to continue.  Never terminates while background
        tasks are still running.
        """
        if self._running_asyncio_tasks:
            return None
        # Check metric-based termination
        if self._config.termination_condition:
            for ev in self._evaluations:
                if ev.passed:
                    logger.info(
                        "Termination: metrics meet condition '%s'",
                        self._config.termination_condition,
                    )
                    return "termination_condition_met"

        # Check abandon threshold
        failed_count = sum(1 for c in self._candidates if c.status == CandidateStatus.failed)
        if failed_count >= self._config.candidate_abandon_threshold:
            logger.warning(
                "Abandon threshold: %d failed candidates",
                failed_count,
            )
            return "abandon_threshold_reached"

        return None

    def _parse_termination_condition(
        self,
    ) -> list[tuple[str, float]]:
        """Parse 'accuracy>=0.95,f1>=0.9' into [(metric, threshold)]."""
        if not self._config.termination_condition:
            return []
        conditions: list[tuple[str, float]] = []
        for part in self._config.termination_condition.split(","):
            part = part.strip()
            if ">=" in part:
                metric, value = part.split(">=", 1)
                conditions.append((metric.strip(), float(value.strip())))
        return conditions

    # -- Event emission and state persistence -----------------------------

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to the event log."""
        await self._event_log.append(
            Event(
                seq=self._id_gen.next_event_seq(),
                type=event_type,
                timestamp=datetime.datetime.now(datetime.UTC),
                data=data,
            )
        )

    async def _persist_state(self) -> None:
        """Persist runtime state, tasks, and candidates."""
        await self._state_store.save_runtime(self._runtime_state)
        await self._state_store.save_tasks(self._tasks)
        await self._state_store.save_candidates(self._candidates)
        await self._state_store.save_evaluations(self._evaluations)

    # -- Crash recovery ---------------------------------------------------

    async def _recover_from_crash(self) -> None:
        """Detect and recover from a previous unclean shutdown."""
        pid_path = self._aurelia_dir / "state" / "pid"

        # 1. Check for stale PID file
        if pid_path.exists():
            old_pid_str = pid_path.read_text().strip()
            try:
                old_pid = int(old_pid_str)
                os.kill(old_pid, 0)
                # Process is still running
                msg = (
                    f"Another Aurelia instance is running"
                    f" (pid={old_pid}). Remove {pid_path}"
                    f" manually if this is stale."
                )
                raise RuntimeError(msg)
            except (
                ValueError,
                ProcessLookupError,
                PermissionError,
            ):
                logger.warning(
                    "Detected stale PID file (pid=%s); recovering",
                    old_pid_str,
                )
                pid_path.unlink(missing_ok=True)

        # 2. Mark interrupted tasks as failed
        recovered_count = 0
        for task in self._tasks:
            if task.status == TaskStatus.running:
                task.status = TaskStatus.failed
                task.completed_at = datetime.datetime.now(datetime.UTC)
                task.result = TaskResult(
                    id=self._id_gen.next_id("result"),
                    summary="Task interrupted by crash",
                    error="runtime_crash_recovery",
                )
                self._runtime_state.total_tasks_failed += 1
                recovered_count += 1

        # 3. Mark interrupted candidates as failed
        for candidate in self._candidates:
            if candidate.status in (
                CandidateStatus.active,
                CandidateStatus.evaluating,
            ):
                coder = self._find_task(candidate.branch, "coder")
                evalu = self._find_task(candidate.branch, "evaluator")
                had_crash = (
                    coder is not None
                    and coder.result is not None
                    and coder.result.error == "runtime_crash_recovery"
                ) or (
                    evalu is not None
                    and evalu.result is not None
                    and evalu.result.error == "runtime_crash_recovery"
                )
                if had_crash:
                    candidate.status = CandidateStatus.failed

        # 4. Clean up orphaned worktrees
        try:
            active_worktrees = await self._worktrees.list_active()
            active_branches = {
                c.branch
                for c in self._candidates
                if c.status
                in (
                    CandidateStatus.active,
                    CandidateStatus.evaluating,
                )
            }
            for branch, _path in active_worktrees:
                if branch.startswith("aurelia/") and branch not in active_branches:
                    try:
                        await self._worktrees.remove(branch)
                        logger.info(
                            "Cleaned up orphaned worktree: %s",
                            branch,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to clean orphaned worktree: %s",
                            branch,
                        )
        except Exception:
            logger.warning("Could not enumerate worktrees for cleanup")

        if recovered_count > 0:
            logger.warning(
                "Crash recovery: marked %d interrupted tasks as failed",
                recovered_count,
            )
            await self._emit(
                "runtime.recovered",
                {"tasks_recovered": recovered_count},
            )
            await self._persist_state()

    # -- Signal handling --------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)
