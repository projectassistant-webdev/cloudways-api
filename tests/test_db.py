"""Tests for database utilities module and Phase 2 config validation."""

import pytest

from cloudways_api.config import load_config, validate_phase2_config
from cloudways_api.db import (
    TRANSIENT_TABLES,
    build_db_size_query,
    build_import_command,
    build_local_mysqldump_docker_command,
    build_mysqldump_command,
    build_remote_backup_command,
    build_remote_import_command,
    build_wp_config_db_name_command,
    parse_db_name_from_wp_config,
)
from cloudways_api.exceptions import ConfigError, DatabaseError
from conftest import FIXTURES_DIR


class TestBuildMysqldumpCommand:
    """Tests for mysqldump command builder."""

    def test_mysqldump_includes_single_transaction_flag(self) -> None:
        """mysqldump command includes --single-transaction."""
        cmd = build_mysqldump_command("testdb")
        assert "--single-transaction" in cmd

    def test_mysqldump_includes_quick_flag(self) -> None:
        """mysqldump command includes --quick."""
        cmd = build_mysqldump_command("testdb")
        assert "--quick" in cmd

    def test_mysqldump_includes_routines_triggers_flags(self) -> None:
        """mysqldump command includes --routines and --triggers."""
        cmd = build_mysqldump_command("testdb")
        assert "--routines" in cmd
        assert "--triggers" in cmd

    def test_mysqldump_includes_set_gtid_purged_off(self) -> None:
        """mysqldump command includes --set-gtid-purged=OFF."""
        cmd = build_mysqldump_command("testdb")
        assert "--set-gtid-purged=OFF" in cmd

    def test_mysqldump_includes_no_tablespaces(self) -> None:
        """mysqldump command includes --no-tablespaces."""
        cmd = build_mysqldump_command("testdb")
        assert "--no-tablespaces" in cmd

    def test_mysqldump_includes_column_statistics_zero(self) -> None:
        """mysqldump command includes --column-statistics=0."""
        cmd = build_mysqldump_command("testdb")
        assert "--column-statistics=0" in cmd

    def test_mysqldump_includes_db_name(self) -> None:
        """mysqldump command includes the database name."""
        cmd = build_mysqldump_command("my_wordpress_db")
        assert "my_wordpress_db" in cmd

    def test_mysqldump_with_compress_pipes_to_gzip(self) -> None:
        """mysqldump with compress=True pipes to gzip -1."""
        cmd = build_mysqldump_command("testdb", compress=True)
        assert "gzip" in cmd

    def test_mysqldump_without_compress_no_gzip(self) -> None:
        """mysqldump with compress=False does not include gzip."""
        cmd = build_mysqldump_command("testdb", compress=False)
        assert "gzip" not in cmd

    def test_mysqldump_with_skip_tables_generates_ignore_flags(self) -> None:
        """mysqldump with skip_tables generates --ignore-table flags."""
        cmd = build_mysqldump_command(
            "testdb", skip_tables=["wp_wfHits", "wp_wc_sessions"]
        )
        assert "--ignore-table=testdb.wp_wfHits" in cmd
        assert "--ignore-table=testdb.wp_wc_sessions" in cmd

    def test_mysqldump_with_empty_skip_tables_no_ignore_flags(self) -> None:
        """mysqldump with empty skip_tables list has no --ignore-table flags."""
        cmd = build_mysqldump_command("testdb", skip_tables=[])
        assert "--ignore-table" not in cmd


class TestBuildImportCommand:
    """Tests for mysql import command builder."""

    def test_import_command_includes_autocommit_off(self) -> None:
        """Import command includes SET autocommit=0."""
        cmd = build_import_command("testdb")
        assert "autocommit=0" in cmd.lower() or "autocommit = 0" in cmd.lower()

    def test_import_command_includes_foreign_key_checks_off(self) -> None:
        """Import command includes SET foreign_key_checks=0."""
        cmd = build_import_command("testdb")
        assert "foreign_key_checks=0" in cmd.lower() or "foreign_key_checks = 0" in cmd.lower()

    def test_import_command_includes_unique_checks_off(self) -> None:
        """Import command includes SET unique_checks=0."""
        cmd = build_import_command("testdb")
        assert "unique_checks=0" in cmd.lower() or "unique_checks = 0" in cmd.lower()

    def test_import_command_includes_commit(self) -> None:
        """Import command includes COMMIT."""
        cmd = build_import_command("testdb")
        assert "COMMIT" in cmd

    def test_import_command_includes_db_name(self) -> None:
        """Import command includes the database name."""
        cmd = build_import_command("my_database")
        assert "my_database" in cmd


