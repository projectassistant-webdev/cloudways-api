"""Tests for Cloudflare analytics and logpush commands and client methods.

Covers GET /app/cloudflare/{app_id}/analytics, /security,
/logpush_analytics, and /logpush_security endpoints with mocked
Cloudways API responses, plus CLI command tests and registration tests.
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


def _make_cloudflare_handler(
    analytics_response=None,
    analytics_error=False,
    security_response=None,
    security_error=False,
    logpush_analytics_response=None,
    logpush_analytics_error=False,
    logpush_security_response=None,
    logpush_security_error=False,
):
    """Build httpx mock handler for Cloudflare analytics API calls.

    Returns a (handler, captured) tuple where captured is a mutable list
    that accumulates every httpx.Request seen by the handler.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        url = str(request.url)

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/cloudflare/" in url:
            # CRITICAL: check more-specific paths first to avoid prefix collision
            if "/logpush_security" in url:
                if logpush_security_error:
                    return httpx.Response(422, text="Logpush security failed")
                return httpx.Response(
                    200,
                    json=logpush_security_response
                    or {
                        "app_id": 3937401,
                        "cloudflare_zone_id": "zone123",
                        "security_events": [],
                        "period": "last_24h",
                        "generated_at": "2026-03-15T00:00:00Z",
                        "message": "",
                    },
                )
            if "/logpush_analytics" in url:
                if logpush_analytics_error:
                    return httpx.Response(422, text="Logpush analytics failed")
                return httpx.Response(
                    200,
                    json=logpush_analytics_response
                    or {
                        "app_id": 3937401,
                        "cloudflare_zone_id": "zone123",
                        "analytics": {},
                        "period": "last_24h",
                        "generated_at": "2026-03-15T00:00:00Z",
                        "message": "",
                    },
                )
            if "/analytics" in url:
                if analytics_error:
                    return httpx.Response(422, text="Analytics failed")
                return httpx.Response(
                    200,
                    json=analytics_response
                    or {"status": True, "data": [{"cachStatus": []}]},
                )
            if "/security" in url:
                if security_error:
                    return httpx.Response(422, text="Security failed")
                return httpx.Response(
                    200,
                    json=security_response
                    or {"status": True, "data": [{"eventByServices": []}]},
                )

        return httpx.Response(404)

    return handler, captured


# --- Helper ---


# =====================================================================
# Client Tests
# =====================================================================


