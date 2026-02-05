"""Tests for the append-only JSONL event log."""

from datetime import UTC, datetime

from aurelia.core.events import EventLog
from aurelia.core.models import Event

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _event(seq: int, type_: str = "test", **data) -> Event:
    return Event(seq=seq, type=type_, timestamp=NOW, data=data)


class TestAppendAndReadAll:
    async def test_round_trip(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        e1 = _event(1, "task.started", task_id="t1")
        e2 = _event(2, "task.completed", task_id="t1")
        await log.append(e1)
        await log.append(e2)

        events = await log.read_all()
        assert len(events) == 2
        assert events[0] == e1
        assert events[1] == e2

    async def test_empty_file_returns_empty(self, tmp_path):
        log_path = tmp_path / "events.jsonl"
        log_path.touch()
        log = EventLog(log_path)
        assert await log.read_all() == []

    async def test_missing_file_returns_empty(self, tmp_path):
        log = EventLog(tmp_path / "nonexistent.jsonl")
        assert await log.read_all() == []


class TestReadSince:
    async def test_filters_by_seq(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        for i in range(1, 6):
            await log.append(_event(i))

        events = await log.read_since(3)
        assert len(events) == 3
        assert [e.seq for e in events] == [3, 4, 5]

    async def test_all_events_when_seq_is_1(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_event(1))
        await log.append(_event(2))
        assert len(await log.read_since(1)) == 2


class TestFindUnmatched:
    async def test_finds_started_but_not_completed(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_event(1, "task.started", task_id="t1"))
        await log.append(_event(2, "task.started", task_id="t2"))
        await log.append(_event(3, "task.completed", task_id="t1"))

        unmatched = await log.find_unmatched("task.started", "task.completed")
        assert len(unmatched) == 1
        assert unmatched[0].data["task_id"] == "t2"

    async def test_all_matched_returns_empty(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        await log.append(_event(1, "task.started", task_id="t1"))
        await log.append(_event(2, "task.completed", task_id="t1"))

        unmatched = await log.find_unmatched("task.started", "task.completed")
        assert unmatched == []

    async def test_no_events_returns_empty(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        assert await log.find_unmatched("task.started", "task.completed") == []


class TestCrashRecovery:
    async def test_blank_lines_skipped(self, tmp_path):
        log_path = tmp_path / "events.jsonl"
        e = _event(1)
        log_path.write_text("\n" + e.model_dump_json() + "\n\n\n")
        log = EventLog(log_path)
        events = await log.read_all()
        assert len(events) == 1
        assert events[0] == e

    async def test_malformed_lines_skipped(self, tmp_path):
        log_path = tmp_path / "events.jsonl"
        e = _event(1)
        log_path.write_text("not valid json\n" + e.model_dump_json() + "\n{broken\n")
        log = EventLog(log_path)
        events = await log.read_all()
        assert len(events) == 1
        assert events[0] == e
