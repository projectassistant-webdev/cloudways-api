"""Integration tests for the `cloudways provision app` command."""

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


def _make_servers_response() -> dict:
    return {
        "servers": [
            {
                "id": "1089270",
                "label": "my-server",
                "status": "running",
                "public_ip": "10.0.0.1",
                "apps": [],
            },
            {
                "id": "2222222",
                "label": "another-server",
                "status": "running",
                "public_ip": "10.0.0.2",
                "apps": [],
            },
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
        ]
    }


def _make_create_app_response() -> dict:
    return {
        "app": {
            "id": 5550001,
            "label": "test-app",
        },
        "operation_id": 88001,
    }


def _make_operation_complete_response() -> dict:
    return {
        "operation": {
            "id": 88001,
            "is_completed": True,
            "status": "completed",
        }
    }


def _make_operation_pending_response() -> dict:
    return {
        "operation": {
            "id": 88001,
            "is_completed": False,
            "status": "pending",
        }
    }


# ---------------------------------------------------------------------------
# Mock transport handler
# ---------------------------------------------------------------------------


def _provision_app_transport(request: httpx.Request) -> httpx.Response:
    """Mock transport that handles all provision-app-related endpoints."""
    url = str(request.url)

    if "/oauth/access_token" in url:
        return httpx.Response(200, json=make_auth_response())

    if "/server" in url and "/server_size" not in url and request.method == "GET":
        return httpx.Response(200, json=_make_servers_response())

    if "/app_list" in url:
        return httpx.Response(200, json=_make_app_types_response())

    # POST /app -> create
    if "/app" in url and "/app_list" not in url and request.method == "POST":
        return httpx.Response(200, json=_make_create_app_response())

    # PUT /app/manage/fpm_setting -> PHP version
    if "/fpm_setting" in url and request.method == "PUT":
        return httpx.Response(200, json={"status": True})

    # POST /app/manage/cname -> add domain
    if "/cname" in url and request.method == "POST":
        return httpx.Response(200, json={"status": True})

    # GET /operation/... -> completed
    if "/operation/" in url:
        return httpx.Response(200, json=_make_operation_complete_response())

    return httpx.Response(404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_provision_app(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_fixture: str = "project-config.yml",
    accounts_fixture: str = "accounts.yml",
    transport_handler=None,
    input_text: str | None = None,
) -> object:
    """Run 'cloudways provision app' with all external dependencies mocked."""
    config_path = str(FIXTURES_DIR / config_fixture)
    accounts_path = str(FIXTURES_DIR / accounts_fixture)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    handler = transport_handler or _provision_app_transport
    mock_transport = httpx.MockTransport(handler)

    with patch(
        "cloudways_api.commands.provision.app.CloudwaysClient",
        wraps=make_patched_client_class(mock_transport),
    ), patch(
        "cloudways_api.client.asyncio.sleep",
        return_value=None,
    ):
        result = runner.invoke(
            app,
            ["provision", "app"] + (args or []),
            input=input_text,
        )

    return result


# ===========================================================================
# Test Classes
# ===========================================================================


class TestProvisionAppRegistration:
    """Verify the provision app sub-command is registered."""

    def test_provision_app_exists_in_help(self) -> None:
        """CLI recognises the 'provision app' sub-command."""
        result = runner.invoke(app, ["provision", "--help"])
        assert result.exit_code == 0
        assert "app" in result.output.lower()

    def test_provision_app_help(self) -> None:
        """'provision app --help' shows all expected options."""
        result = runner.invoke(app, ["provision", "app", "--help"])
        assert result.exit_code == 0
        assert "--server-id" in result.output
        assert "--app-label" in result.output
        assert "--app" in result.output
        assert "--app-version" in result.output
        assert "--project" in result.output
        assert "--php" in result.output
        assert "--domain" in result.output
        assert "--timeout" in result.output


class TestProvisionAppNonInteractive:
    """Non-interactive mode: all flags provided, no prompts."""

    def test_provision_app_all_required_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All required flags provided -> app created successfully."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "1089270",
                "--app-label", "my-new-app",
            ],
        )
        assert result.exit_code == 0
        assert "Application Created" in result.output
        assert "Successfully" in result.output

    def test_provision_app_output_shows_app_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the app ID from the API response."""
        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
        )
        assert result.exit_code == 0
        assert "5550001" in result.output

    def test_provision_app_output_shows_server_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the target server ID."""
        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
        )
        assert result.exit_code == 0
        assert "1089270" in result.output

    def test_provision_app_output_shows_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes the chosen app label."""
        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "custom-label"],
        )
        assert result.exit_code == 0
        assert "custom-label" in result.output

    def test_provision_app_output_shows_wordpress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output table includes wordpress as the application type."""
        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
        )
        assert result.exit_code == 0
        assert "wordpress" in result.output

    def test_provision_app_custom_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom --project is accepted and shown in output."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "1089270",
                "--app-label", "test-app",
                "--project", "MyProject",
            ],
        )
        assert result.exit_code == 0
        assert "MyProject" in result.output


