"""Tests for Copilot management commands and client methods.

Covers Copilot plans, billing, subscription management, server settings,
and Insights commands with mocked Cloudways API responses, plus client
method tests for all Copilot and Insights API operations.
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


def _make_copilot_handler(
    plans_response=None,
    plans_error=False,
    status_response=None,
    status_error=False,
    subscribe_response=None,
    subscribe_error=False,
    cancel_response=None,
    cancel_error=False,
    change_plan_response=None,
    change_plan_error=False,
    billing_response=None,
    billing_error=False,
    # Phase 2 flags:
    server_settings_response=None,
    server_settings_error=False,
    update_server_settings_response=None,
    update_server_settings_error=False,
    insights_summary_response=None,
    insights_summary_error=False,
    insights_response=None,
    insights_error=False,
    insight_response=None,
    insight_error=False,
):
    """Build httpx mock handler for all Copilot and Insights API calls.

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

        # Most-specific /copilot paths first:
        if "/copilot/billing/real-time" in url:
            if billing_error:
                return httpx.Response(400, text="Billing failed")
            return httpx.Response(
                200,
                json=billing_response
                or {
                    "data": {
                        "cycle_start": "2026-03-01",
                        "cycle_end": "2026-03-31",
                        "credits_used": 0,
                    }
                },
            )

        if "/copilot/plans/subscribe" in url:
            if method == "POST":
                if subscribe_error:
                    return httpx.Response(400, text="Already subscribed")
                return httpx.Response(
                    200,
                    json=subscribe_response or {"status": True, "data": {}},
                )
            elif method == "DELETE":
                if cancel_error:
                    return httpx.Response(400, text="No active plan")
                return httpx.Response(
                    200,
                    json=cancel_response or {"status": True, "data": {}},
                )

        if "/copilot/plans/status" in url:
            if status_error:
                return httpx.Response(400, text="Status failed")
            return httpx.Response(
                200,
                json=status_response
                or {
                    "data": {
                        "plan_name": "Basic",
                        "status": "active",
                        "expires_at": "2026-04-01",
                    }
                },
            )

        if "/copilot/plans/change" in url:
            if change_plan_error:
                return httpx.Response(400, text="Change failed")
            return httpx.Response(
                200,
                json=change_plan_response or {"status": True, "data": {}},
            )

        if "/copilot/plans" in url:
            if plans_error:
                return httpx.Response(400, text="Plans failed")
            return httpx.Response(
                200,
                json=plans_response
                or {
                    "data": [{"id": 1, "name": "Basic", "price": "9.99"}],
                    "prev_plans": [],
                    "pending_downgrade_request": None,
                },
            )

        if "/copilot/server-settings" in url:
            if method == "POST":
                if update_server_settings_error:
                    return httpx.Response(400, text="Update failed")
                return httpx.Response(
                    200,
                    json=update_server_settings_response
                    or {"status": True, "data": {}},
                )
            else:  # GET
                if server_settings_error:
                    return httpx.Response(400, text="Server settings failed")
                return httpx.Response(
                    200,
                    json=server_settings_response
                    or {"data": [{"server_id": 36780, "insights_enabled": False}]},
                )

        # Most-specific /insights paths first:
        if "/insights/summary" in url:
            if insights_summary_error:
                return httpx.Response(403, text="Insights summary forbidden")
            return httpx.Response(
                200,
                json=insights_summary_response
                or {"data": {"total": 0, "critical": 0, "high": 0}},
            )

        # Check for /insights/{numeric_id} before bare /insights
        insights_detail_match = re.search(r"/insights/(\d+)$", url)
        if insights_detail_match:
            if insight_error:
                return httpx.Response(404, text="Insight not found")
            return httpx.Response(
                200,
                json=insight_response
                or {
                    "alert_id": 12345,
                    "user_id": 1,
                    "server_id": 36780,
                    "type": "security",
                    "subject": "Test insight",
                    "server_label": "test-server",
                    "status": "open",
                    "fix_status": "pending",
                    "severity": "high",
                    "description": "Test description",
                },
            )

        if "/insights" in url:
            if insights_error:
                return httpx.Response(403, text="Insights forbidden")
            return httpx.Response(
                200,
                json=insights_response
                or {
                    "insights": [
                        {
                            "alert_id": 12345,
                            "type": "security",
                            "severity": "high",
                            "subject": "Test insight",
                        }
                    ],
                    "pagination": {},
                },
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests — Phase 1
# ===================================================================


class TestGetCopilotPlans:
    """Tests for CloudwaysClient.get_copilot_plans()."""

    @pytest.mark.asyncio
    async def test_get_copilot_plans_success(self) -> None:
        """GET /copilot/plans returns dict with plan data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_copilot_plans()

        assert isinstance(result, dict)
        # Find the copilot request (not auth)
        request = [r for r in captured if "/copilot/plans" in str(r.url)][-1]
        assert request.method == "GET"
        assert "/copilot/plans" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_copilot_plans_error(self) -> None:
        """GET /copilot/plans error raises APIError."""
        handler, captured = _make_copilot_handler(plans_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_copilot_plans()
            assert "400" in str(exc_info.value)


class TestGetCopilotStatus:
    """Tests for CloudwaysClient.get_copilot_status()."""

    @pytest.mark.asyncio
    async def test_get_copilot_status_success(self) -> None:
        """GET /copilot/plans/status returns dict."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_copilot_status()

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/plans/status" in str(r.url)][-1]
        assert request.method == "GET"
        assert "/copilot/plans/status" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_copilot_status_error(self) -> None:
        """GET /copilot/plans/status error raises APIError."""
        handler, captured = _make_copilot_handler(status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_copilot_status()
            assert "400" in str(exc_info.value)


class TestSubscribeCopilotPlan:
    """Tests for CloudwaysClient.subscribe_copilot_plan()."""

    @pytest.mark.asyncio
    async def test_subscribe_copilot_plan_success(self) -> None:
        """POST /copilot/plans/subscribe with plan_id."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.subscribe_copilot_plan(plan_id=1)

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/plans/subscribe" in str(r.url)][-1]
        assert request.method == "POST"
        assert "plan_id" in request.content.decode()

    @pytest.mark.asyncio
    async def test_subscribe_copilot_plan_error(self) -> None:
        """POST /copilot/plans/subscribe error raises APIError."""
        handler, captured = _make_copilot_handler(subscribe_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.subscribe_copilot_plan(plan_id=1)
            assert "400" in str(exc_info.value)


class TestCancelCopilotPlan:
    """Tests for CloudwaysClient.cancel_copilot_plan()."""

    @pytest.mark.asyncio
    async def test_cancel_copilot_plan_success(self) -> None:
        """DELETE /copilot/plans/subscribe with no body."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.cancel_copilot_plan()

        assert isinstance(result, dict)
        # Find the copilot request (not auth)
        request = [r for r in captured if "/copilot/plans/subscribe" in str(r.url)][-1]
        assert request.method == "DELETE"
        assert "/copilot/plans/subscribe" in str(request.url)

    @pytest.mark.asyncio
    async def test_cancel_copilot_plan_error(self) -> None:
        """DELETE /copilot/plans/subscribe error raises APIError."""
        handler, captured = _make_copilot_handler(cancel_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.cancel_copilot_plan()
            assert "400" in str(exc_info.value)


class TestChangeCopilotPlan:
    """Tests for CloudwaysClient.change_copilot_plan()."""

    @pytest.mark.asyncio
    async def test_change_copilot_plan_with_touchpoint(self) -> None:
        """POST /copilot/plans/change with plan_id and touchpoint."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.change_copilot_plan(
                plan_id=2, touchpoint="upgrade_page"
            )

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/plans/change" in str(r.url)][-1]
        assert request.method == "POST"
        body = request.content.decode()
        assert "plan_id" in body
        assert "touchpoint" in body

    @pytest.mark.asyncio
    async def test_change_copilot_plan_no_touchpoint(self) -> None:
        """POST /copilot/plans/change with only plan_id."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.change_copilot_plan(plan_id=2)

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/plans/change" in str(r.url)][-1]
        body = request.content.decode()
        assert "plan_id" in body
        assert "touchpoint" not in body

    @pytest.mark.asyncio
    async def test_change_copilot_plan_error(self) -> None:
        """POST /copilot/plans/change error raises APIError."""
        handler, captured = _make_copilot_handler(change_plan_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.change_copilot_plan(plan_id=2)
            assert "400" in str(exc_info.value)


class TestGetCopilotBilling:
    """Tests for CloudwaysClient.get_copilot_billing()."""

    @pytest.mark.asyncio
    async def test_get_copilot_billing_with_cycle(self) -> None:
        """GET /copilot/billing/real-time with billing_cycle query param."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_copilot_billing(billing_cycle="2026-01")

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/billing/real-time" in str(r.url)][
            -1
        ]
        assert "billing_cycle=2026-01" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_copilot_billing_no_cycle(self) -> None:
        """GET /copilot/billing/real-time with no query params."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_copilot_billing()

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/billing/real-time" in str(r.url)][
            -1
        ]
        assert "billing_cycle" not in str(request.url)
        assert "/copilot/billing/real-time" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_copilot_billing_api_error(self) -> None:
        """GET /copilot/billing/real-time error raises APIError."""
        handler, captured = _make_copilot_handler(billing_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_copilot_billing()
            assert "400" in str(exc_info.value)


# ===================================================================
# CLI command tests — Phase 1
# ===================================================================


class TestCopilotPlansCli:
    """Tests for `cloudways copilot plans` CLI command."""

    def test_copilot_plans_success(self, set_env) -> None:
        """copilot plans exits 0 and shows plan data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "plans"])

        assert result.exit_code == 0
        assert "Basic" in result.output or "9.99" in result.output

    def test_copilot_plans_error(self, set_env) -> None:
        """copilot plans API error exits 1."""
        handler, captured = _make_copilot_handler(plans_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "plans"])

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestCopilotStatusCli:
    """Tests for `cloudways copilot status` CLI command."""

    def test_copilot_status_success(self, set_env) -> None:
        """copilot status exits 0 and shows status data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "status"])

        assert result.exit_code == 0
        assert "active" in result.output or "2026-04-01" in result.output

    def test_copilot_status_api_error(self, set_env) -> None:
        """copilot status API error exits 1."""
        handler, captured = _make_copilot_handler(status_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "status"])

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestCopilotSubscribeCli:
    """Tests for `cloudways copilot subscribe` CLI command."""

    def test_copilot_subscribe_success(self, set_env) -> None:
        """copilot subscribe exits 0 with success message."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "subscribe", "--plan-id", "1"])

        assert result.exit_code == 0
        assert "Success: Subscribed to Copilot plan." in result.output
        # Verify POST body contains plan_id
        request = [r for r in captured if "/copilot/plans/subscribe" in str(r.url)][-1]
        assert "plan_id" in request.content.decode()

    def test_copilot_subscribe_error(self, set_env) -> None:
        """copilot subscribe API error exits 1."""
        handler, captured = _make_copilot_handler(subscribe_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "subscribe", "--plan-id", "1"])

        assert result.exit_code == 1


class TestCopilotCancelCli:
    """Tests for `cloudways copilot cancel` CLI command."""

    def test_copilot_cancel_success(self, set_env) -> None:
        """copilot cancel exits 0 with success message."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "cancel"])

        assert result.exit_code == 0
        assert "Success: Copilot plan cancelled." in result.output
        # Verify DELETE method was used
        request = [r for r in captured if "/copilot/plans/subscribe" in str(r.url)][-1]
        assert request.method == "DELETE"

    def test_copilot_cancel_error(self, set_env) -> None:
        """copilot cancel API error exits 1."""
        handler, captured = _make_copilot_handler(cancel_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "cancel"])

        assert result.exit_code == 1


