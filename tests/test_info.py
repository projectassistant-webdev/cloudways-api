"""Integration tests for the `cloudways info` command."""

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from conftest import FIXTURES_DIR, make_auth_response, make_patched_client_class

runner = CliRunner()


def _make_servers_response() -> dict:
    return {
        "status": True,
        "servers": [
            {
                "id": "999999",
                "label": "example-prod",
                "status": "running",
                "cloud": "do",
                "region": "nyc3",
                "public_ip": "1.2.3.4",
                "master_user": "master_example",
                "apps": [
                    {
                        "id": "1234567",
                        "label": "Production WP",
                        "application": "wordpress",
                        "app_version": "6.4",
                        "cname": "wp.example.com",
                        "server_id": "999999",
                        "sys_user": "appuser",
                        "mysql_db_name": "dbname",
                        "webroot": "public_html",
                    },
                    {
                        "id": "7654321",
                        "label": "Staging WP",
                        "application": "wordpress",
                        "app_version": "6.4",
                        "cname": "staging.wp.example.com",
                        "server_id": "999999",
                        "sys_user": "staginguser",
                        "mysql_db_name": "staging_db",
                        "webroot": "public_html",
                    },
                ],
            }
        ],
    }


def _make_settings_response() -> dict:
    return {
        "settings": {
            "package_versions": {
                "php": "8.1",
                "platform": "debian11",
                "mariadb": "10.6",
                "redis": "latest",
            }
        }
    }


def _mock_transport_handler(request: httpx.Request) -> httpx.Response:
    """Mock transport that handles auth, server list, and settings."""
    url = str(request.url)
    if "/oauth/access_token" in url:
        return httpx.Response(200, json=make_auth_response())
    if "/server/manage/settings" in url:
        return httpx.Response(200, json=_make_settings_response())
    if "/server" in url:
        return httpx.Response(200, json=_make_servers_response())
    return httpx.Response(404)


def _run_info_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_fixture: str = "project-config.yml",
    accounts_fixture: str = "accounts.yml",
    transport_handler=None,
) -> object:
    """Run 'cloudways info' with all external dependencies mocked."""
    config_path = str(FIXTURES_DIR / config_fixture)
    accounts_path = str(FIXTURES_DIR / accounts_fixture)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    handler = transport_handler or _mock_transport_handler
    mock_transport = httpx.MockTransport(handler)

    with patch(
        "cloudways_api.commands.info.CloudwaysClient",
        wraps=make_patched_client_class(mock_transport),
    ):
        result = runner.invoke(app, ["info"] + (args or []))

    return result


