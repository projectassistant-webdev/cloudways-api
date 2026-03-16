"""Integration tests for the `cloudways provision server` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from conftest import FIXTURES_DIR, make_auth_response, make_patched_client_class

runner = CliRunner()


# ---------------------------------------------------------------------------
# Mock response factories
# ---------------------------------------------------------------------------


def _make_regions_response() -> dict:
    return {
        "regions": [
            {"id": "nyc3", "name": "New York 3"},
            {"id": "sfo3", "name": "San Francisco 3"},
            {"id": "ams3", "name": "Amsterdam 3"},
        ]
    }


def _make_sizes_response() -> dict:
    return {
        "sizes": [
            {"id": "1GB", "name": "1 GB"},
            {"id": "2GB", "name": "2 GB"},
            {"id": "4GB", "name": "4 GB"},
        ]
    }


def _make_app_types_response() -> dict:
    return {
        "app_list": [
            {
                "label": "WordPress",
                "value": "wordpress",
                "versions": ["6.5", "6.4", "6.3"],
            },
            {
                "label": "Laravel",
                "value": "laravel",
                "versions": ["11.0", "10.0"],
            },
        ]
    }


def _make_create_server_response() -> dict:
    return {
        "server": {
            "id": 123456,
            "label": "test-server",
            "public_ip": "10.0.0.1",
        },
        "operation_id": 99001,
    }


def _make_operation_complete_response() -> dict:
    return {
        "operation": {
            "id": 99001,
            "is_completed": True,
            "status": "completed",
        }
    }


def _make_operation_pending_response() -> dict:
    return {
        "operation": {
            "id": 99001,
            "is_completed": False,
            "status": "pending",
        }
    }


# ---------------------------------------------------------------------------
# Mock transport handler
# ---------------------------------------------------------------------------


def _provision_transport_handler(request: httpx.Request) -> httpx.Response:
    """Mock transport that handles all provision-server-related endpoints."""
    url = str(request.url)

    if "/oauth/access_token" in url:
        return httpx.Response(200, json=make_auth_response())

    if "/region" in url:
        return httpx.Response(200, json=_make_regions_response())

    if "/server_size" in url:
        return httpx.Response(200, json=_make_sizes_response())

    if "/app_list" in url:
        return httpx.Response(200, json=_make_app_types_response())

    # POST /server -> create
    if "/server" in url and request.method == "POST":
        return httpx.Response(200, json=_make_create_server_response())

    # GET /operation/... -> completed
    if "/operation/" in url:
        return httpx.Response(200, json=_make_operation_complete_response())

    return httpx.Response(404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_provision_server(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_fixture: str = "project-config.yml",
    accounts_fixture: str = "accounts.yml",
    transport_handler=None,
    input_text: str | None = None,
) -> object:
    """Run 'cloudways provision server' with all external dependencies mocked."""
    config_path = str(FIXTURES_DIR / config_fixture)
    accounts_path = str(FIXTURES_DIR / accounts_fixture)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    handler = transport_handler or _provision_transport_handler
    mock_transport = httpx.MockTransport(handler)

    with patch(
        "cloudways_api.commands.provision.server.CloudwaysClient",
        wraps=make_patched_client_class(mock_transport),
    ), patch(
        "cloudways_api.client.asyncio.sleep",
        return_value=None,
    ):
        result = runner.invoke(
            app,
            ["provision", "server"] + (args or []),
            input=input_text,
        )

    return result


# ===========================================================================
# Test Classes
# ===========================================================================


class TestProvisionServerRegistration:
    """Verify the provision sub-app is registered in the CLI."""

    def test_provision_command_exists(self) -> None:
        """CLI recognises the 'provision' command group."""
        result = runner.invoke(app, ["provision", "--help"])
        assert result.exit_code == 0
        assert "server" in result.output.lower()

    def test_provision_server_help(self) -> None:
        """'provision server --help' shows all expected options."""
        result = runner.invoke(app, ["provision", "server", "--help"])
        assert result.exit_code == 0
        assert "--region" in result.output
        assert "--size" in result.output
        assert "--label" in result.output
        assert "--app-label" in result.output
        assert "--project" in result.output
        assert "--timeout" in result.output


class TestProvisionServerNonInteractive:
    """Non-interactive mode: all flags provided, no prompts."""

    def test_provision_server_all_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All flags provided -> server created successfully."""
        result = _run_provision_server(
            monkeypatch,
            args=[
                "--region", "nyc3",
                "--size", "2GB",
                "--label", "my-test-server",
            ],
        )
        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output

    def test_provision_server_output_shows_server_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the server ID from the API response."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "test-srv"],
        )
        assert result.exit_code == 0
        assert "123456" in result.output

    def test_provision_server_output_shows_ip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the public IP."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "test-srv"],
        )
        assert result.exit_code == 0
        assert "10.0.0.1" in result.output

    def test_provision_server_output_shows_region_and_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the selected region and size."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "sfo3", "--size", "4GB", "--label", "big-srv"],
        )
        assert result.exit_code == 0
        assert "sfo3" in result.output
        assert "4GB" in result.output

    def test_provision_server_custom_app_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom --app-label is accepted without error."""
        result = _run_provision_server(
            monkeypatch,
            args=[
                "--region", "nyc3",
                "--size", "2GB",
                "--label", "srv",
                "--app-label", "custom-wp",
            ],
        )
        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output

    def test_provision_server_custom_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom --project is accepted without error."""
        result = _run_provision_server(
            monkeypatch,
            args=[
                "--region", "nyc3",
                "--size", "2GB",
                "--label", "srv",
                "--project", "MyProject",
            ],
        )
        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output

    def test_provision_server_output_shows_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes DigitalOcean as provider."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
        )
        assert result.exit_code == 0
        assert "DigitalOcean" in result.output

    def test_provision_server_output_shows_elapsed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the creation duration."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
        )
        assert result.exit_code == 0
        # Should show something like "0m Xs"
        assert "m " in result.output and "s" in result.output


