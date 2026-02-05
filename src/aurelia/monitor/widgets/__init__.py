"""Monitor TUI widgets."""

from aurelia.monitor.widgets.candidates import CandidatesPane
from aurelia.monitor.widgets.events import EventsPane
from aurelia.monitor.widgets.header import HeaderWidget
from aurelia.monitor.widgets.plan import PlanPane
from aurelia.monitor.widgets.stats import StatsPane
from aurelia.monitor.widgets.tasks import TasksPane

__all__ = [
    "CandidatesPane",
    "EventsPane",
    "HeaderWidget",
    "PlanPane",
    "StatsPane",
    "TasksPane",
]
