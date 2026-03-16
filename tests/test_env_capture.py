"""Tests for env-capture command and env_detect module.

Covers Bedrock vs traditional WordPress detection, wp-config.php
parsing, output formatting, and the env-capture CLI command with
all output modes and error paths.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.config import validate_ssh_config
from cloudways_api.env_detect import (
    capture_bedrock_env,
    capture_traditional_env,
    detect_env_type,
    format_env_output,
    parse_wp_config_defines,
    parse_wp_config_table_prefix,
)
from cloudways_api.exceptions import ConfigError, SSHError

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

SAMPLE_WP_CONFIG = """<?php
define('DB_NAME', 'wp_mysite');
define('DB_USER', 'db_user_123');
define('DB_PASSWORD', 's3cret_p@ss');
define('DB_HOST', 'localhost');
define('WP_HOME', 'https://example.com');
define('WP_SITEURL', 'https://example.com');

$table_prefix = 'wp_';
"""

SAMPLE_WP_CONFIG_DOUBLE_QUOTES = '''<?php
define("DB_NAME", "double_db");
define("DB_USER", "double_user");
'''

SAMPLE_WP_CONFIG_EXTRA_WHITESPACE = """<?php
define( 'DB_NAME' , 'spaced_db' )  ;
define(  'DB_USER'  ,  'spaced_user'  )  ;
"""

SAMPLE_BEDROCK_ENV = """DB_NAME=mysite_db
DB_USER=root
DB_PASSWORD=secret
DB_HOST=localhost