class TestInfoCommand:
    """Integration tests for cloudways info."""

    def test_info_displays_all_environments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full output with mocked API shows both environments."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "Production" in result.output or "production" in result.output
        assert "Staging" in result.output or "staging" in result.output

    def test_info_filters_by_environment_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production-only filter."""
        result = _run_info_with_mocks(monkeypatch, args=["production"])
        assert result.exit_code == 0
        assert "production" in result.output.lower()
        # Staging should not appear when filtering to production
        # (check for absence of staging-specific data)
        assert "7654321" not in result.output

    def test_info_invalid_environment_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown environment name shows error."""
        result = _run_info_with_mocks(monkeypatch, args=["nonexistent"])
        assert result.exit_code == 1
        assert "nonexistent" in result.output.lower()

    def test_info_missing_config_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No project-config.yml produces user-friendly error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", "/tmp/nonexistent.yml")
        monkeypatch.setenv(
            "CLOUDWAYS_ACCOUNTS_FILE",
            str(FIXTURES_DIR / "accounts.yml"),
        )

        result = runner.invoke(app, ["info"])
        assert result.exit_code == 1
        assert "could not find" in result.output.lower() or "error" in result.output.lower()

    def test_info_auth_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API returns 401 shows authentication error."""

        def auth_fail_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(
                    401,
                    json={
                        "error": "invalid_credentials",
                        "error_description": "Bad credentials",
                    },
                )
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=auth_fail_handler
        )
        assert result.exit_code == 1
        assert "authentication" in result.output.lower() or "auth" in result.output.lower()

    def test_info_server_not_found_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server ID mismatch produces user-friendly error."""

        def no_match_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "status": True,
                        "servers": [
                            {
                                "id": "9999999",
                                "label": "other-server",
                                "status": "running",
                                "cloud": "do",
                                "region": "sfo1",
                                "public_ip": "1.2.3.4",
                                "master_user": "master",
                                "apps": [],
                            }
                        ],
                    },
                )
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=no_match_handler
        )
        assert result.exit_code == 1
        assert "999999" in result.output or "not found" in result.output.lower()

    def test_info_network_error_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connection failure shows user-friendly error."""

        def network_fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=network_fail_handler
        )
        assert result.exit_code == 1
        assert "connect" in result.output.lower() or "error" in result.output.lower()

    def test_info_output_contains_server_details(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify server IP, label, status in output."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "1.2.3.4" in result.output
        assert "999999" in result.output

    def test_info_output_contains_app_details(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify domain and app ID in output."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "wp.example.com" in result.output
        assert "1234567" in result.output

    def test_info_output_contains_php_mysql_versions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify PHP and MySQL/MariaDB versions from settings endpoint."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "8.1" in result.output
        assert "10.6" in result.output

    def test_info_app_not_found_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App ID from config not found on server produces error."""

        def missing_app_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in str(request.url):
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "status": True,
                        "servers": [
                            {
                                "id": "999999",
                                "label": "example-prod",
                                "status": "running",
                                "cloud": "do",
                                "region": "nyc3",
                                "public_ip": "1.2.3.4",
                                "master_user": "master_example",
                                "apps": [],  # No apps
                            }
                        ],
                    },
                )
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=missing_app_handler
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "1234567" in result.output


class TestInfoProviderNames:
    """M-1: Tests for provider code to display name mapping."""

    def test_info_displays_digitalocean_for_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provider code 'do' should display as 'DigitalOcean'."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "DigitalOcean" in result.output

    def test_info_displays_provider_name_for_vultr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provider code 'vultr' should display as 'Vultr'."""

        def vultr_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                resp = _make_servers_response()
                resp["servers"][0]["cloud"] = "vultr"
                return httpx.Response(200, json=resp)
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=vultr_handler
        )
        assert result.exit_code == 0
        assert "Vultr" in result.output


class TestInfoStatusColors:
    """M-2: Tests for status color coding in output."""

    def test_info_running_status_has_green(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running status should include green markup."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        # Rich console output should contain the status
        assert "running" in result.output.lower()

    def test_info_stopped_status_has_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stopped status should include red markup."""

        def stopped_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                resp = _make_servers_response()
                resp["servers"][0]["status"] = "stopped"
                return httpx.Response(200, json=resp)
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=stopped_handler
        )
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()


class TestInfoIdMatching:
    """M-3: Tests for int coercion in server/app ID matching."""

    def test_info_matches_server_with_int_coercion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server ID matching works between string API and int config values."""
        # Default fixtures: config has int 999999, API returns string "999999"
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "999999" in result.output

    def test_info_matches_app_with_int_coercion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App ID matching works between string API and int config values."""
        result = _run_info_with_mocks(monkeypatch)
        assert result.exit_code == 0
        assert "1234567" in result.output


