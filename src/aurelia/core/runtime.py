"""Aurelia runtime orchestrator.

Manages the heartbeat loop, candidate lifecycle, task dispatch,
and graceful shutdown via signal handling.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import signal
from pathlib import Path
from typing import Any

from aurelia.components.coder import CoderComponent
from aurelia.components.evaluator import EvaluatorComponent
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
        self._tasks: list[Task]
        self._candidates: list[Candidate]

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

        self._event_log = EventLog(
            self._aurelia_dir / "logs" / "events.jsonl"
        )

        # 3. Load persisted state
        self._runtime_state = await self._state_store.load_runtime()
        self._id_gen = IdGenerator(self._runtime_state)
        self._tasks = await self._state_store.load_tasks()
        self._candidates = await self._state_store.load_candidates()

        # 4. Git repo setup
        self._git = GitRepo(self._project_dir)
        self._worktrees = WorktreeManager(
            self._git, self._aurelia_dir / "worktrees"
        )

        # 5. Tool registry
        self._tool_registry = ToolRegistry()
        await self._tool_registry.register_builtin()

        # 6. LLM client
        if self._use_mock:
            self._llm_client = MockLLMClient()
        else:
            # Phase 1b only supports mock
            logger.warning(
                "No real LLM provider configured; using mock client"
            )
            self._llm_client = MockLLMClient()

        # 7. Update runtime state
        self._runtime_state.status = "running"
        self._runtime_state.started_at = datetime.datetime.now(
            datetime.UTC
        )

        # 8. Write PID file
        pid_path = self._aurelia_dir / "state" / "pid"
        pid_path.write_text(str(os.getpid()))

        # 9. Install signal handlers
        self._install_signal_handlers()

        # 10. Emit runtime.started event
        await self._emit("runtime.started", {"pid": os.getpid()})
        await self._persist_state()

        logger.info(
            "Aurelia runtime started (pid=%d)", os.getpid()
        )

        try:
            await self._heartbeat_loop()
        finally:
            self._runtime_state.status = "stopped"
            self._runtime_state.stopped_at = datetime.datetime.now(
                datetime.UTC
            )
            await self._emit("runtime.stopped", {})
            await self._persist_state()

            pid_path.unlink(missing_ok=True)
            logger.info("Aurelia runtime stopped")

    async def stop(self) -> None:
        """Signal the runtime to shut down gracefully."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()

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

        Simplified Phase 1b cycle:
        1. Read instruction (detect changes via hash)
        2. Collect completed/failed tasks
        3. If no active candidate, create one (branch + worktree)
        4. If candidate has no running coder task, dispatch coder
        5. If coder completed, dispatch evaluator
        6. If evaluator completed, record evaluation and mark candidate
        7. Persist state
        """
        self._runtime_state.heartbeat_count += 1
        now = datetime.datetime.now(datetime.UTC)
        self._runtime_state.last_heartbeat_at = now

        await self._emit(
            "heartbeat",
            {"count": self._runtime_state.heartbeat_count},
        )

        # 1. Read instruction from README.md
        instruction = self._read_instruction()

        # 2. (Future: collect completed/failed async tasks)

        # 3. Get or create active candidate
        candidate = self._get_active_candidate()
        if candidate is None:
            candidate = await self._create_candidate()

        # 4. Check task pipeline for this candidate
        coder_task = self._find_task(candidate.branch, "coder")
        eval_task = self._find_task(candidate.branch, "evaluator")

        if coder_task is None:
            await self._dispatch_coder(candidate, instruction)
        elif coder_task.status == TaskStatus.running:
            pass  # Coder still running
        elif coder_task.status == TaskStatus.success:
            if eval_task is None:
                await self._dispatch_evaluator(candidate)
            elif eval_task.status == TaskStatus.success:
                await self._finish_candidate(candidate, eval_task)
            elif eval_task.status == TaskStatus.failed:
                candidate.status = CandidateStatus.failed
                error = (
                    eval_task.result.error
                    if eval_task.result
                    else "unknown"
                )
                await self._emit(
                    "candidate.failed",
                    {
                        "candidate_id": candidate.id,
                        "branch": candidate.branch,
                        "error": error,
                    },
                )
        elif coder_task.status == TaskStatus.failed:
            candidate.status = CandidateStatus.failed
            error = (
                coder_task.result.error
                if coder_task.result
                else "unknown"
            )
            await self._emit(
                "candidate.failed",
                {
                    "candidate_id": candidate.id,
                    "branch": candidate.branch,
                    "error": error,
                },
            )

    # -- Helper methods --------------------------------------------------

    def _read_instruction(self) -> str:
        """Read the problem instruction from README.md."""
        readme = self._project_dir / "README.md"
        if readme.exists():
            return readme.read_text()
        return ""

    def _get_active_candidate(self) -> Candidate | None:
        """Return the first active or evaluating candidate."""
        for c in self._candidates:
            if c.status in (
                CandidateStatus.active,
                CandidateStatus.evaluating,
            ):
                return c
        return None

    def _find_task(
        self, branch: str, component: str
    ) -> Task | None:
        """Find the most recent task for a branch and component."""
        for task in reversed(self._tasks):
            if (
                task.branch == branch
                and task.component == component
            ):
                return task
        return None

    async def _create_candidate(self) -> Candidate:
        """Create a new candidate branch and worktree."""
        cand_id = self._id_gen.next_id("cand")
        branch = f"aurelia/{cand_id}"

        await self._git.create_branch(branch)
        wt_path = await self._worktrees.create(branch)

        candidate = Candidate(
            id=cand_id,
            branch=branch,
            parent_branch="main",
            status=CandidateStatus.active,
            created_at=datetime.datetime.now(datetime.UTC),
            worktree_path=str(wt_path),
        )
        self._candidates.append(candidate)

        await self._emit(
            "candidate.created",
            {"candidate_id": cand_id, "branch": branch},
        )
        return candidate

    async def _dispatch_coder(
        self,
        candidate: Candidate,
        instruction: str,
    ) -> None:
        """Create and execute a coder task for the candidate."""
        task = Task(
            id=self._id_gen.next_id("task"),
            thread_id=self._id_gen.next_id("thread"),
            component="coder",
            branch=candidate.branch,
            instruction=f"Improve the solution. {instruction}",
            status=TaskStatus.pending,
            context={
                "worktree_path": candidate.worktree_path,
                "problem_description": self._read_instruction(),
            },
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self._tasks.append(task)
        self._runtime_state.total_tasks_dispatched += 1

        await self._emit(
            "task.created",
            {"task_id": task.id, "component": "coder"},
        )
        await self._execute_task(task, "coder")

    async def _dispatch_evaluator(
        self, candidate: Candidate
    ) -> None:
        """Create and execute an evaluator task."""
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
        await self._execute_task(task, "evaluator")

    async def _execute_task(
        self, task: Task, component_name: str
    ) -> None:
        """Execute a task using the appropriate component."""
        task.status = TaskStatus.running
        task.started_at = datetime.datetime.now(datetime.UTC)
        await self._emit(
            "task.started", {"task_id": task.id}
        )

        try:
            result = await self._run_component(
                task, component_name
            )
            task.result = result
            task.status = TaskStatus.success
            task.completed_at = datetime.datetime.now(
                datetime.UTC
            )
            self._runtime_state.total_tasks_completed += 1

            await self._emit(
                "task.completed",
                {
                    "task_id": task.id,
                    "summary": result.summary,
                },
            )
        except Exception as exc:
            task.status = TaskStatus.failed
            task.completed_at = datetime.datetime.now(
                datetime.UTC
            )
            task.result = TaskResult(
                id=self._id_gen.next_id("result"),
                summary="Task execution failed",
                error=str(exc),
            )
            self._runtime_state.total_tasks_failed += 1

            await self._emit(
                "task.failed",
                {"task_id": task.id, "error": str(exc)},
            )
            logger.exception("Task %s failed", task.id)

    async def _run_component(
        self, task: Task, component_name: str
    ) -> TaskResult:
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

        if component_name == "evaluator":
            evaluator = EvaluatorComponent(
                self._event_log, self._id_gen
            )
            return await evaluator.execute(task)

        msg = f"Unknown component: {component_name}"
        raise ValueError(msg)

    async def _finish_candidate(
        self,
        candidate: Candidate,
        eval_task: Task,
    ) -> None:
        """Record evaluation result and update candidate status."""
        metrics: dict[str, Any] = (
            eval_task.result.metrics if eval_task.result else {}
        )
        passed = all(
            v > 0.5
            for v in metrics.values()
            if isinstance(v, (int, float))
        )

        # Try to retrieve the latest commit SHA
        try:
            commits = await self._git.log(
                candidate.branch, n=1
            )
            commit_sha: str = (
                commits[0]["sha"] if commits else "unknown"
            )
        except Exception:
            commit_sha = "unknown"

        evaluation = Evaluation(
            id=self._id_gen.next_id("eval"),
            task_id=eval_task.id,
            candidate_branch=candidate.branch,
            commit_sha=commit_sha,
            metrics=metrics,
            raw_output=(
                eval_task.result.summary
                if eval_task.result
                else ""
            ),
            timestamp=datetime.datetime.now(datetime.UTC),
            passed=passed,
        )

        candidate.evaluations.append(evaluation.id)
        candidate.status = (
            CandidateStatus.succeeded
            if passed
            else CandidateStatus.failed
        )

        await self._emit(
            "candidate.evaluated",
            {
                "candidate_id": candidate.id,
                "branch": candidate.branch,
                "metrics": metrics,
                "passed": passed,
            },
        )

    # -- Event emission and state persistence -----------------------------

    async def _emit(
        self, event_type: str, data: dict[str, Any]
    ) -> None:
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
        await self._state_store.save_runtime(
            self._runtime_state
        )
        await self._state_store.save_tasks(self._tasks)
        await self._state_store.save_candidates(
            self._candidates
        )

    # -- Signal handling --------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig, self._shutdown_event.set
            )
