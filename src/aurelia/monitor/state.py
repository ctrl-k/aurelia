"""State reader for the monitoring TUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aurelia.core.events import EventLog
from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    Evaluation,
    Event,
    Plan,
    RuntimeState,
    Task,
    TaskStatus,
)
from aurelia.core.state import StateStore


@dataclass
class MonitorState:
    """Aggregated snapshot of all Aurelia state for the monitor."""

    runtime: RuntimeState
    tasks: list[Task]
    candidates: list[Candidate]
    evaluations: list[Evaluation]
    plan: Plan | None
    recent_events: list[Event]
    last_updated: datetime

    @property
    def running_tasks(self) -> list[Task]:
        """Return tasks currently running."""
        return [t for t in self.tasks if t.status == TaskStatus.running]

    @property
    def pending_tasks(self) -> list[Task]:
        """Return tasks waiting to run."""
        return [t for t in self.tasks if t.status == TaskStatus.pending]

    @property
    def active_candidates(self) -> list[Candidate]:
        """Return candidates being worked on."""
        return [
            c
            for c in self.candidates
            if c.status in (CandidateStatus.active, CandidateStatus.evaluating)
        ]

    @property
    def succeeded_candidates(self) -> list[Candidate]:
        """Return candidates that passed evaluation."""
        return [c for c in self.candidates if c.status == CandidateStatus.succeeded]

    @property
    def failed_candidates(self) -> list[Candidate]:
        """Return candidates that failed."""
        return [c for c in self.candidates if c.status == CandidateStatus.failed]


class StateReader:
    """Async state reader that polls .aurelia/ files."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._aurelia_dir = project_dir / ".aurelia"
        self._state_store = StateStore(self._aurelia_dir)
        self._event_log = EventLog(self._aurelia_dir / "logs" / "events.jsonl")

    def aurelia_dir_exists(self) -> bool:
        """Check if .aurelia directory exists."""
        return self._aurelia_dir.exists()

    async def read_state(self) -> MonitorState:
        """Read all state files and return aggregated snapshot."""
        runtime = await self._state_store.load_runtime()
        tasks = await self._state_store.load_tasks()
        candidates = await self._state_store.load_candidates()
        evaluations = await self._state_store.load_evaluations()
        plan = await self._state_store.load_plan()

        # Read recent events (last 100)
        try:
            all_events = await self._event_log.read_all()
            recent_events = all_events[-100:] if all_events else []
        except FileNotFoundError:
            recent_events = []

        return MonitorState(
            runtime=runtime,
            tasks=tasks,
            candidates=candidates,
            evaluations=evaluations,
            plan=plan,
            recent_events=recent_events,
            last_updated=datetime.now(UTC),
        )
