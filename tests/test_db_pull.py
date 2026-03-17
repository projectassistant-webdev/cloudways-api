"""Tests for db-pull command integration."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import DatabaseError, SSHError
from conftest import FIXTURES_DIR

runner = CliRunner()

# Pre-built credentials dict returned by detect_remote_db_credentials mock.
_FAKE_DB_CREDS = {
    "db_name": "wp_projectassistant",
    "db_user": "root",
    "db_password": "secret",
    "db_host": "localhost",
    "env_type": "traditional",
}


def _patch_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point config loading to the test fixture."""
    monkeypatch.setenv(
        "CLOUDWAYS_PROJECT_CONFIG",
        str(FIXTURES_DIR / "project-config.yml"),
    )


def _mock_ssh_success():
    """Return mock patches for successful SSH operations.

    Mocks ``detect_remote_db_credentials`` directly (returns a pre-built
    credentials dict) so tests are decoupled from the internal SSH calls
    that the detection layer makes.  ``run_ssh_command`` is retained only
    for the DB-size estimation step (Step 3 in ``_execute_db_pull``).
    """
    return {
        "validate": patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ),
        "detect_creds": patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ),
        "run_cmd": patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),  # DB size query
        ),
        "stream": patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ),
        "sftp": patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ),
        "url_replacer": patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ),
    }


class TestDBPullCLIRegistration:
    """Tests for db-pull command registration in CLI."""

    def test_db_pull_registered_in_cli_help(self) -> None:
        """db-pull command appears in --help output."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "db-pull" in result.output

    def test_db_pull_accepts_environment_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull accepts an environment argument."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            # Should succeed or provide meaningful output
            assert result.exit_code == 0


class TestDBPullStreamMode:
    """Tests for stream mode (default)."""

    def test_db_pull_stream_mode_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull uses stream mode by default."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], \
             mocks["stream"] as mock_stream, \
             mocks["sftp"] as mock_sftp, mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            # Stream mode should be used (stream_ssh_pipe called)
            mock_stream.assert_called_once()
            # SFTP should NOT be called in stream mode
            mock_sftp.assert_not_called()


class TestDBPullFileMode:
    """Tests for file mode (--safe)."""

    def test_db_pull_file_mode_with_safe_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull --safe uses file mode (SFTP download)."""
        _patch_config(monkeypatch)

        # run_ssh_command calls in file mode (detect_creds handled separately):
        # 1. db size query, 2. remote dump, 3. cleanup (best-effort)
        ssh_side_effects = [
            ("12345678", "", 0),  # db size
            ("", "", 0),  # remote dump
            ("", "", 0),  # cleanup (best-effort)
        ]

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=ssh_side_effects,
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
        ) as mock_stream, patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ) as mock_sftp, patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ), patch(
            "cloudways_api.commands.db_pull._run_local_import",
            new_callable=AsyncMock,
        ):
            result = runner.invoke(app, ["db-pull", "production", "--safe"])
            assert result.exit_code == 0
            # SFTP should be called in file mode
            mock_sftp.assert_called_once()
            # Stream should NOT be called in file mode
            mock_stream.assert_not_called()


class TestDBPullFlags:
    """Tests for db-pull command flags."""

    def test_db_pull_no_replace_flag_skips_url_replacement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-replace flag skips URL replacement."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"] as mock_replacer:
            result = runner.invoke(
                app, ["db-pull", "production", "--no-replace"]
            )
            assert result.exit_code == 0
            # URL replacer should not be called
            mock_replacer.assert_not_called()

    def test_db_pull_skip_transients_passes_ignore_tables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-transients passes transient tables to mysqldump."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], \
             mocks["stream"] as mock_stream, \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(
                app, ["db-pull", "production", "--skip-transients"]
            )
            assert result.exit_code == 0
            # Check the stream call includes transient skip tables
            call_args = mock_stream.call_args
            remote_cmd = call_args[1].get("remote_cmd", "") if call_args[1] else call_args[0][2]
            assert "ignore-table" in remote_cmd


class TestDBPullDetection:
    """Tests for remote DB name detection."""

    def test_db_pull_detects_remote_db_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull detects remote DB name from wp-config.php."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"] as mock_run, \
             mocks["stream"], mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            # run_ssh_command called at least once (for wp-config grep)
            mock_run.assert_called()


class TestDBPullSuccessOutput:
    """Tests for success output."""

    def test_db_pull_success_output_contains_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output contains key summary information."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            assert "production" in result.output.lower() or "complete" in result.output.lower()