class TestCopilotChangePlanCli:
    """Tests for `cloudways copilot change-plan` CLI command."""

    def test_copilot_change_plan_success(self, set_env) -> None:
        """copilot change-plan exits 0 with success message."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "change-plan", "--plan-id", "2"])

        assert result.exit_code == 0
        assert "Success: Copilot plan changed." in result.output
        # Verify only plan_id in body, no touchpoint
        request = [r for r in captured if "/copilot/plans/change" in str(r.url)][-1]
        body = request.content.decode()
        assert "plan_id" in body
        assert "touchpoint" not in body

    def test_copilot_change_plan_with_touchpoint(self, set_env) -> None:
        """copilot change-plan with --touchpoint includes both in body."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "copilot",
                    "change-plan",
                    "--plan-id",
                    "2",
                    "--touchpoint",
                    "upgrade_page",
                ],
            )

        assert result.exit_code == 0
        assert "Success: Copilot plan changed." in result.output
        request = [r for r in captured if "/copilot/plans/change" in str(r.url)][-1]
        body = request.content.decode()
        assert "plan_id" in body
        assert "touchpoint" in body

    def test_copilot_change_plan_api_error(self, set_env) -> None:
        """copilot change-plan API error exits 1."""
        handler, captured = _make_copilot_handler(change_plan_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "change-plan", "--plan-id", "2"])

        assert result.exit_code == 1


