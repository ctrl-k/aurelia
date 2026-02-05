"""Tests for the monitoring TUI."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    RuntimeState,
    Task,
    TaskStatus,
)
from aurelia.monitor.state import MonitorState, StateReader


class TestStateReader:
    """Tests for the StateReader class."""

    async def test_aurelia_dir_exists_false(self, tmp_path):
        """Test aurelia_dir_exists returns False when no .aurelia dir."""
        reader = StateReader(tmp_path)
        assert reader.aurelia_dir_exists() is False

    async def test_aurelia_dir_exists_true(self, tmp_path):
        """Test aurelia_dir_exists returns True when .aurelia exists."""
        (tmp_path / ".aurelia").mkdir()
        reader = StateReader(tmp_path)
        assert reader.aurelia_dir_exists() is True

    async def test_read_state_empty_dir(self, tmp_path):
        """Test reading state from directory with no state files."""
        aurelia_dir = tmp_path / ".aurelia"
        aurelia_dir.mkdir()
        (aurelia_dir / "state").mkdir()
        (aurelia_dir / "logs").mkdir()

        reader = StateReader(tmp_path)
        state = await reader.read_state()

        assert state.runtime.status == "stopped"
        assert state.tasks == []
        assert state.candidates == []
        assert state.evaluations == []
        assert state.plan is None
        assert state.recent_events == []

    async def test_read_state_with_runtime(self, tmp_path):
        """Test reading state with runtime.json present."""
        aurelia_dir = tmp_path / ".aurelia"
        state_dir = aurelia_dir / "state"
        state_dir.mkdir(parents=True)
        (aurelia_dir / "logs").mkdir()

        runtime_data = {
            "status": "running",
            "heartbeat_count": 10,
            "total_tasks_dispatched": 5,
            "total_tasks_completed": 3,
            "total_tasks_failed": 1,
        }
        (state_dir / "runtime.json").write_text(json.dumps(runtime_data))

        reader = StateReader(tmp_path)
        state = await reader.read_state()

        assert state.runtime.status == "running"
        assert state.runtime.heartbeat_count == 10
        assert state.runtime.total_tasks_dispatched == 5

    async def test_read_state_with_tasks(self, tmp_path):
        """Test reading state with tasks.json present."""
        aurelia_dir = tmp_path / ".aurelia"
        state_dir = aurelia_dir / "state"
        state_dir.mkdir(parents=True)
        (aurelia_dir / "logs").mkdir()

        tasks_data = [
            {
                "id": "task-0001",
                "thread_id": "task-0001",
                "component": "coder",
                "branch": "aurelia/cand-0001",
                "instruction": "Improve the code",
                "status": "running",
                "context": {},
                "created_at": datetime.now(UTC).isoformat(),
            },
        ]
        (state_dir / "tasks.json").write_text(json.dumps(tasks_data))

        reader = StateReader(tmp_path)
        state = await reader.read_state()

        assert len(state.tasks) == 1
        assert state.tasks[0].id == "task-0001"
        assert state.tasks[0].status == TaskStatus.running


class TestMonitorState:
    """Tests for the MonitorState dataclass."""

    def test_running_tasks_filter(self):
        """Test running_tasks property filters correctly."""
        tasks = [
            Task(
                id="task-0001",
                thread_id="task-0001",
                component="coder",
                branch="b1",
                instruction="x",
                status=TaskStatus.running,
                context={},
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-0002",
                thread_id="task-0002",
                component="coder",
                branch="b2",
                instruction="y",
                status=TaskStatus.pending,
                context={},
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-0003",
                thread_id="task-0003",
                component="coder",
                branch="b3",
                instruction="z",
                status=TaskStatus.success,
                context={},
                created_at=datetime.now(UTC),
            ),
        ]

        state = MonitorState(
            runtime=RuntimeState(),
            tasks=tasks,
            candidates=[],
            evaluations=[],
            plan=None,
            recent_events=[],
            last_updated=datetime.now(UTC),
        )

        running = state.running_tasks
        assert len(running) == 1
        assert running[0].id == "task-0001"

    def test_pending_tasks_filter(self):
        """Test pending_tasks property filters correctly."""
        tasks = [
            Task(
                id="task-0001",
                thread_id="task-0001",
                component="coder",
                branch="b1",
                instruction="x",
                status=TaskStatus.pending,
                context={},
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-0002",
                thread_id="task-0002",
                component="coder",
                branch="b2",
                instruction="y",
                status=TaskStatus.running,
                context={},
                created_at=datetime.now(UTC),
            ),
        ]

        state = MonitorState(
            runtime=RuntimeState(),
            tasks=tasks,
            candidates=[],
            evaluations=[],
            plan=None,
            recent_events=[],
            last_updated=datetime.now(UTC),
        )

        pending = state.pending_tasks
        assert len(pending) == 1
        assert pending[0].id == "task-0001"

    def test_active_candidates_filter(self):
        """Test active_candidates property filters correctly."""
        candidates = [
            Candidate(
                id="cand-0001",
                branch="aurelia/cand-0001",
                status=CandidateStatus.active,
                created_at=datetime.now(UTC),
            ),
            Candidate(
                id="cand-0002",
                branch="aurelia/cand-0002",
                status=CandidateStatus.evaluating,
                created_at=datetime.now(UTC),
            ),
            Candidate(
                id="cand-0003",
                branch="aurelia/cand-0003",
                status=CandidateStatus.succeeded,
                created_at=datetime.now(UTC),
            ),
        ]

        state = MonitorState(
            runtime=RuntimeState(),
            tasks=[],
            candidates=candidates,
            evaluations=[],
            plan=None,
            recent_events=[],
            last_updated=datetime.now(UTC),
        )

        active = state.active_candidates
        assert len(active) == 2
        assert {c.id for c in active} == {"cand-0001", "cand-0002"}

    def test_succeeded_candidates_filter(self):
        """Test succeeded_candidates property filters correctly."""
        candidates = [
            Candidate(
                id="cand-0001",
                branch="aurelia/cand-0001",
                status=CandidateStatus.succeeded,
                created_at=datetime.now(UTC),
            ),
            Candidate(
                id="cand-0002",
                branch="aurelia/cand-0002",
                status=CandidateStatus.failed,
                created_at=datetime.now(UTC),
            ),
        ]

        state = MonitorState(
            runtime=RuntimeState(),
            tasks=[],
            candidates=candidates,
            evaluations=[],
            plan=None,
            recent_events=[],
            last_updated=datetime.now(UTC),
        )

        succeeded = state.succeeded_candidates
        assert len(succeeded) == 1
        assert succeeded[0].id == "cand-0001"


class TestMonitorWidgets:
    """Tests for monitor widget functionality."""

    def test_header_widget_imports(self):
        """Test HeaderWidget can be imported."""
        from aurelia.monitor.widgets.header import HeaderWidget

        assert HeaderWidget is not None

    def test_tasks_pane_imports(self):
        """Test TasksPane can be imported."""
        from aurelia.monitor.widgets.tasks import TasksPane

        assert TasksPane is not None

    def test_candidates_pane_imports(self):
        """Test CandidatesPane can be imported."""
        from aurelia.monitor.widgets.candidates import CandidatesPane

        assert CandidatesPane is not None

    def test_plan_pane_imports(self):
        """Test PlanPane can be imported."""
        from aurelia.monitor.widgets.plan import PlanPane

        assert PlanPane is not None

    def test_events_pane_imports(self):
        """Test EventsPane can be imported."""
        from aurelia.monitor.widgets.events import EventsPane

        assert EventsPane is not None

    def test_stats_pane_imports(self):
        """Test StatsPane can be imported."""
        from aurelia.monitor.widgets.stats import StatsPane

        assert StatsPane is not None


class TestMonitorApp:
    """Tests for the MonitorApp class."""

    def test_app_imports(self):
        """Test MonitorApp can be imported."""
        from aurelia.monitor.app import MonitorApp, run_monitor

        assert MonitorApp is not None
        assert run_monitor is not None

    def test_app_instantiates(self, tmp_path):
        """Test MonitorApp can be instantiated."""
        from aurelia.monitor.app import MonitorApp

        app = MonitorApp(tmp_path)
        assert app._project_dir == tmp_path
        assert app._poll_interval == 2.0

    def test_app_custom_poll_interval(self, tmp_path):
        """Test MonitorApp accepts custom poll interval."""
        from aurelia.monitor.app import MonitorApp

        app = MonitorApp(tmp_path, poll_interval=5.0)
        assert app._poll_interval == 5.0


class TestModalWidgets:
    """Tests for detail modal widgets."""

    def test_task_detail_modal_imports(self):
        """Test TaskDetailModal can be imported."""
        from aurelia.monitor.widgets.task_detail import TaskDetailModal

        assert TaskDetailModal is not None

    def test_task_detail_modal_instantiates(self):
        """Test TaskDetailModal can be instantiated with a task."""
        from aurelia.monitor.widgets.task_detail import TaskDetailModal

        task = Task(
            id="task-0001",
            thread_id="task-0001",
            component="coder",
            branch="aurelia/cand-0001",
            instruction="Improve the code",
            status=TaskStatus.running,
            context={},
            created_at=datetime.now(UTC),
        )
        modal = TaskDetailModal(task)
        assert modal._task == task

    def test_candidate_detail_modal_imports(self):
        """Test CandidateDetailModal can be imported."""
        from aurelia.monitor.widgets.candidate_detail import CandidateDetailModal

        assert CandidateDetailModal is not None

    def test_candidate_detail_modal_instantiates(self):
        """Test CandidateDetailModal can be instantiated."""
        from aurelia.core.models import Evaluation
        from aurelia.monitor.widgets.candidate_detail import CandidateDetailModal

        candidate = Candidate(
            id="cand-0001",
            branch="aurelia/cand-0001",
            status=CandidateStatus.active,
            created_at=datetime.now(UTC),
        )
        evaluations = [
            Evaluation(
                id="eval-0001",
                task_id="task-0001",
                candidate_branch="aurelia/cand-0001",
                commit_sha="abc123",
                metrics={"accuracy": 0.95},
                raw_output="",
                timestamp=datetime.now(UTC),
                passed=True,
            )
        ]
        modal = CandidateDetailModal(candidate, evaluations)
        assert modal._candidate == candidate
        assert len(modal._evaluations) == 1

    def test_candidate_detail_modal_filters_evaluations(self):
        """Test CandidateDetailModal filters evaluations by branch."""
        from aurelia.core.models import Evaluation
        from aurelia.monitor.widgets.candidate_detail import CandidateDetailModal

        candidate = Candidate(
            id="cand-0001",
            branch="aurelia/cand-0001",
            status=CandidateStatus.active,
            created_at=datetime.now(UTC),
        )
        evaluations = [
            Evaluation(
                id="eval-0001",
                task_id="task-0001",
                candidate_branch="aurelia/cand-0001",
                commit_sha="abc123",
                metrics={"accuracy": 0.95},
                raw_output="",
                timestamp=datetime.now(UTC),
                passed=True,
            ),
            Evaluation(
                id="eval-0002",
                task_id="task-0002",
                candidate_branch="aurelia/cand-0002",  # Different branch
                commit_sha="def456",
                metrics={"accuracy": 0.85},
                raw_output="",
                timestamp=datetime.now(UTC),
                passed=False,
            ),
        ]
        modal = CandidateDetailModal(candidate, evaluations)
        # Should only include eval for cand-0001
        assert len(modal._evaluations) == 1
        assert modal._evaluations[0].id == "eval-0001"

    def test_widgets_export_from_init(self):
        """Test that modals are exported from widgets __init__."""
        from aurelia.monitor.widgets import CandidateDetailModal, TaskDetailModal

        assert TaskDetailModal is not None
        assert CandidateDetailModal is not None
