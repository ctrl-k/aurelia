"""Prometheus metrics for Aurelia."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Runtime info
RUNTIME_STATUS = Gauge("aurelia_runtime_status", "Runtime status (1=running, 0=stopped)")

# Task metrics
TASKS_TOTAL = Counter("aurelia_tasks_total", "Total tasks", ["component", "status"])
TASK_DURATION = Histogram(
    "aurelia_task_duration_seconds",
    "Task duration in seconds",
    ["component"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

# Candidate metrics
CANDIDATES_TOTAL = Counter("aurelia_candidates_total", "Total candidates", ["status"])
EVALUATION_SCORE = Gauge("aurelia_evaluation_score", "Latest evaluation score", ["metric"])

# Token/cost metrics
TOKENS_TOTAL = Counter("aurelia_tokens_total", "Total tokens used", ["type"])
COST_TOTAL = Counter("aurelia_cost_usd_total", "Total cost in USD")

# Heartbeat metrics
HEARTBEAT_COUNT = Gauge("aurelia_heartbeat_count", "Current heartbeat count")
LAST_HEARTBEAT = Gauge("aurelia_last_heartbeat_timestamp", "Last heartbeat timestamp")

# Running task count
RUNNING_TASKS = Gauge("aurelia_running_tasks", "Number of currently running tasks")

__all__ = [
    "RUNTIME_STATUS",
    "TASKS_TOTAL",
    "TASK_DURATION",
    "CANDIDATES_TOTAL",
    "EVALUATION_SCORE",
    "TOKENS_TOTAL",
    "COST_TOTAL",
    "HEARTBEAT_COUNT",
    "LAST_HEARTBEAT",
    "RUNNING_TASKS",
]