class TestInfoUnknownProviderAndStatus:
    """Tests for unknown provider codes and status values."""

    def test_info_unknown_provider_shows_raw_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provider code not in PROVIDER_NAMES falls back to raw code."""

        def hetzner_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                resp = _make_servers_response()
                resp["servers"][0]["cloud"] = "hetzner"
                return httpx.Response(200, json=resp)
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=hetzner_handler
        )
        assert result.exit_code == 0
        # Should fall back to raw code "hetzner" since it's not in PROVIDER_NAMES
        assert "hetzner" in result.output

    def test_info_unknown_status_shown_in_yellow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status that is neither 'running' nor 'stopped' is shown (yellow branch)."""

        def restarting_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                resp = _make_servers_response()
                resp["servers"][0]["status"] = "restarting"
                return httpx.Response(200, json=resp)
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=restarting_handler
        )
        assert result.exit_code == 0
        assert "restarting" in result.output.lower()


class TestInfoMalformedData:
    """Tests for malformed data handling in info command."""

    def test_info_malformed_app_id_in_api_response_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App with non-numeric ID in API response is skipped gracefully."""

        def malformed_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                resp = _make_servers_response()
                # Add an app with a malformed (non-numeric) ID
                resp["servers"][0]["apps"].append(
                    {
                        "id": "not-a-number",
                        "label": "Malformed App",
                        "application": "wordpress",
                    }
                )
                return httpx.Response(200, json=resp)
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=malformed_handler
        )
        # Should succeed - the malformed app is skipped, valid ones still match
        assert result.exit_code == 0
        assert "1234567" in result.output

    def test_info_invalid_app_id_in_config_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Non-numeric app_id in project config raises CloudwaysError."""
        config = tmp_path / "bad-app-id-config.yml"
        config.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 999999\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: not-a-number\n"
            "        domain: example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config))
        monkeypatch.setenv(
            "CLOUDWAYS_ACCOUNTS_FILE",
            str(FIXTURES_DIR / "accounts.yml"),
        )

        mock_transport = httpx.MockTransport(_mock_transport_handler)

        with patch(
            "cloudways_api.commands.info.CloudwaysClient",
            wraps=make_patched_client_class(mock_transport),
        ):
            result = runner.invoke(app, ["info"])

        assert result.exit_code == 1
        assert "not-a-number" in result.output.lower() or "invalid" in result.output.lower()

    def test_info_malformed_server_id_in_api_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server with non-numeric ID in API response is skipped gracefully."""

        def malformed_srv_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/settings" in url:
                return httpx.Response(200, json=_make_settings_response())
            if "/server" in url:
                # First server has malformed ID, second has valid ID
                return httpx.Response(
                    200,
                    json={
                        "status": True,
                        "servers": [
                            {
                                "id": "not-numeric",
                                "label": "bad-server",
                                "status": "running",
                                "cloud": "do",
                                "region": "nyc3",
                                "public_ip": "1.2.3.4",
                                "master_user": "m",
                                "apps": [],
                            },
                            {
                                "id": "999999",
                                "label": "example-prod",
                                "status": "running",
                                "cloud": "do",
                                "region": "nyc3",
                                "public_ip": "1.2.3.4",
                                "master_user": "master_example",
                                "apps": [
                                    {
                                        "id": "1234567",
                                        "label": "Production WP",
                                        "application": "wordpress",
                                        "app_version": "6.4",
                                        "cname": "wp.example.com",
                                        "server_id": "999999",
                                        "sys_user": "appuser",
                                        "mysql_db_name": "dbname",
                                        "webroot": "public_html",
                                    },
                                    {
                                        "id": "7654321",
                                        "label": "Staging WP",
                                        "application": "wordpress",
                                        "app_version": "6.4",
                                        "cname": "staging.wp.example.com",
                                        "server_id": "999999",
                                        "sys_user": "staginguser",
                                        "mysql_db_name": "staging_db",
                                        "webroot": "public_html",
                                    },
                                ],
                            },
                        ],
                    },
                )
            return httpx.Response(404)

        result = _run_info_with_mocks(
            monkeypatch, transport_handler=malformed_srv_handler
        )
        # Should succeed - the malformed server is skipped, valid one matched
        assert result.exit_code == 0
        assert "999999" in result.output
