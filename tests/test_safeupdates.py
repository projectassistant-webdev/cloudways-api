"""Tests for SafeUpdate management commands and client methods.

Covers SafeUpdate availability check, listing, status, settings,
schedule, history, and on-demand trigger commands with mocked
Cloudways API responses, plus client method tests for all SafeUpdate
API operations.
"""

import re
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Handler factory ---


def _make_safeupdates_handler(
    # Phase 1 flags:
    available_response=None,
    available_error=False,
    list_response=None,
    list_error=False,
    get_status_response=None,
    get_status_error=False,
    set_status_response=None,
    set_status_error=False,
    get_settings_response=None,
    get_settings_error=False,
    update_settings_response=None,
    update_settings_error=False,
    # Phase 2 flags:
    schedule_response=None,
    schedule_error=False,
    history_response=None,
    history_error=False,
    trigger_response=None,
    trigger_error=False,
):
    """Build httpx mock handler for all SafeUpdate API calls.

    Returns a (handler, captured) tuple where captured is a mutable list
    that accumulates every httpx.Request seen by the handler.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        # 1. Most-specific static paths (POST handlers BEFORE GET catch-alls):
        if "/app/safeupdates/list" in url and method == "GET":
            if list_error:
                return httpx.Response(400, text="List failed")
            return httpx.Response(
                200,
                json=list_response
                or {
                    "data": [
                        {
                            "app_id": 594631,
                            "label": "myapp",
                            "safeupdate_enabled": True,
                        }
                    ]
                },
            )

        if "/app/safeupdates/status" in url and method == "POST":
            if set_status_error:
                return httpx.Response(400, text="Set status failed")
            return httpx.Response(
                200,
                json=set_status_response or {"status": True, "data": {}},
            )

        if "/app/safeupdates/settings" in url and method == "POST":
            if update_settings_error:
                return httpx.Response(400, text="Update settings failed")
            return httpx.Response(
                200,
                json=update_settings_response or {"status": True, "data": {}},
            )

        # 2. Regex-based app_id paths (GET — in specificity order):
        if re.search(r"/app/safeupdates/(\d+)/status", url) and method == "GET":
            if get_status_error:
                return httpx.Response(400, text="Get status failed")
            return httpx.Response(
                200,
                json=get_status_response
                or {
                    "data": {
                        "app_id": 594631,
                        "safeupdate_enabled": True,
                    }
                },
            )

        if re.search(r"/app/safeupdates/(\d+)/settings", url) and method == "GET":
            if get_settings_error:
                return httpx.Response(400, text="Get settings failed")
            return httpx.Response(
                200,
                json=get_settings_response
                or {
                    "data": {
                        "app_id": 594631,
                        "day_of_week": "monday",
                        "time_slot": "02:00",
                    }
                },
            )

        if re.search(r"/app/safeupdates/(\d+)/schedule", url) and method == "GET":
            if schedule_error:
                return httpx.Response(400, text="Schedule failed")
            return httpx.Response(
                200,
                json=schedule_response
                or {
                    "data": {
                        "app_id": 594631,
                        "scheduled_at": "2026-03-16T02:00:00Z",
                    }
                },
            )

        if re.search(r"/app/safeupdates/(\d+)/history", url) and method == "GET":
            if history_error:
                return httpx.Response(400, text="History failed")
            return httpx.Response(
                200,
                json=history_response
                or {
                    "data": [
                        {
                            "updated_at": "2026-03-01T02:00:00Z",
                            "status": "success",
                        }
                    ]
                },
            )

        if re.search(r"/app/safeupdates/(\d+)$", url) and method == "PUT":
            if trigger_error:
                return httpx.Response(400, text="Trigger failed")
            return httpx.Response(
                200,
                json=trigger_response or {"status": True, "data": {}},
            )

        # 3. Catch-all GET for /app/safeupdates (check + available):
        if "/app/safeupdates" in url and method == "GET":
            if available_error:
                return httpx.Response(400, text="Available check failed")
            return httpx.Response(
                200,
                json=available_response
                or {
                    "data": {
                        "server_id": 36780,
                        "app_id": 594631,
                        "updates_available": True,
                    }
                },
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests -- Phase 1
# ===================================================================


class TestGetSafeupdatesAvailable:
    """Tests for CloudwaysClient.get_safeupdates_available()."""

    @pytest.mark.asyncio
    async def test_get_safeupdates_available_success(self) -> None:
        """GET /app/safeupdates returns dict with available update info."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_safeupdates_available(
                server_id=36780, app_id=594631
            )

        assert isinstance(result, dict)
        request = [r for r in captured if "/app/safeupdates" in str(r.url) and r.method == "GET"][-1]
        assert request.method == "GET"
        assert "/app/safeupdates" in str(request.url)
        assert "server_id=36780" in str(request.url)
        assert "app_id=594631" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_safeupdates_available_error(self) -> None:
        """GET /app/safeupdates error raises APIError."""
        handler, captured = _make_safeupdates_handler(available_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_safeupdates_available(
                    server_id=36780, app_id=594631
                )
            assert "400" in str(exc_info.value)


class TestListSafeupdatesApps:
    """Tests for CloudwaysClient.list_safeupdates_apps()."""

    @pytest.mark.asyncio
    async def test_list_safeupdates_apps_success(self) -> None:
        """GET /app/safeupdates/list returns dict with app list."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.list_safeupdates_apps(server_id=36780)

        assert isinstance(result, dict)
        request = [r for r in captured if "/app/safeupdates/list" in str(r.url)][-1]
        assert request.method == "GET"
        assert "/app/safeupdates/list" in str(request.url)
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_list_safeupdates_apps_error(self) -> None:
        """GET /app/safeupdates/list error raises APIError."""
        handler, captured = _make_safeupdates_handler(list_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.list_safeupdates_apps(server_id=36780)
            assert "400" in str(exc_info.value)


class TestGetSafeupdateStatus:
    """Tests for CloudwaysClient.get_safeupdate_status()."""

    @pytest.mark.asyncio
    async def test_get_safeupdate_status_success(self) -> None:
        """GET /app/safeupdates/{app_id}/status returns dict."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_safeupdate_status(594631, server_id=36780)

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/\d+/status", str(r.url))
        ][-1]
        assert request.method == "GET"
        assert "/app/safeupdates/594631/status" in str(request.url)
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_safeupdate_status_error(self) -> None:
        """GET /app/safeupdates/{app_id}/status error raises APIError."""
        handler, captured = _make_safeupdates_handler(get_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_safeupdate_status(594631, server_id=36780)
            assert "400" in str(exc_info.value)


class TestSetSafeupdateStatus:
    """Tests for CloudwaysClient.set_safeupdate_status()."""

    @pytest.mark.asyncio
    async def test_set_safeupdate_status_enable_success(self) -> None:
        """POST /app/safeupdates/status with status=1 to enable."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.set_safeupdate_status(
                server_id=36780, app_id=594631, status=1
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if "/app/safeupdates/status" in str(r.url) and r.method == "POST"
        ][-1]
        assert request.method == "POST"
        assert "/app/safeupdates/status" in str(request.url)
        body = request.content.decode()
        assert "server_id=36780" in body
        assert "app_id=594631" in body
        assert "status=1" in body

    @pytest.mark.asyncio
    async def test_set_safeupdate_status_disable_success(self) -> None:
        """POST /app/safeupdates/status with status=0 to disable."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.set_safeupdate_status(
                server_id=36780, app_id=594631, status=0
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if "/app/safeupdates/status" in str(r.url) and r.method == "POST"
        ][-1]
        body = request.content.decode()
        assert "server_id=36780" in body
        assert "app_id=594631" in body
        assert "status=0" in body

    @pytest.mark.asyncio
    async def test_set_safeupdate_status_error(self) -> None:
        """POST /app/safeupdates/status error raises APIError."""
        handler, captured = _make_safeupdates_handler(set_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.set_safeupdate_status(
                    server_id=36780, app_id=594631, status=1
                )
            assert "400" in str(exc_info.value)


class TestGetSafeupdateSettings:
    """Tests for CloudwaysClient.get_safeupdate_settings()."""

    @pytest.mark.asyncio
    async def test_get_safeupdate_settings_success(self) -> None:
        """GET /app/safeupdates/{app_id}/settings returns dict."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_safeupdate_settings(594631, server_id=36780)

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/\d+/settings", str(r.url))
        ][-1]
        assert request.method == "GET"
        assert "/app/safeupdates/594631/settings" in str(request.url)
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_safeupdate_settings_error(self) -> None:
        """GET /app/safeupdates/{app_id}/settings error raises APIError."""
        handler, captured = _make_safeupdates_handler(get_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_safeupdate_settings(594631, server_id=36780)
            assert "400" in str(exc_info.value)


class TestUpdateSafeupdateSettings:
    """Tests for CloudwaysClient.update_safeupdate_settings()."""

    @pytest.mark.asyncio
    async def test_update_safeupdate_settings_success(self) -> None:
        """POST /app/safeupdates/settings with all 4 fields."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_safeupdate_settings(
                server_id=36780,
                app_id=594631,
                day_of_week="monday",
                time_slot="02:00",
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if "/app/safeupdates/settings" in str(r.url) and r.method == "POST"
        ][-1]
        assert request.method == "POST"
        body = request.content.decode()
        assert "server_id=36780" in body
        assert "app_id=594631" in body
        assert "day_of_week=monday" in body
        assert "time_slot" in body

    @pytest.mark.asyncio
    async def test_update_safeupdate_settings_error(self) -> None:
        """POST /app/safeupdates/settings error raises APIError."""
        handler, captured = _make_safeupdates_handler(update_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.update_safeupdate_settings(
                    server_id=36780,
                    app_id=594631,
                    day_of_week="monday",
                    time_slot="02:00",
                )
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI command tests -- Phase 1
# ===================================================================


class TestSafeupdatesCheckCli:
    """Tests for `cloudways safeupdates check` CLI command."""

    def test_safeupdates_check_success(self, set_env) -> None:
        """safeupdates check exits 0 and shows update info."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "check", "--server-id", "36780", "--app-id", "594631"],
            )

        assert result.exit_code == 0
        assert "updates_available" in result.output

    def test_safeupdates_check_error(self, set_env) -> None:
        """safeupdates check API error exits 1."""
        handler, captured = _make_safeupdates_handler(available_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "check", "--server-id", "36780", "--app-id", "594631"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesListCli:
    """Tests for `cloudways safeupdates list` CLI command."""

    def test_safeupdates_list_success(self, set_env) -> None:
        """safeupdates list exits 0 and shows app list."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "list", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        assert "safeupdate_enabled" in result.output

    def test_safeupdates_list_error(self, set_env) -> None:
        """safeupdates list API error exits 1."""
        handler, captured = _make_safeupdates_handler(list_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "list", "--server-id", "36780"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesStatusCli:
    """Tests for `cloudways safeupdates status` CLI command."""

    def test_safeupdates_status_success(self, set_env) -> None:
        """safeupdates status exits 0 and shows status info."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "status", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        assert "safeupdate_enabled" in result.output

    def test_safeupdates_status_error(self, set_env) -> None:
        """safeupdates status API error exits 1."""
        handler, captured = _make_safeupdates_handler(get_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "status", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesEnableCli:
    """Tests for `cloudways safeupdates enable` CLI command."""

    def test_safeupdates_enable_success(self, set_env) -> None:
        """safeupdates enable exits 0 with success message."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "enable", "--server-id", "36780", "--app-id", "594631"],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate enabled." in result.output
        # Verify POST body contains status=1
        request = [
            r for r in captured
            if "/app/safeupdates/status" in str(r.url) and r.method == "POST"
        ][-1]
        assert "status=1" in request.content.decode()

    def test_safeupdates_enable_error(self, set_env) -> None:
        """safeupdates enable API error exits 1."""
        handler, captured = _make_safeupdates_handler(set_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "enable", "--server-id", "36780", "--app-id", "594631"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesDisableCli:
    """Tests for `cloudways safeupdates disable` CLI command."""

    def test_safeupdates_disable_success(self, set_env) -> None:
        """safeupdates disable exits 0 with success message."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "disable",
                    "--server-id",
                    "36780",
                    "--app-id",
                    "594631",
                ],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate disabled." in result.output
        # Verify POST body contains status=0
        request = [
            r for r in captured
            if "/app/safeupdates/status" in str(r.url) and r.method == "POST"
        ][-1]
        assert "status=0" in request.content.decode()

    def test_safeupdates_disable_error(self, set_env) -> None:
        """safeupdates disable API error exits 1."""
        handler, captured = _make_safeupdates_handler(set_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "disable",
                    "--server-id",
                    "36780",
                    "--app-id",
                    "594631",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesSettingsCli:
    """Tests for `cloudways safeupdates settings get|set` CLI commands."""

    def test_settings_get_success(self, set_env) -> None:
        """safeupdates settings get exits 0 and shows settings."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "settings", "get", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        assert "day_of_week" in result.output

    def test_settings_get_error(self, set_env) -> None:
        """safeupdates settings get API error exits 1."""
        handler, captured = _make_safeupdates_handler(get_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "settings", "get", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_settings_set_success(self, set_env) -> None:
        """safeupdates settings set exits 0 with success message."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "settings",
                    "set",
                    "--server-id",
                    "36780",
                    "--app-id",
                    "594631",
                    "--day",
                    "monday",
                    "--time",
                    "02:00",
                ],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate settings updated." in result.output
        # Verify POST body
        request = [
            r for r in captured
            if "/app/safeupdates/settings" in str(r.url) and r.method == "POST"
        ][-1]
        body = request.content.decode()
        assert "day_of_week=monday" in body
        assert "time_slot" in body

    def test_settings_set_error(self, set_env) -> None:
        """safeupdates settings set API error exits 1."""
        handler, captured = _make_safeupdates_handler(update_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "settings",
                    "set",
                    "--server-id",
                    "36780",
                    "--app-id",
                    "594631",
                    "--day",
                    "monday",
                    "--time",
                    "02:00",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


# ===================================================================
# Registration test
# ===================================================================


# ===================================================================
# Client method tests -- Phase 2
# ===================================================================


class TestGetSafeupdateSchedule:
    """Tests for CloudwaysClient.get_safeupdate_schedule()."""

    @pytest.mark.asyncio
    async def test_get_safeupdate_schedule_success(self) -> None:
        """GET /app/safeupdates/{app_id}/schedule returns dict."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_safeupdate_schedule(594631, server_id=36780)

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/\d+/schedule", str(r.url))
        ][-1]
        assert request.method == "GET"
        assert "/app/safeupdates/594631/schedule" in str(request.url)
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_safeupdate_schedule_error(self) -> None:
        """GET /app/safeupdates/{app_id}/schedule error raises APIError."""
        handler, captured = _make_safeupdates_handler(schedule_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_safeupdate_schedule(594631, server_id=36780)
            assert "400" in str(exc_info.value)


class TestGetSafeupdateHistory:
    """Tests for CloudwaysClient.get_safeupdate_history()."""

    @pytest.mark.asyncio
    async def test_get_safeupdate_history_success(self) -> None:
        """GET /app/safeupdates/{app_id}/history returns dict."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_safeupdate_history(594631, server_id=36780)

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/\d+/history", str(r.url))
        ][-1]
        assert request.method == "GET"
        assert "/app/safeupdates/594631/history" in str(request.url)
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_safeupdate_history_error(self) -> None:
        """GET /app/safeupdates/{app_id}/history error raises APIError."""
        handler, captured = _make_safeupdates_handler(history_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_safeupdate_history(594631, server_id=36780)
            assert "400" in str(exc_info.value)


class TestTriggerSafeupdate:
    """Tests for CloudwaysClient.trigger_safeupdate()."""

    @pytest.mark.asyncio
    async def test_trigger_safeupdate_core_only(self) -> None:
        """PUT /app/safeupdates/{app_id} with core=True sends core=1."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_safeupdate(
                594631, server_id=36780, core=True
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "server_id" in body
        assert "core=1" in body
        assert "plugins" not in body
        assert "themes" not in body

    @pytest.mark.asyncio
    async def test_trigger_safeupdate_plugins(self) -> None:
        """PUT /app/safeupdates/{app_id} with plugins sends repeated keys."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_safeupdate(
                594631, server_id=36780, plugins=["hello-dolly", "akismet"]
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "server_id=36780" in body
        assert "plugins=hello-dolly" in body
        assert "plugins=akismet" in body
        assert "core" not in body

    @pytest.mark.asyncio
    async def test_trigger_safeupdate_themes(self) -> None:
        """PUT /app/safeupdates/{app_id} with themes sends repeated keys."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_safeupdate(
                594631, server_id=36780, themes=["twentytwentyfour"]
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "themes=twentytwentyfour" in body
        assert "core" not in body
        assert "plugins" not in body

    @pytest.mark.asyncio
    async def test_trigger_safeupdate_all_empty(self) -> None:
        """PUT /app/safeupdates/{app_id} with no flags sends only server_id."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_safeupdate(594631, server_id=36780)

        assert isinstance(result, dict)
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "server_id=36780" in body
        assert "core" not in body
        assert "plugins" not in body
        assert "themes" not in body

    @pytest.mark.asyncio
    async def test_trigger_safeupdate_error(self) -> None:
        """PUT /app/safeupdates/{app_id} error raises APIError."""
        handler, captured = _make_safeupdates_handler(trigger_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.trigger_safeupdate(
                    594631, server_id=36780, core=True
                )
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI command tests -- Phase 2
# ===================================================================


class TestSafeupdatesScheduleCli:
    """Tests for `cloudways safeupdates schedule` CLI command."""

    def test_safeupdates_schedule_success(self, set_env) -> None:
        """safeupdates schedule exits 0 and shows schedule info."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "schedule", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        assert "scheduled_at" in result.output

    def test_safeupdates_schedule_error(self, set_env) -> None:
        """safeupdates schedule API error exits 1."""
        handler, captured = _make_safeupdates_handler(schedule_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "schedule", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesHistoryCli:
    """Tests for `cloudways safeupdates history` CLI command."""

    def test_safeupdates_history_success(self, set_env) -> None:
        """safeupdates history exits 0 and shows history info."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "history", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        assert "updated_at" in result.output

    def test_safeupdates_history_error(self, set_env) -> None:
        """safeupdates history API error exits 1."""
        handler, captured = _make_safeupdates_handler(history_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "history", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestSafeupdatesRunCli:
    """Tests for `cloudways safeupdates run` CLI command."""

    def test_safeupdates_run_core_only(self, set_env) -> None:
        """safeupdates run --core exits 0 with core=1 in body."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "run",
                    "594631",
                    "--server-id",
                    "36780",
                    "--core",
                ],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate triggered." in result.output
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "core=1" in body

    def test_safeupdates_run_with_plugins(self, set_env) -> None:
        """safeupdates run --plugin sends repeated-key plugins."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "run",
                    "594631",
                    "--server-id",
                    "36780",
                    "--plugin",
                    "hello-dolly",
                    "--plugin",
                    "akismet",
                ],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate triggered." in result.output
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "plugins=hello-dolly" in body
        assert "plugins=akismet" in body

    def test_safeupdates_run_with_themes(self, set_env) -> None:
        """safeupdates run --theme sends repeated-key themes."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "run",
                    "594631",
                    "--server-id",
                    "36780",
                    "--theme",
                    "twentytwentyfour",
                    "--theme",
                    "twentytwentyfive",
                ],
            )

        assert result.exit_code == 0
        assert "Success: SafeUpdate triggered." in result.output
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "themes=twentytwentyfour" in body
        assert "themes=twentytwentyfive" in body
        assert "plugins" not in body

    def test_safeupdates_run_no_flags(self, set_env) -> None:
        """safeupdates run with no flags sends only server_id."""
        handler, captured = _make_safeupdates_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["safeupdates", "run", "594631", "--server-id", "36780"],
            )

        assert result.exit_code == 0
        request = [
            r for r in captured
            if re.search(r"/app/safeupdates/594631", str(r.url))
            and r.method == "PUT"
        ][-1]
        body = request.content.decode()
        assert "server_id" in body
        assert "core" not in body
        assert "plugins" not in body
        assert "themes" not in body

    def test_safeupdates_run_error(self, set_env) -> None:
        """safeupdates run API error exits 1."""
        handler, captured = _make_safeupdates_handler(trigger_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.safeupdates.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "safeupdates",
                    "run",
                    "594631",
                    "--server-id",
                    "36780",
                    "--core",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


# ===================================================================
# Registration test
# ===================================================================


class TestSafeupdatesRegistration:
    """Tests for safeupdates group CLI registration."""

    def test_safeupdates_in_main_help(self) -> None:
        """safeupdates group appears in main --help output."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "safeupdates" in result.output

    def test_safeupdates_subcommands_visible(self) -> None:
        """All safeupdates subcommands visible in --help."""
        result = runner.invoke(app, ["safeupdates", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "check",
            "list",
            "status",
            "enable",
            "disable",
            "schedule",
            "history",
            "run",
            "settings",
        ]:
            assert cmd in result.output
