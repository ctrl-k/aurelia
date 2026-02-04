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
   - A **coder** agent reads the problem, uses tools (`read_file`, `write_file`,
     `run_command`) via an LLM to modify the solution.
   - An **evaluator** runs `pixi run evaluate` in the worktree and collects metrics.
   - Results are recorded as events in an append-only JSONL log.
4. The runtime shuts down gracefully on `SIGTERM` or `SIGINT`, persisting all state.

## Setup

Requires [pixi](https://pixi.sh) and Python 3.12+.

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
  components/    Base component engine, coder, evaluator, prompt templates
  llm/           LLM client protocol, mock client, response cache
  git/           Async git operations and worktree management
  tools/         MCP tool server (read_file, write_file, run_command) and registry
```
