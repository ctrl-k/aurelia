"""Tests for core Pydantic models — serialization round-trips."""

from datetime import UTC, datetime

from aurelia.core.models import (
    Candidate,
    CandidateStatus,
    ComponentSpec,
    Event,
    LLMTransaction,
    ModelConfig,
    RuntimeState,
    Task,
    TaskStatus,
)

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2025, 6, 15, 13, 0, 0, tzinfo=UTC)


def _round_trip(model):
    """Dump to JSON and parse back; return the reconstituted object."""
    json_str = model.model_dump_json()
    return type(model).model_validate_json(json_str)


class TestRuntimeStateRoundTrip:
    def test_default(self):
        state = RuntimeState()
        assert _round_trip(state) == state

    def test_with_values(self):
        state = RuntimeState(
            status="running",
            started_at=NOW,
            next_event_seq=42,
            next_seq={"task": 10, "cand": 3},
            heartbeat_count=7,
            total_tokens_used=50000,
            total_cost_usd=1.23,
        )
        assert _round_trip(state) == state


class TestTaskRoundTrip:
    def test_minimal(self):
        task = Task(
            id="task-0001",
            thread_id="thread-0001",
            component="planner",
            branch="main",
            instruction="Do something",
            created_at=NOW,
        )
        assert _round_trip(task) == task

    def test_full(self):
        task = Task(
            id="task-0002",
            thread_id="thread-0001",
            component="coder",
            branch="cand-0001",
            parent_task_id="task-0001",
            instruction="Implement feature X",
            status=TaskStatus.running,
            context={"key": "value"},
            created_at=NOW,
            started_at=LATER,
        )
        assert _round_trip(task) == task


class TestCandidateRoundTrip:
    def test_minimal(self):
        cand = Candidate(
            id="cand-0001",
            branch="cand-0001",
            created_at=NOW,
        )
        assert _round_trip(cand) == cand

    def test_full(self):
        cand = Candidate(
            id="cand-0002",
            branch="cand-0002",
            parent_branch="main",
            status=CandidateStatus.evaluating,
            evaluations=["eval-0001"],
            created_at=NOW,
            worktree_path="/tmp/wt/cand-0002",
        )
        assert _round_trip(cand) == cand


class TestEventRoundTrip:
    def test_basic(self):
        event = Event(seq=1, type="task.started", timestamp=NOW)
        assert _round_trip(event) == event

    def test_with_data(self):
        event = Event(
            seq=5,
            type="task.completed",
            timestamp=LATER,
            data={"task_id": "task-0001", "result": "ok"},
        )
        assert _round_trip(event) == event


class TestLLMTransactionRoundTrip:
    def test_full(self):
        txn = LLMTransaction(
            id="llm-0001",
            event_seq=3,
            task_id="task-0001",
            thread_id="thread-0001",
            component="coder",
            model="gemini-2.5-flash",
            request_contents=[{"role": "user", "parts": [{"text": "hello"}]}],
            request_hash="abc123",
            response_content={"text": "world"},
            tools=[{"name": "read_file"}],
            config={"temperature": 0.0},
            input_tokens=10,
            output_tokens=20,
            latency_ms=150,
            timestamp=NOW,
            from_cache=False,
        )
        assert _round_trip(txn) == txn


class TestComponentSpecRoundTrip:
    def test_minimal(self):
        spec = ComponentSpec(id="comp-0001", name="planner", role="planning")
        assert _round_trip(spec) == spec

    def test_with_model_config(self):
        spec = ComponentSpec(
            id="comp-0002",
            name="coder",
            role="code generation",
            model=ModelConfig(provider="openai", model="gpt-4o", temperature=0.7),
            tools=["read_file", "write_file"],
        )
        assert _round_trip(spec) == spec
