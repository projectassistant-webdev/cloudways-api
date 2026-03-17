"""Tests for db-restore command."""

from contextlib import contextmanager
from pathlib import Path
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


# Simulated ls -lah output for backup listing tests
_LS_OUTPUT = (
    "total 144M\n"
    "-rw-r--r-- 1 root root 48M Feb  6 14:30 "
    "cloudways_backup_wp_projectassistant_20260206_143022.sql.gz\n"
    "-rw-r--r-- 1 root root 47M Feb  5 09:15 "
    "cloudways_backup_wp_projectassistant_20260205_091511.sql.gz\n"
    "-rw-r--r-- 1 root root 46M Feb  4 16:12 "
    "cloudways_backup_wp_projectassistant_20260204_161200.sql.gz\n"
)

# Most recent backup path
_MOST_RECENT = (
    "/tmp/cloudways_backup_wp_projectassistant_20260206_143022.sql.gz\n"
)


@contextmanager
def _mock_db_restore_success(
    ls_output: str = _LS_OUTPUT,
    most_recent: str = _MOST_RECENT,
):
    """Context manager that mocks all SSH/DB operations for restore."""
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
        # ls -lah for listing
        if "ls -lah" in cmd:
            return (ls_output, "", 0)
        # ls -t for most recent
        if "ls -t" in cmd:
            return (most_recent, "", 0)
        # test -s for backup file verification
        if "test -s" in cmd:
            return ("", "", 0)
        # gunzip import command
        if "gunzip" in cmd:
            return ("", "", 0)
        return ("", "", 0)

    with (
        patch(
            "cloudways_api.commands.db_restore.validate_ssh_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "cloudways_api.commands.db_restore.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=mock_ssh_command,
        ) as mock_ssh,
    ):
        yield {"mock_ssh": mock_ssh}


class TestDBRestoreRegistration:
    """Tests for db-restore command registration."""

    def test_db_restore_listed_in_help(self) -> None:
        """cloudways --help lists db-restore command."""
        result = runner.invoke(app, ["--help"])
        assert "db-restore" in result.output

    def test_db_restore_accepts_environment_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-restore accepts a positional environment argument."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0


class TestDBRestoreMostRecent:
    """Tests for restoring most recent backup."""

    def test_restore_finds_most_recent_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-restore production finds most recent backup automatically."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0

    def test_restore_imports_into_remote_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Most recent backup is imported into remote DB."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success() as mocks:
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0
            # Verify import was called via SSH
            assert mocks["mock_ssh"].call_count >= 3  # wp-config + ls -t + import

    def test_restore_success_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Success output shows backup path and timing."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0
            assert "Database Restore Complete" in result.output
            assert "Backup" in result.output
            assert "Time" in result.output


class TestDBRestoreSpecificFile:
    """Tests for restoring from a specific backup file."""

    def test_restore_from_specific_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--backup-file uses specified file."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(
                app,
                [
                    "db-restore",
                    "production",
                    "--backup-file",
                    "/tmp/specific_backup.sql.gz",
                ],
            )
            assert result.exit_code == 0

    def test_nonexistent_backup_file_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent backup file shows error."""
        _patch_config(monkeypatch)

        call_count = 0

        async def mock_ssh(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "test -s" in cmd:
                # File does not exist
                return ("", "No such file", 1)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "db-restore",
                    "production",
                    "--backup-file",
                    "/tmp/nonexistent.sql.gz",
                ],
            )
            assert result.exit_code == 1

    def test_empty_backup_file_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty backup file (zero bytes) shows error."""
        _patch_config(monkeypatch)

        call_count = 0

        async def mock_ssh(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "test -s" in cmd:
                # File exists but is empty (test -s fails)
                return ("", "", 1)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "db-restore",
                    "production",
                    "--backup-file",
                    "/tmp/empty.sql.gz",
                ],
            )
            assert result.exit_code == 1


class TestDBRestoreListBackups:
    """Tests for --list flag."""

    def test_list_displays_formatted_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--list displays available backups as formatted table."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0
            assert "cloudways_backup" in result.output

    def test_list_shows_filename_size_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--list shows filename, size, and date columns."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0
            assert "48M" in result.output or "47M" in result.output

    def test_list_no_backups_shows_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--list with no backups shows 'No backup files found'."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success(ls_output=""):
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0
            assert "no backup" in result.output.lower()

    def test_list_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--list exits with code 0 (list only, no restore)."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0


