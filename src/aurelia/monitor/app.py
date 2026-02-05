"""Main Textual application for the monitoring TUI."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, TabbedContent, TabPane

from aurelia.monitor.state import MonitorState, StateReader
from aurelia.monitor.widgets import (
    CandidatesPane,
    EventsPane,
    HeaderWidget,
    PlanPane,
    StatsPane,
    TasksPane,
)


class MonitorApp(App):
    """Aurelia real-time monitoring dashboard."""

    CSS_PATH = "styles.tcss"
    TITLE = "Aurelia Monitor"
    SUB_TITLE = "Real-time Runtime Dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Prev", show=False),
    ]

    def __init__(
        self,
        project_dir: Path,
        poll_interval: float = 2.0,
    ) -> None:
        super().__init__()
        self._project_dir = project_dir
        self._poll_interval = poll_interval
        self._state_reader = StateReader(project_dir)
        self._current_state: MonitorState | None = None

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header()
        yield HeaderWidget(id="runtime-header")

        with Horizontal(id="main-layout"):
            # Left sidebar - Tasks
            yield TasksPane(id="tasks-pane")

            # Main content area - Tabbed
            with TabbedContent(id="main-tabs"):
                with TabPane("Candidates", id="tab-candidates"):
                    yield CandidatesPane(id="candidates-pane")
                with TabPane("Plan", id="tab-plan"):
                    yield PlanPane(id="plan-pane")
                with TabPane("Events", id="tab-events"):
                    yield EventsPane(id="events-pane")
                with TabPane("Stats", id="tab-stats"):
                    yield StatsPane(id="stats-pane")

        yield Footer()

    async def on_mount(self) -> None:
        """Start the polling loop when app mounts."""
        if not self._state_reader.aurelia_dir_exists():
            self.notify(
                "No .aurelia directory found. Run 'aurelia init' first.",
                severity="warning",
                timeout=5,
            )

        # Initial load
        await self._refresh_state()

        # Start polling timer
        self.set_interval(self._poll_interval, self._refresh_state)

    async def _refresh_state(self) -> None:
        """Poll state files and update all widgets."""
        try:
            self._current_state = await self._state_reader.read_state()
            self._update_widgets()
        except Exception as e:
            self.notify(f"Error reading state: {e}", severity="error", timeout=3)

    def _update_widgets(self) -> None:
        """Push state to all child widgets."""
        if self._current_state is None:
            return

        state = self._current_state

        # Update header
        try:
            header = self.query_one("#runtime-header", HeaderWidget)
            header.update_state(state.runtime)
        except Exception:
            pass

        # Update tasks pane
        try:
            tasks_pane = self.query_one("#tasks-pane", TasksPane)
            tasks_pane.update_tasks(state.tasks)
        except Exception:
            pass

        # Update candidates pane
        try:
            candidates_pane = self.query_one("#candidates-pane", CandidatesPane)
            candidates_pane.update_candidates(state.candidates, state.evaluations)
        except Exception:
            pass

        # Update plan pane
        try:
            plan_pane = self.query_one("#plan-pane", PlanPane)
            plan_pane.update_plan(state.plan)
        except Exception:
            pass

        # Update events pane
        try:
            events_pane = self.query_one("#events-pane", EventsPane)
            events_pane.update_events(state.recent_events)
        except Exception:
            pass

        # Update stats pane
        try:
            stats_pane = self.query_one("#stats-pane", StatsPane)
            stats_pane.update_stats(state)
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Manual refresh action."""
        self.run_worker(self._refresh_state())
        self.notify("Refreshed", timeout=1)


def run_monitor(project_dir: Path, poll_interval: float = 2.0) -> None:
    """Entry point for the monitor command."""
    app = MonitorApp(project_dir, poll_interval)
    app.run()
