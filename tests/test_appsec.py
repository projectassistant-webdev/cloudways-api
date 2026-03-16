"""Tests for app security suite (Imunify360) commands and client methods.

Covers security status, scans, scan polling, events, incidents,
file operations, lifecycle management, and IP allow/blocklist
commands with mocked Cloudways API responses.
"""

import asyncio
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


def _make_appsec_handler(
    # Phase 1 flags
    status_response=None,
    status_error=False,
    list_scans_response=None,
    list_scans_error=False,
    initiate_scan_response=None,
    initiate_scan_error=False,
    scan_status_response=None,
    scan_status_error=False,
    scan_detail_response=None,
    scan_detail_error=False,
    scan_detail_not_found=False,
    events_response=None,
    events_error=False,
    incidents_response=None,
    incidents_error=False,
    # Phase 2 flags
    list_files_response=None,
    list_files_error=False,
    restore_response=None,
    restore_error=False,
    cleaned_diff_response=None,
    cleaned_diff_error=False,
    # Phase 3 flags
    activate_response=None,
    activate_error=False,
    deactivate_response=None,
    deactivate_error=False,
    ip_add_response=None,
    ip_add_error=False,
    ip_remove_response=None,
    ip_remove_error=False,
    # Task polling
    task_response=None,
):
    """Build httpx mock handler for all appsec API calls.

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

        # Task poll for --wait scan (must come before /app/security/ routes)
        if re.search(r"/operation/task/", url):
            return httpx.Response(
                200,
                json=task_response
                or {"is_completed": True, "data": {"scan": "done"}},
            )

        # 1. scans/status BEFORE scans/{id} and bare /scans
        if re.search(r"/app/security/(\d+)/scans/status", url):
            if scan_status_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=scan_status_response
                or {"status": "completed", "data": {"progress": 100}},
            )

        # 2. scans/{id} (specific scan detail) BEFORE bare /scans
        if re.search(r"/app/security/(\d+)/scans/\d+", url):
            if scan_detail_not_found:
                return httpx.Response(
                    404, text="API request failed with status 404"
                )
            if scan_detail_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=scan_detail_response
                or {"scan_id": 42, "status": "completed"},
            )

        # 3. /files/restore BEFORE bare /files
        if re.search(r"/app/security/(\d+)/files/restore", url):
            if restore_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=restore_response or {"status": True},
            )

        # 4. /files/cleaned-diff BEFORE bare /files
        if re.search(r"/app/security/(\d+)/files/cleaned-diff", url):
            if cleaned_diff_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=cleaned_diff_response or {"diff": "clean"},
            )

        # 5. bare /files
        if re.search(r"/app/security/(\d+)/files(\?|$)", url):
            if list_files_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=list_files_response
                or {"files": [], "total": 0},
            )

        # 6. /activate
        if re.search(r"/app/security/(\d+)/activate", url):
            if activate_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=activate_response or {"status": True},
            )

        # 7. /deactivate (PATCH method)
        if re.search(r"/app/security/(\d+)/deactivate", url) and method == "PATCH":
            if deactivate_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=deactivate_response or {"status": True},
            )

        # 8. /incidents
        if re.search(r"/app/security/(\d+)/incidents", url):
            if incidents_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=incidents_response or {"incidents": []},
            )

        # 9. /events
        if re.search(r"/app/security/(\d+)/events", url):
            if events_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=events_response or {"events": []},
            )

        # 10. /ips (dispatch on method: PUT vs DELETE)
        if re.search(r"/app/security/(\d+)/ips", url):
            if method == "PUT":
                if ip_add_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=ip_add_response or {"status": True},
                )
            elif method == "DELETE":
                if ip_remove_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=ip_remove_response or {"status": True},
                )

        # 11. bare /scans (list + initiate -- both GET and POST on same path)
        if re.search(r"/app/security/(\d+)/scans", url):
            if method == "POST":
                if initiate_scan_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=initiate_scan_response
                    or {"status": True, "scan_id": 99},
                )
            else:
                if list_scans_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=list_scans_response
                    or {"scans": [], "total": 0},
                )

        # 12. /status LAST (most ambiguous -- substring of /scans/status)
        if re.search(r"/app/security/(\d+)/status", url):
            if status_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=status_response
                or {"is_active": True, "plan": "pro"},
            )

        return httpx.Response(404, text="Not found")

    return handler, captured


# --- Env helper ---


# ===================================================================
# Phase 1 Tests -- Status, Scans, Events, Incidents
# ===================================================================


class TestGetAppSecurityStatus:
    """Tests for get_app_security_status client method and status CLI command."""

    def test_status_success(self, set_env):
        """GET /app/security/{app_id}/status returns security status dict."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_app_security_status(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        assert result["is_active"] is True
        url = str(captured[-1].url)
        assert "/app/security/1234567/status" in url
        assert "server_id=" in url

    def test_status_error(self, set_env):
        """GET /app/security/{app_id}/status error raises APIError."""
        handler, captured = _make_appsec_handler(status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_app_security_status",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestListSecurityScans:
    """Tests for list_security_scans client method and scans CLI command."""

    def test_list_scans_success(self, set_env):
        """GET /app/security/{app_id}/scans returns scans with pagination params."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.list_security_scans(
                    app_id=1234567,
                    server_id=999999,
                    offset="5",
                    limit="10",
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "server_id=" in url
        assert "offset=" in url
        assert "limit=" in url

    def test_list_scans_error(self, set_env):
        """GET /app/security/{app_id}/scans error raises APIError."""
        handler, captured = _make_appsec_handler(list_scans_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "list_security_scans",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestInitiateSecurityScan:
    """Tests for initiate_security_scan and scan CLI command (with --wait)."""

    def test_initiate_scan_success_no_wait(self, set_env):
        """POST /app/security/{app_id}/scans returns scan result without wait."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.initiate_security_scan(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        assert captured[-1].method == "POST"
        body = captured[-1].content.decode()
        assert "server_id=" in body
        assert "app_id=" in body

    def test_initiate_scan_success_wait(self, set_env):
        """scan --wait with task_id delegates to wait_for_task, exits 0."""
        handler, captured = _make_appsec_handler(
            initiate_scan_response={"task_id": "test-task-uuid"},
            task_response={"is_completed": True, "data": {"scan": "done"}},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with (
            patch(
                "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan", "production", "--wait"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0

    def test_initiate_scan_success_wait_fallback(self, set_env):
        """scan --wait without task_id polls scan-status, exits 0."""
        handler, captured = _make_appsec_handler(
            initiate_scan_response={"status": "pending"},
            scan_status_response={
                "status": "completed",
                "data": {"progress": 100},
            },
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with (
            patch(
                "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan", "production", "--wait"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0

    def test_initiate_scan_error(self, set_env):
        """POST /app/security/{app_id}/scans error raises APIError."""
        handler, captured = _make_appsec_handler(initiate_scan_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "initiate_security_scan",
                    app_id=1234567,
                    server_id=999999,
                )
            )

    def test_scan_wait_failed_status(self, set_env):
        """scan --wait exits 1 when scan status returns 'failed'."""
        handler, captured = _make_appsec_handler(
            initiate_scan_response={"status": "pending"},
            scan_status_response={"status": "failed", "data": {"progress": 0}},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with (
            patch(
                "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan", "production", "--wait"],
            )

        assert result.exit_code == 1
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    def test_scan_wait_error_status(self, set_env):
        """scan --wait exits 1 when scan status returns 'error'."""
        handler, captured = _make_appsec_handler(
            initiate_scan_response={"status": "pending"},
            scan_status_response={"status": "error", "data": {"progress": 0}},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with (
            patch(
                "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan", "production", "--wait"],
            )

        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_scan_wait_timeout(self, set_env):
        """scan --wait exits 1 when scan never completes (timeout)."""
        handler, captured = _make_appsec_handler(
            initiate_scan_response={"status": "pending"},
            scan_status_response={
                "status": "scanning",
                "data": {"progress": 50},
            },
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with (
            patch(
                "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan", "production", "--wait"],
            )

        assert result.exit_code == 1
        assert "did not complete" in result.output.lower()


class TestGetSecurityScanStatus:
    """Tests for get_security_scan_status client method and scan-status CLI."""

    def test_scan_status_success(self, set_env):
        """GET /app/security/{app_id}/scans/status returns scan status dict."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_security_scan_status(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/scans/status" in url
        assert "server_id=" in url

    def test_scan_status_error(self, set_env):
        """GET /app/security/{app_id}/scans/status error raises APIError."""
        handler, captured = _make_appsec_handler(scan_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_security_scan_status",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestGetSecurityScanDetail:
    """Tests for get_security_scan_detail client method and scan-detail CLI."""

    def test_scan_detail_success(self, set_env):
        """GET /app/security/{app_id}/scans/{scan_id} returns scan detail."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_security_scan_detail(
                    app_id=1234567, scan_id=42, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/scans/42" in url
        assert "server_id=" in url

    def test_scan_detail_not_found(self, set_env):
        """GET /app/security/{app_id}/scans/{scan_id} 404 raises APIError."""
        handler, captured = _make_appsec_handler(scan_detail_not_found=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_security_scan_detail",
                    app_id=1234567,
                    scan_id=9999,
                    server_id=999999,
                )
            )


class TestGetSecurityEvents:
    """Tests for get_security_events client method and events CLI command."""

    def test_events_success(self, set_env):
        """GET /app/security/{app_id}/events returns events dict."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_security_events(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/events" in url
        assert "server_id=" in url

    def test_events_error(self, set_env):
        """GET /app/security/{app_id}/events error raises APIError."""
        handler, captured = _make_appsec_handler(events_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_security_events",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestGetSecurityIncidents:
    """Tests for get_security_incidents client method and incidents CLI command."""

    def test_incidents_success(self, set_env):
        """GET /app/security/{app_id}/incidents returns incidents dict."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_security_incidents(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/incidents" in url
        assert "server_id=" in url

    def test_incidents_error(self, set_env):
        """GET /app/security/{app_id}/incidents error raises APIError."""
        handler, captured = _make_appsec_handler(incidents_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_security_incidents",
                    app_id=1234567,
                    server_id=999999,
                )
            )


# --- Helper for async client calls ---


async def _async_client_call(PatchedClient, method_name, **kwargs):
    """Helper to call an async client method by name."""
    async with PatchedClient("test@example.com", "key") as client:
        method = getattr(client, method_name)
        return await method(**kwargs)


# ===================================================================
# Phase 2 Tests -- File Operations
# ===================================================================


class TestListSecurityFiles:
    """Tests for list_security_files client method and files CLI command."""

    def test_list_files_success(self, set_env):
        """GET /app/security/{app_id}/files returns files with pagination params."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.list_security_files(
                    app_id=1234567,
                    server_id=999999,
                    offset="5",
                    limit="10",
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/app/security/1234567/files" in url
        assert "server_id=" in url
        assert "offset=" in url
        assert "limit=" in url

    def test_list_files_error(self, set_env):
        """GET /app/security/{app_id}/files error raises APIError."""
        handler, captured = _make_appsec_handler(list_files_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "list_security_files",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestRestoreSecurityFiles:
    """Tests for restore_security_files client method and restore CLI command."""

    def test_restore_success(self, set_env):
        """POST /app/security/{app_id}/files/restore sends all body fields (CLI)."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "appsec",
                    "restore",
                    "production",
                    "--db",
                    "mydb",
                    "--files",
                    "wp-config.php,index.php",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        body = captured[-1].content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "db=" in body
        assert "files=" in body

    def test_restore_error(self, set_env):
        """POST /app/security/{app_id}/files/restore error raises APIError."""
        handler, captured = _make_appsec_handler(restore_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "restore_security_files",
                    app_id=1234567,
                    server_id=999999,
                    db="mydb",
                    files="wp-config.php",
                )
            )

    def test_restore_missing_args(self, set_env):
        """CLI restore without --db and --files exits non-zero."""
        result = runner.invoke(app, ["appsec", "restore", "production"])
        assert result.exit_code != 0


class TestGetCleanedDiff:
    """Tests for get_cleaned_diff client method and cleaned-diff CLI command."""

    def test_cleaned_diff_success(self, set_env):
        """GET /app/security/{app_id}/files/cleaned-diff returns diff dict."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_cleaned_diff(
                    app_id=1234567, server_id=999999
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        assert result["diff"] == "clean"
        url = str(captured[-1].url)
        assert "/files/cleaned-diff" in url
        assert "server_id=" in url

    def test_cleaned_diff_error(self, set_env):
        """GET /app/security/{app_id}/files/cleaned-diff error raises APIError."""
        handler, captured = _make_appsec_handler(cleaned_diff_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_cleaned_diff",
                    app_id=1234567,
                    server_id=999999,
                )
            )


# ===================================================================
# Phase 3 Tests -- Lifecycle & IP Management
# ===================================================================


class TestActivateSecuritySuite:
    """Tests for activate_security_suite client method and activate CLI command."""

    def test_activate_success(self, set_env):
        """POST /app/security/{app_id}/activate sends body fields (CLI)."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "activate", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        body = captured[-1].content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "mp_offer_availed=" in body

    def test_activate_error(self, set_env):
        """POST /app/security/{app_id}/activate error raises APIError."""
        handler, captured = _make_appsec_handler(activate_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "activate_security_suite",
                    app_id=1234567,
                    server_id=999999,
                )
            )


class TestDeactivateSecuritySuite:
    """Tests for deactivate_security_suite client method and deactivate CLI."""

    def test_deactivate_success(self, set_env):
        """PATCH /app/security/{app_id}/deactivate sends required fields (CLI)."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "appsec",
                    "deactivate",
                    "production",
                    "--app-name",
                    "myapp",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert captured[-1].method == "PATCH"
        body = captured[-1].content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "app_name=" in body
        assert "feedback_text=" not in body  # not included when not provided

    def test_deactivate_with_feedback(self, set_env):
        """PATCH /app/security/{app_id}/deactivate includes feedback_text."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "appsec",
                    "deactivate",
                    "production",
                    "--app-name",
                    "myapp",
                    "--feedback",
                    "Too expensive",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert captured[-1].method == "PATCH"
        body = captured[-1].content.decode()
        assert "feedback_text=" in body

    def test_deactivate_error(self, set_env):
        """PATCH /app/security/{app_id}/deactivate error raises APIError."""
        handler, captured = _make_appsec_handler(deactivate_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "deactivate_security_suite",
                    app_id=1234567,
                    server_id=999999,
                    app_name="myapp",
                )
            )


class TestAddSecurityIp:
    """Tests for add_security_ip client method and ip-add CLI command."""

    def test_ip_add_success(self, set_env):
        """PUT /app/security/{app_id}/ips sends all body fields (CLI)."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "appsec",
                    "ip-add",
                    "production",
                    "--ip",
                    "1.2.3.4",
                    "--mode",
                    "block",
                    "--reason",
                    "suspicious activity",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert captured[-1].method == "PUT"
        body = captured[-1].content.decode()
        assert "server_id=" in body
        assert "app_id=" in body
        assert "ips=" in body
        assert "mode=" in body
        assert "ttl=" in body
        assert "reason=" in body

    def test_ip_add_error(self, set_env):
        """PUT /app/security/{app_id}/ips error raises APIError."""
        handler, captured = _make_appsec_handler(ip_add_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "add_security_ip",
                    app_id=1234567,
                    server_id=999999,
                    ip="1.2.3.4",
                    mode="block",
                    ttl=0,
                    reason="test",
                )
            )


class TestRemoveSecurityIp:
    """Tests for remove_security_ip client method and ip-remove CLI command."""

    def test_ip_remove_success(self, set_env):
        """DELETE /app/security/{app_id}/ips sends body with DELETE method (CLI)."""
        handler, captured = _make_appsec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "appsec",
                    "ip-remove",
                    "production",
                    "--ip",
                    "1.2.3.4",
                    "--mode",
                    "block",
                    "--reason",
                    "no longer needed",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert captured[-1].method == "DELETE"
        body = captured[-1].content.decode()
        assert "server_id=" in body
        assert "app_id=" in body
        assert "ips=" in body
        assert "mode=" in body

    def test_ip_remove_error(self, set_env):
        """DELETE /app/security/{app_id}/ips error raises APIError."""
        handler, captured = _make_appsec_handler(ip_remove_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "remove_security_ip",
                    app_id=1234567,
                    server_id=999999,
                    ip="1.2.3.4",
                    mode="block",
                    ttl=0,
                    reason="test",
                )
            )


# ===================================================================
# CLI Runner Tests -- Commands with only client-method coverage
# ===================================================================


class TestAppsecCliRunner:
    """CLI runner.invoke tests for commands that previously only had client-method tests."""

    def test_status_cli(self, set_env):
        """appsec status <env> exits 0 and prints status."""
        handler, captured = _make_appsec_handler(
            status_response={"is_active": True, "plan": "pro"},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "status", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "is_active" in result.output

    def test_scans_cli(self, set_env):
        """appsec scans <env> exits 0 and prints scan list."""
        handler, captured = _make_appsec_handler(
            list_scans_response={"scans": [{"id": 1}], "total": 1},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "scans", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "scans" in result.output

    def test_scan_status_cli(self, set_env):
        """appsec scan-status <env> exits 0 and prints scan status."""
        handler, captured = _make_appsec_handler(
            scan_status_response={
                "status": "completed",
                "data": {"progress": 100},
            },
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan-status", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "completed" in result.output

    def test_scan_detail_cli(self, set_env):
        """appsec scan-detail <env> --scan-id <id> exits 0 and prints detail."""
        handler, captured = _make_appsec_handler(
            scan_detail_response={"scan_id": 42, "status": "completed"},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "scan-detail", "production", "42"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "42" in result.output

    def test_events_cli(self, set_env):
        """appsec events <env> exits 0 and prints events."""
        handler, captured = _make_appsec_handler(
            events_response={"events": [{"id": 1, "type": "malware"}]},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "events", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "events" in result.output

    def test_incidents_cli(self, set_env):
        """appsec incidents <env> exits 0 and prints incidents."""
        handler, captured = _make_appsec_handler(
            incidents_response={"incidents": [{"id": 1}]},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "incidents", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "incidents" in result.output

    def test_files_cli(self, set_env):
        """appsec files <env> exits 0 and prints file list."""
        handler, captured = _make_appsec_handler(
            list_files_response={"files": [], "total": 0},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "files", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "files" in result.output

    def test_cleaned_diff_cli(self, set_env):
        """appsec cleaned-diff <env> exits 0 and prints diff."""
        handler, captured = _make_appsec_handler(
            cleaned_diff_response={"diff": "clean"},
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.appsec.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["appsec", "cleaned-diff", "production"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "clean" in result.output


# ===================================================================
# Registration Tests
# ===================================================================


class TestAppsecRegistration:
    """Tests verifying appsec command group registration in CLI."""

    def test_appsec_in_help(self):
        """appsec appears in top-level CLI help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "appsec" in result.output

    def test_appsec_subcommands(self):
        """All 14 appsec subcommands appear in appsec --help."""
        result = runner.invoke(app, ["appsec", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "status",
            "scans",
            "scan",
            "scan-status",
            "scan-detail",
            "events",
            "incidents",
            "files",
            "restore",
            "cleaned-diff",
            "activate",
            "deactivate",
            "ip-add",
            "ip-remove",
        ]:
            assert cmd in result.output