class TestProvisionServerValidation:
    """Input validation for region and size values."""

    def test_provision_server_invalid_region(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid region produces a provisioning error."""
        result = _run_provision_server(
            monkeypatch,
            args=[
                "--region", "invalid-region",
                "--size", "2GB",
                "--label", "srv",
            ],
        )
        assert result.exit_code == 1
        assert "invalid-region" in result.output.lower()

    def test_provision_server_invalid_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid server size produces a provisioning error."""
        result = _run_provision_server(
            monkeypatch,
            args=[
                "--region", "nyc3",
                "--size", "999GB",
                "--label", "srv",
            ],
        )
        assert result.exit_code == 1
        assert "999gb" in result.output.lower()


class TestProvisionServerMissingFlags:
    """Non-interactive mode with missing required flags."""

    def test_missing_region_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --region in non-interactive mode fails with clear message."""
        # CliRunner doesn't have a real TTY, so it should be non-interactive.
        # typer.BadParameter raises SystemExit(2).
        result = _run_provision_server(
            monkeypatch,
            args=["--size", "2GB", "--label", "srv"],
        )
        assert result.exit_code != 0
        assert "--region" in result.output

    def test_missing_size_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --size in non-interactive mode fails with clear message."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--label", "srv"],
        )
        assert result.exit_code != 0
        assert "--size" in result.output

    def test_missing_label_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --label in non-interactive mode fails with clear message."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB"],
        )
        assert result.exit_code != 0
        assert "--label" in result.output

    def test_missing_all_flags_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No flags at all in non-interactive mode lists all missing."""
        result = _run_provision_server(monkeypatch, args=[])
        assert result.exit_code != 0
        assert "--region" in result.output
        assert "--size" in result.output
        assert "--label" in result.output


class TestProvisionServerErrorHandling:
    """Error scenarios: auth failures, API errors, timeouts."""

    def test_provision_server_auth_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API returns 401 shows authentication error."""

        def auth_fail_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(401, json={"error": "invalid_credentials"})
            return httpx.Response(404)

        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
            transport_handler=auth_fail_handler,
        )
        assert result.exit_code == 1
        assert "authentication" in result.output.lower() or "error" in result.output.lower()

    def test_provision_server_api_create_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server creation returns 422 shows provisioning error."""

        def create_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                return httpx.Response(
                    422,
                    json={"error": "Quota exceeded"},
                    text="Quota exceeded",
                )
            return httpx.Response(404)

        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
            transport_handler=create_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_provision_server_network_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connection failure shows user-friendly error."""

        def network_fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
            transport_handler=network_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_provision_server_missing_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No project-config.yml produces user-friendly error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", "/tmp/nonexistent.yml")
        monkeypatch.setenv(
            "CLOUDWAYS_ACCOUNTS_FILE",
            str(FIXTURES_DIR / "accounts.yml"),
        )

        mock_transport = httpx.MockTransport(_provision_transport_handler)

        with patch(
            "cloudways_api.commands.provision.server.CloudwaysClient",
            wraps=make_patched_client_class(mock_transport),
        ):
            result = runner.invoke(
                app,
                ["provision", "server", "--region", "nyc3", "--size", "2GB", "--label", "s"],
            )
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestProvisionServerOperationPolling:
    """Tests for operation polling behaviour."""

    def test_provision_server_polls_until_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server creation polls the operation and succeeds."""
        call_count = {"value": 0}

        def polling_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                call_count["value"] += 1
                if call_count["value"] < 3:
                    return httpx.Response(
                        200, json=_make_operation_pending_response()
                    )
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=polling_handler,
            )

        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output
        # Should have polled at least twice before completing
        assert call_count["value"] >= 2

    def test_provision_server_no_operation_id_still_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If API returns no operation_id, skip polling and show result."""

        def no_opid_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "server": {
                            "id": 123456,
                            "label": "test-server",
                            "public_ip": "10.0.0.1",
                        },
                        # No operation_id
                    },
                )
            return httpx.Response(404)

        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "test-srv"],
            transport_handler=no_opid_handler,
        )
        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output


class TestProvisionServerWordPressVersion:
    """Tests for auto-detection of WordPress version."""

    def test_uses_latest_wp_version_from_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Server creation uses the first version from the app_list response."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                # Capture the POST body for assertion
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        # The app_types response has "6.5" as the first WordPress version
        assert captured_data["body"]["app_version"] == "6.5"

    def test_falls_back_when_wp_not_in_app_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If WordPress is not in app_list, falls back to '6.5'."""
        captured_data = {}

        def no_wp_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(
                    200,
                    json={
                        "app_list": [
                            {
                                "label": "Laravel",
                                "value": "laravel",
                                "versions": ["11.0"],
                            }
                        ]
                    },
                )
            if "/server" in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=no_wp_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["app_version"] == "6.5"