WP_ENV=production
WP_HOME=https://example.com
WP_SITEURL=${WP_HOME}/wp
"""


# ---- env_detect.py unit tests ----


class TestDetectEnvType:
    """Tests for detect_env_type()."""

    @pytest.mark.asyncio
    async def test_bedrock_returns_bedrock(self) -> None:
        """AC-3A.1: Returns 'bedrock' when .env exists."""
        with patch(
            "cloudways_api.env_detect.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("bedrock\n", "", 0),
        ):
            result = await detect_env_type("host", "user", "/app")
            assert result == "bedrock"

    @pytest.mark.asyncio
    async def test_traditional_returns_traditional(self) -> None:
        """AC-3A.2: Returns 'traditional' when no .env exists."""
        with patch(
            "cloudways_api.env_detect.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("traditional\n", "", 0),
        ):
            result = await detect_env_type("host", "user", "/app")
            assert result == "traditional"


    @pytest.mark.asyncio
    async def test_invalid_webroot_raises_config_error(self) -> None:
        """M-3: Neither .env nor wp-config.php raises ConfigError."""
        with patch(
            "cloudways_api.env_detect.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=[
                ("traditional\n", "", 0),  # First call: no .env
                ("missing\n", "", 0),      # Second call: no wp-config.php
            ],
        ):
            with pytest.raises(ConfigError, match="Neither .env nor wp-config.php"):
                await detect_env_type("host", "user", "/invalid/path")


class TestCaptureBedrock:
    """Tests for capture_bedrock_env()."""

    @pytest.mark.asyncio
    async def test_reads_env_file(self) -> None:
        """AC-3A.3: Reads .env via SSH cat command."""
        with patch(
            "cloudways_api.env_detect.run_ssh_command",
            new_callable=AsyncMock,
            return_value=(SAMPLE_BEDROCK_ENV, "", 0),
        ) as mock_ssh:
            result = await capture_bedrock_env("host", "user", "/app")
            assert result == SAMPLE_BEDROCK_ENV
            mock_ssh.assert_called_once_with("host", "user", "cat /app/.env")


class TestCaptureTraditional:
    """Tests for capture_traditional_env()."""

    @pytest.mark.asyncio
    async def test_parses_wp_config(self) -> None:
        """AC-3A.4: Reads wp-config.php and extracts environment variables."""
        with patch(
            "cloudways_api.env_detect.run_ssh_command",
            new_callable=AsyncMock,
            return_value=(SAMPLE_WP_CONFIG, "", 0),
        ):
            result = await capture_traditional_env("host", "user", "/app")
            assert result["DB_NAME"] == "wp_mysite"
            assert result["DB_USER"] == "db_user_123"
            assert result["DB_PASSWORD"] == "s3cret_p@ss"
            assert result["DB_HOST"] == "localhost"
            assert result["TABLE_PREFIX"] == "wp_"


class TestParseWpConfigDefines:
    """Tests for parse_wp_config_defines()."""

    def test_single_quotes(self) -> None:
        """AC-3A.5: Extracts define() with single quotes."""
        result = parse_wp_config_defines("define('DB_NAME', 'mydb');")
        assert result == {"DB_NAME": "mydb"}

    def test_double_quotes(self) -> None:
        """AC-3A.6: Extracts define() with double quotes."""
        result = parse_wp_config_defines(SAMPLE_WP_CONFIG_DOUBLE_QUOTES)
        assert result["DB_NAME"] == "double_db"
        assert result["DB_USER"] == "double_user"

    def test_extra_whitespace(self) -> None:
        """AC-3A.7: Handles extra whitespace in define()."""
        result = parse_wp_config_defines(SAMPLE_WP_CONFIG_EXTRA_WHITESPACE)
        assert result["DB_NAME"] == "spaced_db"
        assert result["DB_USER"] == "spaced_user"

    def test_extracts_all_constants(self) -> None:
        """AC-3A.8: Extracts all target constants."""
        result = parse_wp_config_defines(SAMPLE_WP_CONFIG)
        expected_keys = {
            "DB_NAME", "DB_USER", "DB_PASSWORD",
            "DB_HOST", "WP_HOME", "WP_SITEURL",
        }
        assert expected_keys.issubset(result.keys())

    def test_empty_content_returns_empty_dict(self) -> None:
        """Empty input returns empty dict."""
        result = parse_wp_config_defines("")
        assert result == {}

    def test_no_defines_returns_empty_dict(self) -> None:
        """Content without define() returns empty dict."""
        result = parse_wp_config_defines("<?php\n// no defines\n")
        assert result == {}

    def test_skips_getenv_calls(self) -> None:
        """AC-3A.26: Skips define() calls with getenv()."""
        content = "define('DB_NAME', getenv('DB_NAME'));"
        result = parse_wp_config_defines(content)
        assert "DB_NAME" not in result

    def test_skips_concatenation(self) -> None:
        """AC-3A.27: Skips define() calls with string concatenation."""
        content = "define('DB_NAME', 'prefix_' . $var);"
        result = parse_wp_config_defines(content)
        assert "DB_NAME" not in result

    def test_skips_commented_lines_double_slash(self) -> None:
        """AC-3A.28: Skips lines starting with //."""
        content = "// define('DB_NAME', 'commented_db');"
        result = parse_wp_config_defines(content)
        assert "DB_NAME" not in result

    def test_skips_commented_lines_hash(self) -> None:
        """AC-3A.28: Skips lines starting with #."""
        content = "# define('DB_NAME', 'commented_db');"
        result = parse_wp_config_defines(content)
        assert "DB_NAME" not in result


class TestParseWpConfigTablePrefix:
    """Tests for parse_wp_config_table_prefix()."""

    def test_standard_prefix(self) -> None:
        """AC-3A.9: Extracts standard 'wp_' prefix."""
        result = parse_wp_config_table_prefix("$table_prefix = 'wp_';")
        assert result == "wp_"

    def test_custom_prefix(self) -> None:
        """Custom prefix extracted correctly."""
        result = parse_wp_config_table_prefix("$table_prefix = 'mysite_';")
        assert result == "mysite_"

    def test_not_found_returns_none(self) -> None:
        """AC-3A.10: Returns None when no table_prefix found."""
        result = parse_wp_config_table_prefix("<?php\n// no prefix\n")
        assert result is None


