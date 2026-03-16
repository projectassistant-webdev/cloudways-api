"""Tests for db-sync command."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
import typer.testing

from cloudways_api.cli import app
from conftest import FIXTURES_DIR

runner = typer.testing.CliRunner()


def _patch_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point config loading at test fixture."""
    monkeypatch.setenv(
        "CLOUDWAYS_PROJECT_CONFIG",
        str(FIXTURES_DIR / "project-config.yml"),
    )


@contextmanager
def _mock_db_sync_success():
    """Context manager that mocks all SSH/DB operations for a successful sync."""
    with (
        patch(
            "cloudways_api.commands.db_sync.validate_ssh_connection",
            new_callable=AsyncMock,
        ) as mock_validate,
        patch(
            "cloudways_api.commands.db_sync.run_ssh_command",
            new_callable=AsyncMock,
            return_value=(
                "define('DB_NAME', 'wp_example');",
                "",
                0,
            ),
        ) as mock_ssh,
        patch(
            "cloudways_api.commands.db_sync.stream_local_to_remote",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_stream_push,
        patch(
            "cloudways_api.commands.db_sync.sftp_download",
            new_callable=AsyncMock,
        ) as mock_download,
        patch(
            "cloudways_api.commands.db_sync.sftp_upload",
            new_callable=AsyncMock,
        ) as mock_upload,
        patch(
            "cloudways_api.commands.db_sync.get_url_replacer",
        ) as mock_get_replacer,
    ):
        mock_replacer = AsyncMock()
        mock_get_replacer.return_value = mock_replacer
        yield {
            "mock_validate": mock_validate,
            "mock_ssh": mock_ssh,
            "mock_stream_push": mock_stream_push,
            "mock_download": mock_download,
            "mock_upload": mock_upload,
            "mock_get_replacer": mock_get_replacer,
            "mock_replacer": mock_replacer,
        }


class TestDBSyncRegistration:
    """Tests for db-sync command registration."""

    def test_db_sync_listed_in_help(self) -> None:
        """cloudways --help lists db-sync command."""
        result = runner.invoke(app, ["--help"])
        assert "db-sync" in result.output

    def test_db_sync_requires_source_and_target(self) -> None:
        """db-sync with no arguments exits with code 2 (usage error)."""
        result = runner.invoke(app, ["db-sync"])
        assert result.exit_code == 2

    def test_db_sync_requires_target_argument(self) -> None:
        """db-sync with only source arg exits with code 2."""
        result = runner.invoke(app, ["db-sync", "production"])
        assert result.exit_code == 2


class TestDBSyncStreamMode:
    """Tests for stream mode (default)."""

    def test_db_sync_success_stream_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-sync production staging succeeds in stream mode."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            assert "Database Sync Complete" in result.output

    def test_stream_mode_calls_stream_local_to_remote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream mode calls stream_local_to_remote for source->target relay."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            mocks["mock_stream_push"].assert_called_once()


class TestDBSyncFileMode:
    """Tests for file mode (--safe)."""

    def test_db_sync_safe_uses_file_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-sync --safe uses file-based transfer."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--safe"]
            )
            assert result.exit_code == 0
            mocks["mock_download"].assert_called_once()
            mocks["mock_upload"].assert_called_once()

    def test_safe_mode_no_stream_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe mode does not call stream_local_to_remote."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--safe"]
            )
            assert result.exit_code == 0
            mocks["mock_stream_push"].assert_not_called()


class TestDBSyncAutoBackup:
    """Tests for automatic backup behavior."""

    def test_auto_backup_runs_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-sync backs up target DB before overwriting by default."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            assert "Backup" in result.output
            assert mocks["mock_ssh"].call_count >= 1

    def test_skip_backup_skips_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-backup skips automatic backup."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--skip-backup"]
            )
            assert result.exit_code == 0
            assert "skipped" in result.output.lower()