class TestProvisionAppPostCreation:
    """Post-creation configuration: PHP version and domain."""

    def test_provision_app_with_php_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--php-version flag triggers PHP version update after creation."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "1089270",
                "--app-label", "test-app",
                "--php", "8.2",
            ],
        )
        assert result.exit_code == 0
        assert "8.2" in result.output
        assert "Application Created" in result.output
        assert "Successfully" in result.output

    def test_provision_app_with_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--domain flag triggers domain addition after creation."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "1089270",
                "--app-label", "test-app",
                "--domain", "example.com",
            ],
        )
        assert result.exit_code == 0
        assert "example.com" in result.output
        assert "Application Created" in result.output
        assert "Successfully" in result.output

    def test_provision_app_with_both_php_and_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both --php-version and --domain are processed."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "1089270",
                "--app-label", "test-app",
                "--php", "8.3",
                "--domain", "staging.example.com",
            ],
        )
        assert result.exit_code == 0
        assert "8.3" in result.output
        assert "staging.example.com" in result.output


class TestProvisionAppValidation:
    """Input validation for server ID."""

    def test_provision_app_invalid_server_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent server ID produces an error."""
        result = _run_provision_app(
            monkeypatch,
            args=[
                "--server-id", "9999999",
                "--app-label", "test-app",
            ],
        )
        assert result.exit_code == 1
        assert "9999999" in result.output or "not found" in result.output.lower()


class TestProvisionAppMissingFlags:
    """Non-interactive mode with missing required flags."""

    def test_missing_server_id_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --server-id in non-interactive mode fails with clear message."""
        result = _run_provision_app(
            monkeypatch,
            args=["--app-label", "test-app"],
        )
        assert result.exit_code != 0
        assert "--server-id" in result.output

    def test_missing_app_label_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --app-label in non-interactive mode fails with clear message."""
        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270"],
        )
        assert result.exit_code != 0
        assert "--app-label" in result.output

    def test_missing_all_flags_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No flags at all in non-interactive mode lists all missing."""
        result = _run_provision_app(monkeypatch, args=[])
        assert result.exit_code != 0
        assert "--server-id" in result.output
        assert "--app-label" in result.output


class TestProvisionAppErrorHandling:
    """Error scenarios: auth failures, API errors."""

    def test_provision_app_auth_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API returns 401 shows authentication error."""

        def auth_fail_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(401, json={"error": "invalid_credentials"})
            return httpx.Response(404)

        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
            transport_handler=auth_fail_handler,
        )
        assert result.exit_code == 1
        assert "authentication" in result.output.lower() or "error" in result.output.lower()

    def test_provision_app_api_create_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App creation returns error shows provisioning error."""

        def create_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(
                    422,
                    json={"error": "Server quota exceeded"},
                    text="Server quota exceeded",
                )
            return httpx.Response(404)

        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
            transport_handler=create_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_provision_app_network_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connection failure shows user-friendly error."""

        def network_fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
            transport_handler=network_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_provision_app_missing_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No project-config.yml produces user-friendly error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", "/tmp/nonexistent.yml")
        monkeypatch.setenv(
            "CLOUDWAYS_ACCOUNTS_FILE",
            str(FIXTURES_DIR / "accounts.yml"),
        )

        mock_transport = httpx.MockTransport(_provision_app_transport)

        with patch(
            "cloudways_api.commands.provision.app.CloudwaysClient",
            wraps=make_patched_client_class(mock_transport),
        ):
            result = runner.invoke(
                app,
                [
                    "provision", "app",
                    "--server-id", "1089270",
                    "--app-label", "t",
                ],
            )
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestProvisionAppOperationPolling:
    """Tests for operation polling behaviour."""

    def test_provision_app_polls_until_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """App creation polls the operation and succeeds."""
        call_count = {"value": 0}

        def polling_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_app_response())
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
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                ],
                transport_handler=polling_handler,
            )

        assert result.exit_code == 0
        assert "Application Created" in result.output
        assert "Successfully" in result.output
        assert call_count["value"] >= 2

    def test_provision_app_no_operation_id_still_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If API returns no operation_id, skip polling and show result."""

        def no_opid_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "app": {
                            "id": 5550001,
                            "label": "test-app",
                        },
                        # No operation_id
                    },
                )
            return httpx.Response(404)

        result = _run_provision_app(
            monkeypatch,
            args=["--server-id", "1089270", "--app-label", "test-app"],
            transport_handler=no_opid_handler,
        )
        assert result.exit_code == 0
        assert "Application Created" in result.output
        assert "Successfully" in result.output


