"""Tests for setup-bedrock composite command.

Covers full success path, step failures, .env skip logic,
--dry-run mode, --with-cache-plugins passthrough, --webroot passthrough,
summary output, exit codes, and idempotent re-run.
"""

import os
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cloudways_api.cli import app

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "project-config.yml")
ACCOUNTS_PATH = os.path.join(FIXTURES_DIR, "accounts.yml")


def _env_vars() -> dict:
    """Standard env vars pointing to test fixture config."""
    return {
        "CLOUDWAYS_PROJECT_CONFIG": CONFIG_PATH,
        "CLOUDWAYS_ACCOUNTS_FILE": ACCOUNTS_PATH,
    }


class TestSetupBedrockCommand:
    """Tests for the setup-bedrock composite CLI command."""

    def _invoke(self, args: list[str]) -> object:
        """Invoke setup-bedrock with standard config env vars."""
        return runner.invoke(app, ["setup-bedrock"] + args, env=_env_vars())

    # ------------------------------------------------------------------
    # Full success path
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_full_success_all_steps(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-1..4: All 4 steps execute successfully in order."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)  # all checks pass

        result = self._invoke(["staging"])
        assert result.exit_code == 0

        # Verify all steps were called
        mock_env_exists.assert_called_once()
        mock_env_gen.assert_called_once()
        mock_set_webroot.assert_called_once()
        mock_init_shared.assert_called_once()
        mock_verify.assert_called_once()

    # ------------------------------------------------------------------
    # Dry-run mode
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_dry_run_no_execution(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-6: --dry-run shows planned steps without executing."""
        result = self._invoke(["staging", "--dry-run"])
        assert result.exit_code == 0

        # None of the step functions should be called in dry-run
        mock_env_exists.assert_not_called()
        mock_env_gen.assert_not_called()
        mock_set_webroot.assert_not_called()
        mock_init_shared.assert_not_called()
        mock_verify.assert_not_called()

        # Output should indicate dry-run
        assert "dry run" in result.output.lower() or "dry-run" in result.output.lower()

    # ------------------------------------------------------------------
    # .env already exists -> skip env-generate
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_env_already_exists_skip_env_generate(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-1: Skips env-generate when .env already exists on server."""
        mock_env_exists.return_value = True
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging"])
        assert result.exit_code == 0

        # env-generate should NOT have been called
        mock_env_gen.assert_not_called()

        # Other steps should still run
        mock_set_webroot.assert_called_once()
        mock_init_shared.assert_called_once()
        mock_verify.assert_called_once()

        # Output should mention skip
        assert "skip" in result.output.lower() or "already exists" in result.output.lower()

    # ------------------------------------------------------------------
    # Step failures (stop on steps 1-3)
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_env_generate_fails_stops_early(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-7: env-generate failure stops execution with error."""
        mock_env_exists.return_value = False
        mock_env_gen.side_effect = Exception("API connection failed")

        result = self._invoke(["staging"])
        assert result.exit_code == 1

        # Subsequent steps should NOT run
        mock_set_webroot.assert_not_called()
        mock_init_shared.assert_not_called()
        mock_verify.assert_not_called()

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_set_webroot_fails_stops_early(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-7: set-webroot failure stops execution with error."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.side_effect = Exception("Webroot API error")

        result = self._invoke(["staging"])
        assert result.exit_code == 1

        # init-shared and verify should NOT run
        mock_init_shared.assert_not_called()
        mock_verify.assert_not_called()

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_init_shared_fails_stops_early(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-7: init-shared failure stops execution with error."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.side_effect = Exception("SSH permission denied")

        result = self._invoke(["staging"])
        assert result.exit_code == 1

        # verify should NOT run
        mock_verify.assert_not_called()

    # ------------------------------------------------------------------
    # verify-setup failure: reports but summary still shows
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_verify_setup_fails_reports_but_completes(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-7: verify-setup failure reported in summary but does not prevent summary."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (5, 8)  # only 5 of 8 checks passed

        result = self._invoke(["staging"])
        # Exit code 1 because not all verify checks passed
        assert result.exit_code == 1

        # Summary should still be shown even though verify had failures
        assert "summary" in result.output.lower() or "setup" in result.output.lower()

    # ------------------------------------------------------------------
    # Flag passthrough
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_with_cache_plugins_passthrough(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-8: --with-cache-plugins is passed through to init-shared."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging", "--with-cache-plugins"])
        assert result.exit_code == 0

        # Verify init-shared was called with cache plugins flag
        call_kwargs = mock_init_shared.call_args
        assert call_kwargs is not None
        # The with_cache_plugins kwarg should be True
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get("with_cache_plugins") is True
        else:
            # positional args -- check that True is in the args
            assert True in call_kwargs.args

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_custom_webroot_passthrough(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-2: Custom --webroot is passed through to set-webroot step."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging", "--webroot", "public_html/web"])
        assert result.exit_code == 0

        # set-webroot should receive the custom path
        call_kwargs = mock_set_webroot.call_args
        assert call_kwargs is not None
        # Check webroot arg
        all_args = str(call_kwargs)
        assert "public_html/web" in all_args

    # ------------------------------------------------------------------
    # Summary output
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_summary_output_verification(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-5: Rich-formatted summary of all steps with status."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging"])
        assert result.exit_code == 0

        # Summary should mention key steps
        output_lower = result.output.lower()
        assert "env" in output_lower or ".env" in output_lower
        assert "webroot" in output_lower
        assert "shared" in output_lower or "init" in output_lower
        assert "verif" in output_lower or "check" in output_lower

    # ------------------------------------------------------------------
    # Exit codes
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_exit_code_0_all_pass(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-9: Returns exit code 0 when all steps succeed."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging"])
        assert result.exit_code == 0

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_exit_code_1_failure(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """AC-P4-10: Returns exit code 1 when any step fails."""
        mock_env_exists.return_value = False
        mock_env_gen.side_effect = Exception("Failed")

        result = self._invoke(["staging"])
        assert result.exit_code == 1

    # ------------------------------------------------------------------
    # Invalid environment
    # ------------------------------------------------------------------

    def test_invalid_environment(self) -> None:
        """Returns exit code 1 for unknown environment."""
        result = self._invoke(["nonexistent-env"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    # ------------------------------------------------------------------
    # Idempotent re-run
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_idempotent_rerun(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """Setup-bedrock is safe to re-run (skips existing .env, set-webroot is idempotent)."""
        mock_env_exists.return_value = True  # .env already exists
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging"])
        assert result.exit_code == 0

        # env-generate should be skipped
        mock_env_gen.assert_not_called()

    # ------------------------------------------------------------------
    # Ready-to-deploy message
    # ------------------------------------------------------------------

    @patch("cloudways_api.commands.setup_bedrock._run_verify_setup")
    @patch("cloudways_api.commands.setup_bedrock._run_init_shared")
    @patch("cloudways_api.commands.setup_bedrock._run_set_webroot")
    @patch("cloudways_api.commands.setup_bedrock._run_env_generate")
    @patch("cloudways_api.commands.setup_bedrock._env_exists_on_server")
    def test_ready_to_deploy_message(
        self,
        mock_env_exists: AsyncMock,
        mock_env_gen: AsyncMock,
        mock_set_webroot: AsyncMock,
        mock_init_shared: AsyncMock,
        mock_verify: AsyncMock,
    ) -> None:
        """Shows 'Ready to deploy' message when all steps succeed."""
        mock_env_exists.return_value = False
        mock_env_gen.return_value = None
        mock_set_webroot.return_value = None
        mock_init_shared.return_value = None
        mock_verify.return_value = (8, 8)

        result = self._invoke(["staging"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "deploy" in output_lower or "cap" in output_lower


class TestSetupBedrockHelp:
    """CLI registration tests for setup-bedrock."""

    def test_setup_bedrock_help(self) -> None:
        """setup-bedrock is registered and shows help text."""
        result = runner.invoke(app, ["setup-bedrock", "--help"])
        assert result.exit_code == 0
        assert "setup-bedrock" in result.output.lower() or "bedrock" in result.output.lower()
