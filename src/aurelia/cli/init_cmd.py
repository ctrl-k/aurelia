"""Interactive project initialization wizard."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click

from aurelia.cli.wizard_prompts import (
    get_evaluate_prompt,
    get_readme_prompt,
    get_solution_prompt,
)


def run_init() -> None:
    """Run the interactive init wizard."""
    project_dir = Path.cwd()

    click.echo("")
    click.echo(click.style("  Aurelia Project Setup", bold=True))
    click.echo(f"  Directory: {project_dir}")
    click.echo("")

    # Step 0: Prerequisites
    if not _check_prerequisites():
        raise SystemExit(1)

    # Step 1: API Key
    _setup_api_key()

    # Step 2: README.md (problem statement)
    _setup_readme(project_dir)

    # Step 3: evaluate.py (evaluation script)
    _setup_evaluate(project_dir)

    # Step 4: solution.py (baseline implementation)
    _setup_solution(project_dir)

    # Step 5: Project configuration
    _setup_pixi_config(project_dir)
    _setup_pyproject(project_dir)
    _setup_tests_dir(project_dir)
    _setup_aurelia_config(project_dir)

    # Step 6: Git
    _ensure_git_repo(project_dir)

    click.echo("")
    click.echo(click.style("  Project initialized successfully!", fg="green", bold=True))
    click.echo("")
    click.echo("  Next steps:")
    click.echo("    1. Review the generated files")
    click.echo("    2. Run: pixi install")
    click.echo("    3. Run: pixi run test")
    click.echo("    4. Run: aurelia start")
    click.echo("")


# ---------------------------------------------------------------------------
# Step 0: Prerequisites
# ---------------------------------------------------------------------------


def _check_prerequisites() -> bool:
    """Verify required tools are installed."""
    click.echo("  Checking prerequisites...")

    tools = [
        ("gemini", "Gemini CLI", "npm install -g @google/gemini-cli"),
        ("git", "Git", "https://git-scm.com/downloads"),
        ("pixi", "Pixi", "https://pixi.sh"),
    ]

    missing = []
    for cmd, name, install_hint in tools:
        if shutil.which(cmd) is None:
            missing.append((name, install_hint))
        else:
            click.echo(f"    {click.style('OK', fg='green')} {name}")

    if missing:
        click.echo("")
        click.echo(click.style("  Missing required tools:", fg="red"))
        for name, hint in missing:
            click.echo(f"    - {name}: {hint}")
        click.echo("")
        return False

    click.echo("")
    return True


# ---------------------------------------------------------------------------
# Step 1: API Key
# ---------------------------------------------------------------------------


def _setup_api_key() -> None:
    """Detect or prompt for API key."""
    click.echo(click.style("  Step 1: API Key", bold=True))

    existing = os.environ.get("GEMINI_API_KEY")

    if existing:
        # Mask the key for display
        if len(existing) > 12:
            masked = existing[:8] + "..." + existing[-4:]
        else:
            masked = existing[:4] + "..."

        use_existing = click.confirm(
            f"    Found GEMINI_API_KEY ({masked}). Use this?",
            default=True,
        )
        if use_existing:
            click.echo("    Using existing API key.")
            click.echo("")
            return

    # Prompt for new key
    click.echo("    GEMINI_API_KEY not found or declined.")
    api_key = click.prompt("    Enter your Gemini API key", hide_input=True)

    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        click.echo("    API key set for this session.")
        click.echo("")
        click.echo("    Tip: Add to your shell profile for persistence:")
        click.echo(f"      export GEMINI_API_KEY='{api_key[:8]}...'")

    click.echo("")


# ---------------------------------------------------------------------------
# Step 2: README.md
# ---------------------------------------------------------------------------


def _setup_readme(project_dir: Path) -> None:
    """Create README.md with problem statement."""
    click.echo(click.style("  Step 2: Problem Statement (README.md)", bold=True))

    readme_path = project_dir / "README.md"

    if readme_path.exists():
        click.echo("    README.md already exists. Skipping.")
        click.echo("")
        return

    click.echo("    README.md defines the problem Aurelia will solve.")
    choice = click.prompt(
        "    How would you like to create it?",
        type=click.Choice(["interactive", "edit", "skip"], case_sensitive=False),
        default="interactive",
    )

    if choice == "skip":
        click.echo("    Skipping README.md creation.")
        click.echo("")
        return

    if choice == "edit":
        _open_editor(
            readme_path,
            "# Problem Statement\n\nDescribe the problem to solve here.\n\n"
            "## Input/Output\n\nDescribe inputs and expected outputs.\n\n"
            "## Evaluation Criteria\n\nHow will solutions be measured?\n",
        )
        click.echo("")
        return

    # Interactive mode
    click.echo("")
    click.echo("    Let's create your problem statement interactively.")
    summary = click.prompt(
        "    Describe your project in 3-4 sentences",
        default="",
    )

    if not summary:
        click.echo("    No summary provided. Skipping README.md.")
        click.echo("")
        return

    _run_gemini_interactive(project_dir, "readme", summary)
    click.echo("")


# ---------------------------------------------------------------------------
# Step 3: evaluate.py
# ---------------------------------------------------------------------------


def _setup_evaluate(project_dir: Path) -> None:
    """Create evaluate.py evaluation script."""
    click.echo(click.style("  Step 3: Evaluation Script (evaluate.py)", bold=True))

    eval_path = project_dir / "evaluate.py"

    if eval_path.exists():
        click.echo("    evaluate.py already exists. Skipping.")
        click.echo("")
        return

    readme_path = project_dir / "README.md"
    if not readme_path.exists():
        click.echo("    Warning: README.md not found. Creating evaluate.py may be difficult.")

    click.echo("    evaluate.py measures solution quality with numeric metrics.")
    choice = click.prompt(
        "    How would you like to create it?",
        type=click.Choice(["interactive", "edit", "skip"], case_sensitive=False),
        default="interactive",
    )

    if choice == "skip":
        click.echo("    Skipping evaluate.py creation.")
        click.echo("")
        return

    if choice == "edit":
        _open_editor(
            eval_path,
            '"""Evaluation script for Aurelia."""\n\n'
            "import json\n"
            "from solution import main  # adjust import as needed\n\n\n"
            "def evaluate():\n"
            '    """Run evaluation and print JSON metrics."""\n'
            "    # TODO: implement evaluation\n"
            "    result = {'accuracy': 0.0, 'speed_ms': 0.0}\n"
            "    print(json.dumps(result))\n\n\n"
            'if __name__ == "__main__":\n'
            "    evaluate()\n",
        )
        click.echo("")
        return

    # Interactive mode
    _run_gemini_interactive(project_dir, "evaluate", "")
    click.echo("")


# ---------------------------------------------------------------------------
# Step 4: solution.py
# ---------------------------------------------------------------------------


def _setup_solution(project_dir: Path) -> None:
    """Create baseline solution.py."""
    click.echo(click.style("  Step 4: Baseline Solution (solution.py)", bold=True))

    solution_path = project_dir / "solution.py"

    if solution_path.exists():
        click.echo("    solution.py already exists. Skipping.")
        click.echo("")
        return

    readme_path = project_dir / "README.md"
    eval_path = project_dir / "evaluate.py"
    if not readme_path.exists() or not eval_path.exists():
        click.echo("    Warning: README.md or evaluate.py not found.")
        click.echo("    Creating solution.py may be difficult without them.")

    click.echo("    solution.py is the baseline that Aurelia will improve.")
    choice = click.prompt(
        "    How would you like to create it?",
        type=click.Choice(["interactive", "edit", "skip"], case_sensitive=False),
        default="interactive",
    )

    if choice == "skip":
        click.echo("    Skipping solution.py creation.")
        click.echo("")
        return

    if choice == "edit":
        _open_editor(
            solution_path,
            '"""Solution module for Aurelia project."""\n\n\n'
            "def main():\n"
            '    """Main solution function."""\n'
            "    # TODO: implement solution\n"
            "    pass\n",
        )
        click.echo("")
        return

    # Interactive mode
    _run_gemini_interactive(project_dir, "solution", "")
    click.echo("")


# ---------------------------------------------------------------------------
# Step 5: Project Configuration
# ---------------------------------------------------------------------------


def _setup_pixi_config(project_dir: Path) -> None:
    """Create pixi.toml with standard tasks."""
    pixi_path = project_dir / "pixi.toml"

    if pixi_path.exists():
        return

    # Sanitize project name
    project_name = project_dir.name.replace(" ", "-").lower()
    project_name = "".join(c for c in project_name if c.isalnum() or c == "-")

    content = f'''[workspace]
name = "{project_name}"
channels = ["conda-forge"]
platforms = ["osx-arm64", "osx-64", "linux-64"]

[dependencies]
python = ">=3.12"
pytest = ">=8.0"
ruff = ">=0.4"

[tasks]
test = "pytest tests/"
evaluate = "python evaluate.py"
lint = "ruff check ."
fmt = "ruff format ."
'''

    pixi_path.write_text(content)
    click.echo("    Created pixi.toml")


def _setup_pyproject(project_dir: Path) -> None:
    """Create pyproject.toml for Python tooling."""
    pyproject_path = project_dir / "pyproject.toml"

    if pyproject_path.exists():
        return

    project_name = project_dir.name.replace(" ", "-").lower()
    project_name = "".join(c for c in project_name if c.isalnum() or c == "-")

    content = f'''[project]
name = "{project_name}"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
'''

    pyproject_path.write_text(content)
    click.echo("    Created pyproject.toml")


def _setup_tests_dir(project_dir: Path) -> None:
    """Ensure tests directory exists."""
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    init_file = tests_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")


def _setup_aurelia_config(project_dir: Path) -> None:
    """Create .aurelia directory structure and config."""
    click.echo(click.style("  Step 5: Aurelia Configuration", bold=True))

    aurelia_dir = project_dir / ".aurelia"
    for subdir in ["state", "logs", "cache", "reports", "config"]:
        (aurelia_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Write workflow config
    workflow_cfg = aurelia_dir / "config" / "workflow.yaml"
    if not workflow_cfg.exists():
        content = """runtime:
  max_concurrent_tasks: 4
  heartbeat_interval_s: 60
  candidate_abandon_threshold: 5
