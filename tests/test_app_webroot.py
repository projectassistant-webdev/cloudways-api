"""Tests for app set-webroot / app get-webroot commands and update_webroot client method.

Covers:
- CloudwaysClient.update_webroot() method (3 tests)
- set-webroot command (5 tests)
- get-webroot command (4 tests)
- CLI registration (3 tests)
"""

import os
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from tests.conftest import make_auth_response, make_patched_client_class

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# Mock response factories
# ---------------------------------------------------------------------------


def _make_server_response(webroot: str = "public_html") -> dict:
    """Build a server list response with webroot info.

    Matches the real Cloudways API shape where ``application`` is a
    string (e.g. ``"wordpress"``) and ``webroot`` is a top-level field
    on each app object.
    """
    return {
        "servers": [
            {
                "id": "999999",
                "label": "example-prod",
                "status": "running",
                "public_ip": "1.2.3.4",
                "apps": [
                    {
                        "id": "1234567",
                        "label": "production-app",
                        "application": "wordpress",
                        "webroot": webroot,
                    },
                    {
                        "id": "7654321",
                        "label": "staging-app",
                        "application": "wordpress",
                        "webroot": "public_html",
                    },
                ],
            },
        ]
    }


def _make_webroot_handler(
    *,
    update_success: bool = True,
    server_response: dict | None = None,
) -> callable:
    """Build httpx mock handler for webroot API calls."""
    if server_response is None:
        server_response = _make_server_response()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/app/manage/webroot" in url and method == "POST":
            if not update_success:
                return httpx.Response(
                    422, text="Failed to update webroot"
                )
            return httpx.Response(200, content=b"")

        if "/server" in url and method == "GET":
            return httpx.Response(200, json=server_response)

        return httpx.Response(404)

    return handler


# ---------------------------------------------------------------------------
# Client method tests: update_webroot()
# ---------------------------------------------------------------------------


class TestUpdateWebroot:
    """Tests for CloudwaysClient.update_webroot()."""

    @pytest.mark.asyncio
    async def test_update_webroot_success(self) -> None:
        """Sends POST /app/manage/webroot with correct parameters."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/manage/webroot" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_webroot(
                server_id=999999,
                app_id=1234567,
                webroot="public_html/current/web",
            )

        assert result == {}
        post_reqs = [
            r
            for r in captured
            if r.method == "POST" and "/app/manage/webroot" in str(r.url)
        ]
        assert len(post_reqs) == 1
        # Verify payload
        body = post_reqs[0].content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "webroot=public_html%2Fcurrent%2Fweb" in body

    @pytest.mark.asyncio
    async def test_update_webroot_api_error(self) -> None:
        """Raises APIError on API failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/manage/webroot" in str(request.url):
                return httpx.Response(422, text="Failed to update webroot")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_webroot(
                    server_id=999999,
                    app_id=1234567,
                    webroot="public_html/current/web",
                )

    @pytest.mark.asyncio
    async def test_update_webroot_empty_response(self) -> None:
        """Returns {} when POST returns 200 with empty body."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/manage/webroot" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_webroot(
                server_id=999999,
                app_id=1234567,
                webroot="public_html/current/web",
            )

        assert result == {}


# ---------------------------------------------------------------------------
# CLI command tests: app set-webroot
# ---------------------------------------------------------------------------


class TestSetWebroot:
    """Tests for `cloudways app set-webroot` command."""

    def test_set_webroot_default_path(self, set_env) -> None:
        """AC-P3-1/2/4: Updates webroot with default path, exits 0."""
        handler = _make_webroot_handler(update_success=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "set-webroot", "production"])

        assert result.exit_code == 0, result.output
        assert "public_html/current/web" in result.output
        assert "production" in result.output

    def test_set_webroot_custom_path(self, set_env) -> None:
        """AC-P3-3: Accepts custom webroot path via --path."""
        handler = _make_webroot_handler(update_success=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["app", "set-webroot", "production", "--path", "public_html"],
            )

        assert result.exit_code == 0, result.output
        assert "public_html" in result.output

    def test_set_webroot_api_error(self, set_env) -> None:
        """AC-P3-5: API failure exits with code 1."""
        handler = _make_webroot_handler(update_success=False)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "set-webroot", "production"])

        assert result.exit_code == 1

    def test_set_webroot_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(app, ["app", "set-webroot", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_set_webroot_confirmation_message(self, set_env) -> None:
        """AC-P3-4: Displays confirmation message on success."""
        handler = _make_webroot_handler(update_success=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "set-webroot", "production"])

        assert result.exit_code == 0
        assert "Webroot updated" in result.output


# ---------------------------------------------------------------------------
# CLI command tests: app get-webroot
# ---------------------------------------------------------------------------


class TestGetWebroot:
    """Tests for `cloudways app get-webroot` command."""

    def test_get_webroot_success(self, set_env) -> None:
        """AC-P3-6/7: Retrieves and displays current webroot, exits 0."""
        server_resp = _make_server_response(webroot="public_html/current/web")
        handler = _make_webroot_handler(server_response=server_resp)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "get-webroot", "production"])

        assert result.exit_code == 0, result.output
        assert "public_html/current/web" in result.output
        assert "production" in result.output

    def test_get_webroot_app_not_found(self, set_env) -> None:
        """AC-P3-8: App not found in server info exits with code 1."""
        # Server response with no matching app_id
        server_resp = {
            "servers": [
                {
                    "id": "9999999",
                    "label": "other-server",
                    "status": "running",
                    "public_ip": "10.0.0.1",
                    "apps": [],
                }
            ]
        }
        handler = _make_webroot_handler(server_response=server_resp)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "get-webroot", "production"])

        assert result.exit_code == 1

    def test_get_webroot_api_error(self, set_env) -> None:
        """AC-P3-8: API error exits with code 1."""

        def error_handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server" in url:
                return httpx.Response(400, text="Bad Request")
            return httpx.Response(404)

        transport = httpx.MockTransport(error_handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.app_webroot.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["app", "get-webroot", "production"])

        assert result.exit_code == 1

    def test_get_webroot_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(app, ["app", "get-webroot", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# CLI registration tests
# ---------------------------------------------------------------------------


class TestAppWebrootRegistration:
    """Tests for app command group registration in CLI."""

    def test_app_group_in_help(self) -> None:
        """app appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "app" in result.output

    def test_app_set_webroot_help(self) -> None:
        """app set-webroot --help shows usage info."""
        result = runner.invoke(app, ["app", "set-webroot", "--help"])
        assert result.exit_code == 0
        assert "--path" in result.output

    def test_app_get_webroot_help(self) -> None:
        """app get-webroot --help shows usage info."""
        result = runner.invoke(app, ["app", "get-webroot", "--help"])
        assert result.exit_code == 0
        assert "ENVIRONMENT" in result.output