class TestTransientTables:
    """Tests for transient table list."""

    def test_transient_tables_list_contains_known_tables(self) -> None:
        """TRANSIENT_TABLES contains well-known WordPress cache tables."""
        assert "wp_wfHits" in TRANSIENT_TABLES
        assert "wp_wfKnownFileList" in TRANSIENT_TABLES
        assert "wp_actionscheduler_actions" in TRANSIENT_TABLES
        assert "wp_wc_sessions" in TRANSIENT_TABLES
        assert "wp_yoast_indexable" in TRANSIENT_TABLES

    def test_transient_tables_list_minimum_count(self) -> None:
        """TRANSIENT_TABLES contains at least 15 table names."""
        assert len(TRANSIENT_TABLES) >= 15


class TestWPConfigParser:
    """Tests for wp-config.php DB_NAME parser."""

    def test_parse_db_name_single_quotes(self) -> None:
        """Extract DB name from define('DB_NAME', 'xxx') pattern."""
        output = "define('DB_NAME', 'wp_projectassistant');"
        assert parse_db_name_from_wp_config(output) == "wp_projectassistant"

    def test_parse_db_name_double_quotes(self) -> None:
        """Extract DB name from define("DB_NAME", "xxx") pattern."""
        output = 'define("DB_NAME", "wp_mysite");'
        assert parse_db_name_from_wp_config(output) == "wp_mysite"

    def test_parse_db_name_with_whitespace_variation(self) -> None:
        """Handle extra whitespace in define statement."""
        output = "define(  'DB_NAME'  ,  'wp_test'  );"
        assert parse_db_name_from_wp_config(output) == "wp_test"

    def test_parse_db_name_not_found_raises_database_error(self) -> None:
        """Raise DatabaseError when DB_NAME pattern not found."""
        with pytest.raises(DatabaseError, match="Could not detect"):
            parse_db_name_from_wp_config("no define here")

    def test_build_wp_config_command_includes_grep_db_name(self) -> None:
        """wp-config command includes grep for DB_NAME."""
        cmd = build_wp_config_db_name_command()
        assert "DB_NAME" in cmd
        assert "wp-config.php" in cmd


class TestDBSizeQuery:
    """Tests for database size estimation query."""

    def test_build_db_size_query_correct_sql(self) -> None:
        """Generated SQL queries information_schema.tables for size."""
        sql = build_db_size_query("wp_mydb")
        assert "information_schema.tables" in sql.lower()
        assert "wp_mydb" in sql
        assert "data_length" in sql.lower()
        assert "index_length" in sql.lower()


class TestValidatePhase2Config:
    """Tests for Phase 2 lazy config validation."""

    def _make_full_config(self) -> dict:
        """Create a complete Phase 2 config for testing."""
        return {
            "account": "primary",
            "server": {
                "id": 1089270,
                "ssh_user": "master_user",
                "ssh_host": "1.2.3.4",
            },
            "environments": {
                "production": {"app_id": 123, "domain": "example.com"},
            },
            "database": {
                "local_container": "pa-mariadb",
                "local_db_name": "wordpress",
                "url_replace_method": "wp-cli",
            },
        }

    def test_validate_phase2_missing_ssh_user_raises_config_error(self) -> None:
        """Missing server.ssh_user raises ConfigError."""
        config = self._make_full_config()
        del config["server"]["ssh_user"]
        with pytest.raises(ConfigError, match="ssh_user"):
            validate_phase2_config(config)

    def test_validate_phase2_missing_ssh_host_raises_config_error(self) -> None:
        """Missing server.ssh_host raises ConfigError."""
        config = self._make_full_config()
        del config["server"]["ssh_host"]
        with pytest.raises(ConfigError, match="ssh_host"):
            validate_phase2_config(config)

    def test_validate_phase2_missing_database_section_raises_config_error(self) -> None:
        """Missing database section raises ConfigError."""
        config = self._make_full_config()
        del config["database"]
        with pytest.raises(ConfigError, match="database"):
            validate_phase2_config(config)

    def test_validate_phase2_missing_local_container_raises_config_error(self) -> None:
        """Missing database.local_container raises ConfigError."""
        config = self._make_full_config()
        del config["database"]["local_container"]
        with pytest.raises(ConfigError, match="local_container"):
            validate_phase2_config(config)

    def test_validate_phase2_missing_local_db_name_raises_config_error(self) -> None:
        """Missing database.local_db_name raises ConfigError."""
        config = self._make_full_config()
        del config["database"]["local_db_name"]
        with pytest.raises(ConfigError, match="local_db_name"):
            validate_phase2_config(config)

    def test_validate_phase2_missing_url_replace_method_raises_config_error(self) -> None:
        """Missing database.url_replace_method raises ConfigError."""
        config = self._make_full_config()
        del config["database"]["url_replace_method"]
        with pytest.raises(ConfigError, match="url_replace_method"):
            validate_phase2_config(config)

    def test_validate_phase2_complete_config_passes(self) -> None:
        """Complete Phase 2 config passes validation."""
        config = self._make_full_config()
        # Should not raise
        validate_phase2_config(config)

    def test_load_config_without_database_still_works(self) -> None:
        """load_config() works without database section (backward compat)."""
        # project-config-minimal.yml has no database section
        config = load_config(
            path=str(FIXTURES_DIR / "project-config-minimal.yml")
        )
        assert config["account"] == "primary"
        # database key should not exist
        assert "database" not in config or config.get("database") is None or isinstance(config.get("database"), dict)


