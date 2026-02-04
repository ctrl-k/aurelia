"""Config loading utilities for Aurelia."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from aurelia.core.models import ComponentSpec, ModelConfig, RuntimeConfig

logger = logging.getLogger(__name__)


def load_workflow_config(aurelia_dir: Path) -> dict[str, Any]:
    """Load .aurelia/config/workflow.yaml as a dict.

    Returns empty dict if the file doesn't exist.
    """
    path = aurelia_dir / "config" / "workflow.yaml"
    if not path.exists():
        logger.debug("No workflow config found at %s; using defaults", path)
        return {}

    logger.info("Loading workflow config from %s", path)
    with path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        logger.warning("workflow.yaml did not contain a mapping; using empty dict")
        return {}

    return data


def make_runtime_config(workflow: dict[str, Any]) -> RuntimeConfig:
    """Build a RuntimeConfig from workflow.yaml values.

    Only fields present in *workflow* override the defaults defined in
    :class:`RuntimeConfig`.
    """
    runtime_section = workflow.get("runtime", {})
    if not isinstance(runtime_section, dict):
        logger.warning("'runtime' key is not a mapping; ignoring")
        runtime_section = {}

    # Filter to only the fields RuntimeConfig actually declares so that
    # unknown keys don't cause a validation error.
    valid_fields = RuntimeConfig.model_fields
    filtered = {k: v for k, v in runtime_section.items() if k in valid_fields}

    if dropped := set(runtime_section) - set(filtered):
        logger.warning("Ignoring unknown runtime config keys: %s", sorted(dropped))

    return RuntimeConfig(**filtered)


def default_component_specs() -> dict[str, ComponentSpec]:
    """Return default specs for the three built-in components.

    Components
    ----------
    root
        Root orchestrator.  Does not call an LLM directly.
    coder
        Writes and modifies code.  Uses the default :class:`ModelConfig`.
    evaluator
        Evaluates solution quality by running a subprocess.  No LLM needed.
    """
    root = ComponentSpec(
        id="root",
        name="Root Orchestrator",
        role="Orchestrate the overall workflow",
    )

    coder = ComponentSpec(
        id="coder",
        name="Coder",
        role="Write and modify code to solve the problem",
        model=ModelConfig(),
        tools=["read_file", "write_file", "run_command"],
    )

    evaluator = ComponentSpec(
        id="evaluator",
        name="Evaluator",
        role="Evaluate solution quality by running the evaluation script",
    )

    return {
        "root": root,
        "coder": coder,
        "evaluator": evaluator,
    }