"""
        workflow_cfg.write_text(content)

    # Write components config
    components_cfg = aurelia_dir / "config" / "components.yaml"
    if not components_cfg.exists():
        components_cfg.write_text("components: []\n")

    # Update .gitignore
    gitignore = project_dir / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    if ".aurelia/" not in gitignore_content:
        with open(gitignore, "a") as f:
            if gitignore_content and not gitignore_content.endswith("\n"):
                f.write("\n")
            f.write("\n# Aurelia runtime state\n.aurelia/\n")

    click.echo("    Created .aurelia/ directory structure")
    click.echo("")


# ---------------------------------------------------------------------------
# Step 6: Git
# ---------------------------------------------------------------------------


def _ensure_git_repo(project_dir: Path) -> None:
    """Initialize a git repo with an initial commit if one doesn't exist."""
    click.echo(click.style("  Step 6: Git Repository", bold=True))

    git_dir = project_dir / ".git"
    if git_dir.exists():
        click.echo("    Git repository already exists.")
        click.echo("")
        return

    click.echo("    Initializing git repository...")
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=project_dir,
        check=True,
        capture_output=True,
    )
    click.echo("    Created git repository with initial commit.")
    click.echo("")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_editor(path: Path, default_content: str = "") -> None:
    """Open file in user's editor."""
    editor = os.environ.get("EDITOR", "nano")

    if not path.exists():
        path.write_text(default_content)

    click.echo(f"    Opening {path.name} in {editor}...")
    subprocess.run([editor, str(path)])

    if path.exists() and path.stat().st_size > 0:
        click.echo(f"    {path.name} saved.")
    else:
        click.echo(f"    Warning: {path.name} is empty or missing.")


