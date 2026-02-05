"""Events pane widget showing live event feed."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import RichLog

from aurelia.core.models import Event


class EventsPane(Vertical):
    """Live event feed showing recent events."""

    DEFAULT_CSS = """
    EventsPane {
        height: 1fr;
        padding: 1;
    }

    EventsPane RichLog {
        height: 1fr;
        border: solid $surface-darken-1;
        padding: 0 1;
        scrollbar-gutter: stable;
    }
    """

    def compose(self):
        """Compose the pane layout."""
        yield RichLog(id="events-log", highlight=True, markup=True, wrap=True)

    def update_events(self, events: list[Event]) -> None:
        """Update the events log with recent events."""
        log = self.query_one("#events-log", RichLog)
        log.clear()

        # Show last 50 events, oldest first
        for event in events[-50:]:
            line = self._format_event(event)
            log.write(line)

    def _format_event(self, event: Event) -> str:
        """Format a single event for display."""
        # Timestamp
        timestamp = event.timestamp.strftime("%H:%M:%S")

        # Color-code event type
        color = self._get_event_color(event.type)

        # Format key data fields
        data_parts = []
        for key, value in list(event.data.items())[:4]:
            # Truncate long values
            str_val = str(value)
            if len(str_val) > 20:
                str_val = str_val[:17] + "..."
            data_parts.append(f"{key}={str_val}")

        data_str = " ".join(data_parts) if data_parts else ""

        return f"[dim]{timestamp}[/] {color}{event.type}[/] {data_str}"

    def _get_event_color(self, event_type: str) -> str:
        """Get color markup for event type."""
        if "failed" in event_type or "error" in event_type:
            return "[red]"
        if "completed" in event_type or "succeeded" in event_type:
            return "[green]"
        if "started" in event_type or "created" in event_type:
            return "[blue]"
        if "evaluated" in event_type:
            return "[cyan]"
        if "heartbeat" in event_type:
            return "[dim]"
        if "terminated" in event_type or "stopped" in event_type:
            return "[yellow]"
        return "[white]"