class TestCopilotBillingCli:
    """Tests for `cloudways copilot billing` CLI command."""

    def test_copilot_billing_success(self, set_env) -> None:
        """copilot billing exits 0 with no billing_cycle in URL."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "billing"])

        assert result.exit_code == 0
        request = [r for r in captured if "/copilot/billing/real-time" in str(r.url)][
            -1
        ]
        assert "billing_cycle" not in str(request.url)

    def test_copilot_billing_with_cycle(self, set_env) -> None:
        """copilot billing --billing-cycle sends query param."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "billing", "--billing-cycle", "2026-01"]
            )

        assert result.exit_code == 0
        request = [r for r in captured if "/copilot/billing/real-time" in str(r.url)][
            -1
        ]
        assert "billing_cycle=2026-01" in str(request.url)

    def test_copilot_billing_invalid_cycle(self, set_env) -> None:
        """copilot billing with invalid cycle format exits 1."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "billing", "--billing-cycle", "2026-1"]
            )

        assert result.exit_code == 1
        assert (
            "Error: --billing-cycle must be in YYYY-MM format (e.g., 2026-01)"
            in result.output
        )


# ===================================================================
# Registration tests
# ===================================================================


class TestCopilotRegistration:
    """Tests for copilot group registration in CLI."""

    def test_copilot_in_main_help(self) -> None:
        """copilot group appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "copilot" in result.output

    def test_copilot_subcommands_visible(self) -> None:
        """All 11 subcommands visible in copilot --help."""
        result = runner.invoke(app, ["copilot", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "plans",
            "status",
            "subscribe",
            "cancel",
            "change-plan",
            "billing",
            "server-settings",
            "enable-insights",
            "disable-insights",
            "insights",
            "insight",
        ]:
            assert cmd in result.output


# ===================================================================
# Client method tests — Phase 2
# ===================================================================


class TestGetCopilotServerSettings:
    """Tests for CloudwaysClient.get_copilot_server_settings()."""

    @pytest.mark.asyncio
    async def test_get_copilot_server_settings_success(self) -> None:
        """GET /copilot/server-settings returns dict."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_copilot_server_settings()

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/server-settings" in str(r.url)][-1]
        assert request.method == "GET"
        assert "/copilot/server-settings" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_copilot_server_settings_error(self) -> None:
        """GET /copilot/server-settings error raises APIError."""
        handler, captured = _make_copilot_handler(server_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_copilot_server_settings()
            assert "400" in str(exc_info.value)


class TestUpdateCopilotServerSettings:
    """Tests for CloudwaysClient.update_copilot_server_settings()."""

    @pytest.mark.asyncio
    async def test_enable_insights_success(self) -> None:
        """POST /copilot/server-settings with insights_enabled=True."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_copilot_server_settings(
                server_id=36780, insights_enabled=True
            )

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/server-settings" in str(r.url)][-1]
        assert request.method == "POST"
        body = request.content.decode()
        assert "server_id" in body
        assert "insights_enabled" in body

    @pytest.mark.asyncio
    async def test_disable_insights_success(self) -> None:
        """POST /copilot/server-settings with insights_enabled=False."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_copilot_server_settings(
                server_id=36780, insights_enabled=False
            )

        assert isinstance(result, dict)
        request = [r for r in captured if "/copilot/server-settings" in str(r.url)][-1]
        assert request.method == "POST"
        body = request.content.decode()
        assert "server_id" in body
        assert "insights_enabled" in body

    @pytest.mark.asyncio
    async def test_update_server_settings_error(self) -> None:
        """POST /copilot/server-settings error raises APIError."""
        handler, captured = _make_copilot_handler(update_server_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.update_copilot_server_settings(
                    server_id=36780, insights_enabled=True
                )
            assert "400" in str(exc_info.value)


class TestGetInsightsSummary:
    """Tests for CloudwaysClient.get_insights_summary()."""

    @pytest.mark.asyncio
    async def test_get_insights_summary_success(self) -> None:
        """GET /insights/summary returns dict (not /copilot/insights)."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_insights_summary()

        assert isinstance(result, dict)
        request = [r for r in captured if "/insights/summary" in str(r.url)][-1]
        assert "/insights/summary" in str(request.url)
        assert "copilot" not in str(request.url)

    @pytest.mark.asyncio
    async def test_get_insights_summary_error(self) -> None:
        """GET /insights/summary error raises APIError."""
        handler, captured = _make_copilot_handler(insights_summary_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_insights_summary()
            assert "403" in str(exc_info.value)


class TestGetInsights:
    """Tests for CloudwaysClient.get_insights()."""

    @pytest.mark.asyncio
    async def test_get_insights_success(self) -> None:
        """GET /insights returns dict with insights key."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_insights()

        assert isinstance(result, dict)
        assert "insights" in result
        request = [r for r in captured if "/insights" in str(r.url)][-1]
        assert "/insights" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_insights_error(self) -> None:
        """GET /insights error raises APIError."""
        handler, captured = _make_copilot_handler(insights_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_insights()
            assert "403" in str(exc_info.value)


class TestGetInsight:
    """Tests for CloudwaysClient.get_insight()."""

    @pytest.mark.asyncio
    async def test_get_insight_success(self) -> None:
        """GET /insights/12345 returns dict with alert data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_insight(alert_id=12345)

        assert isinstance(result, dict)
        request = [r for r in captured if "/insights/12345" in str(r.url)][-1]
        assert "/insights/12345" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_insight_not_found(self) -> None:
        """GET /insights/{id} 404 raises APIError."""
        handler, captured = _make_copilot_handler(insight_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_insight(alert_id=12345)
            assert "404" in str(exc_info.value)


# ===================================================================
# CLI command tests — Phase 2
# ===================================================================


class TestCopilotServerSettingsCli:
    """Tests for `cloudways copilot server-settings` CLI command."""

    def test_copilot_server_settings_success(self, set_env) -> None:
        """copilot server-settings exits 0 and shows server data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "server-settings"])

        assert result.exit_code == 0
        assert "36780" in result.output

    def test_copilot_server_settings_error(self, set_env) -> None:
        """copilot server-settings API error exits 1."""
        handler, captured = _make_copilot_handler(server_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "server-settings"])

        assert result.exit_code == 1
        assert "API request failed with status 400" in result.output


class TestCopilotEnableInsightsCli:
    """Tests for `cloudways copilot enable-insights` CLI command."""

    def test_copilot_enable_insights_success(self, set_env) -> None:
        """copilot enable-insights exits 0 with success message."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "enable-insights", "--server-id", "36780"]
            )

        assert result.exit_code == 0
        assert "Success: Insights enabled for server 36780." in result.output
        # Verify POST body contains server_id and insights_enabled
        request = [r for r in captured if "/copilot/server-settings" in str(r.url)][-1]
        body = request.content.decode()
        assert "server_id" in body
        assert "insights_enabled" in body

    def test_copilot_enable_insights_error(self, set_env) -> None:
        """copilot enable-insights API error exits 1."""
        handler, captured = _make_copilot_handler(update_server_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "enable-insights", "--server-id", "36780"]
            )

        assert result.exit_code == 1