class TestProvisionAppDefaults:
    """Tests for default values of optional parameters."""

    def test_default_project_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default project_name is 'Default' when not provided."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["project_name"] == "Default"

    def test_sends_application_wordpress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST body always sends application=wordpress."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["application"] == "wordpress"

    def test_uses_latest_wp_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST body uses the first version from app_list for WordPress."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["app_version"] == "6.5"


class TestProvisionAppPostCreationWarnings:
    """Post-creation config failures produce warnings, not errors."""

    def test_php_version_failure_shows_warning_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PHP version update failure shows warning but app creation succeeds."""

        def php_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_app_response())
            if "/fpm_setting" in url and request.method == "PUT":
                return httpx.Response(422, json={"error": "Invalid PHP version"})
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                    "--php", "9.9",
                ],
                transport_handler=php_fail_handler,
            )

        # App creation should still succeed
        assert result.exit_code == 0
        assert "Application Created" in result.output
        assert "Successfully" in result.output

    def test_domain_failure_shows_warning_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Domain add failure shows warning but app creation succeeds."""

        def domain_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_app_response())
            if "/cname" in url and request.method == "POST":
                return httpx.Response(422, json={"error": "Invalid domain"})
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                    "--domain", "bad-domain",
                ],
                transport_handler=domain_fail_handler,
            )

        # App creation should still succeed
        assert result.exit_code == 0
        assert "Application Created" in result.output
        assert "Successfully" in result.output


class TestProvisionAppTypeAndVersion:
    """Tests for --app and --app-version CLI options."""

    def test_custom_app_type_sent_to_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--app flag overrides the default wordpress application type."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(
                    200,
                    json={
                        "app_list": [
                            {
                                "label": "Laravel",
                                "value": "laravel",
                                "versions": ["11.0", "10.0"],
                            }
                        ]
                    },
                )
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                    "--app", "laravel",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["application"] == "laravel"
        assert "laravel" in result.output

    def test_explicit_app_version_sent_to_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--app-version flag sets the version directly, skipping API lookup."""
        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                # Should NOT be called when --app-version is provided
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep",
            return_value=None,
        ):
            result = _run_provision_app(
                monkeypatch,
                args=[
                    "--server-id", "1089270",
                    "--app-label", "test-app",
                    "--app-version", "6.3",
                ],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["app_version"] == "6.3"


class TestProvisionAppInteractivePrompts:
    """Interactive mode: prompts for missing values when stdin is a TTY."""

    def test_interactive_server_selection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --server-id triggers interactive server list and prompt."""
        with patch(
            "cloudways_api.commands.provision.app.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch(
                "cloudways_api.client.asyncio.sleep",
                return_value=None,
            ):
                result = _run_provision_app(
                    monkeypatch,
                    args=["--app-label", "test-app"],
                    # Choose server 1089270 from the list
                    input_text="1089270\n",
                )

        assert result.exit_code == 0
        assert "Application Created" in result.output

    def test_interactive_app_label_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --app-label triggers interactive label prompt."""
        with patch(
            "cloudways_api.commands.provision.app.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            with patch(
                "cloudways_api.client.asyncio.sleep",
                return_value=None,
            ):
                result = _run_provision_app(
                    monkeypatch,
                    args=["--server-id", "1089270"],
                    input_text="my-prompted-app\n",
                )

        assert result.exit_code == 0
        assert "Application Created" in result.output

    def test_interactive_no_servers_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Interactive mode with no servers on account raises ProvisioningError."""

        def empty_servers_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json={"servers": []})
            return httpx.Response(404)

        with patch(
            "cloudways_api.commands.provision.app.sys"
        ) as mock_sys:
            mock_sys.stdin.isatty.return_value = True
            result = _run_provision_app(
                monkeypatch,
                args=[],
                transport_handler=empty_servers_handler,
                input_text="",
            )

        assert result.exit_code == 1
        assert "no servers" in result.output.lower() or "error" in result.output.lower()


