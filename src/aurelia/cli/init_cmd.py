"""Interactive project initialization wizard."""
from __future__ import annotations

import os
from pathlib import Path

import click


def run_init() -> None:
    """Run the interactive init wizard."""
    project_dir = Path.cwd()
    click.echo(f"Initializing Aurelia project in: {project_dir}")

    # Check for README
    readme = project_dir / "README.md"
    if not readme.exists():
        click.echo("Warning: No README.md found in project directory.")

    # Provider selection
    provider = click.prompt(
        "Model provider",
        type=click.Choice(["gemini", "openai", "anthropic"], case_sensitive=False),
        default="gemini",
    )

    # API key hint
    env_var = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    key_var = env_var.get(provider, "API_KEY")
    if not os.environ.get(key_var):
        click.echo(f"Hint: set {key_var} environment variable for {provider}.")

    # Runtime parameters
    max_concurrent = click.prompt("Max concurrent tasks", default=4, type=int)
    heartbeat_s = click.prompt("Heartbeat interval (seconds)", default=60, type=int)
    termination = click.prompt(
        "Termination condition (e.g. 'accuracy>=0.95', or empty)",
        default="",
        type=str,
    )

    # Create .aurelia directory structure
    aurelia_dir = project_dir / ".aurelia"
    for subdir in ["state", "logs", "cache", "reports", "config"]:
        (aurelia_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Write workflow config (nested under runtime: key)
    lines = [
        "runtime:",
        f"  max_concurrent_tasks: {max_concurrent}",
        f"  heartbeat_interval_s: {heartbeat_s}",
    ]
    if termination:
        lines.append(f'  termination_condition: "{termination}"')

    workflow_cfg = aurelia_dir / "config" / "workflow.yaml"
    workflow_cfg.write_text("\n".join(lines) + "\n")

    # Write components config (empty placeholder)
    components_cfg = aurelia_dir / "config" / "components.yaml"
    components_cfg.write_text("components: []\n")

    # Add .aurelia/ to .gitignore if not already there
    gitignore = project_dir / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    if ".aurelia/" not in gitignore_content:
        with open(gitignore, "a") as f:
            f.write("\n# Aurelia runtime state\n.aurelia/\n")

    click.echo(f"Aurelia project initialized in {aurelia_dir}")
