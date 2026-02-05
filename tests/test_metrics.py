"""Tests for Prometheus metrics."""

from __future__ import annotations

from prometheus_client import REGISTRY

from aurelia.metrics import (
    CANDIDATES_TOTAL,
    COST_TOTAL,
    EVALUATION_SCORE,
    HEARTBEAT_COUNT,
    LAST_HEARTBEAT,
    RUNNING_TASKS,
    RUNTIME_STATUS,
    TASK_DURATION,
    TASKS_TOTAL,
    TOKENS_TOTAL,
)


class TestMetricsDefinitions:
    """Test that metrics are properly defined."""

    def test_runtime_status_exists(self) -> None:
        """Test RUNTIME_STATUS gauge exists."""
        assert RUNTIME_STATUS is not None
        RUNTIME_STATUS.set(1)
        assert RUNTIME_STATUS._value.get() == 1.0

    def test_tasks_total_counter(self) -> None:
        """Test TASKS_TOTAL counter with labels."""
        # Counter increments
        TASKS_TOTAL.labels(component="coder", status="success").inc()
        TASKS_TOTAL.labels(component="evaluator", status="failed").inc()
        # Verify it doesn't error

    def test_task_duration_histogram(self) -> None:
        """Test TASK_DURATION histogram."""
        TASK_DURATION.labels(component="coder").observe(5.5)
        TASK_DURATION.labels(component="evaluator").observe(120.0)

    def test_candidates_total_counter(self) -> None:
        """Test CANDIDATES_TOTAL counter."""
        CANDIDATES_TOTAL.labels(status="succeeded").inc()
        CANDIDATES_TOTAL.labels(status="failed").inc()

    def test_evaluation_score_gauge(self) -> None:
        """Test EVALUATION_SCORE gauge."""
        EVALUATION_SCORE.labels(metric="accuracy").set(0.95)
        EVALUATION_SCORE.labels(metric="f1").set(0.88)

    def test_tokens_total_counter(self) -> None:
        """Test TOKENS_TOTAL counter."""
        TOKENS_TOTAL.labels(type="input").inc(1000)
        TOKENS_TOTAL.labels(type="output").inc(500)

    def test_cost_total_counter(self) -> None:
        """Test COST_TOTAL counter."""
        COST_TOTAL.inc(0.0125)

    def test_heartbeat_metrics(self) -> None:
        """Test heartbeat gauges."""
        HEARTBEAT_COUNT.set(10)
        assert HEARTBEAT_COUNT._value.get() == 10.0

        LAST_HEARTBEAT.set(1704067200.0)  # Some timestamp
        assert LAST_HEARTBEAT._value.get() == 1704067200.0

    def test_running_tasks_gauge(self) -> None:
        """Test RUNNING_TASKS gauge."""
        RUNNING_TASKS.set(3)
        assert RUNNING_TASKS._value.get() == 3.0


class TestMetricsServer:
    """Test the metrics server module."""

    def test_start_metrics_server_import(self) -> None:
        """Test that start_metrics_server can be imported."""
        from aurelia.metrics.server import start_metrics_server

        assert callable(start_metrics_server)


class TestMetricsInRegistry:
    """Test that metrics are registered in the default registry."""

    def test_metrics_registered(self) -> None:
        """Test that our custom metrics appear in the registry."""
        # Get all metric names from registry
        metric_names = [m.name for m in REGISTRY.collect()]

        # Check some of our metrics are present
        # Note: Counters don't have _total suffix in the name attribute
        assert "aurelia_runtime_status" in metric_names
        assert "aurelia_tasks" in metric_names  # Counter without _total
        assert "aurelia_heartbeat_count" in metric_names