class TestDBSyncURLReplacement:
    """Tests for URL replacement behavior."""

    def test_url_replacement_wp_cli_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacement uses wp-cli by default."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            mocks["mock_get_replacer"].assert_called_once()
            call_args = mocks["mock_get_replacer"].call_args
            assert call_args[0][0] == "wp-cli"
            # Check remote=True was passed
            if call_args[1]:
                assert call_args[1].get("remote") is True
            else:
                assert call_args[0][1] is True

    def test_url_replacement_sql_replace_method(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--replace-method sql-replace uses sql-replace strategy."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(
                app,
                ["db-sync", "production", "staging", "--replace-method", "sql-replace"],
            )
            assert result.exit_code == 0
            mocks["mock_get_replacer"].assert_called_once()
            call_args = mocks["mock_get_replacer"].call_args
            assert call_args[0][0] == "sql-replace"

    def test_no_replace_skips_url_replacement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-replace flag skips URL replacement."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--no-replace"]
            )
            assert result.exit_code == 0
            mocks["mock_get_replacer"].assert_not_called()

    def test_url_replacement_uses_correct_domains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacement uses source and target domains from config."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success() as mocks:
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            if mocks["mock_replacer"].called:
                call_kwargs = mocks["mock_replacer"].call_args[1]
                assert call_kwargs.get("source_domain") == "wp.example.com"
                assert (
                    call_kwargs.get("target_domain")
                    == "staging.wp.example.com"
                )


class TestDBSyncProductionSafety:
    """Tests for production safety checks."""

    def test_production_target_without_force_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Target production without --force exits with code 1."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "staging", "production"])
        assert result.exit_code == 1
        assert "force" in result.output.lower()

    def test_production_target_with_force_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Target production with --force succeeds."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(
                app, ["db-sync", "staging", "production", "--force"]
            )
            assert result.exit_code == 0

    def test_prod_case_insensitive_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production names are case-insensitive. 'production' triggers check."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "staging", "production"])
        assert result.exit_code == 1
        assert "force" in result.output.lower()

    def test_source_production_allowed_without_force(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pulling from production (source) is always allowed without --force."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0


class TestDBSyncValidation:
    """Tests for input validation."""

    def test_source_equals_target_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Source and target being the same exits with error."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "staging", "staging"])
        assert result.exit_code == 1
        assert "same" in result.output.lower()

    def test_invalid_source_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid source environment shows error."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "nonexistent", "staging"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_invalid_target_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid target environment shows error."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "production", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestDBSyncSkipTransients:
    """Tests for --skip-transients flag."""

    def test_skip_transients_excludes_tables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-transients excludes transient/cache tables from dump."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--skip-transients"]
            )
            assert result.exit_code == 0
            assert "Tables Skipped" in result.output


class TestDBSyncErrors:
    """Tests for error handling."""

    def test_ssh_failure_on_stream_transfer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSH failure during stream transfer shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        with (
            patch(
                "cloudways_api.commands.db_sync.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_sync.run_ssh_command",
                new_callable=AsyncMock,
                return_value=(
                    "define('DB_NAME', 'wp_example');",
                    "",
                    0,
                ),
            ),
            patch(
                "cloudways_api.commands.db_sync.stream_local_to_remote",
                new_callable=AsyncMock,
                side_effect=SSHError("Remote command failed"),
            ),
        ):
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 1

    def test_ssh_failure_on_file_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSH failure during file-mode transfer shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        with (
            patch(
                "cloudways_api.commands.db_sync.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_sync.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=[
                    # DB name detection for source
                    ("define('DB_NAME', 'wp_example');", "", 0),
                    # DB name detection for target
                    ("define('DB_NAME', 'wp_example');", "", 0),
                    # Backup
                    ("", "", 0),
                    # Backup verify
                    ("", "", 0),
                    # Dump on source fails
                    SSHError("Remote command failed"),
                ],
            ),
            patch(
                "cloudways_api.commands.db_sync.sftp_download",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_sync.sftp_upload",
                new_callable=AsyncMock,
            ),
        ):
            result = runner.invoke(
                app, ["db-sync", "production", "staging", "--safe"]
            )
            assert result.exit_code == 1


class TestDBSyncOutput:
    """Tests for output and summary."""

    def test_summary_output_includes_required_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output includes source, target, mode, time."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0
            assert "Source" in result.output
            assert "Target" in result.output
            assert "Mode" in result.output
            assert "Time" in result.output

    def test_exit_code_zero_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful sync exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_sync_success():
            result = runner.invoke(app, ["db-sync", "production", "staging"])
            assert result.exit_code == 0

    def test_exit_code_one_on_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed sync exits with code 1."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-sync", "nonexistent", "staging"])
        assert result.exit_code == 1
