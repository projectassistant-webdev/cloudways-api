"""Tests for server & app monitoring commands and client methods.

Covers task polling infrastructure, server bandwidth/disk summary,
server usage analytics, server monitor detail graphs, app summary,
traffic analytics, PHP/MySQL/cron analytics, and all corresponding
CLI commands with mocked Cloudways API responses.
"""

import time
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError, OperationTimeoutError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# Sample response fixtures
TASK_ENVELOPE = {"status": True, "task_id": "18d4f7f4-f220-4bbb-bcd3-a6357e125306"}
TASK_COMPLETED = {"is_completed": True, "data": {"cpu": 45.2}}


# --- Handler factory ---


def _make_monitor_handler(
    # Task polling
    task_status_response=None,
    task_status_error=False,
    # Phase 1 - server
    server_summary_response=None,
    server_summary_error=False,
    server_usage_response=None,
    server_usage_error=False,
    server_detail_response=None,
    server_detail_error=False,
    # Phase 2 - app summary + traffic
    app_summary_response=None,
    app_summary_error=False,
    traffic_response=None,
    traffic_error=False,
    traffic_details_response=None,
    traffic_details_error=False,
    # Phase 3 - analytics
    php_response=None,
    php_error=False,
    mysql_response=None,
    mysql_error=False,
    cron_response=None,
    cron_error=False,
):
    """Build httpx mock handler for all monitor/analytics API calls.

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

        # 1. trafficDetails BEFORE traffic (prefix collision)
        if "/analytics/trafficDetails" in url and method == "POST":
            if traffic_details_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(
                200,
                json=traffic_details_response or TASK_ENVELOPE,
            )

        # 2. Specific analytics paths
        if "/analytics/php" in url:
            if php_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=php_response or TASK_ENVELOPE)

        if "/analytics/mysql" in url:
            if mysql_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=mysql_response or TASK_ENVELOPE)

        if "/analytics/cron" in url:
            if cron_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=cron_response or TASK_ENVELOPE)

        if "/analytics/serverUsage" in url:
            if server_usage_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=server_usage_response or TASK_ENVELOPE)

        # 3. monitor/detail before monitor/summary (more specific)
        if "/monitor/detail" in url:
            if server_detail_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=server_detail_response or TASK_ENVELOPE)

        # 4. analytics/traffic (GET -- after trafficDetails)
        if "/analytics/traffic" in url and method == "GET":
            if traffic_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(200, json=traffic_response or TASK_ENVELOPE)

        # 5. monitor/summary routing: app vs server
        if "/monitor/summary" in url:
            if "app_id" in url:
                if app_summary_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=app_summary_response
                    or {"data": {"bw": 1234, "type": "bw"}},
                )
            else:
                if server_summary_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=server_summary_response
                    or {"data": {"bandwidth": 5678, "type": "bandwidth"}},
                )

        # 6. task polling
        if "/operation/task/" in url:
            if task_status_error:
                return httpx.Response(400, text="API request failed with status 400")
            return httpx.Response(
                200, json=task_status_response or TASK_COMPLETED
            )

        return httpx.Response(404, text="Not found")

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests -- Phase 1
# ===================================================================


class TestGetTaskStatus:
    """Tests for CloudwaysClient.get_task_status()."""

    @pytest.mark.asyncio
    async def test_get_task_status_success(self) -> None:
        """GET /operation/task/{task_id} returns dict with task UUID in URL."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_task_status(
                "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
            )

        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in url
        assert captured[-1].method == "GET"

    @pytest.mark.asyncio
    async def test_get_task_status_error(self) -> None:
        """GET /operation/task/{task_id} error raises APIError."""
        handler, captured = _make_monitor_handler(task_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_task_status(
                    "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
                )
            assert "400" in str(exc_info.value)


class TestWaitForTask:
    """Tests for CloudwaysClient.wait_for_task()."""

    @pytest.mark.asyncio
    async def test_wait_for_task_completion(self) -> None:
        """wait_for_task returns result when is_completed is truthy."""
        handler, captured = _make_monitor_handler(
            task_status_response=TASK_COMPLETED
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with PatchedClient("test@example.com", "key") as client:
                result = await client.wait_for_task(
                    "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
                )

        assert result["is_completed"] is True
        assert result["data"]["cpu"] == 45.2

    @pytest.mark.asyncio
    async def test_wait_for_task_timeout(self) -> None:
        """wait_for_task raises OperationTimeoutError on timeout."""
        handler, captured = _make_monitor_handler(
            task_status_response={"is_completed": False, "task_id": "abc-123"}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = time.monotonic()
        call_count = 0

        def mock_monotonic():
            nonlocal call_count
            call_count += 1
            return start_time + (call_count * 100)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic", side_effect=mock_monotonic
            ):
                async with PatchedClient("test@example.com", "key") as client:
                    with pytest.raises(OperationTimeoutError) as exc_info:
                        await client.wait_for_task(
                            "18d4f7f4-f220-4bbb-bcd3-a6357e125306",
                            max_wait=300,
                        )

        assert exc_info.value.operation_id == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        assert exc_info.value.max_wait == 300

    @pytest.mark.asyncio
    async def test_wait_for_task_api_error_propagates(self) -> None:
        """APIError from get_task_status propagates unmodified."""
        handler, captured = _make_monitor_handler(task_status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with PatchedClient("test@example.com", "key") as client:
                with pytest.raises(APIError) as exc_info:
                    await client.wait_for_task(
                        "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
                    )
                assert "400" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_wait_for_task_invalid_max_wait(self) -> None:
        """wait_for_task raises ValueError when max_wait <= 0."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(ValueError, match="max_wait must be positive"):
                await client.wait_for_task(
                    "18d4f7f4-f220-4bbb-bcd3-a6357e125306",
                    max_wait=0,
                )

    @pytest.mark.asyncio
    async def test_wait_for_task_invalid_poll_interval(self) -> None:
        """wait_for_task raises ValueError when poll_interval <= 0."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(ValueError, match="poll_interval must be positive"):
                await client.wait_for_task(
                    "18d4f7f4-f220-4bbb-bcd3-a6357e125306",
                    poll_interval=-1,
                )


class TestGetServerMonitorSummary:
    """Tests for CloudwaysClient.get_server_monitor_summary()."""

    @pytest.mark.asyncio
    async def test_get_server_monitor_summary_success(self) -> None:
        """GET /server/monitor/summary returns dict with server_id and type."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_server_monitor_summary(
                server_id=36780, summary_type="bandwidth"
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured if "/monitor/summary" in str(r.url)
        ][-1]
        assert request.method == "GET"
        assert "server_id=36780" in str(request.url)
        assert "type=bandwidth" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_server_monitor_summary_error(self) -> None:
        """GET /server/monitor/summary error raises APIError."""
        handler, captured = _make_monitor_handler(server_summary_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_server_monitor_summary(
                    server_id=36780, summary_type="bandwidth"
                )
            assert "400" in str(exc_info.value)


class TestGetServerUsage:
    """Tests for CloudwaysClient.get_server_usage()."""

    @pytest.mark.asyncio
    async def test_get_server_usage_success(self) -> None:
        """GET /server/analytics/serverUsage returns task envelope."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_server_usage(server_id=36780)

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        request = [
            r for r in captured if "/analytics/serverUsage" in str(r.url)
        ][-1]
        assert request.method == "GET"
        assert "server_id=36780" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_server_usage_error(self) -> None:
        """GET /server/analytics/serverUsage error raises APIError."""
        handler, captured = _make_monitor_handler(server_usage_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_server_usage(server_id=36780)
            assert "400" in str(exc_info.value)


class TestGetServerMonitorDetail:
    """Tests for CloudwaysClient.get_server_monitor_detail()."""

    @pytest.mark.asyncio
    async def test_get_server_monitor_detail_with_format(self) -> None:
        """GET /server/monitor/detail includes output_format when provided."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_server_monitor_detail(
                server_id=36780,
                target="cpu",
                duration="1h",
                storage=True,
                timezone="UTC",
                output_format="json",
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured if "/monitor/detail" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id=36780" in url
        assert "target=cpu" in url
        assert "duration=1h" in url
        assert "storage=true" in url
        assert "timezone=UTC" in url
        assert "output_format=json" in url

    @pytest.mark.asyncio
    async def test_get_server_monitor_detail_without_format(self) -> None:
        """GET /server/monitor/detail omits output_format when None."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_server_monitor_detail(
                server_id=36780,
                target="mem",
                duration="30m",
                storage=False,
                timezone="America/New_York",
            )

        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "output_format" not in url
        assert "server_id=36780" in url
        assert "target=mem" in url

    @pytest.mark.asyncio
    async def test_get_server_monitor_detail_error(self) -> None:
        """GET /server/monitor/detail error raises APIError."""
        handler, captured = _make_monitor_handler(server_detail_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_server_monitor_detail(
                    server_id=36780,
                    target="cpu",
                    duration="1h",
                    storage=False,
                    timezone="UTC",
                )
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI tests -- Phase 1
# ===================================================================


class TestMonitorServerSummaryCli:
    """Tests for cloudways monitor server-summary CLI command."""

    def test_server_summary_success(self, set_env) -> None:
        """server-summary exits 0 with response data."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "server-summary",
                    "--server-id",
                    "36780",
                    "--type",
                    "bandwidth",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "bandwidth" in result.output

    def test_server_summary_error(self, set_env) -> None:
        """server-summary exits 1 on API error."""
        handler, captured = _make_monitor_handler(server_summary_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "server-summary",
                    "--server-id",
                    "36780",
                    "--type",
                    "disk",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_server_summary_invalid_type(self) -> None:
        """server-summary exits 2 for invalid --type value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "server-summary",
                "--server-id",
                "36780",
                "--type",
                "invalid_type",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--type'" in result.output


class TestMonitorServerUsageCli:
    """Tests for cloudways monitor server-usage CLI command."""

    def test_server_usage_no_wait(self, set_env) -> None:
        """server-usage without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            server_usage_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["monitor", "server-usage", "--server-id", "36780"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_server_usage_with_wait(self, set_env) -> None:
        """server-usage with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            server_usage_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "server-usage",
                        "--server-id",
                        "36780",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_server_usage_error(self, set_env) -> None:
        """server-usage exits 1 on API error."""
        handler, captured = _make_monitor_handler(server_usage_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["monitor", "server-usage", "--server-id", "36780"],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestMonitorServerGraphCli:
    """Tests for cloudways monitor server-graph CLI command."""

    def test_server_graph_no_wait(self, set_env) -> None:
        """server-graph without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            server_detail_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "server-graph",
                    "--server-id",
                    "36780",
                    "--target",
                    "cpu",
                    "--duration",
                    "1h",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_server_graph_with_wait(self, set_env) -> None:
        """server-graph with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            server_detail_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "server-graph",
                        "--server-id",
                        "36780",
                        "--target",
                        "cpu",
                        "--duration",
                        "1h",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_server_graph_default_params(self, set_env) -> None:
        """server-graph sends defaults for --storage, --timezone, --format."""
        handler, captured = _make_monitor_handler(
            server_detail_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "server-graph",
                    "--server-id",
                    "36780",
                    "--target",
                    "cpu",
                    "--duration",
                    "15m",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # Find the monitor/detail request
        detail_requests = [
            r for r in captured if "/monitor/detail" in str(r.url)
        ]
        assert len(detail_requests) >= 1
        url = str(detail_requests[-1].url)
        assert "storage=false" in url
        assert "timezone=UTC" in url
        assert "output_format=json" in url

    def test_server_graph_error(self, set_env) -> None:
        """server-graph exits 1 on API error."""
        handler, captured = _make_monitor_handler(server_detail_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "server-graph",
                    "--server-id",
                    "36780",
                    "--target",
                    "cpu",
                    "--duration",
                    "1h",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_server_graph_invalid_duration(self) -> None:
        """server-graph exits 2 for invalid --duration value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "server-graph",
                "--server-id",
                "36780",
                "--target",
                "cpu",
                "--duration",
                "2h",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--duration'" in result.output


# ===================================================================
# Client method tests -- Phase 2
# ===================================================================


class TestGetAppMonitorSummary:
    """Tests for CloudwaysClient.get_app_monitor_summary()."""

    @pytest.mark.asyncio
    async def test_get_app_monitor_summary_success(self) -> None:
        """GET /app/monitor/summary returns dict with server_id, app_id, type."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_monitor_summary(
                server_id=36780, app_id=1234567, summary_type="bw"
            )

        assert isinstance(result, dict)
        request = [
            r for r in captured if "/monitor/summary" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id=36780" in url
        assert "app_id=1234567" in url
        assert "type=bw" in url

    @pytest.mark.asyncio
    async def test_get_app_monitor_summary_error(self) -> None:
        """GET /app/monitor/summary error raises APIError."""
        handler, captured = _make_monitor_handler(app_summary_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_monitor_summary(
                    server_id=36780, app_id=1234567, summary_type="bw"
                )
            assert "400" in str(exc_info.value)


class TestGetAppTrafficAnalytics:
    """Tests for CloudwaysClient.get_app_traffic_analytics()."""

    @pytest.mark.asyncio
    async def test_get_app_traffic_analytics_success(self) -> None:
        """GET /app/analytics/traffic returns task envelope with all 4 params."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_traffic_analytics(
                server_id=36780,
                app_id=1234567,
                duration="1h",
                resource="top_ips",
            )

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        request = [
            r for r in captured if "/analytics/traffic" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id=36780" in url
        assert "app_id=1234567" in url
        assert "duration=1h" in url
        assert "resource=top_ips" in url

    @pytest.mark.asyncio
    async def test_get_app_traffic_analytics_error(self) -> None:
        """GET /app/analytics/traffic error raises APIError."""
        handler, captured = _make_monitor_handler(traffic_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_traffic_analytics(
                    server_id=36780,
                    app_id=1234567,
                    duration="1h",
                    resource="top_ips",
                )
            assert "400" in str(exc_info.value)


class TestGetAppTrafficDetails:
    """Tests for CloudwaysClient.get_app_traffic_details()."""

    @pytest.mark.asyncio
    async def test_get_app_traffic_details_success(self) -> None:
        """POST /app/analytics/trafficDetails uses from/until (not from_dt/until_dt)."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_traffic_details(
                server_id=36780,
                app_id=1234567,
                from_dt="01/03/2026 00:00",
                until_dt="15/03/2026 23:59",
                resource="top_ips",
            )

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"

        request = captured[-1]
        assert request.method == "POST"
        assert "/analytics/trafficDetails" in str(request.url)

        body = request.content.decode()
        assert "from=" in body
        assert "until=" in body
        assert "from_dt=" not in body
        assert "until_dt=" not in body
        assert "server_id=" in body
        assert "app_id=" in body
        assert "resource=" in body

    @pytest.mark.asyncio
    async def test_get_app_traffic_details_with_resource_list(self) -> None:
        """POST /app/analytics/trafficDetails includes resource_list as repeated keys."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_traffic_details(
                server_id=36780,
                app_id=1234567,
                from_dt="01/03/2026 00:00",
                until_dt="15/03/2026 23:59",
                resource="top_ips",
                resource_list=["a", "b"],
            )

        assert isinstance(result, dict)
        body = captured[-1].content.decode()
        assert body.count("resource_list=") == 2

    @pytest.mark.asyncio
    async def test_get_app_traffic_details_error(self) -> None:
        """POST /app/analytics/trafficDetails error raises APIError."""
        handler, captured = _make_monitor_handler(traffic_details_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_traffic_details(
                    server_id=36780,
                    app_id=1234567,
                    from_dt="01/03/2026 00:00",
                    until_dt="15/03/2026 23:59",
                    resource="top_ips",
                )
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI tests -- Phase 2
# ===================================================================


class TestMonitorAppSummaryCli:
    """Tests for cloudways monitor app-summary CLI command."""

    def test_app_summary_success(self, set_env) -> None:
        """app-summary exits 0 with response data."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "app-summary",
                    "production",
                    "--type",
                    "bw",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "bw" in result.output

    def test_app_summary_error(self, set_env) -> None:
        """app-summary exits 1 on API error."""
        handler, captured = _make_monitor_handler(app_summary_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "app-summary",
                    "production",
                    "--type",
                    "db",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_app_summary_invalid_type(self) -> None:
        """app-summary exits 2 for invalid --type value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "app-summary",
                "production",
                "--type",
                "invalid",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--type'" in result.output


class TestMonitorTrafficCli:
    """Tests for cloudways monitor traffic CLI command."""

    def test_traffic_no_wait(self, set_env) -> None:
        """traffic without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            traffic_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "traffic",
                    "production",
                    "--duration",
                    "1h",
                    "--resource",
                    "top_ips",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_traffic_with_wait(self, set_env) -> None:
        """traffic with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            traffic_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "traffic",
                        "production",
                        "--duration",
                        "1h",
                        "--resource",
                        "top_ips",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_traffic_error(self, set_env) -> None:
        """traffic exits 1 on API error."""
        handler, captured = _make_monitor_handler(traffic_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "traffic",
                    "production",
                    "--duration",
                    "1h",
                    "--resource",
                    "top_ips",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_traffic_invalid_resource(self) -> None:
        """traffic exits 2 for invalid --resource value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "traffic",
                "production",
                "--duration",
                "1h",
                "--resource",
                "invalid_resource",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--resource'" in result.output


class TestMonitorTrafficDetailsCli:
    """Tests for cloudways monitor traffic-details CLI command."""

    def test_traffic_details_no_wait(self, set_env) -> None:
        """traffic-details exits 0 with task_id, POST body uses from/until."""
        handler, captured = _make_monitor_handler(
            traffic_details_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "traffic-details",
                    "production",
                    "--from",
                    "01/03/2026 00:00",
                    "--until",
                    "15/03/2026 23:59",
                    "--resource",
                    "top_ips",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_traffic_details_with_wait(self, set_env) -> None:
        """traffic-details with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            traffic_details_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "traffic-details",
                        "production",
                        "--from",
                        "01/03/2026 00:00",
                        "--until",
                        "15/03/2026 23:59",
                        "--resource",
                        "top_ips",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_traffic_details_error(self, set_env) -> None:
        """traffic-details exits 1 on API error."""
        handler, captured = _make_monitor_handler(traffic_details_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "traffic-details",
                    "production",
                    "--from",
                    "01/03/2026 00:00",
                    "--until",
                    "15/03/2026 23:59",
                    "--resource",
                    "top_ips",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_traffic_details_invalid_environment(self, set_env) -> None:
        """traffic-details exits 1 for invalid environment name."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "traffic-details",
                    "nonexistent-env",
                    "--from",
                    "01/03/2026 00:00",
                    "--until",
                    "15/03/2026 23:59",
                    "--resource",
                    "top_ips",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


# ===================================================================
# Client method tests -- Phase 3
# ===================================================================


class TestGetAppPhpAnalytics:
    """Tests for CloudwaysClient.get_app_php_analytics()."""

    @pytest.mark.asyncio
    async def test_get_app_php_analytics_success(self) -> None:
        """GET /app/analytics/php returns task envelope with all 4 params."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_php_analytics(
                server_id=36780,
                app_id=1234567,
                duration="1h",
                resource="slow_pages",
            )

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        request = [
            r for r in captured if "/analytics/php" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id=36780" in url
        assert "app_id=1234567" in url
        assert "duration=1h" in url
        assert "resource=slow_pages" in url

    @pytest.mark.asyncio
    async def test_get_app_php_analytics_error(self) -> None:
        """GET /app/analytics/php error raises APIError."""
        handler, captured = _make_monitor_handler(php_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_php_analytics(
                    server_id=36780,
                    app_id=1234567,
                    duration="1h",
                    resource="slow_pages",
                )
            assert "400" in str(exc_info.value)


class TestGetAppMysqlAnalytics:
    """Tests for CloudwaysClient.get_app_mysql_analytics()."""

    @pytest.mark.asyncio
    async def test_get_app_mysql_analytics_success(self) -> None:
        """GET /app/analytics/mysql returns task envelope with all 4 params."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_mysql_analytics(
                server_id=36780,
                app_id=1234567,
                duration="30m",
                resource="slow_queries",
            )

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        request = [
            r for r in captured if "/analytics/mysql" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id=36780" in url
        assert "app_id=1234567" in url
        assert "duration=30m" in url
        assert "resource=slow_queries" in url

    @pytest.mark.asyncio
    async def test_get_app_mysql_analytics_error(self) -> None:
        """GET /app/analytics/mysql error raises APIError."""
        handler, captured = _make_monitor_handler(mysql_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_mysql_analytics(
                    server_id=36780,
                    app_id=1234567,
                    duration="30m",
                    resource="slow_queries",
                )
            assert "400" in str(exc_info.value)


class TestGetAppCronAnalytics:
    """Tests for CloudwaysClient.get_app_cron_analytics()."""

    @pytest.mark.asyncio
    async def test_get_app_cron_analytics_success(self) -> None:
        """GET /app/analytics/cron returns task envelope with only server_id and app_id."""
        handler, captured = _make_monitor_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_cron_analytics(
                server_id=36780,
                app_id=1234567,
            )

        assert isinstance(result, dict)
        assert result["task_id"] == "18d4f7f4-f220-4bbb-bcd3-a6357e125306"
        request = [
            r for r in captured if "/analytics/cron" in str(r.url)
        ][-1]
        assert request.method == "GET"
        url = str(request.url)
        assert "server_id" in url
        assert "app_id" in url
        assert "duration" not in url
        assert "resource" not in url

    @pytest.mark.asyncio
    async def test_get_app_cron_analytics_error(self) -> None:
        """GET /app/analytics/cron error raises APIError."""
        handler, captured = _make_monitor_handler(cron_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_app_cron_analytics(
                    server_id=36780,
                    app_id=1234567,
                )
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI tests -- Phase 3
# ===================================================================


class TestMonitorPhpCli:
    """Tests for cloudways monitor php CLI command."""

    def test_php_no_wait(self, set_env) -> None:
        """php without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            php_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "php",
                    "production",
                    "--duration",
                    "1h",
                    "--resource",
                    "slow_pages",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_php_with_wait(self, set_env) -> None:
        """php with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            php_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "php",
                        "production",
                        "--duration",
                        "1h",
                        "--resource",
                        "slow_pages",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_php_error(self, set_env) -> None:
        """php exits 1 on API error."""
        handler, captured = _make_monitor_handler(php_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "php",
                    "production",
                    "--duration",
                    "1h",
                    "--resource",
                    "slow_pages",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_php_invalid_resource(self) -> None:
        """php exits 2 for invalid --resource value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "php",
                "production",
                "--duration",
                "1h",
                "--resource",
                "invalid_resource",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--resource'" in result.output


class TestMonitorMysqlCli:
    """Tests for cloudways monitor mysql CLI command."""

    def test_mysql_no_wait(self, set_env) -> None:
        """mysql without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            mysql_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "mysql",
                    "production",
                    "--duration",
                    "30m",
                    "--resource",
                    "slow_queries",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_mysql_with_wait(self, set_env) -> None:
        """mysql with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            mysql_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "mysql",
                        "production",
                        "--duration",
                        "30m",
                        "--resource",
                        "slow_queries",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_mysql_error(self, set_env) -> None:
        """mysql exits 1 on API error."""
        handler, captured = _make_monitor_handler(mysql_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "mysql",
                    "production",
                    "--duration",
                    "30m",
                    "--resource",
                    "slow_queries",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output

    def test_mysql_invalid_resource(self) -> None:
        """mysql exits 2 for invalid --resource value."""
        result = runner.invoke(
            app,
            [
                "monitor",
                "mysql",
                "production",
                "--duration",
                "30m",
                "--resource",
                "invalid_resource",
            ],
        )

        assert result.exit_code == 2
        assert "Invalid value for '--resource'" in result.output


class TestMonitorCronCli:
    """Tests for cloudways monitor cron CLI command."""

    def test_cron_no_wait(self, set_env) -> None:
        """cron without --wait exits 0 with task_id in output."""
        handler, captured = _make_monitor_handler(
            cron_response=TASK_ENVELOPE
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "cron",
                    "production",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "task_id" in result.output
        assert "18d4f7f4-f220-4bbb-bcd3-a6357e125306" in result.output

    def test_cron_with_wait(self, set_env) -> None:
        """cron with --wait polls and prints final result."""
        handler, captured = _make_monitor_handler(
            cron_response=TASK_ENVELOPE,
            task_status_response=TASK_COMPLETED,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            with patch("cloudways_api.client.asyncio.sleep", return_value=None):
                result = runner.invoke(
                    app,
                    [
                        "monitor",
                        "cron",
                        "production",
                        "--wait",
                    ],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0
        assert "is_completed" in result.output

    def test_cron_error(self, set_env) -> None:
        """cron exits 1 on API error."""
        handler, captured = _make_monitor_handler(cron_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.monitor.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "monitor",
                    "cron",
                    "production",
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestMonitorRegistration:
    """Tests for monitor group registration in CLI."""

    def test_monitor_in_help(self) -> None:
        """cloudways --help shows 'monitor' command group."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "monitor" in result.output

    def test_monitor_subcommands(self) -> None:
        """cloudways monitor --help shows all 9 subcommands."""
        result = runner.invoke(app, ["monitor", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "server-summary",
            "server-usage",
            "server-graph",
            "app-summary",
            "traffic",
            "traffic-details",
            "php",
            "mysql",
            "cron",
        ]:
            assert cmd in result.output
