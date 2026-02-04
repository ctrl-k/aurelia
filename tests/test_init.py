"""Tests for the CLI entry point."""

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
        """Verify the init command is registered (will prompt for input)."""
        runner = CliRunner()
        # Send empty input to get past prompts — it will fail but proves the command is wired
        result = runner.invoke(cli, ["init"], input="\n\n\n")
        # The command should at least start (print the init message)
        assert "Initializing Aurelia project" in result.output

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
