"""Tests for verify-setup command.

Covers SSH connectivity check, shared directory check, .env file checks,
linked file/dir checks, git remote check, verbose output, exit codes,
and error handling.
"""

import os
import tempfile
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cloudways_api.cli import app

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "project-config.yml")
ACCOUNTS_PATH = os.path.join(FIXTURES_DIR, "accounts.yml")


class TestVerifySetupCommand:
    """Tests for the verify-setup CLI command."""

    def _invoke(self, args: list[str], env_overrides: dict | None = None) -> object:
        """Invoke verify-setup with standard config env vars."""
        env = {
            "CLOUDWAYS_PROJECT_CONFIG": CONFIG_PATH,
            "CLOUDWAYS_ACCOUNTS_FILE": ACCOUNTS_PATH,
        }
        if env_overrides:
            env.update(env_overrides)
        return runner.invoke(app, ["verify-setup"] + args, env=env)

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_all_checks_pass(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-9: All checks pass, shows 'Ready to deploy' message."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity check
            ("", "", 0),               # shared dir exists
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has 3 required keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote accessible
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "ready to deploy" in output_lower or "checks passed" in output_lower

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_ssh_connectivity_fail(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-1: Reports failure when SSH connectivity check fails."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        from cloudways_api.exceptions import SSHError

        mock_ssh.side_effect = SSHError("Connection refused")
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        output_lower = result.output.lower()
        assert "fail" in output_lower or "error" in output_lower

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_shared_dir_missing(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-2: Reports failure when shared directory does not exist."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 1),               # shared dir MISSING
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_env_file_missing(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-3: Reports failure when .env file does not exist."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 1),               # .env MISSING
            ("0\n", "", 0),            # .env keys check (0 because no .env)
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_env_missing_required_keys(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-4: Reports failure when .env is missing required keys."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("1\n", "", 0),            # .env has only 1 key (need 3)
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_env_with_all_keys(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-4: Passes when .env has all required keys."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("5\n", "", 0),            # .env has 5 keys (>= 3 required)
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_linked_file_missing(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-5: Reports failure when a linked file is missing."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 1),               # web/.htaccess MISSING
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_linked_dir_missing(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-6: Reports failure when a linked directory is missing."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 1),               # web/app/uploads MISSING
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_git_remote_accessible(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-7: Git remote check passes with exit code 0 or 1."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "logged in", 1),      # git remote: exit 1 (authenticated but no shell)
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_git_remote_inaccessible(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-7: Git remote check fails with exit codes other than 0 or 1."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "timeout", 128),      # git remote: FAIL (connection error)
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_verbose_output(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-11: --verbose shows additional detail per check."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging", "--verbose"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        # Verbose output should show command details
        assert (
            "echo ok" in output_lower
            or "command" in output_lower
            or "test -d" in output_lower
        )

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_all_checks_fail(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """All checks fail, reports 0/N checks passed."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("", "error", 1),          # SSH connectivity FAIL
            ("", "", 1),               # shared dir MISSING
            ("", "", 1),               # .env MISSING
            ("0\n", "", 0),            # .env has 0 keys
            ("", "", 1),               # web/.htaccess MISSING
            ("", "", 1),               # web/robots.txt MISSING
            ("", "", 1),               # web/app/uploads MISSING
            ("", "", 1),               # web/app/cache MISSING
            ("", "error", 128),        # git remote FAIL
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "0/" in result.output or "0 of" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_partial_pass(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """Reports correct count when some checks pass and some fail."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 1),               # web/.htaccess MISSING
            ("", "", 0),               # web/robots.txt OK
            ("", "", 0),               # web/app/uploads OK
            ("", "", 1),               # web/app/cache MISSING
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        # Should show partial pass count (e.g., 7/9 or similar)
        output = result.output
        assert "/" in output  # Shows pass/total count

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_summary_count(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-9: Reports total checks passed count."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/robots.txt exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # web/app/cache exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0
        # Should show all checks passed count
        assert "9/9" in result.output or "checks passed" in result.output.lower()

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_exit_code_0_all_pass(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-10: Returns exit code 0 when all checks pass."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),
            ("", "", 0),
            ("", "", 0),
            ("3\n", "", 0),
            ("", "", 0),
            ("", "", 0),
            ("", "", 0),
            ("", "", 0),
            ("", "", 0),
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_exit_code_1_any_fail(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """AC-P2-10: Returns exit code 1 when any check fails."""
        mock_files.return_value = [".env", "web/.htaccess", "web/robots.txt"]
        mock_dirs.return_value = ["web/app/uploads", "web/app/cache"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env OK
            ("3\n", "", 0),            # .env keys OK
            ("", "", 0),               # web/.htaccess OK
            ("", "", 0),               # web/robots.txt OK
            ("", "", 0),               # web/app/uploads OK
            ("", "", 0),               # web/app/cache OK
            ("", "error", 128),        # git remote FAIL
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1

    def test_invalid_environment(self) -> None:
        """Returns exit code 1 for invalid environment name."""
        result = self._invoke(["nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_missing_ssh_config(self) -> None:
        """Returns exit code 1 when SSH config is missing."""
        config_content = """
hosting:
  cloudways:
    account: test
    server:
      id: 12345
    environments:
      staging:
        app_id: 67890
        domain: staging.example.com
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as f:
            f.write(config_content)
            tmp_path = f.name

        try:
            result = self._invoke(
                ["staging"],
                env_overrides={"CLOUDWAYS_PROJECT_CONFIG": tmp_path},
            )
            assert result.exit_code == 1
            assert "ssh" in result.output.lower()
        finally:
            os.unlink(tmp_path)

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_mid_sequence_ssh_exception_continues(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """SSH exception on a mid-sequence check marks it FAIL but continues."""
        from cloudways_api.exceptions import SSHError

        mock_files.return_value = [".env", "web/.htaccess"]
        mock_dirs.return_value = ["web/app/uploads"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            SSHError("Connection dropped"),  # shared dir check RAISES
            ("", "", 0),               # .env exists
            ("3\n", "", 0),            # .env has keys
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        output_lower = result.output.lower()
        # The failed check should appear, plus remaining checks should run
        assert "fail" in output_lower
        assert "ok" in output_lower
        # All 7 checks should be attempted
        assert mock_ssh.call_count == 7

    @patch("cloudways_api.commands.verify_setup.get_linked_dirs_for_environment")
    @patch("cloudways_api.commands.verify_setup.get_linked_files_for_environment")
    @patch("cloudways_api.commands.verify_setup.run_ssh_command")
    def test_env_key_count_non_numeric_output(
        self, mock_ssh: AsyncMock, mock_files: AsyncMock, mock_dirs: AsyncMock
    ) -> None:
        """Non-numeric grep output for .env key count marks check as FAIL."""
        mock_files.return_value = [".env", "web/.htaccess"]
        mock_dirs.return_value = ["web/app/uploads"]
        mock_ssh.side_effect = [
            ("ok\n", "", 0),           # SSH connectivity OK
            ("", "", 0),               # shared dir OK
            ("", "", 0),               # .env exists
            ("not-a-number\n", "", 0), # .env keys: non-numeric output
            ("", "", 0),               # web/.htaccess exists
            ("", "", 0),               # web/app/uploads exists
            ("", "", 0),               # git remote OK
        ]
        result = self._invoke(["staging"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower()
