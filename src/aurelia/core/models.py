"""Core domain models for Aurelia.

All domain objects are Pydantic BaseModel classes. IDs use deterministic,
sequential, type-prefixed identifiers (e.g. "task-0001").
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------


class ModelConfig(BaseModel):
    """LLM configuration for a component. Fields align with GenerateContentConfig."""

    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    temperature: float = 0.0
    max_output_tokens: int = 8192
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None
    system_instruction: str | None = None
    response_mime_type: str | None = None


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class SandboxConfig(BaseModel):
    """Docker sandbox configuration for code-executing components."""

    image: str
    memory_limit: str = "2g"
    cpu_limit: float = 1.0
    network: bool = False
    read_only_mounts: list[str] = Field(default_factory=list)
    writable_mounts: list[str] = Field(default_factory=list)
    timeout_s: int = 300
    env_forward: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestrator / triggering
# ---------------------------------------------------------------------------


class ComponentTrigger(BaseModel):
    """Defines when a parent should dispatch work to a child component."""

    target_component: str
    condition: str
    priority: int = 10
    cooldown_s: int = 0
    max_concurrent: int = 1


class OrchestratorConfig(BaseModel):
    """Configuration for a component that dispatches to sub-components."""

    triggers: list[ComponentTrigger] = Field(default_factory=list)
    dispatch_strategy: str = "llm"


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------


class ComponentSpec(BaseModel):
    """Definition of a workflow component (agent)."""

    id: str
    name: str
    role: str
    model: ModelConfig = Field(default_factory=ModelConfig)
    tools: list[str] = Field(default_factory=list)
    orchestrator: OrchestratorConfig | None = None
    heartbeat_interval_s: int = 30
    max_retries: int = 2
    sandbox: SandboxConfig | None = None
    is_custom: bool = False
    skills: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TaskStatus(StrEnum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class TaskResult(BaseModel):
    """Structured output from a completed component task."""

    id: str
    summary: str
    artifacts: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class Task(BaseModel):
    """A unit of work assigned to a component."""

    id: str
    thread_id: str
    component: str
    branch: str
    parent_task_id: str | None = None
    instruction: str
    status: TaskStatus = TaskStatus.pending
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    last_heartbeat: datetime | None = None


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------


class CandidateStatus(StrEnum):
    active = "active"
    evaluating = "evaluating"
    succeeded = "succeeded"
    failed = "failed"
    abandoned = "abandoned"


class Candidate(BaseModel):
    """A solution branch in the git repository."""

    id: str
    branch: str
    parent_branch: str | None = None
    status: CandidateStatus = CandidateStatus.active
    evaluations: list[str] = Field(default_factory=list)
    created_at: datetime
    worktree_path: str | None = None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class Evaluation(BaseModel):
    """Result of running the evaluation script against a candidate."""

    id: str
    task_id: str
    candidate_branch: str
    commit_sha: str
    metrics: dict[str, float]
    raw_output: str
    timestamp: datetime
    passed: bool


# ---------------------------------------------------------------------------
# Runtime configuration and state
# ---------------------------------------------------------------------------


class RuntimeConfig(BaseModel):
    """Configuration for the Aurelia runtime."""

    max_concurrent_tasks: int = 4
    heartbeat_interval_s: int = 60
    candidate_abandon_threshold: int = 3
    termination_condition: str = ""
    presubmit_checks: list[str] = Field(default_factory=lambda: ["pixi run test"])
    candidate_selection: str = "top_k_with_wildcard"
    dispatcher: str = "default"
    report_interval_heartbeats: int = 5
    token_budget: int | None = None
    heartbeat_file: str = "HEARTBEAT.md"
    task_timeout_s: int = 600  # 10 minutes default
    heartbeat_stale_threshold_s: int = 120  # 2 minutes - warn if stale


class RuntimeState(BaseModel):
    """Mutable runtime state, persisted to .aurelia/state/runtime.json."""

    status: str = "stopped"
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    # Global sequence counters (monotonic, deterministic)
    next_event_seq: int = 1
    next_seq: dict[str, int] = Field(default_factory=dict)

    # Operational counters
    heartbeat_count: int = 0
    total_tasks_dispatched: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    last_heartbeat_at: datetime | None = None
    last_instruction_hash: str | None = None


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


class Event(BaseModel):
    """A single entry in the append-only event log."""

    seq: int
    type: str
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LLM transaction
# ---------------------------------------------------------------------------


class LLMTransaction(BaseModel):
    """Record of a single LLM request/response pair."""

    id: str
    event_seq: int
    task_id: str
    thread_id: str
    component: str
    model: str
    request_contents: list[dict[str, Any]]
    request_hash: str
    response_content: dict[str, Any]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    timestamp: datetime
    from_cache: bool = False


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class Heartbeat(BaseModel):
    """Proof-of-life signal from a running component."""

    task_id: str
    component: str
    timestamp: datetime
    status: str = "alive"
    progress: str | None = None


# ---------------------------------------------------------------------------
# Git note
# ---------------------------------------------------------------------------


class GitNote(BaseModel):
    """Structured annotation on a git commit."""

    author_component: str
    note_type: str
    content: str
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


class KnowledgeEntry(BaseModel):
    """An entry in the shared knowledge base."""

    id: str
    author_component: str
    tags: list[str] = Field(default_factory=list)
    content: str
    attachments: list[str] = Field(default_factory=list)
    created_at: datetime
    related_branches: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Notebook
# ---------------------------------------------------------------------------


class NotebookSpec(BaseModel):
    """Metadata for a per-candidate Jupyter notebook."""

    candidate_branch: str
    path: str
    last_generated_commit: str
    sections: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dispatch / planning
# ---------------------------------------------------------------------------


class PlanItemStatus(StrEnum):
    todo = "todo"
    assigned = "assigned"
    complete = "complete"
    failed = "failed"


class PlanItem(BaseModel):
    """A single actionable item in an improvement plan."""

    id: str
    description: str
    instruction: str
    parent_branch: str = "main"
    status: PlanItemStatus = PlanItemStatus.todo
    priority: int = 0
    depends_on: list[str] = Field(default_factory=list)
    assigned_candidate_id: str | None = None
    assigned_branch: str | None = None


class Plan(BaseModel):
    """A structured improvement plan produced by a Planner."""

    id: str
    summary: str
    items: list[PlanItem] = Field(default_factory=list)
    created_at: datetime
    revision: int = 0


class DispatchRequest(BaseModel):
    """A request from a Dispatcher to create a new candidate."""

    parent_branch: str
    instruction: str
    context: dict[str, Any] = Field(default_factory=dict)
    plan_item_id: str | None = None


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class ToolRegistration(BaseModel):
    """An MCP tool with Aurelia-specific execution metadata."""

    name: str
    description: str
    input_schema: dict[str, Any]
    requires_sandbox: bool = False
    handler: str = ""
