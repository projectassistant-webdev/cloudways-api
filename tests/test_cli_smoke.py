"""CLI smoke tests ensuring every command is registered and reachable.

These tests verify that:
1. Every command is registered and responds to --help
2. Commands produce user-friendly errors when config is missing
3. The provision sub-command group is properly wired

No real API calls are made; these are pure CLI integration tests.
"""

import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Top-level CLI smoke tests
# ---------------------------------------------------------------------------


class TestCLITopLevel:
    """Verify top-level CLI behaviour."""

    def test_help_flag_shows_all_commands(self) -> None:
        """--help lists every registered command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in [
            "info",
            "db-pull",
            "db-push",
            "db-restore",
            "env-capture",
            "ssh",
            "capistrano",
            "provision",
        ]:
            assert cmd in result.output

    def test_version_flag(self) -> None:
        """--version prints version string and exits cleanly."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "cloudways-api" in result.output


# ---------------------------------------------------------------------------
# Per-command --help smoke tests
# ---------------------------------------------------------------------------


class TestCommandHelp:
    """Each command responds to --help with exit code 0."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["info", "--help"],
            ["db-pull", "--help"],
            ["db-push", "--help"],
            ["db-restore", "--help"],
            ["env-capture", "--help"],
            ["ssh", "--help"],
            ["capistrano", "--help"],
            ["provision", "--help"],
            ["provision", "server", "--help"],
            ["provision", "app", "--help"],
        ],
        ids=[
            "info",
            "db-pull",
            "db-push",
            "db-restore",
            "env-capture",
            "ssh",
            "capistrano",
            "provision",
            "provision-server",
            "provision-app",
        ],
    )
    def test_help_exits_zero(self, cmd_args: list[str]) -> None:
        """Command --help exits with code 0."""
        result = runner.invoke(app, cmd_args)
        assert result.exit_code == 0
        assert len(result.output) > 0


# ---------------------------------------------------------------------------
# Missing config smoke tests
# ---------------------------------------------------------------------------


class TestMissingConfig:
    """Commands that require project config produce errors when it is absent."""

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["info"],
            ["db-pull", "production"],
            ["db-push", "production"],
            ["db-restore", "production"],
            ["env-capture", "production"],
        ],
        ids=[
            "info",
            "db-pull",
            "db-push",
            "db-restore",
            "env-capture",
        ],
    )
    def test_missing_config_exits_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cmd_args: list[str],
    ) -> None:
        """Command without config file exits with non-zero status."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", "/tmp/nonexistent.yml")
        monkeypatch.setenv(
            "CLOUDWAYS_ACCOUNTS_FILE", "/tmp/nonexistent-accounts.yml"
        )
        result = runner.invoke(app, cmd_args)
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Provision sub-command smoke tests
# ---------------------------------------------------------------------------


class TestProvisionSubCommands:
    """Verify provision sub-commands are wired correctly."""

    def test_provision_lists_server_and_app(self) -> None:
        """provision --help shows both server and app sub-commands."""
        result = runner.invoke(app, ["provision", "--help"])
        assert result.exit_code == 0
        assert "server" in result.output.lower()
        assert "app" in result.output.lower()
