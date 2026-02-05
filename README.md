---
title: Untitled
author: ctrl
date: 2026-02-04T23:34:49Z
---

# Aurelia

Aurelia is a CLI tool that automates iterative code improvement using LLM agents.
It creates candidate solution branches, dispatches a coder agent to modify code,
runs an evaluation script to measure quality, and records results — all in a
loop driven by a heartbeat scheduler.

## How it works

1. You provide a project with a `README.md` (problem statement) and an `evaluate.py`
   (scoring script that prints JSON metrics to stdout).
2. Aurelia initializes a `.aurelia/` directory to hold runtime state, logs, and config.
3. On `aurelia start`, a heartbeat loop begins:
   - A candidate git branch and worktree are created.
   - A **coder** agent runs [Gemini CLI](https://github.com/google-gemini/gemini-cli)
     inside a Docker container to read and modify the solution.
   - A **presubmit** check runs `pixi run test` to verify the changes.
   - An **evaluator** runs `pixi run evaluate` in the worktree and collects metrics.
   - Results are recorded as events in an append-only JSONL log.
   - On the next cycle, a new candidate is created — branching from the best
     previous solution if one succeeded — and the coder receives feedback from
     all prior evaluation results.
4. The runtime stops when a termination condition is met, when too many
   candidates fail, or on `SIGTERM` / `SIGINT`.

## Environment variables

Set your API key before running Aurelia:

```bash
export GEMINI_API_KEY=your-key-here    # for Gemini CLI
```

The key is forwarded into the Docker container automatically.

## Setup

Requires [pixi](https://pixi.sh), Python 3.12+, and [Docker](https://docs.docker.com/get-docker/).

```
pixi install
```

## Quick start

```bash
# Initialize a project
cd my-project
aurelia init

# Start the runtime (mock LLM for testing)
aurelia start --mock

# Check status
aurelia status

# Stop the runtime
aurelia stop
```

## Example project

The `example_project/` directory contains a minimal setup:

```bash
cd example_project
aurelia init          # creates .aurelia/ directory
aurelia start --mock  # runs one cycle with a mock LLM client
```

The example problem is implementing `sqrt(n)`. The evaluation script measures
accuracy (mean absolute error vs `math.sqrt`) and speed.

## CLI reference

```
aurelia init                  Initialize .aurelia/ in the current directory
aurelia start [--mock]        Start the runtime (--mock uses a fake LLM)
aurelia stop                  Send SIGTERM to a running runtime
aurelia status                Print runtime state summary
aurelia monitor               Open real-time TUI dashboard
aurelia report                View the latest progress report
```

## Configuration

After `aurelia init`, settings are in `.aurelia/config/workflow.yaml`:

```yaml
runtime:
  heartbeat_interval_s: 60
  max_concurrent_tasks: 4
  termination_condition: "accuracy>=0.95"   # stop when this metric is reached
  candidate_abandon_threshold: 3            # stop after this many failures
  dispatcher: "default"                     # "default" or "planner"
```

## Development

```bash
pixi run test       # run tests
pixi run lint       # run ruff linter
pixi run fmt        # auto-format code
pixi run typecheck  # run pyright
```

## Project layout

```
src/aurelia/
  cli/           CLI entry point and init wizard
  core/          Models, config, event log, state store, ID generator, runtime
  components/    Base component engine, coder, evaluator, planner, presubmit, prompt templates
  dispatch/      Dispatcher protocol, DefaultDispatcher, PlannerDispatcher
  monitor/       Real-time Textual TUI dashboard
  llm/           LLM client protocol, mock client, response cache
  git/           Async git operations and worktree management
  sandbox/       Docker client, Dockerfile for containerised code agents
  tools/         MCP tool server (read_file, write_file, run_command) and registry
```