class TestProvisionAppTimeoutHint:
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
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(200, json=_make_app_types_response())
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_app_response())
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
                result = _run_provision_app(
                    monkeypatch,
                    args=[
                        "--server-id", "1089270",
                        "--app-label", "test-app",
                        "--timeout", "300",
                    ],
                    transport_handler=timeout_handler,
                )

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output


class TestProvisionAppTemplateConfigureBlock:
    """Template configure sub-block tests for provision app."""

    def test_template_configure_php_version(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Template configure.php_version is used for post-creation PHP config."""
        tpl = tmp_path / "app-tpl.yml"
        tpl.write_text(
            "provision:\n"
            "  type: app\n"
            "  server_id: 1089270\n"
            "  app_label: tpl-app\n"
            "  configure:\n"
            "    php_version: '8.3'\n"
        )

        with patch(
            "cloudways_api.client.asyncio.sleep", return_value=None
        ):
            result = _run_provision_app(
                monkeypatch,
                args=["--from-template", str(tpl)],
            )

        assert result.exit_code == 0
        assert "8.3" in result.output

    def test_template_configure_domain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Template configure.domain is used for post-creation domain config."""
        tpl = tmp_path / "app-tpl.yml"
        tpl.write_text(
            "provision:\n"
            "  type: app\n"
            "  server_id: 1089270\n"
            "  app_label: tpl-app\n"
            "  configure:\n"
            "    domain: tpl.example.com\n"
        )

        with patch(
            "cloudways_api.client.asyncio.sleep", return_value=None
        ):
            result = _run_provision_app(
                monkeypatch,
                args=["--from-template", str(tpl)],
            )

        assert result.exit_code == 0
        assert "tpl.example.com" in result.output

    def test_template_overrides_app_type(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Template application field overrides default 'wordpress' app type."""
        tpl = tmp_path / "app-tpl.yml"
        tpl.write_text(
            "provision:\n"
            "  type: app\n"
            "  server_id: 1089270\n"
            "  app_label: tpl-app\n"
            "  application: phplaravel\n"
        )

        captured_data = {}

        def capture_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url and request.method == "GET":
                return httpx.Response(200, json=_make_servers_response())
            if "/app_list" in url:
                return httpx.Response(
                    200,
                    json={
                        "app_list": [
                            {
                                "label": "Laravel",
                                "value": "phplaravel",
                                "versions": ["11.0", "10.0"],
                            },
                        ]
                    },
                )
            if "/app" in url and "/app_list" not in url and request.method == "POST":
                captured_data["body"] = dict(
                    httpx.QueryParams(request.content.decode())
                )
                return httpx.Response(200, json=_make_create_app_response())
            if "/operation/" in url:
                return httpx.Response(
                    200, json=_make_operation_complete_response()
                )
            return httpx.Response(404)

        with patch(
            "cloudways_api.client.asyncio.sleep", return_value=None
        ):
            result = _run_provision_app(
                monkeypatch,
                args=["--from-template", str(tpl)],
                transport_handler=capture_handler,
            )

        assert result.exit_code == 0
        assert captured_data["body"]["application"] == "phplaravel"

    def test_template_wrong_type_raises_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Template with type='server' raises ConfigError when used for app."""
        tpl = tmp_path / "wrong-type.yml"
        tpl.write_text(
            "provision:\n"
            "  type: server\n"
            "  provider: do\n"
            "  region: nyc3\n"
            "  size: 2GB\n"
            "  server_label: srv\n"
        )

        result = _run_provision_app(
            monkeypatch,
            args=["--from-template", str(tpl)],
        )
        assert result.exit_code == 1
        assert "server" in result.output.lower()
        assert "app" in result.output.lower()
