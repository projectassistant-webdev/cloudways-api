"""Tests for server lifecycle commands and client methods.

Covers stop, start, restart, delete, and rename commands with mocked
Cloudways API responses, plus client method tests for server operations.
"""

import time as _time
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Mock API response helpers ---


def _make_operation_complete_response():
    """Return a completed operation response."""
    return {"operation": {"is_completed": True, "status": "completed"}}


def _make_operation_pending_response():
    """Return a pending (not completed) operation response."""
    return {"operation": {"is_completed": False, "status": "pending"}}


# --- Handler factory ---


def _make_server_handler(
    stop_response=None,
    start_response=None,
    restart_response=None,
    delete_response=None,
    update_response=None,
    operation_response=None,
    stop_error=False,
    start_error=False,
    restart_error=False,
    delete_error=False,
    update_error=False,
    upgrade_php_response=None,
    upgrade_php_error=False,
):
    """Build httpx mock handler for server lifecycle API calls."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/operation/" in url:
            return httpx.Response(
                200, json=operation_response or _make_operation_complete_response()
            )

        # Specific paths BEFORE generic /server/ patterns
        if "/server/stop" in url and method == "POST":
            if stop_error:
                return httpx.Response(422, text="Server cannot be stopped")
            return httpx.Response(200, json=stop_response or {"operation_id": 99001})

        if "/server/start" in url and method == "POST":
            if start_error:
                return httpx.Response(422, text="Server cannot be started")
            return httpx.Response(200, json=start_response or {"operation_id": 99001})

        if "/server/restart" in url and method == "POST":
            if restart_error:
                return httpx.Response(422, text="Server cannot be restarted")
            return httpx.Response(200, json=restart_response or {"operation_id": 99001})

        if "/server/" in url and method == "DELETE":
            if delete_error:
                return httpx.Response(422, text="Server cannot be deleted")
            return httpx.Response(200, json=delete_response or {"operation_id": 99001})

        if "/server/" in url and method == "PUT":
            if update_error:
                return httpx.Response(404, text="Not found")
            return httpx.Response(200, json=update_response or {})

        if "/server/manage/package" in url and method == "POST":
            if upgrade_php_error:
                return httpx.Response(422, text="Package upgrade failed")
            return httpx.Response(
                200, json=upgrade_php_response or {"operation_id": 99001}
            )

        return httpx.Response(404)

    return handler


# --- Env helper ---


# ===================================================================
# Client method tests
# ===================================================================


class TestStopServer:
    """Tests for CloudwaysClient.stop_server()."""

    @pytest.mark.asyncio
    async def test_stop_server_success(self) -> None:
        """POST /server/stop with server_id in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/stop" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={"operation_id": 99001})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.stop_server(server_id=1089270)

        assert result["operation_id"] == 99001
        request = [
            r for r in captured if r.method == "POST" and "/server/stop" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/server/stop" in str(request.url)
        assert request.content.decode() == "server_id=1089270"

    @pytest.mark.asyncio
    async def test_stop_server_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/stop" in str(request.url):
                return httpx.Response(422, text="Server cannot be stopped")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.stop_server(server_id=1089270)


class TestStartServer:
    """Tests for CloudwaysClient.start_server()."""

    @pytest.mark.asyncio
    async def test_start_server_success(self) -> None:
        """POST /server/start with server_id in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/start" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={"operation_id": 99001})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.start_server(server_id=1089270)

        assert result["operation_id"] == 99001
        request = [
            r for r in captured if r.method == "POST" and "/server/start" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/server/start" in str(request.url)
        assert request.content.decode() == "server_id=1089270"

    @pytest.mark.asyncio
    async def test_start_server_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/start" in str(request.url):
                return httpx.Response(422, text="Server cannot be started")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.start_server(server_id=1089270)


class TestRestartServer:
    """Tests for CloudwaysClient.restart_server()."""

    @pytest.mark.asyncio
    async def test_restart_server_success(self) -> None:
        """POST /server/restart with server_id in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/restart" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={"operation_id": 99001})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.restart_server(server_id=1089270)

        assert result["operation_id"] == 99001
        request = [
            r
            for r in captured
            if r.method == "POST" and "/server/restart" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/server/restart" in str(request.url)
        assert request.content.decode() == "server_id=1089270"

    @pytest.mark.asyncio
    async def test_restart_server_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/restart" in str(request.url):
                return httpx.Response(422, text="Server cannot be restarted")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.restart_server(server_id=1089270)


class TestDeleteServer:
    """Tests for CloudwaysClient.delete_server()."""

    @pytest.mark.asyncio
    async def test_delete_server_success(self) -> None:
        """DELETE /server/{id} with server_id in path, empty body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/1089270" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, json={"operation_id": 99001})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_server(server_id=1089270)

        assert result["operation_id"] == 99001
        request = [r for r in captured if r.method == "DELETE"][0]
        assert request.method == "DELETE"
        assert "/server/1089270" in str(request.url)
        assert request.content == b""

    @pytest.mark.asyncio
    async def test_delete_server_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(422, text="Server cannot be deleted")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.delete_server(server_id=1089270)


class TestUpdateServer:
    """Tests for CloudwaysClient.update_server()."""

    @pytest.mark.asyncio
    async def test_update_server_success(self) -> None:
        """PUT /server/{id} with label in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/1089270" in str(request.url) and request.method == "PUT":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_server(
                server_id=1089270, label="my-new-server"
            )

        assert result == {}
        request = [r for r in captured if r.method == "PUT"][0]
        assert request.method == "PUT"
        assert "/server/1089270" in str(request.url)
        assert request.content.decode() == "label=my-new-server"

    @pytest.mark.asyncio
    async def test_update_server_api_error(self) -> None:
        """Raises APIError on 404."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/" in str(request.url) and request.method == "PUT":
                return httpx.Response(404, text="Not found")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_server(server_id=1089270, label="my-new-server")

    @pytest.mark.asyncio
    async def test_update_server_empty_body(self) -> None:
        """Returns {} when PUT returns 200 with empty body."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/" in str(request.url) and request.method == "PUT":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_server(
                server_id=1089270, label="my-new-server"
            )

        assert result == {}


class TestManageServerPackage:
    """Tests for CloudwaysClient.manage_server_package()."""

    @pytest.mark.asyncio
    async def test_manage_server_package_success(self) -> None:
        """POST /server/manage/package with form-encoded body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/package" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={"operation_id": 99001})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.manage_server_package(
                server_id=1089270, package_name="php", package_version="8.2"
            )

        assert result["operation_id"] == 99001
        request = [
            r
            for r in captured
            if r.method == "POST" and "/server/manage/package" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/server/manage/package" in str(request.url)
        body = request.content.decode()
        assert "server_id=1089270" in body
        assert "package_name=php" in body
        assert "package_version=8.2" in body

    @pytest.mark.asyncio
    async def test_manage_server_package_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/package" in str(request.url):
                return httpx.Response(422, text="Package upgrade failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.manage_server_package(
                    server_id=1089270, package_name="php", package_version="8.2"
                )


# ===================================================================
# CLI command tests
# ===================================================================


class TestServerStop:
    """Tests for `cloudways server stop` command."""

    def test_server_stop_success(self, set_env) -> None:
        """Stops server, polls operation, prints success."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "stop"])

        assert result.exit_code == 0, result.output
        assert "Server 1089270 stopped." in result.output

    def test_server_stop_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler = _make_server_handler(stop_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "stop"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_server_stop_timeout(self, set_env) -> None:
        """Operation timeout exits 1 with platform hint."""
        handler = _make_server_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.server.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(app, ["server", "stop", "--timeout", "1"])

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output

    def test_server_stop_no_operation_id(self, set_env) -> None:
        """No operation_id in response skips polling, still succeeds."""
        handler = _make_server_handler(stop_response={})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "stop"])

        assert result.exit_code == 0, result.output
        assert "Server 1089270 stopped." in result.output


