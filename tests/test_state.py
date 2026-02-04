"""Tests for the atomic JSON state store."""

from datetime import UTC, datetime

from aurelia.core.models import RuntimeConfig, RuntimeState, Task, TaskStatus
from aurelia.core.state import StateStore

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_task(id_: str) -> Task:
    return Task(
        id=id_,
        thread_id="thread-0001",
        component="planner",
        branch="main",
        instruction="Do work",
        status=TaskStatus.pending,
        created_at=NOW,
    )


class TestRuntimeRoundTrip:
    async def test_save_load(self, tmp_path):
        store = StateStore(tmp_path)
        state = RuntimeState(
            status="running",
            started_at=NOW,
            next_event_seq=10,
            next_seq={"task": 5},
        )
        await store.save_runtime(state)
        loaded = await store.load_runtime()
        assert loaded == state

    async def test_missing_returns_default(self, tmp_path):
        store = StateStore(tmp_path)
        loaded = await store.load_runtime()
        assert loaded == RuntimeState()


class TestTasksRoundTrip:
    async def test_save_load(self, tmp_path):
        store = StateStore(tmp_path)
        tasks = [_make_task("task-0001"), _make_task("task-0002")]
        await store.save_tasks(tasks)
        loaded = await store.load_tasks()
        assert loaded == tasks

    async def test_missing_returns_empty(self, tmp_path):
        store = StateStore(tmp_path)
        assert await store.load_tasks() == []


class TestAtomicWrites:
    async def test_tmp_file_does_not_linger(self, tmp_path):
        store = StateStore(tmp_path)
        await store.save_runtime(RuntimeState())
        state_dir = tmp_path / "state"
        tmp_files = list(state_dir.glob("*.tmp"))
        assert tmp_files == []

    async def test_backup_rotation(self, tmp_path):
        store = StateStore(tmp_path)
        state_dir = tmp_path / "state"

        # First write: no backup yet
        await store.save_runtime(RuntimeState(status="v1"))
        assert not (state_dir / "runtime.json.bak.1").exists()

        # Second write: .bak.1 should exist
        await store.save_runtime(RuntimeState(status="v2"))
        assert (state_dir / "runtime.json.bak.1").exists()

        # Third write: .bak.2 should exist
        await store.save_runtime(RuntimeState(status="v3"))
        assert (state_dir / "runtime.json.bak.1").exists()
        assert (state_dir / "runtime.json.bak.2").exists()


class TestCorruptionRecovery:
    async def test_corrupted_primary_falls_back_to_backup(self, tmp_path):
        store = StateStore(tmp_path)
        state_dir = tmp_path / "state"

        # Write good state twice so .bak.1 is created
        good_state = RuntimeState(status="good")
        await store.save_runtime(good_state)
        await store.save_runtime(good_state)

        # Corrupt the primary file
        (state_dir / "runtime.json").write_text("{{not json}}")

        loaded = await store.load_runtime()
        assert loaded == good_state


class TestInitialize:
    async def test_creates_directories(self, tmp_path):
        store = StateStore(tmp_path)
        await store.initialize(RuntimeConfig())
        for subdir in ["state", "logs", "cache", "reports", "config"]:
            assert (tmp_path / subdir).is_dir()
