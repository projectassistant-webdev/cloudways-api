"""Tests for capistrano_parser module.

Covers parsing of linked_files and linked_dirs from Ruby Capistrano
config files, fallback defaults, and error handling.
"""

import logging
from pathlib import Path

import pytest

from cloudways_api.capistrano_parser import (
    get_linked_dirs_for_environment,
    get_linked_files_for_environment,
    parse_linked_dirs,
    parse_linked_files,
)


# ---------------------------------------------------------------------------
# parse_linked_files tests
# ---------------------------------------------------------------------------


class TestParseLinkedFiles:
    """Tests for parse_linked_files() function."""

    def test_parse_linked_files_single_quoted(self, tmp_path: Path) -> None:
        """AC-P1-1: Parses linked_files with single-quoted strings."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text(
            "set :linked_files, fetch(:linked_files, []).push('.env', 'web/.htaccess', 'web/robots.txt')\n"
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess", "web/robots.txt"]

    def test_parse_linked_files_double_quoted(self, tmp_path: Path) -> None:
        """AC-P1-3: Handles double-quoted strings."""
        stage_file = tmp_path / "production.rb"
        stage_file.write_text(
            'set :linked_files, fetch(:linked_files, []).push(".env", "web/.htaccess")\n'
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess"]

    def test_parse_linked_files_mixed_quotes(self, tmp_path: Path) -> None:
        """AC-P1-3: Handles mixed single and double quotes."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text(
            "set :linked_files, fetch(:linked_files, []).push('.env', \"web/.htaccess\")\n"
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess"]

    def test_parse_linked_files_with_whitespace(self, tmp_path: Path) -> None:
        """Handles whitespace variations in .push() arguments."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text(
            "set :linked_files, fetch(:linked_files, []).push(  '.env' ,  'web/.htaccess'  )\n"
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess"]

    def test_parse_linked_files_with_comments(self, tmp_path: Path) -> None:
        """Ignores comment lines in the Ruby file."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text(
            "# This is a comment\n"
            "set :linked_files, fetch(:linked_files, []).push('.env', 'web/.htaccess')\n"
            "# Another comment\n"
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess"]

    def test_parse_linked_files_no_linked_files_line(self, tmp_path: Path) -> None:
        """Raises ValueError when no linked_files line is found."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text("set :branch, 'main'\n")
        with pytest.raises(ValueError, match="linked_files"):
            parse_linked_files(stage_file)

    def test_parse_linked_files_empty_push(self, tmp_path: Path) -> None:
        """Handles empty .push() call with no arguments."""
        stage_file = tmp_path / "staging.rb"
        stage_file.write_text(
            "set :linked_files, fetch(:linked_files, []).push()\n"
        )
        result = parse_linked_files(stage_file)
        assert result == []

    def test_parse_linked_files_file_not_found(self) -> None:
        """AC-P1-6: Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_linked_files("/nonexistent/path/staging.rb")

    def test_parse_linked_files_real_world_bedrock(self, tmp_path: Path) -> None:
        """Handles a real-world Bedrock Capistrano stage config."""
        stage_file = tmp_path / "production.rb"
        stage_file.write_text(
            'server "1.2.3.4", user: "bitbucket-pawp", roles: %w{app db web}\n'
            "\n"
            'set :branch, "main"\n'
            'set :deploy_to, "~/public_html"\n'
            "\n"
            "set :linked_files, fetch(:linked_files, []).push('.env', 'web/.htaccess', 'web/robots.txt')\n"
        )
        result = parse_linked_files(stage_file)
        assert result == [".env", "web/.htaccess", "web/robots.txt"]


# ---------------------------------------------------------------------------
# parse_linked_dirs tests
# ---------------------------------------------------------------------------


