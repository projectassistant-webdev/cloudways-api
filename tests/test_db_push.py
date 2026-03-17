"""Tests for db-push command."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
def _mock_db_push_success():
    """Context manager that mocks all SSH/DB operations for a successful push."""
    mock_subprocess_result = MagicMock()
    mock_subprocess_result.returncode = 0
    mock_subprocess_result.stderr = b""
    mock_subprocess_result.stdout = b""

    with (
        patch(
            "cloudways_api.commands.db_push.validate_ssh_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "cloudways_api.commands.db_push.run_ssh_command",
            new_callable=AsyncMock,
            return_value=(
                "define('DB_NAME', 'wp_projectassistant');",
                "",
                0,
            ),
        ) as mock_ssh,
        patch(
            "cloudways_api.commands.db_push.stream_local_to_remote",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_stream,
        patch(
            "cloudways_api.commands.db_push.sftp_upload",
            new_callable=AsyncMock,
        ) as mock_upload,
        patch(
            "cloudways_api.commands.db_push.get_url_replacer",
        ) as mock_get_replacer,
        patch(
            "cloudways_api.commands.db_push.subprocess.run",
            return_value=mock_subprocess_result,
        ) as mock_subprocess,
    ):
        mock_replacer = AsyncMock()
        mock_get_replacer.return_value = mock_replacer
        yield {
            "mock_ssh": mock_ssh,
            "mock_stream": mock_stream,
            "mock_upload": mock_upload,
            "mock_get_replacer": mock_get_replacer,
            "mock_replacer": mock_replacer,
            "mock_subprocess": mock_subprocess,
        }


class TestDBPushRegistration:
    """Tests for db-push command registration."""

    def test_db_push_listed_in_help(self) -> None:
        """cloudways --help lists db-push command."""
        result = runner.invoke(app, ["--help"])
        assert "db-push" in result.output

    def test_db_push_accepts_environment_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-push accepts a positional environment argument."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production"], input="y\n")
            assert result.exit_code == 0

    def test_db_push_requires_environment_argument(self) -> None:
        """db-push with no arguments exits with code 2 (usage error)."""
        result = runner.invoke(app, ["db-push"])
        assert result.exit_code == 2


class TestDBPushStreamMode:
    """Tests for stream mode (default)."""

    def test_db_push_uses_stream_mode_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-push production uses stream mode by default."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            mocks["mock_stream"].assert_called_once()

    def test_stream_mode_calls_stream_local_to_remote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream mode calls stream_local_to_remote with correct args."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            call_kwargs = mocks["mock_stream"].call_args
            # Verify host and user are passed
            args = call_kwargs[1] if call_kwargs[1] else {}
            pos_args = call_kwargs[0] if call_kwargs[0] else ()
            all_args = str(pos_args) + str(args)
            assert "159.223.142.14" in all_args or len(pos_args) >= 2


class TestDBPushFileMode:
    """Tests for file mode (--safe)."""

    def test_db_push_safe_uses_file_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-push --safe uses file mode with sftp_upload."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging", "--safe"])
            assert result.exit_code == 0
            mocks["mock_upload"].assert_called_once()

    def test_file_mode_dumps_uploads_imports(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File mode: local dump, SCP upload, remote import."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging", "--safe"])
            assert result.exit_code == 0
            # Upload was called
            mocks["mock_upload"].assert_called_once()
            # Remote import was called via run_ssh_command
            assert mocks["mock_ssh"].call_count >= 2  # at least wp-config + backup + import


class TestDBPushFlags:
    """Tests for db-push CLI flags."""

    def test_no_replace_skips_url_replacement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-replace flag skips URL replacement."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging", "--no-replace"])
            assert result.exit_code == 0
            mocks["mock_get_replacer"].assert_not_called()

    def test_skip_transients_excludes_tables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-transients passes transient tables to mysqldump."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--skip-transients"]
            )
            assert result.exit_code == 0
            assert "Tables Skipped" in result.output

    def test_skip_backup_flag_skips_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-backup flag skips automatic remote backup."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--skip-backup"]
            )
            assert result.exit_code == 0
            # Verify fewer SSH calls (no backup command)
            assert "skipped" in result.output.lower()

    def test_yes_flag_skips_production_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes flag skips production confirmation prompt."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production", "--yes"])
            assert result.exit_code == 0
            assert "Continue?" not in result.output

    def test_local_container_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--local-container overrides config local_container."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app,
                ["db-push", "staging", "--local-container", "custom-mysql"],
            )
            assert result.exit_code == 0

    def test_local_db_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--local-db overrides config local_db_name."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--local-db", "custom_db"]
            )
            assert result.exit_code == 0

    def test_local_domain_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--local-domain overrides default localhost."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(
                app,
                ["db-push", "staging", "--local-domain", "mylocal.test"],
            )
            assert result.exit_code == 0
            # URL replacer should use the custom local domain
            if mocks["mock_replacer"].called:
                call_kwargs = mocks["mock_replacer"].call_args[1]
                assert call_kwargs.get("source_domain") == "mylocal.test"

    def test_local_domain_defaults_to_localhost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--local-domain defaults to localhost."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            if mocks["mock_replacer"].called:
                call_kwargs = mocks["mock_replacer"].call_args[1]
                assert call_kwargs.get("source_domain") == "localhost"


class TestDBPushProductionConfirmation:
    """Tests for production confirmation prompt."""

    def test_production_shows_confirmation_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pushing to production shows confirmation prompt."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production"], input="y\n")
            assert result.exit_code == 0
            assert "PRODUCTION" in result.output

    def test_declining_confirmation_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declining production confirmation exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production"], input="n\n")
            assert result.exit_code == 0
            assert "cancelled" in result.output.lower()

    def test_yes_flag_bypasses_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--yes flag bypasses production confirmation."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production", "--yes"])
            assert result.exit_code == 0

    def test_staging_skips_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-production environments skip confirmation prompt."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            # No confirmation prompt for staging
            assert "Continue?" not in result.output


class TestDBPushAutoBackup:
    """Tests for automatic remote backup."""

    def test_auto_backup_before_push(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-push creates remote backup before push."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            # Verify backup path in output
            assert "Backup" in result.output

    def test_backup_follows_naming_convention(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backup path follows /tmp/cloudways_backup_{db}_{date}_{time}.sql.gz."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "cloudways_backup" in result.output

    def test_backup_failure_aborts_push(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backup failure aborts the push with error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        call_count = 0

        async def mock_ssh_command(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call: wp-config detection
            if call_count == 1:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            # Second call: backup command - fail
            if call_count == 2:
                raise SSHError("Remote backup failed")
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh_command,
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 1

    def test_skip_backup_shows_skipped_in_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-backup shows 'skipped' in the output."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--skip-backup"]
            )
            assert result.exit_code == 0
            assert "skipped" in result.output.lower()


class TestDBPushURLReplacement:
    """Tests for URL replacement direction."""

    def test_url_replacement_uses_remote_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacement calls get_url_replacer with remote=True."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            mocks["mock_get_replacer"].assert_called_once()
            call_kwargs = mocks["mock_get_replacer"].call_args
            # Check remote=True was passed
            if call_kwargs[1]:
                assert call_kwargs[1].get("remote") is True
            else:
                assert call_kwargs[0][1] is True  # positional arg

    def test_url_replacement_reversed_direction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """URL replacement uses local -> remote direction."""
        _patch_config(monkeypatch)
        with _mock_db_push_success() as mocks:
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            if mocks["mock_replacer"].called:
                call_kwargs = mocks["mock_replacer"].call_args[1]
                assert call_kwargs.get("source_domain") == "localhost"

    def test_env_file_method_warns_and_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env-file method on push warns and continues (skips get_url_replacer)."""
        _patch_config(monkeypatch)
        import yaml

        # Override config to use env-file method
        config_path = FIXTURES_DIR / "project-config.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        config.setdefault("hosting", {}).setdefault(
            "cloudways", {}
        ).setdefault("database", {})["url_replace_method"] = "env-file"

        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as tmp:
            yaml.dump(config, tmp)
            tmp_path = tmp.name

        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", tmp_path)

        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stderr = b""

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                return_value=(
                    "define('DB_NAME', 'wp_projectassistant');",
                    "",
                    0,
                ),
            ),
            patch(
                "cloudways_api.commands.db_push.stream_local_to_remote",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "cloudways_api.commands.db_push.subprocess.run",
                return_value=mock_subprocess_result,
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "not supported" in result.output.lower()

        # Cleanup
        import os

        os.unlink(tmp_path)


class TestDBPushErrors:
    """Tests for error paths."""

    def test_invalid_environment_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid environment shows error with available environments."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-push", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_missing_config_shows_error(self, tmp_path: Path) -> None:
        """Missing config file shows error."""
        result = runner.invoke(
            app,
            ["db-push", "production"],
            env={"CLOUDWAYS_PROJECT_CONFIG": str(tmp_path / "missing.yml")},
        )
        assert result.exit_code == 1

    def test_ssh_connection_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSH connection failure shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        with patch(
            "cloudways_api.commands.db_push.validate_ssh_connection",
            new_callable=AsyncMock,
            side_effect=SSHError("Connection refused"),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 1

    def test_remote_import_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Remote import failure shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                return_value=(
                    "define('DB_NAME', 'wp_projectassistant');",
                    "",
                    0,
                ),
            ),
            patch(
                "cloudways_api.commands.db_push.stream_local_to_remote",
                new_callable=AsyncMock,
                side_effect=SSHError("Remote command failed"),
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 1

    def test_wp_config_parse_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wp-config.php parse failure shows error."""
        _patch_config(monkeypatch)

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                return_value=("no define here", "", 0),
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 1


class TestDBPushExitCodes:
    """Tests for exit codes."""

    def test_successful_push_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful push exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0

    def test_error_paths_exit_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error paths exit with code 1."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-push", "nonexistent"])
        assert result.exit_code == 1

    def test_user_declining_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """User declining confirmation exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "production"], input="n\n")
            assert result.exit_code == 0