class TestDBRestoreErrors:
    """Tests for error paths."""

    def test_invalid_environment_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid environment shows error."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-restore", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_ssh_connection_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SSH connection failure shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        with patch(
            "cloudways_api.commands.db_restore.validate_ssh_connection",
            new_callable=AsyncMock,
            side_effect=SSHError("Connection refused"),
        ):
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 1

    def test_no_backups_found_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No backups found shows helpful error message."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success(most_recent="\n"):
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 1
            assert "no backup" in result.output.lower()

    def test_remote_import_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Remote import failure shows error."""
        _patch_config(monkeypatch)
        from cloudways_api.exceptions import SSHError

        call_count = 0

        async def mock_ssh(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "ls -t" in cmd:
                return (_MOST_RECENT, "", 0)
            if "test -s" in cmd:
                return ("", "", 0)
            if "gunzip" in cmd:
                raise SSHError("Import failed")
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 1

    def test_wp_config_parse_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """wp-config.php parse failure shows error."""
        _patch_config(monkeypatch)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                return_value=("no define here", "", 0),
            ),
        ):
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 1

    def test_missing_config_shows_error(self, tmp_path: Path) -> None:
        """Missing config file shows error."""
        result = runner.invoke(
            app,
            ["db-restore", "production"],
            env={"CLOUDWAYS_PROJECT_CONFIG": str(tmp_path / "missing.yml")},
        )
        assert result.exit_code == 1


class TestDBRestoreExitCodes:
    """Tests for exit codes."""

    def test_successful_restore_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful restore exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0

    def test_error_paths_exit_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error paths exit with code 1."""
        _patch_config(monkeypatch)
        result = runner.invoke(app, ["db-restore", "nonexistent"])
        assert result.exit_code == 1

    def test_list_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--list exits with code 0."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0


class TestDBRestoreBackupVerification:
    """Tests for backup file verification (test -s) with raise_on_error=False."""

    def test_verify_uses_raise_on_error_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """test -s verification passes raise_on_error=False."""
        _patch_config(monkeypatch)

        captured_kwargs: list[dict] = []

        async def mock_ssh(*args, **kwargs):
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "test -s" in cmd:
                captured_kwargs.append(kwargs)
            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "ls -t" in cmd:
                return (_MOST_RECENT, "", 0)
            if "test -s" in cmd:
                return ("", "", 0)
            if "gunzip" in cmd:
                return ("", "", 0)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0
            # Verify raise_on_error=False was passed for test -s call
            assert len(captured_kwargs) >= 1
            assert captured_kwargs[0].get("raise_on_error") is False

    def test_missing_backup_raises_database_error_not_ssh_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing backup file raises DatabaseError with clear message."""
        _patch_config(monkeypatch)

        async def mock_ssh(*args, **kwargs):
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "test -s" in cmd:
                return ("", "", 1)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "db-restore", "production",
                    "--backup-file", "/tmp/missing.sql.gz",
                ],
            )
            assert result.exit_code == 1
            assert "not found or empty" in result.output.lower()


class TestDBRestoreListBackupsErrorHandling:
    """Tests for _list_backups with ls returning non-zero."""

    def test_list_ls_nonzero_shows_no_backups(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ls returning non-zero shows 'No backup files found'."""
        _patch_config(monkeypatch)

        async def mock_ssh(*args, **kwargs):
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "ls -lah" in cmd:
                # ls fails when no files match glob
                return ("", "ls: cannot access ...: No such file", 2)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0
            assert "no backup" in result.output.lower()

    def test_list_ls_uses_raise_on_error_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_list_backups passes raise_on_error=False to ls command."""
        _patch_config(monkeypatch)

        captured_kwargs: list[dict] = []

        async def mock_ssh(*args, **kwargs):
            cmd = ""
            if len(args) >= 3:
                cmd = args[2]
            elif "command" in kwargs:
                cmd = kwargs["command"]

            if "ls -lah" in cmd:
                captured_kwargs.append(kwargs)
            if "DB_NAME" in cmd:
                return ("define('DB_NAME', 'wp_projectassistant');", "", 0)
            if "ls -lah" in cmd:
                return (_LS_OUTPUT, "", 0)
            return ("", "", 0)

        with (
            patch(
                "cloudways_api.commands.db_restore.validate_ssh_connection",
                new_callable=AsyncMock,
            ),
            patch(
                "cloudways_api.commands.db_restore.run_ssh_command",
                new_callable=AsyncMock,
                side_effect=mock_ssh,
            ),
        ):
            result = runner.invoke(
                app, ["db-restore", "production", "--list"]
            )
            assert result.exit_code == 0
            # Verify raise_on_error=False was passed for ls command
            assert len(captured_kwargs) >= 1
            assert captured_kwargs[0].get("raise_on_error") is False


class TestDBRestoreEdgeCases:
    """Tests for edge cases."""

    def test_staging_environment_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Restore works with staging environment."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "staging"])
            assert result.exit_code == 0

    def test_restore_complete_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """db-restore outputs 'Database Restore Complete' on success."""
        _patch_config(monkeypatch)
        with _mock_db_restore_success():
            result = runner.invoke(app, ["db-restore", "production"])
            assert result.exit_code == 0
            assert "Database Restore Complete" in result.output
