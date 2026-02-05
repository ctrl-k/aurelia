"""Tests for the CLI init wizard."""

from __future__ import annotations

import os
from unittest.mock import patch

from click.testing import CliRunner

from aurelia.cli.main import cli


class TestCLIGroup:
    def test_cli_has_expected_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for cmd in ("init", "start", "stop", "status", "replay", "monitor", "report"):
            assert cmd in result.output

    def test_init_command_exists(self):
        """Verify the init command is registered."""
        runner = CliRunner()
        # Send inputs to skip through wizard steps
        # The wizard should at least start and show the title
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli,
                ["init"],
                input="y\nskip\nskip\nskip\n",  # API key yes, skip all files
            )
            assert "Aurelia Project Setup" in result.output

    def test_start_command_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "--help"])
        assert result.exit_code == 0
        assert "--mock" in result.output
        assert "--project-dir" in result.output

    def test_status_command_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0
        assert "--project-dir" in result.output


class TestInitWizardPrerequisites:
    """Tests for the prerequisites check."""

    def test_check_prerequisites_all_present(self):
        """Test that prerequisites check passes when all tools are present."""
        from aurelia.cli.init_cmd import _check_prerequisites

        # Mock shutil.which to return paths for all tools
        with patch("aurelia.cli.init_cmd.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/mock"
            result = _check_prerequisites()
            assert result is True

    def test_check_prerequisites_missing_tool(self):
        """Test that prerequisites check fails when a tool is missing."""
        from aurelia.cli.init_cmd import _check_prerequisites

        # Mock shutil.which to return None for gemini
        def mock_which(cmd):
            if cmd == "gemini":
                return None
            return "/usr/bin/mock"

        with patch("aurelia.cli.init_cmd.shutil.which", side_effect=mock_which):
            result = _check_prerequisites()
            assert result is False


class TestInitWizardAPIKey:
    """Tests for API key setup."""

    def test_api_key_found_and_accepted(self):
        """Test API key detection when key exists and user accepts."""
        from aurelia.cli.init_cmd import _setup_api_key

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-12345678"}):
            with patch("aurelia.cli.init_cmd.click.confirm", return_value=True):
                _setup_api_key()
                # Key should still be set
                assert os.environ.get("GEMINI_API_KEY") == "test-key-12345678"

    def test_api_key_not_found_prompted(self):
        """Test API key prompt when no key exists."""
        from aurelia.cli.init_cmd import _setup_api_key

        env = os.environ.copy()
        env.pop("GEMINI_API_KEY", None)

        with patch.dict(os.environ, env, clear=True):
            with patch("aurelia.cli.init_cmd.click.prompt", return_value="new-api-key"):
                _setup_api_key()
                assert os.environ.get("GEMINI_API_KEY") == "new-api-key"


class TestInitWizardFileCreation:
    """Tests for file creation steps."""

    def test_setup_readme_skip(self, tmp_path):
        """Test skipping README.md creation."""
        from aurelia.cli.init_cmd import _setup_readme

        with patch("aurelia.cli.init_cmd.click.prompt", return_value="skip"):
            _setup_readme(tmp_path)

        assert not (tmp_path / "README.md").exists()

    def test_setup_readme_already_exists(self, tmp_path):
        """Test that existing README.md is not overwritten."""
        from aurelia.cli.init_cmd import _setup_readme

        readme = tmp_path / "README.md"
        readme.write_text("# Existing README")

        _setup_readme(tmp_path)

        assert readme.read_text() == "# Existing README"

    def test_setup_evaluate_skip(self, tmp_path):
        """Test skipping evaluate.py creation."""
        from aurelia.cli.init_cmd import _setup_evaluate

        with patch("aurelia.cli.init_cmd.click.prompt", return_value="skip"):
            _setup_evaluate(tmp_path)

        assert not (tmp_path / "evaluate.py").exists()

    def test_setup_solution_skip(self, tmp_path):
        """Test skipping solution.py creation."""
        from aurelia.cli.init_cmd import _setup_solution

        with patch("aurelia.cli.init_cmd.click.prompt", return_value="skip"):
            _setup_solution(tmp_path)

        assert not (tmp_path / "solution.py").exists()


class TestInitWizardConfig:
    """Tests for configuration file generation."""

    def test_setup_pixi_config(self, tmp_path):
        """Test pixi.toml generation."""
        from aurelia.cli.init_cmd import _setup_pixi_config

        _setup_pixi_config(tmp_path)

        pixi_path = tmp_path / "pixi.toml"
        assert pixi_path.exists()

        content = pixi_path.read_text()
        assert "[workspace]" in content
        assert "[dependencies]" in content
        assert "[tasks]" in content
        assert "test = " in content
        assert "evaluate = " in content

    def test_setup_pixi_config_already_exists(self, tmp_path):
        """Test that existing pixi.toml is not overwritten."""
        from aurelia.cli.init_cmd import _setup_pixi_config

        pixi_path = tmp_path / "pixi.toml"
        pixi_path.write_text("# Existing config")

        _setup_pixi_config(tmp_path)

        assert pixi_path.read_text() == "# Existing config"

    def test_setup_pyproject(self, tmp_path):
        """Test pyproject.toml generation."""
        from aurelia.cli.init_cmd import _setup_pyproject

        _setup_pyproject(tmp_path)

        pyproject_path = tmp_path / "pyproject.toml"
        assert pyproject_path.exists()

        content = pyproject_path.read_text()
        assert "[project]" in content
        assert "[tool.ruff]" in content
        assert "[tool.pytest.ini_options]" in content

    def test_setup_aurelia_config(self, tmp_path):
        """Test .aurelia directory structure creation."""
        from aurelia.cli.init_cmd import _setup_aurelia_config

        _setup_aurelia_config(tmp_path)

        aurelia_dir = tmp_path / ".aurelia"
        assert aurelia_dir.exists()
        assert (aurelia_dir / "state").exists()
        assert (aurelia_dir / "logs").exists()
        assert (aurelia_dir / "config").exists()
        assert (aurelia_dir / "config" / "workflow.yaml").exists()

    def test_setup_tests_dir(self, tmp_path):
        """Test tests directory creation."""
        from aurelia.cli.init_cmd import _setup_tests_dir

        _setup_tests_dir(tmp_path)

        tests_dir = tmp_path / "tests"
        assert tests_dir.exists()
        assert (tests_dir / "__init__.py").exists()


class TestWizardPrompts:
    """Tests for the wizard prompts module."""

    def test_get_readme_prompt(self):
        """Test README prompt generation."""
        from aurelia.cli.wizard_prompts import get_readme_prompt

        prompt = get_readme_prompt("A project to sort numbers")
        assert "A project to sort numbers" in prompt
        assert "clarifying questions" in prompt
        assert "README.md" in prompt

    def test_get_evaluate_prompt(self):
        """Test evaluate prompt generation."""
        from aurelia.cli.wizard_prompts import get_evaluate_prompt

        prompt = get_evaluate_prompt()
        assert "evaluate.py" in prompt
        assert "JSON" in prompt
        assert "metrics" in prompt

    def test_get_solution_prompt(self):
        """Test solution prompt generation."""
        from aurelia.cli.wizard_prompts import get_solution_prompt

        prompt = get_solution_prompt()
        assert "solution.py" in prompt
        assert "baseline" in prompt.lower()
        assert "test" in prompt.lower()
