"""Tests for the deterministic ID generator."""

from aurelia.core.ids import IdGenerator
from aurelia.core.models import RuntimeState


class TestNextId:
    def test_sequential_with_prefix(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        assert gen.next_id("task") == "task-000001"
        assert gen.next_id("task") == "task-000002"
        assert gen.next_id("task") == "task-000003"

    def test_zero_padding(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        id_ = gen.next_id("cand")
        assert id_ == "cand-000001"
        assert len(id_.split("-")[1]) == 6

    def test_independent_prefixes(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        assert gen.next_id("task") == "task-000001"
        assert gen.next_id("cand") == "cand-000001"
        assert gen.next_id("task") == "task-000002"
        assert gen.next_id("cand") == "cand-000002"

    def test_overflow_past_999999(self):
        state = RuntimeState(next_seq={"task": 999999})
        gen = IdGenerator(state)
        assert gen.next_id("task") == "task-999999"
        assert gen.next_id("task") == "task-1000000"

    def test_state_is_mutated(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        gen.next_id("task")
        gen.next_id("task")
        assert state.next_seq["task"] == 3


class TestNextEventSeq:
    def test_monotonic(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        seq1 = gen.next_event_seq()
        seq2 = gen.next_event_seq()
        seq3 = gen.next_event_seq()
        assert seq1 == 1
        assert seq2 == 2
        assert seq3 == 3

    def test_starts_from_state(self):
        state = RuntimeState(next_event_seq=100)
        gen = IdGenerator(state)
        assert gen.next_event_seq() == 100
        assert gen.next_event_seq() == 101

    def test_state_is_mutated(self):
        state = RuntimeState()
        gen = IdGenerator(state)
        gen.next_event_seq()
        gen.next_event_seq()
        assert state.next_event_seq == 3
