"""Tests for the `cloudways reset-permissions` command."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from conftest import FIXTURES_DIR, make_auth_response, make_patched_client_class

runner = CliRunner()


# ---------------------------------------------------------------------------
# Mock transport handler
# ---------------------------------------------------------------------------


def _reset_perms_transport(request: httpx.Request) -> httpx.Response:
    """Mock transport for reset-permissions endpoint."""
    url = str(request.url)

    if "/oauth/access_token" in url:
        return httpx.Response(200, json=make_auth_response())

    if "/app/manage/reset_permissions" in url and request.method == "POST":
        return httpx.Response(200, json={})

    return httpx.Response(404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_reset_permissions(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_fixture: str = "project-config.yml",
    accounts_fixture: str = "accounts.yml",
    transport_handler=None,
) -> object:
    """Run 'cloudways reset-permissions' with all external deps mocked."""
    config_path = str(FIXTURES_DIR / config_fixture)
    accounts_path = str(FIXTURES_DIR / accounts_fixture)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    handler = transport_handler or _reset_perms_transport
    mock_transport = httpx.MockTransport(handler)

    with patch(
        "cloudways_api.commands.reset_permissions.CloudwaysClient",
        wraps=make_patched_client_class(mock_transport),
    ):
        result = runner.invoke(
            app,
            ["reset-permissions"] + (args or []),
        )

    return result


# ===========================================================================
# Tests
# ===========================================================================


class TestResetPermissionsRegistration:
    """Verify the reset-permissions command is registered."""

    def test_reset_permissions_registered(self) -> None:
        """'cloudways reset-permissions --help' exits 0."""
        result = runner.invoke(app, ["reset-permissions", "--help"])
        assert result.exit_code == 0
        assert "reset" in result.output.lower()


class TestResetPermissionsSuccess:
    """Happy path: API returns 200."""

    def test_reset_permissions_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exits 0 and output contains success message."""
        result = _run_reset_permissions(
            monkeypatch,
            args=["production"],
        )
        assert result.exit_code == 0
        assert "permissions reset" in result.output.lower() or "successfully" in result.output.lower()


class TestResetPermissionsErrors:
    """Error scenarios."""

    def test_reset_permissions_api_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API returns 4xx -> exits 1."""

        def api_fail_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/manage/reset_permissions" in url:
                return httpx.Response(422, json={"error": "Failed"})
            return httpx.Response(404)

        result = _run_reset_permissions(
            monkeypatch,
            args=["production"],
            transport_handler=api_fail_handler,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_reset_permissions_invalid_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-existent environment -> exits 1 with 'not found'."""
        result = _run_reset_permissions(
            monkeypatch,
            args=["nonexistent"],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()