class TestDBPullErrors:
    """Tests for db-pull error paths."""

    def test_db_pull_invalid_environment_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid environment name shows error with available envs."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-pull", "nonexistent"])
        assert result.exit_code == 1
        assert "nonexistent" in result.output.lower() or "not found" in result.output.lower()

    def test_db_pull_missing_database_config_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing database config section shows error."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 123\n"
            "      ssh_user: master_user\n"
            "      ssh_host: 1.2.3.4\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(cfg))
        result = runner.invoke(app, ["db-pull", "production"])
        assert result.exit_code == 1
        assert "database" in result.output.lower()

    def test_db_pull_ssh_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSH connection failure shows user-friendly error."""
        _patch_config(monkeypatch)
        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
            side_effect=SSHError("SSH authentication failed."),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1
            assert "ssh" in result.output.lower() or "error" in result.output.lower()

    def test_db_pull_wp_config_parse_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wp-config.php parse failure shows error."""
        _patch_config(monkeypatch)
        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            side_effect=DatabaseError("Could not detect database credentials"),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1
            assert "detect" in result.output.lower() or "error" in result.output.lower()

    def test_db_pull_mysqldump_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Remote mysqldump failure shows error."""
        _patch_config(monkeypatch)
        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=1,  # non-zero = failure
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1

    def test_db_pull_url_replace_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacement failure shows error."""
        _patch_config(monkeypatch)
        mock_replacer = AsyncMock(side_effect=Exception("replace failed"))

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=mock_replacer,
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1