class TestParseLinkedDirs:
    """Tests for parse_linked_dirs() function."""

    def test_parse_linked_dirs_success(self, tmp_path: Path) -> None:
        """AC-P1-2: Parses linked_dirs from deploy.rb."""
        deploy_file = tmp_path / "deploy.rb"
        deploy_file.write_text(
            "set :linked_dirs, fetch(:linked_dirs, []).push('web/app/uploads', 'web/app/cache')\n"
        )
        result = parse_linked_dirs(deploy_file)
        assert result == ["web/app/uploads", "web/app/cache"]

    def test_parse_linked_dirs_no_line(self, tmp_path: Path) -> None:
        """Raises ValueError when no linked_dirs line found."""
        deploy_file = tmp_path / "deploy.rb"
        deploy_file.write_text("set :application, 'myapp'\n")
        with pytest.raises(ValueError, match="linked_dirs"):
            parse_linked_dirs(deploy_file)

    def test_parse_linked_dirs_file_not_found(self) -> None:
        """Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_linked_dirs("/nonexistent/deploy.rb")

    def test_parse_linked_dirs_single_dir(self, tmp_path: Path) -> None:
        """Handles a single linked directory."""
        deploy_file = tmp_path / "deploy.rb"
        deploy_file.write_text(
            "set :linked_dirs, fetch(:linked_dirs, []).push('web/app/uploads')\n"
        )
        result = parse_linked_dirs(deploy_file)
        assert result == ["web/app/uploads"]


# ---------------------------------------------------------------------------
# get_linked_files_for_environment tests
# ---------------------------------------------------------------------------


class TestGetLinkedFilesForEnvironment:
    """Tests for get_linked_files_for_environment() fallback function."""

    def test_returns_parsed_files_when_config_exists(self, tmp_path: Path) -> None:
        """Uses Capistrano config when config/deploy/{env}.rb exists."""
        config_dir = tmp_path / "config" / "deploy"
        config_dir.mkdir(parents=True)
        stage_file = config_dir / "staging.rb"
        stage_file.write_text(
            "set :linked_files, fetch(:linked_files, []).push('.env', 'web/.htaccess')\n"
        )
        result = get_linked_files_for_environment("staging", project_root=tmp_path)
        assert result == [".env", "web/.htaccess"]

    def test_returns_defaults_when_no_config(self, tmp_path: Path) -> None:
        """AC-P1-4: Falls back to defaults when no Capistrano config exists."""
        result = get_linked_files_for_environment("staging", project_root=tmp_path)
        assert result == [".env", "web/.htaccess", "web/robots.txt"]

    def test_logs_warning_on_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AC-P1-5: Logs warning when falling back to defaults."""
        with caplog.at_level(logging.WARNING):
            get_linked_files_for_environment("staging", project_root=tmp_path)
        assert "default linked files" in caplog.text.lower()


# ---------------------------------------------------------------------------
# get_linked_dirs_for_environment tests
# ---------------------------------------------------------------------------


class TestGetLinkedDirsForEnvironment:
    """Tests for get_linked_dirs_for_environment() fallback function."""

    def test_returns_parsed_dirs_when_config_exists(self, tmp_path: Path) -> None:
        """Uses deploy.rb when it exists."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        deploy_file = config_dir / "deploy.rb"
        deploy_file.write_text(
            "set :linked_dirs, fetch(:linked_dirs, []).push('web/app/uploads', 'web/app/cache')\n"
        )
        result = get_linked_dirs_for_environment(project_root=tmp_path)
        assert result == ["web/app/uploads", "web/app/cache"]

    def test_returns_defaults_when_no_config(self, tmp_path: Path) -> None:
        """AC-P1-4: Falls back to defaults when no deploy.rb exists."""
        result = get_linked_dirs_for_environment(project_root=tmp_path)
        assert result == ["web/app/uploads", "web/app/cache"]

    def test_logs_warning_on_fallback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logs warning when falling back to defaults."""
        with caplog.at_level(logging.WARNING):
            get_linked_dirs_for_environment(project_root=tmp_path)
        assert "default linked dirs" in caplog.text.lower()
