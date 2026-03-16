"""Tests for CloudwaysBot alerts commands and client methods.

Covers alert list, mark-as-read, mark-all-read commands with mocked
Cloudways API responses, plus client method tests for all Phase 1
alert operations and Phase 2 integration channel management.
"""

from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Handler factory ---


def _make_alerts_handler(
    alerts_response=None,
    alerts_error=False,
    alerts_page_response=None,
    alerts_page_error=False,
    mark_read_error=False,
    mark_all_read_error=False,
    integrations_response=None,
    integrations_error=False,
    create_integration_response=None,
    create_integration_error=False,
    integration_channels_response=None,
    integration_channels_error=False,
    update_integration_response=None,
    update_integration_error=False,
    delete_integration_error=False,
):
    """Build httpx mock handler for alert and integration API calls.

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

        # CRITICAL: /alert/markAllRead/ BEFORE /alert/markAsRead/
        # to avoid prefix collision
        if "/alert/markAllRead/" in url and method == "POST":
            if mark_all_read_error:
                return httpx.Response(422, text="Mark all read failed")
            return httpx.Response(200, content=b"")

        if "/alert/markAsRead/" in url and method == "POST":
            if mark_read_error:
                return httpx.Response(422, text="Mark read failed")
            return httpx.Response(200, content=b"")

        # /alerts/{last_id} — check for numeric suffix after /alerts/
        if "/alerts/" in url and method == "GET":
            # Check if there's a numeric ID after /alerts/
            path_part = url.split("/alerts/")[-1].split("?")[0]
            if path_part and path_part.isdigit():
                # Paginated request
                if alerts_page_error:
                    return httpx.Response(422, text="Alerts page failed")
                return httpx.Response(
                    200,
                    json=alerts_page_response
                    or {
                        "alerts": [
                            {
                                "id": 70001,
                                "details": {
                                    "subject": "Page alert",
                                    "desc": "Page description",
                                },
                            }
                        ]
                    },
                )
            # Non-paginated request (just /alerts/)
            if alerts_error:
                return httpx.Response(422, text="Alerts failed")
            return httpx.Response(
                200,
                json=alerts_response
                or {
                    "alerts": [
                        {
                            "id": 80001,
                            "details": {
                                "subject": "Test alert",
                                "desc": "Test description",
                            },
                        }
                    ]
                },
            )

        # CRITICAL: /integrations/create BEFORE /integrations
        # to avoid shorter prefix matching longer path
        if "/integrations/create" in url and method == "GET":
            if integration_channels_error:
                return httpx.Response(422, text="Channels lookup failed")
            return httpx.Response(
                200,
                json=integration_channels_response
                or {
                    "channels": [
                        {"id": 2, "name": "Email"},
                        {"id": 3, "name": "Slack"},
                    ],
                    "events": [
                        {"id": 1, "name": "Server down", "level": "critical"},
                        {"id": 2, "name": "Backup complete", "level": "info"},
                    ],
                },
            )

        # DELETE /integrations/{channel_id}
        if "/integrations/" in url and method == "DELETE":
            if delete_integration_error:
                return httpx.Response(422, text="Delete integration failed")
            return httpx.Response(200, content=b"")

        # PUT /integrations/{channel_id}
        if "/integrations/" in url and method == "PUT":
            if update_integration_error:
                return httpx.Response(422, text="Update integration failed")
            return httpx.Response(
                200,
                json=update_integration_response
                or {
                    "integration": {
                        "id": 5001,
                        "name": "Updated Channel",
                        "channel": 2,
                        "events": [1, 2],
                        "is_active": True,
                    }
                },
            )

        # POST /integrations (create new integration)
        if "/integrations" in url and method == "POST":
            if create_integration_error:
                return httpx.Response(422, text="Create integration failed")
            return httpx.Response(
                200,
                json=create_integration_response
                or {
                    "integration": {
                        "id": 9001,
                        "name": "My Channel",
                        "channel": 2,
                        "events": [1, 2],
                        "is_active": True,
                    }
                },
            )

        # GET /integrations (list all)
        if "/integrations" in url and method == "GET":
            if integrations_error:
                return httpx.Response(422, text="Integrations failed")
            return httpx.Response(
                200,
                json=integrations_response
                or {
                    "integrations": [
                        {
                            "id": 9001,
                            "name": "My Channel",
                            "channel": 2,
                            "events": [1, 2],
                            "is_active": True,
                        }
                    ]
                },
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests — Phase 1
# ===================================================================


class TestGetAlerts:
    """Tests for CloudwaysClient.get_alerts()."""

    @pytest.mark.asyncio
    async def test_get_alerts_success(self) -> None:
        """GET /alerts/ returns list of alerts."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alerts/" in str(request.url) and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "alerts": [
                            {
                                "id": 80001,
                                "details": {
                                    "subject": "Test alert",
                                    "desc": "Test description",
                                },
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_alerts()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 80001

    @pytest.mark.asyncio
    async def test_get_alerts_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alerts/" in str(request.url):
                return httpx.Response(422, text="Alerts failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_alerts()


class TestGetAlertsPage:
    """Tests for CloudwaysClient.get_alerts_page()."""

    @pytest.mark.asyncio
    async def test_get_alerts_page_success(self) -> None:
        """GET /alerts/{last_id} returns list and path param is in URL."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alerts/88888" in str(request.url) and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "alerts": [
                            {
                                "id": 70001,
                                "details": {
                                    "subject": "Page alert",
                                    "desc": "Page description",
                                },
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_alerts_page(88888)

        assert isinstance(result, list)
        request = [
            r for r in captured if r.method == "GET" and "/alerts/" in str(r.url)
        ][0]
        assert "/alerts/88888" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_alerts_page_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alerts/" in str(request.url):
                return httpx.Response(422, text="Alerts page failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_alerts_page(88888)


class TestMarkAlertRead:
    """Tests for CloudwaysClient.mark_alert_read()."""

    @pytest.mark.asyncio
    async def test_mark_alert_read_success(self) -> None:
        """POST /alert/markAsRead/{alert_id} returns {} and path param verified."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/alert/markAsRead/12345" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.mark_alert_read(12345)

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/alert/markAsRead/" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/alert/markAsRead/12345" in str(request.url)

    @pytest.mark.asyncio
    async def test_mark_alert_read_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alert/markAsRead/" in str(request.url):
                return httpx.Response(422, text="Mark read failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.mark_alert_read(12345)


class TestMarkAllAlertsRead:
    """Tests for CloudwaysClient.mark_all_alerts_read()."""

    @pytest.mark.asyncio
    async def test_mark_all_alerts_read_success(self) -> None:
        """POST /alert/markAllRead/ returns {}."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alert/markAllRead/" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.mark_all_alerts_read()

        assert result == {}

    @pytest.mark.asyncio
    async def test_mark_all_alerts_read_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/alert/markAllRead/" in str(request.url):
                return httpx.Response(422, text="Mark all read failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.mark_all_alerts_read()


# ===================================================================
# CLI command tests — Phase 1
# ===================================================================


class TestAlertsListCli:
    """Tests for `cloudways alerts list` command."""

    def test_alerts_list_success(self, set_env) -> None:
        """Without --page, calls GET /alerts/ and prints alert details."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "list"])

        assert result.exit_code == 0, result.output
        assert "Test alert" in result.output or "80001" in result.output

    def test_alerts_list_with_page(self, set_env) -> None:
        """With --page 88888, calls GET /alerts/88888 and prints alert details."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "list", "--page", "88888"])

        assert result.exit_code == 0, result.output
        assert "Page alert" in result.output or "70001" in result.output
        # Verify the paginated URL was hit
        alert_requests = [
            r
            for r in captured
            if "/alerts/" in str(r.url)
            and r.method == "GET"
            and "/oauth" not in str(r.url)
        ]
        assert any("/alerts/88888" in str(r.url) for r in alert_requests)

    def test_alerts_list_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(alerts_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "list"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestAlertsReadCli:
    """Tests for `cloudways alerts read <alert-id>` command."""

    def test_alerts_read_success(self, set_env) -> None:
        """Marks alert as read and prints confirmation."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "read", "12345"])

        assert result.exit_code == 0, result.output
        assert "marked as read" in result.output.lower()

    def test_alerts_read_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(mark_read_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "read", "12345"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestAlertsReadAllCli:
    """Tests for `cloudways alerts read-all` command."""

    def test_alerts_read_all_success(self, set_env) -> None:
        """Marks all alerts as read and prints confirmation."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "read-all"])

        assert result.exit_code == 0, result.output
        assert "all alerts marked as read" in result.output.lower()

    def test_alerts_read_all_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(mark_all_read_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "read-all"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


# ===================================================================
# CLI registration tests
# ===================================================================


class TestAlertsRegistration:
    """Tests for alerts command registration in CLI."""

    def test_alerts_in_main_help(self) -> None:
        """alerts appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "alerts" in result.output

    def test_alerts_subcommands_visible(self) -> None:
        """alerts --help shows list, read, read-all, channels subcommands."""
        result = runner.invoke(app, ["alerts", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "read" in result.output
        assert "read-all" in result.output
        assert "channels" in result.output

    def test_channels_subcommands_visible(self) -> None:
        """alerts channels --help shows list, available, add, update, delete."""
        result = runner.invoke(app, ["alerts", "channels", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "available" in result.output
        assert "add" in result.output
        assert "update" in result.output
        assert "delete" in result.output


# ===================================================================
# Client method tests — Phase 2
# ===================================================================


class TestGetIntegrations:
    """Tests for CloudwaysClient.get_integrations()."""

    @pytest.mark.asyncio
    async def test_get_integrations_success(self) -> None:
        """GET /integrations returns list of integrations."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations" in str(request.url) and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "integrations": [
                            {
                                "id": 9001,
                                "name": "My Channel",
                                "channel": 2,
                                "events": [1, 2],
                                "is_active": True,
                            }
                        ]
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_integrations()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == 9001

    @pytest.mark.asyncio
    async def test_get_integrations_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations" in str(request.url):
                return httpx.Response(422, text="Integrations failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_integrations()


class TestGetIntegrationChannels:
    """Tests for CloudwaysClient.get_integration_channels()."""

    @pytest.mark.asyncio
    async def test_get_integration_channels_success(self) -> None:
        """GET /integrations/create returns channels and events."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/integrations/create" in str(request.url)
                and request.method == "GET"
            ):
                return httpx.Response(
                    200,
                    json={
                        "channels": [{"id": 2, "name": "Email"}],
                        "events": [
                            {"id": 1, "name": "Server down", "level": "critical"}
                        ],
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_integration_channels()

        assert isinstance(result, dict)
        assert "channels" in result
        assert "events" in result

    @pytest.mark.asyncio
    async def test_get_integration_channels_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations/create" in str(request.url):
                return httpx.Response(422, text="Channels lookup failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_integration_channels()


class TestCreateIntegration:
    """Tests for CloudwaysClient.create_integration()."""

    @pytest.mark.asyncio
    async def test_create_integration_success(self) -> None:
        """POST /integrations with form body including events as repeated fields."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/integrations" in str(request.url)
                and "/integrations/create" not in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(
                    200,
                    json={
                        "integration": {
                            "id": 9001,
                            "name": "My Channel",
                            "channel": 2,
                            "events": [1, 2],
                            "is_active": True,
                        }
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.create_integration(
                name="My Channel",
                channel=2,
                events=[1, 2],
                to="user@example.com",
                url=None,
                is_active=True,
            )

        assert isinstance(result, dict)
        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/integrations" in str(r.url)
            and "/integrations/create" not in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/integrations" in str(request.url)
        decoded_body = request.content.decode()
        assert "name=" in decoded_body
        assert "channel=" in decoded_body
        assert "events=" in decoded_body
        assert "is_active=" in decoded_body

    @pytest.mark.asyncio
    async def test_create_integration_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations" in str(request.url) and request.method == "POST":
                return httpx.Response(422, text="Create integration failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.create_integration(
                    name="Fail Channel",
                    channel=2,
                    events=[1],
                )

    @pytest.mark.asyncio
    async def test_create_integration_optional_fields_omitted(self) -> None:
        """Optional fields to and url are omitted from body when None."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/integrations" in str(request.url)
                and "/integrations/create" not in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(
                    200,
                    json={
                        "integration": {
                            "id": 9002,
                            "name": "No Optional",
                            "channel": 3,
                            "events": [1],
                            "is_active": True,
                        }
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.create_integration(
                name="No Optional",
                channel=3,
                events=[1],
                to=None,
                url=None,
            )

        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/integrations" in str(r.url)
            and "/integrations/create" not in str(r.url)
        ][0]
        decoded_body = request.content.decode()
        assert "to=" not in decoded_body
        assert "url=" not in decoded_body


class TestUpdateIntegration:
    """Tests for CloudwaysClient.update_integration()."""

    @pytest.mark.asyncio
    async def test_update_integration_success(self) -> None:
        """PUT /integrations/{channel_id} with form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations/5001" in str(request.url) and request.method == "PUT":
                return httpx.Response(
                    200,
                    json={
                        "integration": {
                            "id": 5001,
                            "name": "Updated Channel",
                            "channel": 2,
                            "events": [1, 2],
                            "is_active": True,
                        }
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_integration(
                5001,
                name="Updated Channel",
                channel=2,
                events=[1, 2],
            )

        assert isinstance(result, dict)
        request = [
            r
            for r in captured
            if r.method == "PUT" and "/integrations/5001" in str(r.url)
        ][0]
        assert request.method == "PUT"
        assert "/integrations/5001" in str(request.url)
        decoded_body = request.content.decode()
        assert "events=" in decoded_body
        assert "name=" in decoded_body

    @pytest.mark.asyncio
    async def test_update_integration_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations/" in str(request.url) and request.method == "PUT":
                return httpx.Response(422, text="Update integration failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_integration(
                    5001,
                    name="Fail",
                    channel=2,
                    events=[1],
                )


class TestDeleteIntegration:
    """Tests for CloudwaysClient.delete_integration()."""

    @pytest.mark.asyncio
    async def test_delete_integration_success(self) -> None:
        """DELETE /integrations/{channel_id} returns {}."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations/5001" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_integration(5001)

        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_integration_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/integrations/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(422, text="Delete integration failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.delete_integration(5001)


# ===================================================================
# CLI command tests — Phase 2
# ===================================================================


class TestChannelsListCli:
    """Tests for `cloudways alerts channels list` command."""

    def test_channels_list_success(self, set_env) -> None:
        """Lists configured channels and prints details."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "channels", "list"])

        assert result.exit_code == 0, result.output
        assert "My Channel" in result.output or "9001" in result.output

    def test_channels_list_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(integrations_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "channels", "list"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestChannelsAvailableCli:
    """Tests for `cloudways alerts channels available` command."""

    def test_channels_available_success(self, set_env) -> None:
        """Lists available channel types and event types."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "channels", "available"])

        assert result.exit_code == 0, result.output
        assert "Email" in result.output or "Slack" in result.output

    def test_channels_available_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(integration_channels_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["alerts", "channels", "available"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestChannelsAddCli:
    """Tests for `cloudways alerts channels add` command."""

    def test_channels_add_success(self, set_env) -> None:
        """Creates a channel and prints confirmation."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "alerts",
                    "channels",
                    "add",
                    "--name",
                    "My Channel",
                    "--channel",
                    "2",
                    "--events",
                    "1,2",
                    "--to",
                    "user@example.com",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "created" in result.output.lower() or "Created" in result.output

    def test_channels_add_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(create_integration_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "alerts",
                    "channels",
                    "add",
                    "--name",
                    "Fail",
                    "--channel",
                    "2",
                    "--events",
                    "1",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_channels_add_invalid_events(self, set_env) -> None:
        """Non-integer events exits 1 with error."""
        result = runner.invoke(
            app,
            [
                "alerts",
                "channels",
                "add",
                "--name",
                "Bad",
                "--channel",
                "2",
                "--events",
                "abc",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid event ID" in result.output

    def test_channels_add_empty_events(self, set_env) -> None:
        """Empty events string exits 1 with error."""
        result = runner.invoke(
            app,
            [
                "alerts",
                "channels",
                "add",
                "--name",
                "Empty",
                "--channel",
                "2",
                "--events",
                "",
            ],
        )

        assert result.exit_code == 1
        assert "--events cannot be empty" in result.output


class TestChannelsUpdateCli:
    """Tests for `cloudways alerts channels update` command."""

    def test_channels_update_success(self, set_env) -> None:
        """Updates a channel and prints confirmation."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "alerts",
                    "channels",
                    "update",
                    "5001",
                    "--name",
                    "Updated",
                    "--channel",
                    "2",
                    "--events",
                    "1,2",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "updated" in result.output.lower()

    def test_channels_update_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(update_integration_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "alerts",
                    "channels",
                    "update",
                    "5001",
                    "--name",
                    "Fail",
                    "--channel",
                    "2",
                    "--events",
                    "1",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestChannelsDeleteCli:
    """Tests for `cloudways alerts channels delete` command."""

    def test_channels_delete_success(self, set_env) -> None:
        """Deletes a channel and prints confirmation."""
        handler, captured = _make_alerts_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["alerts", "channels", "delete", "5001"]
            )

        assert result.exit_code == 0, result.output
        assert "deleted" in result.output.lower() or "Deleted" in result.output

    def test_channels_delete_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_alerts_handler(delete_integration_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.alerts.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["alerts", "channels", "delete", "5001"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output