class TestFormatEnvOutput:
    """Tests for format_env_output()."""

    def test_includes_header_comment(self) -> None:
        """AC-3A.11: Header comment present."""
        result = format_env_output(
            {"DB_NAME": "test"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert "# Captured from wp-config.php (traditional WordPress)" in result
        assert "# Date: 2026-02-06T12:00:00" in result

    def test_formats_key_value_pairs(self) -> None:
        """Keys formatted as KEY=VALUE."""
        result = format_env_output(
            {"DB_NAME": "mydb", "DB_USER": "user"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert "DB_NAME=mydb" in result
        assert "DB_USER=user" in result

    def test_alphabetical_ordering(self) -> None:
        """M-2: Keys output in alphabetical order."""
        result = format_env_output(
            {"ZEBRA": "z", "APPLE": "a", "MANGO": "m"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        lines = [
            line for line in result.splitlines()
            if line and not line.startswith("#")
        ]
        assert lines == ["APPLE=a", "MANGO=m", "ZEBRA=z"]

    def test_bedrock_type_header(self) -> None:
        """Header shows .env source for bedrock type."""
        result = format_env_output(
            {"WP_ENV": "production"},
            "bedrock",
            timestamp="2026-02-06T12:00:00",
        )
        assert "# Captured from .env (bedrock WordPress)" in result

    def test_value_with_spaces_quoted(self) -> None:
        """M-1: Values with spaces are wrapped in double quotes."""
        result = format_env_output(
            {"SITE_NAME": "My Website"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert 'SITE_NAME="My Website"' in result

    def test_value_with_hash_quoted(self) -> None:
        """M-1: Values with # are wrapped in double quotes."""
        result = format_env_output(
            {"DB_PASSWORD": "pass#word"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert 'DB_PASSWORD="pass#word"' in result

    def test_value_with_dollar_escaped(self) -> None:
        """M-1: Values with $ are quoted and $ is escaped."""
        result = format_env_output(
            {"WP_SITEURL": "${WP_HOME}/wp"},
            "bedrock",
            timestamp="2026-02-06T12:00:00",
        )
        assert 'WP_SITEURL="\\${WP_HOME}/wp"' in result

    def test_value_with_double_quote_escaped(self) -> None:
        """M-1: Values with double quotes are properly escaped."""
        result = format_env_output(
            {"MSG": 'say "hello"'},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert 'MSG="say \\"hello\\""' in result

    def test_simple_value_not_quoted(self) -> None:
        """M-1: Simple values without special chars are not quoted."""
        result = format_env_output(
            {"DB_HOST": "localhost"},
            "traditional",
            timestamp="2026-02-06T12:00:00",
        )
        assert "DB_HOST=localhost" in result


# ---- config.py validate_ssh_config tests ----


class TestValidateSSHConfig:
    """Tests for validate_ssh_config()."""

    def test_missing_ssh_user_raises(self) -> None:
        """AC-3A.23/AC-3A.16: Missing ssh_user raises ConfigError."""
        with pytest.raises(ConfigError, match="ssh_user"):
            validate_ssh_config({"server": {"ssh_host": "1.2.3.4"}})

    def test_missing_ssh_host_raises(self) -> None:
        """Missing ssh_host raises ConfigError."""
        with pytest.raises(ConfigError, match="ssh_host"):
            validate_ssh_config({"server": {"ssh_user": "master"}})

    def test_passes_without_database(self) -> None:
        """AC-3A.23: Passes without database section."""
        # Should NOT raise - no database section required
        validate_ssh_config({
            "server": {"ssh_user": "master", "ssh_host": "1.2.3.4"}
        })


# ---- env-capture command integration tests ----


class TestEnvCaptureCommand:
    """Integration tests for the env-capture CLI command."""

    def _config_path(self) -> str:
        return os.path.join(FIXTURES_DIR, "project-config.yml")

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="bedrock",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_bedrock_env",
        new_callable=AsyncMock,
        return_value=SAMPLE_BEDROCK_ENV,
    )
    def test_bedrock_default_output_file(
        self, mock_capture, mock_detect, tmp_path, monkeypatch
    ) -> None:
        """AC-3A.12: Default output writes to .env.{environment}."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".env.production").exists()

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="traditional",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_traditional_env",
        new_callable=AsyncMock,
        return_value={
            "DB_NAME": "wp_mysite",
            "DB_USER": "db_user",
            "DB_PASSWORD": "pass",
            "DB_HOST": "localhost",
        },
    )
    def test_traditional_default_output_file(
        self, mock_capture, mock_detect, tmp_path, monkeypatch
    ) -> None:
        """AC-3A.12: Traditional WP writes to .env.{environment}."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".env.production").exists()
        content = (tmp_path / ".env.production").read_text()
        assert "DB_NAME=wp_mysite" in content

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="bedrock",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_bedrock_env",
        new_callable=AsyncMock,
        return_value=SAMPLE_BEDROCK_ENV,
    )
    def test_custom_output_path(
        self, mock_capture, mock_detect, tmp_path, monkeypatch
    ) -> None:
        """AC-3A.13: --output writes to specified path."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        monkeypatch.chdir(tmp_path)
        out_file = str(tmp_path / "custom.env")
        result = runner.invoke(
            app, ["env-capture", "production", "--output", out_file]
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "custom.env").exists()

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="bedrock",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_bedrock_env",
        new_callable=AsyncMock,
        return_value=SAMPLE_BEDROCK_ENV,
    )
    def test_stdout_mode_no_file(
        self, mock_capture, mock_detect, tmp_path, monkeypatch
    ) -> None:
        """AC-3A.14: --stdout prints to stdout without writing file."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env-capture", "production", "--stdout"])
        assert result.exit_code == 0, result.output
        assert "DB_NAME" in result.output
        assert not (tmp_path / ".env.production").exists()

    def test_invalid_environment_error(self, monkeypatch) -> None:
        """AC-3A.15: Invalid environment shows error message."""
        monkeypatch.setenv(
            "CLOUDWAYS_PROJECT_CONFIG", self._config_path()
        )
        result = runner.invoke(app, ["env-capture", "nonexistent"])
        assert result.exit_code == 1
        assert "nonexistent" in result.output
        assert "not found" in result.output

    def test_missing_ssh_config_error(self, tmp_path, monkeypatch) -> None:
        """AC-3A.16: Missing SSH config shows descriptive error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            "hosting:\n  cloudways:\n    account: primary\n"
            "    server:\n      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config_file))
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 1
        assert "ssh_user" in result.output or "ssh_host" in result.output

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        side_effect=SSHError("Connection refused"),
    )
    def test_ssh_failure_error(self, mock_detect, monkeypatch) -> None:
        """AC-3A.17: SSH failure shows error."""
        monkeypatch.setenv(
            "CLOUDWAYS_PROJECT_CONFIG", self._config_path()
        )
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 1
        assert "Error" in result.output

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="traditional",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_traditional_env",
        new_callable=AsyncMock,
        return_value={},
    )
    def test_empty_wp_config_parse_error(
        self, mock_capture, mock_detect, monkeypatch
    ) -> None:
        """AC-3A.19: No defines found raises error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 1
        assert "parse" in result.output.lower() or "Error" in result.output

    def test_registered_in_cli_help(self) -> None:
        """AC-3A.20: env-capture appears in CLI help."""
        result = runner.invoke(app, ["--help"])
        assert "env-capture" in result.output

    @patch(
        "cloudways_api.commands.env_capture.detect_env_type",
        new_callable=AsyncMock,
        return_value="bedrock",
    )
    @patch(
        "cloudways_api.commands.env_capture.capture_bedrock_env",
        new_callable=AsyncMock,
        return_value=SAMPLE_BEDROCK_ENV,
    )
    def test_exit_code_zero_on_success(
        self, mock_capture, mock_detect, tmp_path, monkeypatch
    ) -> None:
        """AC-3A.21: Exit code 0 on success."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", self._config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["env-capture", "production"])
        assert result.exit_code == 0

    def test_exit_code_one_on_error(self, monkeypatch) -> None:
        """AC-3A.22: Exit code 1 on error paths."""
        monkeypatch.setenv(
            "CLOUDWAYS_PROJECT_CONFIG", self._config_path()
        )
        result = runner.invoke(app, ["env-capture", "nonexistent"])
        assert result.exit_code == 1

    def test_stdout_and_output_mutually_exclusive(
        self, monkeypatch
    ) -> None:
        """M-2: --stdout and --output together produce an error."""
        monkeypatch.setenv(
            "CLOUDWAYS_PROJECT_CONFIG", self._config_path()
        )
        result = runner.invoke(
            app,
            ["env-capture", "production", "--stdout", "--output", "out.env"],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output
