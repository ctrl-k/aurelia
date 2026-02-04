"""Deterministic, sequential, type-prefixed ID generator.

IDs are formatted as "<prefix>-<seq>" where seq is zero-padded to at least
4 digits. The counters are maintained in RuntimeState.next_seq and
RuntimeState.next_event_seq for global event ordering.
"""

from __future__ import annotations

from aurelia.core.models import RuntimeState


class IdGenerator:
    """Generates sequential IDs backed by RuntimeState counters."""

    def __init__(self, state: RuntimeState) -> None:
        self._state = state

    def next_id(self, prefix: str) -> str:
        """Generate the next ID for the given type prefix.

        Example: next_id("task") -> "task-0001", "task-0002", ...
        """
        current = self._state.next_seq.get(prefix, 1)
        self._state.next_seq[prefix] = current + 1
        return f"{prefix}-{current:04d}"

    def next_event_seq(self) -> int:
        """Return the next global event sequence number."""
        seq = self._state.next_event_seq
        self._state.next_event_seq = seq + 1
        return seq