class TestGetCloudflareAnalytics:
    """Tests for CloudwaysClient.get_cloudflare_analytics()."""

    @pytest.mark.asyncio
    async def test_get_cloudflare_analytics_success(self):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            result = await client.get_cloudflare_analytics(
                app_id=3937401, server_id=1089270, mins=60
            )

        assert isinstance(result, list)
        # Find the cloudflare analytics request (skip auth)
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        request = cf_requests[0]
        assert "/cloudflare/" in str(request.url)
        assert "/analytics" in str(request.url)
        assert "server_id" in str(request.url)
        assert "mins" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_cloudflare_analytics_api_error(self):
        handler, _ = _make_cloudflare_handler(analytics_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            with pytest.raises(APIError, match="API request failed with status 422"):
                await client.get_cloudflare_analytics(
                    app_id=3937401, server_id=1089270, mins=60
                )


class TestGetCloudflareSecurity:
    """Tests for CloudwaysClient.get_cloudflare_security()."""

    @pytest.mark.asyncio
    async def test_get_cloudflare_security_success(self):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            result = await client.get_cloudflare_security(
                app_id=3937401, server_id=1089270, mins=60
            )

        assert isinstance(result, list)
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        request = cf_requests[0]
        assert "/cloudflare/" in str(request.url)
        assert "/security" in str(request.url)
        assert "server_id" in str(request.url)
        assert "mins" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_cloudflare_security_api_error(self):
        handler, _ = _make_cloudflare_handler(security_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            with pytest.raises(APIError, match="API request failed with status 422"):
                await client.get_cloudflare_security(
                    app_id=3937401, server_id=1089270, mins=60
                )


class TestGetCloudflareLogpushAnalytics:
    """Tests for CloudwaysClient.get_cloudflare_logpush_analytics()."""

    @pytest.mark.asyncio
    async def test_get_cloudflare_logpush_analytics_success(self):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            result = await client.get_cloudflare_logpush_analytics(app_id=3937401)

        assert isinstance(result, dict)
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        request = cf_requests[0]
        assert "/cloudflare/" in str(request.url)
        assert "/logpush_analytics" in str(request.url)
        assert "server_id" not in str(request.url)

    @pytest.mark.asyncio
    async def test_get_cloudflare_logpush_analytics_api_error(self):
        handler, _ = _make_cloudflare_handler(logpush_analytics_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            with pytest.raises(APIError, match="API request failed with status 422"):
                await client.get_cloudflare_logpush_analytics(app_id=3937401)


class TestGetCloudflareLogpushSecurity:
    """Tests for CloudwaysClient.get_cloudflare_logpush_security()."""

    @pytest.mark.asyncio
    async def test_get_cloudflare_logpush_security_success(self):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            result = await client.get_cloudflare_logpush_security(app_id=3937401)

        assert isinstance(result, dict)
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        request = cf_requests[0]
        assert "/cloudflare/" in str(request.url)
        assert "/logpush_security" in str(request.url)
        assert "server_id" not in str(request.url)

    @pytest.mark.asyncio
    async def test_get_cloudflare_logpush_security_api_error(self):
        handler, _ = _make_cloudflare_handler(logpush_security_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@test.com", "key123") as client:
            with pytest.raises(APIError, match="API request failed with status 422"):
                await client.get_cloudflare_logpush_security(app_id=3937401)


# =====================================================================
# CLI Tests
# =====================================================================


class TestCloudflareAnalyticsCli:
    """Tests for `cloudways cloudflare analytics` CLI command."""

    def test_cloudflare_analytics_success(self, set_env):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["cloudflare", "analytics", "production"])

        assert result.exit_code == 0
        assert "[" in result.output or "{" in result.output
        assert "API request failed" not in result.output

    def test_cloudflare_analytics_custom_mins(self, set_env):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["cloudflare", "analytics", "production", "--mins", "1440"]
            )

        assert result.exit_code == 0
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        assert "mins=1440" in str(cf_requests[0].url)

    def test_cloudflare_analytics_api_error(self, set_env):
        handler, _ = _make_cloudflare_handler(analytics_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["cloudflare", "analytics", "production"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestCloudflareSecurityCli:
    """Tests for `cloudways cloudflare security` CLI command."""

    def test_cloudflare_security_success(self, set_env):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["cloudflare", "security", "production"])

        assert result.exit_code == 0
        assert "[" in result.output or "{" in result.output
        assert "API request failed" not in result.output

    def test_cloudflare_security_api_error(self, set_env):
        handler, _ = _make_cloudflare_handler(security_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["cloudflare", "security", "production"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestCloudflareLogpushCli:
    """Tests for `cloudways cloudflare logpush` CLI command."""

    def test_cloudflare_logpush_analytics_success(self, set_env):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                ["cloudflare", "logpush", "production", "--type", "analytics"],
            )

        assert result.exit_code == 0
        assert "{" in result.output
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        assert "/logpush_analytics" in str(cf_requests[0].url)

    def test_cloudflare_logpush_security_success(self, set_env):
        handler, captured = _make_cloudflare_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                ["cloudflare", "logpush", "production", "--type", "security"],
            )

        assert result.exit_code == 0
        assert "{" in result.output
        cf_requests = [r for r in captured if "/cloudflare/" in str(r.url)]
        assert len(cf_requests) == 1
        assert "/logpush_security" in str(cf_requests[0].url)

    def test_cloudflare_logpush_api_error(self, set_env):
        handler, _ = _make_cloudflare_handler(logpush_analytics_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.cloudflare.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                ["cloudflare", "logpush", "production", "--type", "analytics"],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


# =====================================================================
# Registration Tests
# =====================================================================


class TestCloudflareRegistration:
    """Verify cloudflare group is registered in CLI."""

    def test_cloudflare_in_main_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "cloudflare" in result.output

    def test_cloudflare_subcommands_visible(self):
        result = runner.invoke(app, ["cloudflare", "--help"])
        assert result.exit_code == 0
        assert "analytics" in result.output
        assert "security" in result.output
        assert "logpush" in result.output
