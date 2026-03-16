"""Tests for init-shared command.

Covers directory creation, linked file creation, template loading,
dry-run mode, force overwrite, cache plugins, and error handling.
"""

import os
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cloudways_api.cli import app

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "project-config.yml")
ACCOUNTS_PATH = os.path.join(FIXTURES_DIR, "accounts.yml")


def _make_ssh_mock(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> AsyncMock:
    """Create an AsyncMock for run_ssh_command."""
    mock = AsyncMock(return_value=(stdout, stderr, returncode))
    return mock


class TestInitSharedCommand:
    """Tests for the init-shared CLI command."""

    def _invoke(self, args: list[str], env_overrides: dict | None = None) -> object:
        """Invoke init-shared with standard config env vars."""
        env = {
            "CLOUDWAYS_PROJECT_CONFIG": CONFIG_PATH,
            "CLOUDWAYS_ACCOUNTS_FILE": ACCOUNTS_PATH,
        }
        if env_overrides:
            env.update(env_overrides)
        return runner.invoke(app, ["init-shared"] + args, env=env)

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_creates_all_shared_directories(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-7: Creates shared directories via mkdir -p."""
        mock_ssh.return_value = ("", "", 0)
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        # Verify mkdir -p calls were made
        mkdir_calls = [
            call for call in mock_ssh.call_args_list
            if "mkdir -p" in str(call)
        ]
        assert len(mkdir_calls) > 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_creates_htaccess_with_bedrock_rules(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-8: Creates .htaccess with standard Bedrock rewrite rules."""
        # First call for mkdir, subsequent calls check file existence (not found)
        # then create files
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        # Verify .htaccess content was written with Bedrock rules
        create_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "RewriteEngine" in str(call) or ".htaccess" in str(call)
        ]
        assert len(create_calls) > 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_creates_staging_robots(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-9: Creates staging robots.txt that blocks all crawlers."""
        mock_ssh.return_value = ("", "", 0)
        # Make file checks return "not found" so files get created
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        # Find the robots.txt creation call
        robots_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "Disallow: /" in str(call)
        ]
        assert len(robots_calls) > 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_creates_production_robots_with_sitemap(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-10: Creates production robots.txt with sitemap URL."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["production"])
        assert result.exit_code == 0
        # Verify robots.txt has sitemap with domain
        robots_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "sitemap" in str(call).lower()
        ]
        assert len(robots_calls) > 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_skips_existing_files(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-11: Skips existing files without error."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 0),  # test -f .htaccess -> exists
            ("", "", 0),  # test -f robots.txt -> exists
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        assert "skipping" in result.output.lower() or "already exists" in result.output.lower()

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_dry_run_no_ssh_commands(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-12: --dry-run shows planned actions without executing SSH."""
        result = self._invoke(["staging", "--dry-run"])
        assert result.exit_code == 0
        mock_ssh.assert_not_called()
        assert "dry run" in result.output.lower() or "would" in result.output.lower()

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_with_cache_plugins(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-13: --with-cache-plugins creates placeholder cache files."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
            ("", "", 0),  # ensure web/app dir exists
            ("", "", 1),  # test -f object-cache.php -> not found
            ("", "", 0),  # create object-cache.php
            ("", "", 1),  # test -f advanced-cache.php -> not found
            ("", "", 0),  # create advanced-cache.php
        ]
        result = self._invoke(["staging", "--with-cache-plugins"])
        assert result.exit_code == 0
        cache_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "object-cache.php" in str(call) or "advanced-cache.php" in str(call)
        ]
        assert len(cache_calls) > 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_force_overwrites_files(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-14: --force overwrites existing linked files."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 0),  # create .htaccess (no check, force mode)
            ("", "", 0),  # create robots.txt (no check, force mode)
        ]
        result = self._invoke(["staging", "--force"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_empty_htaccess_flag(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-15: --empty-htaccess creates empty .htaccess."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create empty .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["staging", "--empty-htaccess"])
        assert result.exit_code == 0
        # The .htaccess create call should NOT contain RewriteEngine
        htaccess_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "RewriteEngine" in str(call)
        ]
        assert len(htaccess_calls) == 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_reports_summary(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-16: Reports summary of created/skipped files."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 0),  # test -f robots.txt -> exists (skip)
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        # Should have some kind of summary output
        output_lower = result.output.lower()
        assert "created" in output_lower or "skipped" in output_lower or "summary" in output_lower or "htaccess" in output_lower

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_ssh_failure_returns_exit_code_1(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-17: Returns exit code 1 on SSH failure."""
        from cloudways_api.exceptions import SSHError
        mock_ssh.side_effect = SSHError("Connection refused")
        result = self._invoke(["staging"])
        assert result.exit_code == 1

    def test_invalid_environment(self) -> None:
        """Returns exit code 1 for invalid environment name."""
        result = self._invoke(["nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_exit_code_0_on_success(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-17: Returns exit code 0 on success."""
        mock_ssh.return_value = ("", "", 0)
        # Simulate all file checks return "not found" then create succeeds
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_idempotent_rerun(self, mock_ssh: AsyncMock) -> None:
        """Re-running when all files exist skips everything."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 0),  # test -f .htaccess -> exists
            ("", "", 0),  # test -f robots.txt -> exists
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    @patch("cloudways_api.commands.init_shared.get_linked_files_for_environment")
    @patch("cloudways_api.commands.init_shared.get_linked_dirs_for_environment")
    def test_uses_capistrano_parser(
        self, mock_dirs: AsyncMock, mock_files: AsyncMock, mock_ssh: AsyncMock
    ) -> None:
        """Uses capistrano_parser to get linked files and dirs."""
        mock_files.return_value = [".env", "web/.htaccess"]
        mock_dirs.return_value = ["web/app/uploads"]
        mock_ssh.return_value = ("", "", 0)
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 0),  # test -f .htaccess -> exists
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        mock_files.assert_called_once()
        mock_dirs.assert_called_once()

    @patch("cloudways_api.commands.init_shared.run_ssh_command")
    def test_template_wp_home_replacement(self, mock_ssh: AsyncMock) -> None:
        """AC-P1-19: Production robots.txt replaces {{WP_HOME}} with domain."""
        mock_ssh.side_effect = [
            ("", "", 0),  # mkdir -p
            ("", "", 1),  # test -f .htaccess -> not found
            ("", "", 0),  # create .htaccess
            ("", "", 1),  # test -f robots.txt -> not found
            ("", "", 0),  # create robots.txt
        ]
        result = self._invoke(["production"])
        assert result.exit_code == 0
        # Check the robots call contains the domain, not the placeholder
        robots_calls = [
            str(call) for call in mock_ssh.call_args_list
            if "wp.example.com" in str(call)
        ]
        assert len(robots_calls) > 0
