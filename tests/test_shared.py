"""Tests for the _shared module's load_creds helper."""

from unittest.mock import patch

from cloudways_api.commands._shared import load_creds


class TestLoadCreds:
    """Tests for the load_creds convenience helper."""

    @patch("cloudways_api.commands._shared.load_credentials")
    @patch("cloudways_api.commands._shared.load_config")
    def test_returns_creds_and_config(self, mock_load_config, mock_load_creds):
        """load_creds returns (credentials, config) tuple."""
        mock_load_config.return_value = {"account": "acme"}
        mock_load_creds.return_value = {
            "email": "a@b.com",
            "api_key": "key123",
        }

        creds, config = load_creds()

        assert config == {"account": "acme"}
        assert creds == {"email": "a@b.com", "api_key": "key123"}

    @patch("cloudways_api.commands._shared.load_credentials")
    @patch("cloudways_api.commands._shared.load_config")
    def test_passes_account_to_load_credentials(
        self, mock_load_config, mock_load_creds
    ):
        """load_creds extracts account from config and passes to load_credentials."""
        mock_load_config.return_value = {"account": "agency-x"}
        mock_load_creds.return_value = {"email": "e", "api_key": "k"}

        load_creds()

        mock_load_creds.assert_called_once_with("agency-x")

    @patch("cloudways_api.commands._shared.load_credentials")
    @patch("cloudways_api.commands._shared.load_config")
    def test_calls_load_config_once(self, mock_load_config, mock_load_creds):
        """load_creds calls load_config exactly once."""
        mock_load_config.return_value = {"account": "test"}
        mock_load_creds.return_value = {}

        load_creds()

        mock_load_config.assert_called_once()