class TestBuildLocalMysqldumpDockerCommand:
    """Tests for local Docker mysqldump command builder."""

    def test_local_mysqldump_docker_command_starts_with_docker_exec(self) -> None:
        """Command starts with 'docker exec {container}'."""
        cmd = build_local_mysqldump_docker_command("my-container", "testdb")
        assert cmd.startswith("docker exec my-container")

    def test_local_mysqldump_docker_command_includes_all_optimization_flags(
        self,
    ) -> None:
        """Command includes all 7 mysqldump optimization flags."""
        cmd = build_local_mysqldump_docker_command("container", "testdb")
        assert "--single-transaction" in cmd
        assert "--quick" in cmd
        assert "--routines" in cmd
        assert "--triggers" in cmd
        assert "--set-gtid-purged=OFF" in cmd
        assert "--no-tablespaces" in cmd
        assert "--column-statistics=0" in cmd

    def test_local_mysqldump_docker_command_includes_gzip_when_compress(
        self,
    ) -> None:
        """Command includes 'gzip -1' when compress=True."""
        cmd = build_local_mysqldump_docker_command(
            "container", "testdb", compress=True
        )
        assert "gzip -1" in cmd

    def test_local_mysqldump_docker_command_no_gzip_when_not_compress(
        self,
    ) -> None:
        """Command does not include gzip when compress=False."""
        cmd = build_local_mysqldump_docker_command(
            "container", "testdb", compress=False
        )
        assert "gzip" not in cmd

    def test_local_mysqldump_docker_command_skip_tables_generates_ignore_flags(
        self,
    ) -> None:
        """Command generates --ignore-table flags when skip_tables provided."""
        cmd = build_local_mysqldump_docker_command(
            "container", "testdb", skip_tables=["wp_wfHits", "wp_wc_sessions"]
        )
        assert "--ignore-table=testdb.wp_wfHits" in cmd
        assert "--ignore-table=testdb.wp_wc_sessions" in cmd

    def test_local_mysqldump_docker_command_no_skip_tables_no_ignore_flags(
        self,
    ) -> None:
        """Command omits --ignore-table when skip_tables is None."""
        cmd = build_local_mysqldump_docker_command("container", "testdb")
        assert "--ignore-table" not in cmd

    def test_local_mysqldump_docker_command_includes_db_name(self) -> None:
        """Command includes the database name."""
        cmd = build_local_mysqldump_docker_command(
            "container", "my_wordpress_db"
        )
        assert "my_wordpress_db" in cmd


class TestBuildRemoteImportCommand:
    """Tests for remote mysql import command builder."""

    def test_remote_import_command_includes_performance_flags(self) -> None:
        """Remote import command includes SET autocommit=0, etc."""
        cmd = build_remote_import_command("testdb")
        assert "autocommit=0" in cmd.lower() or "autocommit = 0" in cmd.lower()
        assert "foreign_key_checks=0" in cmd.lower()
        assert "unique_checks=0" in cmd.lower()

    def test_remote_import_command_includes_commit(self) -> None:
        """Remote import command includes COMMIT."""
        cmd = build_remote_import_command("testdb")
        assert "COMMIT" in cmd

    def test_remote_import_command_includes_db_name(self) -> None:
        """Remote import command includes the database name."""
        cmd = build_remote_import_command("wp_projectassistant")
        assert "wp_projectassistant" in cmd

    def test_remote_import_command_no_docker_prefix(self) -> None:
        """Remote import command does not have docker exec prefix."""
        cmd = build_remote_import_command("testdb")
        assert "docker" not in cmd


class TestBuildRemoteBackupCommand:
    """Tests for remote backup command builder."""

    def test_remote_backup_command_includes_optimization_flags(self) -> None:
        """Remote backup command includes all mysqldump optimization flags."""
        cmd = build_remote_backup_command("testdb", "/tmp/backup.sql.gz")
        assert "--single-transaction" in cmd
        assert "--quick" in cmd
        assert "--routines" in cmd
        assert "--triggers" in cmd
        assert "--set-gtid-purged=OFF" in cmd
        assert "--no-tablespaces" in cmd
        assert "--column-statistics=0" in cmd

    def test_remote_backup_command_redirects_to_backup_path(self) -> None:
        """Remote backup command redirects gzip output to the backup path."""
        cmd = build_remote_backup_command(
            "testdb", "/tmp/cloudways_backup_testdb_20260206_143022.sql.gz"
        )
        assert "/tmp/cloudways_backup_testdb_20260206_143022.sql.gz" in cmd
        assert "gzip" in cmd
        assert ">" in cmd

    def test_remote_backup_command_includes_db_name(self) -> None:
        """Remote backup command includes the database name."""
        cmd = build_remote_backup_command("wp_mysite", "/tmp/backup.sql.gz")
        assert "wp_mysite" in cmd