def _run_gemini_interactive(
    project_dir: Path,
    task: str,
    context: str,
) -> None:
    """Launch interactive Gemini CLI session for guided file creation."""
    # Get the appropriate prompt
    if task == "readme":
        prompt = get_readme_prompt(context)
    elif task == "evaluate":
        prompt = get_evaluate_prompt()
    elif task == "solution":
        prompt = get_solution_prompt()
    else:
        msg = f"Unknown task: {task}"
        raise ValueError(msg)

    # Write system prompt to temp file
    system_file = project_dir / ".gemini_wizard_system.md"
    system_file.write_text(prompt)

    try:
        click.echo("")
        click.echo("    Starting interactive Gemini session...")
        click.echo("    (The AI will guide you through creating the file)")
        click.echo("")

        env = os.environ.copy()
        env["GEMINI_SYSTEM_MD"] = str(system_file)

        # Run Gemini CLI interactively (no -y flag)
        result = subprocess.run(
            ["gemini"],
            cwd=project_dir,
            env=env,
        )

        if result.returncode != 0:
            click.echo(f"    Gemini CLI exited with code {result.returncode}")

        click.echo("")
        click.echo("    Interactive session complete.")

    except KeyboardInterrupt:
        click.echo("")
        click.echo("    Session cancelled by user.")

    finally:
        system_file.unlink(missing_ok=True)