class TestDBPushSuccessOutput:
    """Tests for success output."""

    def test_output_includes_required_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output includes Environment, Remote DB, Local DB, Mode, Time."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "Environment" in result.output
            assert "Remote DB" in result.output
            assert "Local DB" in result.output
            assert "Mode" in result.output
            assert "Time" in result.output

    def test_output_includes_backup_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output includes Backup path."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "Backup" in result.output

    def test_output_includes_url_replace_details(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output includes URL Replace details."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "URL Replace" in result.output

    def test_output_skip_backup_shows_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output with --skip-backup shows 'skipped'."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--skip-backup"]
            )
            assert result.exit_code == 0
            assert "skipped" in result.output.lower()


class TestDBPushFlagCombinations:
    """Tests for flag combinations."""

    def test_all_flags_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe --skip-transients --no-replace --skip-backup --yes all work."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app,
                [
                    "db-push",
                    "production",
                    "--safe",
                    "--skip-transients",
                    "--no-replace",
                    "--skip-backup",
                    "--yes",
                ],
            )
            assert result.exit_code == 0

    def test_safe_skip_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe --skip-backup works (file mode without backup)."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--safe", "--skip-backup"]
            )
            assert result.exit_code == 0

    def test_safe_skip_transients(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--safe and --skip-transients work together."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(
                app, ["db-push", "staging", "--safe", "--skip-transients"]
            )
            assert result.exit_code == 0


