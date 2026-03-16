"""Tests for CLI entry point, version display, and exception hierarchy."""

from typer.testing import CliRunner

from cloudways_api import __version__
from cloudways_api.cli import app
from cloudways_api.exceptions import (
    APIError,
    AuthenticationError,
    CloudwaysError,
    ConfigError,
    CredentialsError,
    RateLimitError,
    ServerError,
)

runner = CliRunner()


class TestCLIHelp:
    """Tests for the --help output."""

    def test_cli_help_shows_available_commands(self) -> None:
        """Verify --help output lists available commands including 'info'."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "info" in result.output
        assert "Cloudways API operations tool" in result.output

    def test_cli_help_shows_version_option(self) -> None:
        """Verify --help output lists --version option."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--version" in result.output


class TestCLIVersion:
    """Tests for the --version output."""

    def test_cli_version_shows_version_string(self) -> None:
        """Verify --version outputs the correct version string."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"cloudways-api v{__version__}" in result.output

    def test_version_matches_package(self) -> None:
        """Verify __version__ is 0.1.0."""
        assert __version__ == "0.1.0"


class TestExceptionHierarchy:
    """Tests for the custom exception hierarchy."""

    def test_cloudways_error_is_base_exception(self) -> None:
        """CloudwaysError inherits from Exception."""
        assert issubclass(CloudwaysError, Exception)

    def test_config_error_inherits_cloudways_error(self) -> None:
        """ConfigError inherits from CloudwaysError."""
        assert issubclass(ConfigError, CloudwaysError)

    def test_credentials_error_inherits_cloudways_error(self) -> None:
        """CredentialsError inherits from CloudwaysError."""
        assert issubclass(CredentialsError, CloudwaysError)

    def test_authentication_error_inherits_cloudways_error(self) -> None:
        """AuthenticationError inherits from CloudwaysError."""
        assert issubclass(AuthenticationError, CloudwaysError)

    def test_api_error_inherits_cloudways_error(self) -> None:
        """APIError inherits from CloudwaysError."""
        assert issubclass(APIError, CloudwaysError)

    def test_rate_limit_error_inherits_api_error(self) -> None:
        """RateLimitError inherits from APIError."""
        assert issubclass(RateLimitError, APIError)

    def test_server_error_inherits_api_error(self) -> None:
        """ServerError inherits from APIError."""
        assert issubclass(ServerError, APIError)

    def test_all_exceptions_catchable_by_base(self) -> None:
        """All custom exceptions are catchable by CloudwaysError."""
        for exc_class in [
            ConfigError,
            CredentialsError,
            AuthenticationError,
            APIError,
            RateLimitError,
            ServerError,
        ]:
            try:
                raise exc_class("test message")
            except CloudwaysError:
                pass  # Expected

    def test_exception_preserves_message(self) -> None:
        """Exceptions preserve their error message."""
        msg = "Something went wrong"
        err = CloudwaysError(msg)
        assert str(err) == msg