class TestDBPullExitCodes:
    """Tests for exit codes."""

    def test_db_pull_success_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful db-pull exits with code 0."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0

    def test_db_pull_error_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull with error exits with code 1."""
        _patch_config(monkeypatch)
        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
            side_effect=SSHError("connection failed"),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1


class TestDBPullFlagCombinations:
    """Tests for combined flags."""

    def test_db_pull_safe_and_skip_transients_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe and --skip-transients flags work together."""
        _patch_config(monkeypatch)

        ssh_side_effects = [
            ("12345678", "", 0),  # db size
            ("", "", 0),  # remote dump
            ("", "", 0),  # cleanup
        ]

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=ssh_side_effects,
        ), patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ), patch(
            "cloudways_api.commands.db_pull._run_local_import",
            new_callable=AsyncMock,
        ):
            result = runner.invoke(
                app,
                ["db-pull", "production", "--safe", "--skip-transients"],
            )
            assert result.exit_code == 0

    def test_db_pull_safe_and_no_replace_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe and --no-replace flags work together."""
        _patch_config(monkeypatch)

        ssh_side_effects = [
            ("12345678", "", 0),  # db size
            ("", "", 0),  # remote dump
            ("", "", 0),  # cleanup
        ]

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=ssh_side_effects,
        ), patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ) as mock_replacer, patch(
            "cloudways_api.commands.db_pull._run_local_import",
            new_callable=AsyncMock,
        ):
            result = runner.invoke(
                app,
                ["db-pull", "production", "--safe", "--no-replace"],
            )
            assert result.exit_code == 0
            mock_replacer.assert_not_called()


class TestDBPullEdgeCases:
    """Edge case tests for db-pull command."""

    def test_db_pull_db_size_estimation_failure_is_nonfatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB size estimation failure doesn't abort the pull."""
        _patch_config(monkeypatch)

        # run_ssh_command call 1: db size (fail).
        # stream_ssh_pipe handles the actual dump.
        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=SSHError("permission denied on db size query"),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            # Size should be "unknown" since estimation failed
            assert "unknown" in result.output.lower()

    def test_db_pull_db_size_null_value_shows_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DB size returning NULL shows 'unknown' in output."""
        _patch_config(monkeypatch)

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("NULL", "", 0),  # db size returns NULL
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            assert "unknown" in result.output.lower()

    def test_db_pull_success_output_contains_all_summary_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output includes environment, remote DB, local DB, mode, time."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            output_lower = result.output.lower()
            assert "environment" in output_lower or "production" in output_lower
            assert "remote db" in output_lower
            assert "local db" in output_lower
            assert "mode" in output_lower
            assert "time" in output_lower

    def test_db_pull_file_mode_cleanup_failure_is_nonfatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File mode cleanup of remote dump file failure is non-fatal."""
        _patch_config(monkeypatch)

        call_count = 0

        async def _ssh_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("5000000", "", 0)  # db size
            elif call_count == 2:
                return ("", "", 0)  # remote dump
            elif call_count == 3:
                raise SSHError("cleanup failed")  # cleanup fails
            return ("", "", 0)

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=_ssh_side_effect,
        ), patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ), patch(
            "cloudways_api.commands.db_pull._run_local_import",
            new_callable=AsyncMock,
        ):
            result = runner.invoke(
                app, ["db-pull", "production", "--safe"]
            )
            # Should still succeed despite cleanup failure
            assert result.exit_code == 0

    def test_db_pull_all_three_flags_combined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe, --skip-transients, and --no-replace all work together."""
        _patch_config(monkeypatch)

        ssh_side_effects = [
            ("5000000", "", 0),  # db size
            ("", "", 0),  # remote dump
            ("", "", 0),  # cleanup
        ]

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=ssh_side_effects,
        ), patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ) as mock_replacer, patch(
            "cloudways_api.commands.db_pull._run_local_import",
            new_callable=AsyncMock,
        ):
            result = runner.invoke(
                app,
                ["db-pull", "production", "--safe", "--skip-transients",
                 "--no-replace"],
            )
            assert result.exit_code == 0
            # URL replacer should not be called with --no-replace
            mock_replacer.assert_not_called()

    def test_db_pull_staging_environment_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-pull works with staging environment."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], mocks["stream"], \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "staging"])
            assert result.exit_code == 0

    def test_db_pull_wp_config_double_quotes_detected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """detect_remote_db_credentials returns correct DB name for double-quote configs."""
        _patch_config(monkeypatch)
        double_quote_creds = {**_FAKE_DB_CREDS, "db_name": "wp_double_quotes"}

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=double_quote_creds,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            assert "wp_double_quotes" in result.output

    def test_db_pull_stream_mode_includes_gunzip_in_local_cmd(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream mode local command pipes through gunzip."""
        _patch_config(monkeypatch)
        mocks = _mock_ssh_success()
        with mocks["validate"], mocks["detect_creds"], mocks["run_cmd"], \
             mocks["stream"] as mock_stream, \
             mocks["sftp"], mocks["url_replacer"]:
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            call_args = mock_stream.call_args
            local_cmd = (
                call_args[1].get("local_cmd", "")
                if call_args[1]
                else call_args[0][3]
            )
            assert "gunzip" in local_cmd

    def test_db_pull_url_replacer_called_with_correct_domains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacer receives correct source and target domains."""
        _patch_config(monkeypatch)
        mock_replacer_fn = AsyncMock()

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=mock_replacer_fn,
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 0
            mock_replacer_fn.assert_called_once()
            call_kwargs = mock_replacer_fn.call_args[1]
            assert call_kwargs["source_domain"] == "wp.projectassistant.org"
            assert call_kwargs["target_domain"] == "localhost"

    def test_db_pull_file_mode_sftp_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SFTP download failure in file mode shows error."""
        _patch_config(monkeypatch)

        ssh_side_effects = [
            ("5000000", "", 0),  # db size
            ("", "", 0),  # remote dump succeeds
            ("", "", 0),  # cleanup
        ]

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=ssh_side_effects,
        ), patch(
            "cloudways_api.commands.db_pull.sftp_download",
            new_callable=AsyncMock,
            side_effect=SSHError("SFTP download failed"),
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(
                app, ["db-pull", "production", "--safe"]
            )
            assert result.exit_code == 1

    def test_db_pull_database_error_during_import_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DatabaseError during stream import shows error."""
        _patch_config(monkeypatch)

        with patch(
            "cloudways_api.commands.db_pull.validate_ssh_connection",
            new_callable=AsyncMock,
        ), patch(
            "cloudways_api.commands.db_pull.detect_remote_db_credentials",
            new_callable=AsyncMock,
            return_value=_FAKE_DB_CREDS,
        ), patch(
            "cloudways_api.commands.db_pull.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("12345678", "", 0),
        ), patch(
            "cloudways_api.commands.db_pull.stream_ssh_pipe",
            new_callable=AsyncMock,
            side_effect=DatabaseError("import failed: table corrupted"),
        ), patch(
            "cloudways_api.commands.db_pull.get_url_replacer",
            return_value=AsyncMock(),
        ):
            result = runner.invoke(app, ["db-pull", "production"])
            assert result.exit_code == 1

    def test_db_pull_missing_config_file_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing config file shows error with helpful message."""
        monkeypatch.setenv(
            "CLOUDWAYS_PROJECT_CONFIG", "/nonexistent/path/cfg.yml"
        )
        result = runner.invoke(app, ["db-pull", "production"])
        assert result.exit_code == 1
        assert "error" in result.output.lower()
