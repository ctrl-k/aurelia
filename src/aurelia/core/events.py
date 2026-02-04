"""Append-only JSONL event log with crash-recovery support.

Events are serialized as one JSON object per line. Malformed or blank lines
are silently skipped on read so the log tolerates incomplete writes after a
crash.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anyio

from aurelia.core.models import Event


class EventLog:
    """Append-only, fsync-backed JSONL event log.

    Parameters
    ----------
    path:
        Filesystem path to the ``.jsonl`` file.  Parent directories are
        created automatically on the first :meth:`append`.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def append(self, event: Event) -> None:
        """Serialize *event* to JSON, append as a single line, and fsync."""

        def _write() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = event.model_dump_json() + "\n"
            fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)

        await anyio.to_thread.run_sync(_write)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def _load_events(self) -> list[Event]:
        """Read and parse all events, skipping blank or malformed lines."""
        apath = anyio.Path(self._path)
        if not await apath.exists():
            return []

        raw = await apath.read_text(encoding="utf-8")
        events: list[Event] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(Event.model_validate_json(stripped))
            except Exception:  # noqa: BLE001 – crash recovery: skip bad lines
                continue
        return events

    # ------------------------------------------------------------------
    # Public readers
    # ------------------------------------------------------------------

    async def read_all(self) -> list[Event]:
        """Return every valid event in the log."""
        return await self._load_events()

    async def read_since(self, seq: int) -> list[Event]:
        """Return events whose ``seq`` is >= *seq*."""
        return [e for e in await self._load_events() if e.seq >= seq]

    async def find_unmatched(self, start_type: str, end_type: str) -> list[Event]:
        """Find *start_type* events with no corresponding *end_type* event.

        Matching is done via ``data["task_id"]``.  A start event is
        considered unmatched if no end event with the same ``task_id``
        exists anywhere in the log.  This is used for crash recovery
        (e.g. tasks that were started but never completed).
        """
        events = await self._load_events()

        completed_task_ids: set[Any] = set()
        for e in events:
            if e.type == end_type and "task_id" in e.data:
                completed_task_ids.add(e.data["task_id"])

        return [
            e
            for e in events
            if e.type == start_type
            and "task_id" in e.data
            and e.data["task_id"] not in completed_task_ids
        ]