class TestProvisionServerDefaults:
    """Tests for default values of optional parameters."""

    def test_default_app_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default app_label is 'my-app' when not provided."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["app_label"] == "my-app"

    def test_default_project_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default project_name is 'Default' when not provided."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["project_name"] == "Default"

    def test_sends_cloud_do_and_application_wordpress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST body always sends cloud=do and application=wordpress."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_server(
                monkeypatch,
                args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["cloud"] == "do"
        assert captured_data["body"]["application"] == "wordpress"


class TestProvisionServerOutputTable:
    """Tests for the Rich table content in success output."""

    def test_output_shows_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The chosen label appears in the output table."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "my-label"],
        )
        assert result.exit_code == 0
        assert "my-label" in result.output

    def test_output_shows_running_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table shows 'running' status."""
        result = _run_provision_server(
            monkeypatch,
            args=["--region", "nyc3", "--size", "2GB", "--label", "srv"],
        )
        assert result.exit_code == 0
        assert "running" in result.output.lower()


class TestProvisionServerInteractivePrompts:
    """Interactive mode: prompts for missing values when stdin is a TTY."""

    def test_interactive_prompts_for_region_size_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing flags trigger interactive prompts when stdin is a TTY."""
        with patch(
            "cloudways_api.commands.provision.server.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch(
                "cloudways_api.client.asyncio.sleep",
                return_value=None,
            ):
                result = _run_provision_server(
                    monkeypatch,
                    args=[],
                    # Provide input: region, size, label
                    input_text="nyc3\n2GB\nmy-interactive-srv\n",
                )

        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output

    def test_interactive_prompts_for_label_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When only label is missing, only label is prompted."""
        with patch(
            "cloudways_api.commands.provision.server.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch(
                "cloudways_api.client.asyncio.sleep",
                return_value=None,
            ):
                result = _run_provision_server(
                    monkeypatch,
                    args=["--region", "nyc3", "--size", "2GB"],
                    input_text="prompted-label\n",
                )

        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output

    def test_interactive_prompts_for_region_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When only region is missing, region is prompted."""
        with patch(
            "cloudways_api.commands.provision.server.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch(
                "cloudways_api.client.asyncio.sleep",
                return_value=None,
            ):
                result = _run_provision_server(
                    monkeypatch,
                    args=["--size", "2GB", "--label", "srv"],
                    input_text="nyc3\n",
                )

        assert result.exit_code == 0
        assert "Server Created Successfully" in result.output


class TestProvisionServerTimeoutHint:
    """Operation timeout shows platform hint."""

    def test_timeout_shows_cloudways_platform_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OperationTimeoutError shows hint about checking platform.cloudways.com."""
        import time as _time

        def timeout_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_pending_response()
                )
            return httpx.Response(404)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch(
            "cloudways_api.client.asyncio.sleep", return_value=None
        ):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                result = _run_provision_server(
                    monkeypatch,
                    args=[
                        "--region", "nyc3",
                        "--size", "2GB",
                        "--label", "srv",
                        "--timeout", "600",
                    ],
                    transport_handler=timeout_handler,
                )

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output


class TestProvisionServerTemplate:
    """Template edge cases for provision server."""

    def test_template_wrong_type_raises_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Template with type='app' raises ConfigError when used for server."""
        tpl = tmp_path / "wrong-type.yml"
        tpl.write_text(
            "provision:\n"
            "  type: app\n"
            "  server_id: 999999\n"
            "  app_label: my-app\n"
        )

        result = _run_provision_server(
            monkeypatch,
            args=["--from-template", str(tpl)],
        )
        assert result.exit_code == 1
        assert "app" in result.output.lower()
        assert "server" in result.output.lower()

    def test_template_with_partial_cli_overrides(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLI flags override template values (e.g., --region overrides template region)."""
        tpl = tmp_path / "server-tpl.yml"
        tpl.write_text(
            "provision:\n"
            "  type: server\n"
            "  provider: do\n"
            "  region: ams3\n"
            "  size: 1GB\n"
            "  server_label: template-srv\n"
        )

        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/region" in url:
                return httpx.Response(200, json=_make_regions_response())
            if "/server_size" in url:
                return httpx.Response(200, json=_make_sizes_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/server" in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_server_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep", return_value=None
        ):
            result = _run_provision_server(
                monkeypatch,
                args=[
                    "--from-template", str(tpl),
                    "--region", "nyc3",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        # CLI --region overrides template's ams3
        assert captured_data["body"]["region"] == "nyc3"
        # Template's size is still used
        assert captured_data["body"]["instance_type"] == "1GB"