class TestServerStart:
    """Tests for `cloudways server start` command."""

    def test_server_start_success(self, set_env) -> None:
        """Starts server, polls operation, prints success."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "start"])

        assert result.exit_code == 0, result.output
        assert "Server 1089270 started." in result.output

    def test_server_start_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler = _make_server_handler(start_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "start"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_server_start_timeout(self, set_env) -> None:
        """Operation timeout exits 1 with platform hint."""
        handler = _make_server_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.server.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(app, ["server", "start", "--timeout", "1"])

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output


class TestServerRestart:
    """Tests for `cloudways server restart` command."""

    def test_server_restart_success(self, set_env) -> None:
        """Restarts server, polls operation, prints success."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "restart"])

        assert result.exit_code == 0, result.output
        assert "Server 1089270 restarted." in result.output

    def test_server_restart_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler = _make_server_handler(restart_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "restart"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_server_restart_timeout(self, set_env) -> None:
        """Operation timeout exits 1 with platform hint."""
        handler = _make_server_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.server.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(app, ["server", "restart", "--timeout", "1"])

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output


class TestServerDelete:
    """Tests for `cloudways server delete` command."""

    def test_server_delete_no_confirm(self, set_env) -> None:
        """Without --confirm, exits 1 with error message."""
        result = runner.invoke(app, ["server", "delete"])

        assert result.exit_code == 1
        assert "--confirm flag required" in result.output

    def test_server_delete_success(self, set_env) -> None:
        """With --confirm, deletes server, polls, prints success."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "delete", "--confirm"])

        assert result.exit_code == 0, result.output
        assert "Server 1089270 deleted." in result.output

    def test_server_delete_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler = _make_server_handler(delete_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "delete", "--confirm"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_server_delete_timeout(self, set_env) -> None:
        """Operation timeout exits 1 with platform hint."""
        handler = _make_server_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.server.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(
                        app,
                        ["server", "delete", "--confirm", "--timeout", "1"],
                    )

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output


class TestServerRename:
    """Tests for `cloudways server rename` command."""

    def test_server_rename_success(self, set_env) -> None:
        """Renames server, prints confirmation."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["server", "rename", "--label", "my-new-server"]
            )

        assert result.exit_code == 0, result.output
        assert "Renamed server 1089270 to 'my-new-server'" in result.output

    def test_server_rename_blank_label(self, set_env) -> None:
        """Blank --label exits with code 1."""
        result = runner.invoke(app, ["server", "rename", "--label", ""])

        assert result.exit_code == 1
        assert "--label cannot be blank" in result.output

    def test_server_rename_whitespace_label(self, set_env) -> None:
        """Whitespace-only --label exits with code 1."""
        result = runner.invoke(app, ["server", "rename", "--label", "   "])

        assert result.exit_code == 1
        assert "--label cannot be blank" in result.output

    def test_server_rename_api_error(self, set_env) -> None:
        """API 404 exits with code 1."""
        handler = _make_server_handler(update_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["server", "rename", "--label", "my-new-server"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 404" in result.output

    def test_server_rename_does_not_poll(self, set_env) -> None:
        """Rename never triggers operation polling."""
        captured_urls = []

        def tracking_handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/server/" in url and request.method == "PUT":
                return httpx.Response(200, json={})
            if "/operation/" in url:
                # If this is reached, polling happened (should not)
                return httpx.Response(404, text="Should not poll")
            return httpx.Response(404)

        transport = httpx.MockTransport(tracking_handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["server", "rename", "--label", "my-new-server"]
            )

        assert result.exit_code == 0
        assert not any("/operation/" in url for url in captured_urls)


class TestServerUpgradePhp:
    """Tests for `cloudways server upgrade-php` command."""

    def test_server_upgrade_php_success(self, set_env) -> None:
        """Upgrades PHP, polls operation, prints success."""
        handler = _make_server_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["server", "upgrade-php", "--version", "8.3"])

        assert result.exit_code == 0, result.output
        assert "PHP upgraded to 8.3 on server 1089270." in result.output

    def test_server_upgrade_php_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler = _make_server_handler(upgrade_php_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "upgrade-php", "--version", "8.3"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_server_upgrade_php_timeout(self, set_env) -> None:
        """Operation timeout exits 1 with platform hint."""
        handler = _make_server_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.server.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(
                        app,
                        ["server", "upgrade-php", "--version", "8.3", "--timeout", "1"],
                    )

        assert result.exit_code == 1
        assert "platform.cloudways.com" in result.output

    def test_server_upgrade_php_blank_version(self, set_env) -> None:
        """Blank --version exits with code 1."""
        result = runner.invoke(app, ["server", "upgrade-php", "--version", ""])

        assert result.exit_code == 1
        assert "--version cannot be blank" in result.output

    def test_server_upgrade_php_no_operation_id(self, set_env) -> None:
        """No operation_id in response skips polling, still succeeds."""
        handler = _make_server_handler(upgrade_php_response={})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.server.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["server", "upgrade-php", "--version", "8.3"])

        assert result.exit_code == 0, result.output
        assert "PHP upgraded to 8.3 on server 1089270." in result.output


# ===================================================================
# CLI registration tests
# ===================================================================


class TestServerRegistration:
    """Tests for server command registration in CLI."""

    def test_server_in_help(self) -> None:
        """server appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "server" in result.output

    def test_server_help(self) -> None:
        """server --help shows all subcommands."""
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "stop" in result.output
        assert "start" in result.output
        assert "restart" in result.output
        assert "delete" in result.output
        assert "rename" in result.output
        assert "upgrade-php" in result.output
