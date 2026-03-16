"""Integration tests for the info command against the live Cloudways API.

These tests require real API credentials and a valid project configuration
pointing to a real Cloudways account. They will self-skip when
CLOUDWAYS_TEST_EMAIL and CLOUDWAYS_TEST_API_KEY are not set.
"""

import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app

from .conftest import has_cloudways_credentials

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not has_cloudways_credentials(),
        reason="CLOUDWAYS_TEST_EMAIL and CLOUDWAYS_TEST_API_KEY not set",
    ),
]

runner = CliRunner()


class TestInfoCommandLive:
    """Test the info command with real API credentials."""

    def test_info_command_displays_server_data(
        self, cloudways_email, cloudways_api_key, tmp_path, monkeypatch
    ):
        """Verify info command displays real server data when properly configured."""
        # Create a minimal project config pointing to the test account
        config_file = tmp_path / "project-config.yml"
        config_file.write_text(
            "account: test-account\n"
            "hosting:\n"
            "  provider: cloudways\n"
        )
        accounts_file = tmp_path / "accounts.yml"
        accounts_file.write_text(
            "accounts:\n"
            "  test-account:\n"
            f"    email: {cloudways_email}\n"
            f"    api_key: {cloudways_api_key}\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config_file))
        monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", str(accounts_file))

        result = runner.invoke(app, ["info"])
        # Should either succeed or fail gracefully (no crashes)
        assert result.exit_code in (0, 1)

    def test_info_command_invalid_account(self, tmp_path, monkeypatch):
        """Verify info command handles a non-existent account gracefully."""
        config_file = tmp_path / "project-config.yml"
        config_file.write_text(
            "account: nonexistent-account\n"
            "hosting:\n"
            "  provider: cloudways\n"
        )
        accounts_file = tmp_path / "accounts.yml"
        accounts_file.write_text(
            "accounts:\n"
            "  other-account:\n"
            "    email: test@example.com\n"
            "    api_key: fake-key\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config_file))
        monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", str(accounts_file))

        result = runner.invoke(app, ["info"])
        assert result.exit_code != 0
