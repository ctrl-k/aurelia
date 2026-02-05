"""Tests for the report generation command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from aurelia.cli.main import cli


def _write_state(
    state_dir: Path,
    runtime: dict,
    candidates: list,
    evaluations: list,
    tasks: list,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "runtime.json").write_text(json.dumps(runtime))
    (state_dir / "candidates.json").write_text(json.dumps(candidates))
    (state_dir / "evaluations.json").write_text(json.dumps(evaluations))
    (state_dir / "tasks.json").write_text(json.dumps(tasks))


class TestReportWithData:
    def test_report_with_data(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        runtime = {
            "status": "stopped",
            "started_at": "2025-01-01T00:00:00Z",
            "stopped_at": "2025-01-01T00:05:30Z",
            "heartbeat_count": 10,
            "total_tasks_dispatched": 5,
            "total_tasks_completed": 4,
            "total_tasks_failed": 1,
        }
        candidates = [
            {"id": "cand-0001", "status": "succeeded", "branch": "aurelia/cand-0001"},
            {"id": "cand-0002", "status": "failed", "branch": "aurelia/cand-0002"},
        ]
        evaluations = [
            {
                "id": "eval-0001",
                "candidate_branch": "aurelia/cand-0001",
                "commit_sha": "abc123",
                "metrics": {"accuracy": 0.95, "speed_ms": 5.0},
                "passed": True,
            },
        ]
        tasks = [
            {"component": "coder", "status": "success"},
            {"component": "evaluator", "status": "success"},
            {"component": "coder", "status": "failed"},
        ]

        _write_state(project / ".aurelia" / "state", runtime, candidates, evaluations, tasks)

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--project-dir", str(project)])

        assert result.exit_code == 0
        assert "Run Summary" in result.output
        assert "stopped" in result.output
        assert "Candidates" in result.output
        assert "cand-0001" in result.output
        assert "Best Candidate" in result.output
        assert "accuracy" in result.output
        assert "0.9500" in result.output


class TestReportEmptyProject:
    def test_report_empty_project(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--project-dir", str(project)])

        assert result.exit_code == 0
        assert "No .aurelia/state directory" in result.output


class TestReportNoRuntime:
    def test_report_no_runtime(self, tmp_path):
        project = tmp_path / "project"
        state_dir = project / ".aurelia" / "state"
        state_dir.mkdir(parents=True)

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--project-dir", str(project)])

        assert result.exit_code == 0
        assert "No runtime state found" in result.output


class TestReportFormatsMetrics:
    def test_report_formats_float_metrics(self, tmp_path):
        project = tmp_path / "project"

        runtime = {
            "status": "stopped",
            "heartbeat_count": 1,
            "total_tasks_dispatched": 1,
            "total_tasks_completed": 1,
            "total_tasks_failed": 0,
        }
        candidates = [
            {"id": "cand-0001", "status": "succeeded", "branch": "aurelia/cand-0001"},
        ]
        evaluations = [
            {
                "id": "eval-0001",
                "candidate_branch": "aurelia/cand-0001",
                "commit_sha": "def456",
                "metrics": {"accuracy": 0.123456789},
                "passed": True,
            },
        ]

        _write_state(project / ".aurelia" / "state", runtime, candidates, evaluations, [])

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--project-dir", str(project)])

        assert result.exit_code == 0
        # Candidate table uses 4 decimal places
        assert "0.1235" in result.output
        # Best candidate section uses 6 decimal places
        assert "0.123457" in result.output


class TestReportFailures:
    def test_report_shows_failures(self, tmp_path):
        project = tmp_path / "project"

        runtime = {
            "status": "stopped",
            "heartbeat_count": 0,
            "total_tasks_dispatched": 1,
            "total_tasks_completed": 0,
            "total_tasks_failed": 1,
        }
        candidates = [
            {"id": "cand-0001", "status": "failed", "branch": "aurelia/cand-0001"},
        ]
        tasks = [
            {
                "component": "presubmit",
                "status": "failed",
                "branch": "aurelia/cand-0001",
                "result": {"error": "Check 'pixi run test' failed (exit 1)"},
            },
        ]

        _write_state(project / ".aurelia" / "state", runtime, candidates, [], tasks)

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--project-dir", str(project)])

        assert result.exit_code == 0
        assert "Failures" in result.output
        assert "pixi run test" in result.output
