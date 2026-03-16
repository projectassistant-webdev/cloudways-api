"""Integration tests for the `cloudways provision staging` command."""

from __future__ import annotations

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


def _make_create_staging_response() -> dict:
    return {
        "app": {
            "id": 7770001,
            "label": "staging-production",
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


def _provision_staging_transport(request: httpx.Request) -> httpx.Response:
    """Mock transport that handles all provision-staging-related endpoints."""
    url = str(request.url)

    if "/oauth/access_token" in url:
        return httpx.Response(200, json=make_auth_response())

    # POST /app/clone -> create staging clone
    if "/app/clone" in url and request.method == "POST":
        return httpx.Response(200, json=_make_create_staging_response())

    # GET /operation/... -> completed
    if "/operation/" in url:
        return httpx.Response(200, json=_make_operation_complete_response())

    return httpx.Response(404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_provision_staging(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_fixture: str = "project-config.yml",
    accounts_fixture: str = "accounts.yml",
    transport_handler=None,
    input_text: str | None = None,
) -> object:
    """Run 'cloudways provision staging' with all external dependencies mocked."""
    config_path = str(FIXTURES_DIR / config_fixture)
    accounts_path = str(FIXTURES_DIR / accounts_fixture)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    handler = transport_handler or _provision_staging_transport
    mock_transport = httpx.MockTransport(handler)

    with patch(
        "cloudways_api.commands.provision.staging.CloudwaysClient",
        wraps=make_patched_client_class(mock_transport),
    ):
        result = runner.invoke(
            app,
            ["provision", "staging"] + (args or []),
            input=input_text,
        )

    return result


# ===========================================================================
# Test Classes
# ===========================================================================


class TestProvisionStagingRegistration:
    """Verify the provision staging sub-command is registered."""

    def test_provision_staging_registered(self) -> None:
        """CLI recognises the 'provision staging' sub-command and --help exits 0."""
        result = runner.invoke(app, ["provision", "staging", "--help"])
        assert result.exit_code == 0
        assert "staging" in result.output.lower()


class TestProvisionStagingNonInteractive:
    """Non-interactive mode: all flags provided, no prompts."""

    def test_provision_staging_non_interactive_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All flags provided -> staging app cloned successfully."""
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            result = _run_provision_staging(
                monkeypatch,
                args=[
                    "production",
                    "--label", "my-staging",
                ],
            )
        assert result.exit_code == 0
        assert "Staging" in result.output or "staging" in result.output.lower()

    def test_provision_staging_shows_app_id_in_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Output contains the staging app ID from the API response."""
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            result = _run_provision_staging(
                monkeypatch,
                args=["production", "--label", "my-staging"],
            )
        assert result.exit_code == 0
        assert "7770001" in result.output


class TestProvisionStagingMissingLabel:
    """Non-interactive mode with missing --label."""

    def test_provision_staging_missing_label_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing --label in non-interactive mode exits 1 with error message."""
        result = _run_provision_staging(
            monkeypatch,
            args=["production"],
        )
        assert result.exit_code != 0
        assert "--label" in result.output.lower() or "label" in result.output.lower()


class TestProvisionStagingErrorHandling:
    """Error scenarios: auth failures, API errors."""

    def test_provision_staging_auth_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API returns 401 shows authentication error."""

        def auth_fail_handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(401, json={"error": "invalid_credentials"})
            return httpx.Response(404)

        result = _run_provision_staging(
            monkeypatch,
            args=["production", "--label", "my-staging"],
            transport_handler=auth_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_provision_staging_api_error_4xx(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Staging creation returns 4xx shows error."""

        def create_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/clone" in url and request.method == "POST":
                return httpx.Response(
                    422,
                    json={"error": "Staging limit reached"},
                    text="Staging limit reached",
                )
            return httpx.Response(404)

        result = _run_provision_staging(
            monkeypatch,
            args=["production", "--label", "my-staging"],
            transport_handler=create_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestProvisionStagingOperationPolling:
    """Tests for operation polling behaviour."""

    def test_provision_staging_polls_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Staging creation polls the operation and succeeds."""
        call_count = {"value": 0}

        def polling_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/clone" in url and request.method == "POST":
                return httpx.Response(200, json=_make_create_staging_response())
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
            result = _run_provision_staging(
                monkeypatch,
                args=["production", "--label", "my-staging"],
                transport_handler=polling_handler,
            )

        assert result.exit_code == 0
        assert call_count["value"] >= 2