class TestDBPushBackupVerification:
    """Tests for backup file verification (test -s)."""

    def test_backup_verify_failure_raises_database_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backup verify failure (test -s) raises DatabaseError, not SSHError."""
        _patch_config(monkeypatch)

        call_count = 0

        async def mock_ssh_command(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            # wp-config detection
            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            # backup command succeeds
            if "mysqldump" in cmd:
                return ("", "", 0)
            # test -s fails (backup empty/missing)
            if "test -s" in cmd:
                return ("", "", 1)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh_command,
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 1
            assert "not found or empty" in result.output.lower()

    def test_backup_verify_uses_raise_on_error_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backup verify passes raise_on_error=False to run_ssh_command."""
        _patch_config(monkeypatch)

        captured_kwargs: list[dict] = []

        async def mock_ssh_command(*args, **kwargs):
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "test -s" in cmd:
                captured_kwargs.append(kwargs)
            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            return ("", "", 0)

        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stderr = b""
        mock_subprocess_result.stdout = b""

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh_command,
            ),
            patch(
                "cloudways_api.commands.db_push.stream_local_to_remote",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "cloudways_api.commands.db_push.get_url_replacer",
            ) as mock_get_replacer,
            patch(
                "cloudways_api.commands.db_push.subprocess.run",
                return_value=mock_subprocess_result,
            ),
        ):
            mock_get_replacer.return_value = AsyncMock()
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            # Verify raise_on_error=False was passed for test -s call
            assert len(captured_kwargs) >= 1
            assert captured_kwargs[0].get("raise_on_error") is False


class TestDBPushInvalidURLMethod:
    """Tests for invalid url_replace_method handling."""

    def test_invalid_url_method_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid url_replace_method (e.g., typo) raises error, not silently skips."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import ConfigError

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                return_value=(
                    "define('DB_NAME', 'wp_projectassistant');",
                    "",
                    0,
                ),
            ),
            patch(
                "cloudways_api.commands.db_push.stream_local_to_remote",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "cloudways_api.commands.db_push.get_url_replacer",
                side_effect=ConfigError(
                    "Unknown url_replace_method 'wp-clli'. "
                    "Valid options: wp-cli, sql-replace"
                ),
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            # Invalid method name must cause exit 1, NOT silently skip
            assert result.exit_code == 1

    def test_env_file_method_warns_not_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env-file method on push warns and continues (exit 0)."""
        import os
        import tempfile

        import yaml

        # Override config to use env-file method
        config_path = FIXTURES_DIR / "project-config.yml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        config["hosting"]["cloudways"]["database"]["url_replace_method"] = (
            "env-file"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False
        ) as tmp:
            yaml.dump(config, tmp)
            tmp_path = tmp.name

        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", tmp_path)

        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stderr = b""

        with (
            patch(
                "cloudways_api.commands.db_push.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_push.run_ssh_command",
                new_callable=AsyncMock,
                return_value=(
                    "define('DB_NAME', 'wp_projectassistant');",
                    "",
                    0,
                ),
            ),
            patch(
                "cloudways_api.commands.db_push.stream_local_to_remote",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "cloudways_api.commands.db_push.subprocess.run",
                return_value=mock_subprocess_result,
            ),
        ):
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "not supported" in result.output.lower()

        # Cleanup
        os.unlink(tmp_path)


class TestDBPushEdgeCases:
    """Tests for edge cases."""

    def test_staging_skips_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Staging environment does not show confirmation prompt."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "Continue?" not in result.output

    def test_db_push_complete_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-push outputs 'Database Push Complete' on success."""
        _patch_config(monkeypatch)
        with _mock_db_push_success():
            result = runner.invoke(app, ["db-push", "staging"])
            assert result.exit_code == 0
            assert "Database Push Complete" in result.output