class TestCopilotDisableInsightsCli:
    """Tests for `cloudways copilot disable-insights` CLI command."""

    def test_copilot_disable_insights_success(self, set_env) -> None:
        """copilot disable-insights exits 0 with success message."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "disable-insights", "--server-id", "36780"]
            )

        assert result.exit_code == 0
        assert "Success: Insights disabled for server 36780." in result.output
        # Verify POST body contains server_id and insights_enabled
        request = [r for r in captured if "/copilot/server-settings" in str(r.url)][-1]
        body = request.content.decode()
        assert "server_id" in body
        assert "insights_enabled" in body

    def test_copilot_disable_insights_api_error(self, set_env) -> None:
        """copilot disable-insights API error exits 1."""
        handler, captured = _make_copilot_handler(update_server_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["copilot", "disable-insights", "--server-id", "36780"]
            )

        assert result.exit_code == 1


class TestCopilotInsightsCli:
    """Tests for `cloudways copilot insights` CLI command."""

    def test_copilot_insights_success(self, set_env) -> None:
        """copilot insights exits 0 and shows insight data."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "insights"])

        assert result.exit_code == 0
        assert "12345" in result.output or "Test insight" in result.output

    def test_copilot_insights_error(self, set_env) -> None:
        """copilot insights API error exits 1."""
        handler, captured = _make_copilot_handler(insights_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "insights"])

        assert result.exit_code == 1


class TestCopilotInsightCli:
    """Tests for `cloudways copilot insight` CLI command."""

    def test_copilot_insight_success(self, set_env) -> None:
        """copilot insight exits 0 and shows insight detail."""
        handler, captured = _make_copilot_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "insight", "12345"])

        assert result.exit_code == 0
        # Verify the alert_id was in the request URL
        request = [r for r in captured if "/insights/12345" in str(r.url)][-1]
        assert "12345" in str(request.url)

    def test_copilot_insight_not_found(self, set_env) -> None:
        """copilot insight with unknown ID exits 1."""
        handler, captured = _make_copilot_handler(insight_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.copilot.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["copilot", "insight", "99999"])

        assert result.exit_code == 1
