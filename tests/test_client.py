"""Tests for the async API client with OAuth and retry logic."""

import time
from unittest.mock import patch

import httpx
import pytest

from cloudways_api.client import CloudwaysClient
from cloudways_api.exceptions import (
    APIError,
    AuthenticationError,
    OperationTimeoutError,
    ProvisioningError,
    RateLimitError,
    ServerError,
)


def _make_auth_response() -> dict:
    """Return a successful OAuth token response body."""
    return {
        "access_token": "test_token_abc123",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def _make_servers_response() -> dict:
    """Return a server list response body matching fixture data."""
    return {
        "status": True,
        "servers": [
            {
                "id": "999999",
                "label": "example-prod",
                "status": "running",
                "cloud": "do",
                "region": "nyc3",
                "public_ip": "1.2.3.4",
                "master_user": "master_example",
                "apps": [
                    {
                        "id": "1234567",
                        "label": "My WordPress App",
                        "application": "wordpress",
                        "app_version": "6.4",
                        "cname": "wp.example.com",
                        "server_id": "999999",
                        "sys_user": "appuser",
                        "mysql_db_name": "dbname",
                        "webroot": "public_html",
                    }
                ],
            }
        ],
    }


def _make_settings_response() -> dict:
    """Return a server settings response body."""
    return {
        "settings": {
            "package_versions": {
                "php": "8.1",
                "platform": "debian11",
                "mariadb": "10.6",
                "redis": "latest",
                "elasticsearch": "7.17",
            }
        }
    }


def _build_transport(handler):
    """Create an httpx.MockTransport from a handler function."""
    return httpx.MockTransport(handler)


class TestClientAuthentication:
    """Tests for OAuth authentication."""

    @pytest.mark.asyncio
    async def test_client_authenticates_with_correct_params(self) -> None:
        """Verify POST body includes email, api_key, grant_type=password."""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                captured_request["body"] = request.content.decode()
                captured_request["method"] = request.method
                captured_request["content_type"] = request.headers.get("content-type", "")
                return httpx.Response(200, json=_make_auth_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            token = await client.authenticate()

        assert token == "test_token_abc123"
        assert "email=test%40example.com" in captured_request["body"]
        assert "api_key=test_key" in captured_request["body"]
        assert "grant_type=password" in captured_request["body"]
        assert captured_request["method"] == "POST"

    @pytest.mark.asyncio
    async def test_client_caches_token_within_validity(self) -> None:
        """Two API calls should result in only one auth request."""
        auth_call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_call_count
            if "/oauth/access_token" in str(request.url):
                auth_call_count += 1
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client.get_servers()
            await client.get_servers()

        assert auth_call_count == 1

    @pytest.mark.asyncio
    async def test_client_refreshes_expired_token(self) -> None:
        """Token older than 3000s triggers re-authentication."""
        auth_call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_call_count
            if "/oauth/access_token" in str(request.url):
                auth_call_count += 1
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client.get_servers()
            # Simulate token expiry by backdating the timestamp
            client._token_obtained_at = time.monotonic() - 3100
            await client.get_servers()

        assert auth_call_count == 2

    @pytest.mark.asyncio
    async def test_client_auth_failure_raises_authentication_error(self) -> None:
        """401 response raises AuthenticationError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(
                    401,
                    json={
                        "error": "invalid_credentials",
                        "error_description": "The user credentials were incorrect.",
                    },
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="bad_key",
            transport=transport,
        ) as client:
            with pytest.raises(AuthenticationError):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_client_includes_bearer_token_header(self) -> None:
        """Verify Authorization: Bearer header is sent on API requests."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                captured_headers["authorization"] = request.headers.get(
                    "authorization", ""
                )
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client.get_servers()

        assert captured_headers["authorization"] == "Bearer test_token_abc123"

    @pytest.mark.asyncio
    async def test_client_grant_type_password_in_auth_request(self) -> None:
        """Verify grant_type=password is included in auth request body."""
        captured_body = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                captured_body["content"] = request.content.decode()
                return httpx.Response(200, json=_make_auth_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client.authenticate()

        assert "grant_type=password" in captured_body["content"]


class TestClientGetServers:
    """Tests for the get_servers method."""

    @pytest.mark.asyncio
    async def test_client_get_servers_returns_server_list(self) -> None:
        """Happy path for get_servers()."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            servers = await client.get_servers()

        assert len(servers) == 1
        assert servers[0]["id"] == "999999"
        assert servers[0]["label"] == "example-prod"


class TestClientGetServerSettings:
    """Tests for the get_server_settings method."""

    @pytest.mark.asyncio
    async def test_client_get_server_settings_returns_settings(self) -> None:
        """Happy path for get_server_settings()."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server/manage/settings" in str(request.url):
                return httpx.Response(200, json=_make_settings_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            settings = await client.get_server_settings(999999)

        assert settings["settings"]["package_versions"]["php"] == "8.1"
        assert settings["settings"]["package_versions"]["mariadb"] == "10.6"


class TestClientRetryLogic:
    """Tests for retry behavior on transient errors."""

    @pytest.mark.asyncio
    async def test_client_rate_limit_retries(self) -> None:
        """429 triggers retry after Retry-After delay."""
        attempt_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                attempt_count += 1
                if attempt_count == 1:
                    return httpx.Response(
                        429, headers={"Retry-After": "0"}
                    )
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            servers = await client.get_servers()

        assert len(servers) == 1
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_client_server_error_retries_with_backoff(self) -> None:
        """500/502/503 retry with exponential backoff."""
        attempt_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                attempt_count += 1
                if attempt_count <= 2:
                    return httpx.Response(500)
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        # Patch sleep to avoid real delays in tests
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com",
                api_key="test_key",
                transport=transport,
            ) as client:
                servers = await client.get_servers()

        assert len(servers) == 1
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_client_max_retries_raises_server_error(self) -> None:
        """After 3 retries for 5xx, raises ServerError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url):
                return httpx.Response(500)
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com",
                api_key="test_key",
                transport=transport,
            ) as client:
                with pytest.raises(ServerError):
                    await client.get_servers()

    @pytest.mark.asyncio
    async def test_client_rate_limit_max_retries_raises(self) -> None:
        """After 3 retries for 429, raises RateLimitError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url):
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(RateLimitError):
                await client.get_servers()


class TestClientErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_client_network_error_raises_api_error(self) -> None:
        """Connection failure raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="connect"):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_client_timeout_configured(self) -> None:
        """Verify the client timeout is set to 30 seconds."""
        transport = _build_transport(lambda r: httpx.Response(200))
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            assert client._http_client.timeout.connect == 30.0

    @pytest.mark.asyncio
    async def test_client_base_url_set_unconditionally(self) -> None:
        """H-1: base_url must always be set, even without mock transport."""
        # Without transport, the client should still have a base_url set
        client = CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
        )
        base = str(client._http_client.base_url).rstrip("/")
        assert base == "https://api.cloudways.com/api/v2"
        await client._http_client.aclose()

    @pytest.mark.asyncio
    async def test_client_base_url_set_with_transport(self) -> None:
        """H-1: base_url also set when transport is provided."""
        transport = _build_transport(lambda r: httpx.Response(200))
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            base = str(client._http_client.base_url).rstrip("/")
            assert base == "https://api.cloudways.com/api/v2"

    @pytest.mark.asyncio
    async def test_client_uses_relative_paths_for_auth(self) -> None:
        """H-1: auth request uses relative path /oauth/access_token."""
        captured_url = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_url["path"] = str(request.url)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client.authenticate()

        # Should use the BASE_URL + relative path
        assert "api.cloudways.com" in captured_url["path"]
        assert "/oauth/access_token" in captured_url["path"]

    @pytest.mark.asyncio
    async def test_client_malformed_json_response_raises_api_error(self) -> None:
        """H-2: Non-JSON response during auth raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, text="not json at all")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="Unexpected response format"):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_client_missing_access_token_key_raises_api_error(self) -> None:
        """H-2: JSON response missing access_token key raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json={"token_type": "Bearer"})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="Unexpected response format"):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_client_malformed_json_on_api_request_raises_api_error(self) -> None:
        """H-2: Non-JSON success response on API request raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(200, text="not json")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="Unexpected response format"):
                await client.get_servers()

    @pytest.mark.asyncio
    async def test_client_retry_after_header_non_numeric(self) -> None:
        """M-4: Non-numeric Retry-After header falls back to default delay."""
        attempt_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                attempt_count += 1
                if attempt_count == 1:
                    return httpx.Response(
                        429, headers={"Retry-After": "not-a-number"}
                    )
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None) as mock_sleep:
            async with CloudwaysClient(
                email="test@example.com",
                api_key="test_key",
                transport=transport,
            ) as client:
                servers = await client.get_servers()

        assert len(servers) == 1
        assert attempt_count == 2
        # Should have used default delay (30 seconds)
        mock_sleep.assert_called_with(30)

    @pytest.mark.asyncio
    async def test_client_401_on_api_call_triggers_reauth(self) -> None:
        """401 on an API call invalidates token and retries once."""
        auth_count = 0
        api_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_count, api_count
            if "/oauth/access_token" in str(request.url):
                auth_count += 1
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                api_count += 1
                if api_count == 1:
                    return httpx.Response(401, json={"error": "invalid_token"})
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            servers = await client.get_servers()

        assert len(servers) == 1
        assert auth_count == 2  # Initial auth + re-auth after 401


# ------------------------------------------------------------------
# Phase 4A: Exception hierarchy tests
# ------------------------------------------------------------------


class TestProvisioningExceptions:
    """Tests for ProvisioningError and OperationTimeoutError."""

    def test_provisioning_error_is_cloudways_error_subclass(self) -> None:
        """ProvisioningError inherits from CloudwaysError."""
        from cloudways_api.exceptions import CloudwaysError

        err = ProvisioningError("test")
        assert isinstance(err, CloudwaysError)

    def test_operation_timeout_error_is_provisioning_error_subclass(self) -> None:
        """OperationTimeoutError inherits from ProvisioningError."""
        err = OperationTimeoutError(operation_id=123, elapsed=601.0, max_wait=600)
        assert isinstance(err, ProvisioningError)

    def test_operation_timeout_error_stores_attributes(self) -> None:
        """OperationTimeoutError stores operation_id, elapsed, max_wait."""
        err = OperationTimeoutError(operation_id=99, elapsed=305.5, max_wait=300)
        assert err.operation_id == 99
        assert err.elapsed == 305.5
        assert err.max_wait == 300

    def test_operation_timeout_error_message_format(self) -> None:
        """OperationTimeoutError has a human-readable message."""
        err = OperationTimeoutError(operation_id=42, elapsed=610.0, max_wait=600)
        assert "42" in str(err)
        assert "600" in str(err)
        assert "610" in str(err)


# ------------------------------------------------------------------
# Phase 4A: POST data support tests
# ------------------------------------------------------------------


class TestClientPostDataSupport:
    """Tests for _api_request data parameter (POST body support)."""

    @pytest.mark.asyncio
    async def test_api_request_sends_data_as_form_body(self) -> None:
        """data parameter is sent as form-encoded POST body."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and request.method == "POST":
                captured["body"] = request.content.decode()
                captured["method"] = request.method
                return httpx.Response(
                    200,
                    json={"server": {"id": "123"}, "operation_id": 99, "status": True},
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client._api_request(
                "POST",
                "/server",
                data={"cloud": "do", "region": "nyc3"},
            )

        assert captured["method"] == "POST"
        assert "cloud=do" in captured["body"]
        assert "region=nyc3" in captured["body"]

    @pytest.mark.asyncio
    async def test_api_request_without_data_backward_compatible(self) -> None:
        """GET requests without data parameter work as before."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                return httpx.Response(200, json=_make_servers_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            servers = await client.get_servers()

        assert len(servers) == 1

    @pytest.mark.asyncio
    async def test_api_request_data_preserved_in_reauth_retry(self) -> None:
        """data is passed through in the recursive 401 re-auth call."""
        api_call_count = 0
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal api_call_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and request.method == "POST":
                api_call_count += 1
                captured_bodies.append(request.content.decode())
                if api_call_count == 1:
                    return httpx.Response(401, json={"error": "expired"})
                return httpx.Response(
                    200,
                    json={"server": {"id": "123"}, "operation_id": 99, "status": True},
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            await client._api_request(
                "POST", "/server", data={"cloud": "do", "region": "nyc3"}
            )

        assert api_call_count == 2
        # Both attempts should have the same body data
        assert "cloud=do" in captured_bodies[0]
        assert "cloud=do" in captured_bodies[1]

    @pytest.mark.asyncio
    async def test_api_request_data_preserved_in_server_error_retry(self) -> None:
        """data is preserved across 5xx retries."""
        attempt_count = 0
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and request.method == "POST":
                attempt_count += 1
                captured_bodies.append(request.content.decode())
                if attempt_count == 1:
                    return httpx.Response(500)
                return httpx.Response(
                    200,
                    json={"server": {"id": "123"}, "operation_id": 99, "status": True},
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com",
                api_key="test_key",
                transport=transport,
            ) as client:
                await client._api_request(
                    "POST", "/server", data={"cloud": "do"}
                )

        assert attempt_count == 2
        assert "cloud=do" in captured_bodies[0]
        assert "cloud=do" in captured_bodies[1]


# ------------------------------------------------------------------
# Phase 4A: Metadata method tests
# ------------------------------------------------------------------


def _make_provider_response() -> dict:
    """Return provider list response body."""
    return {
        "providers": [
            {"id": "do", "name": "DigitalOcean"},
            {"id": "vultr", "name": "Vultr"},
        ]
    }


def _make_region_response() -> dict:
    """Return region list response body for DigitalOcean."""
    return {
        "regions": [
            {"id": "nyc1", "name": "New York 1"},
            {"id": "nyc3", "name": "New York 3"},
            {"id": "sfo1", "name": "San Francisco 1"},
            {"id": "lon1", "name": "London 1"},
        ]
    }


def _make_sizes_response() -> dict:
    """Return server sizes response body for DigitalOcean."""
    return {
        "sizes": [
            {"id": "1GB", "name": "1GB RAM"},
            {"id": "2GB", "name": "2GB RAM"},
            {"id": "4GB", "name": "4GB RAM"},
        ]
    }


def _make_app_types_response() -> dict:
    """Return application types response body."""
    return {
        "app_list": [
            {"label": "WordPress", "value": "wordpress", "versions": ["6.5", "6.4"]},
            {"label": "PHP Laravel", "value": "phplaravel", "versions": ["11.0", "10.0"]},
        ]
    }


def _make_create_server_response() -> dict:
    """Return server creation response body."""
    return {
        "server": {"id": "1234567"},
        "operation_id": 98765,
        "status": True,
    }


def _make_create_app_response() -> dict:
    """Return app creation response body."""
    return {
        "app_id": "9876543",
        "operation_id": 98766,
        "status": True,
    }


def _make_operation_response(is_completed: bool) -> dict:
    """Return operation status response body."""
    return {
        "operation": {
            "id": 98765,
            "is_completed": is_completed,
            "status": "completed" if is_completed else "in_progress",
        }
    }


class TestClientMetadataMethods:
    """Tests for metadata retrieval methods (GET, no side effects)."""

    @pytest.mark.asyncio
    async def test_get_provider_list_returns_providers(self) -> None:
        """get_provider_list() returns list of providers from GET /provider."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/provider"):
                return httpx.Response(200, json=_make_provider_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            providers = await client.get_provider_list()

        assert len(providers) == 2
        assert providers[0]["id"] == "do"

    @pytest.mark.asyncio
    async def test_get_region_list_returns_regions_for_provider(self) -> None:
        """get_region_list() returns regions for given provider."""
        captured_params = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/region" in str(request.url):
                captured_params["url"] = str(request.url)
                return httpx.Response(200, json=_make_region_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            regions = await client.get_region_list("do")

        assert len(regions) == 4
        assert regions[0]["id"] == "nyc1"
        assert "provider=do" in captured_params["url"]

    @pytest.mark.asyncio
    async def test_get_server_sizes_returns_sizes_for_provider(self) -> None:
        """get_server_sizes() returns sizes for given provider."""
        captured_params = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server_size" in str(request.url):
                captured_params["url"] = str(request.url)
                return httpx.Response(200, json=_make_sizes_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            sizes = await client.get_server_sizes("do")

        assert len(sizes) == 3
        assert sizes[1]["id"] == "2GB"
        assert "provider=do" in captured_params["url"]

    @pytest.mark.asyncio
    async def test_get_app_types_returns_app_list(self) -> None:
        """get_app_types() returns list of application types."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app_list" in str(request.url):
                return httpx.Response(200, json=_make_app_types_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            app_types = await client.get_app_types()

        assert len(app_types) == 2
        assert app_types[0]["value"] == "wordpress"


# ------------------------------------------------------------------
# Phase 4A: Mutation method tests
# ------------------------------------------------------------------


class TestClientMutationMethods:
    """Tests for create_server() and create_app() (POST, side effects)."""

    @pytest.mark.asyncio
    async def test_create_server_sends_post_with_all_params(self) -> None:
        """create_server() sends POST /server with all params as form data."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/server") and request.method == "POST":
                captured["body"] = request.content.decode()
                captured["method"] = request.method
                return httpx.Response(200, json=_make_create_server_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            await client.create_server(
                cloud="do",
                region="nyc3",
                instance_type="2GB",
                application="wordpress",
                app_version="6.5",
                server_label="test-server",
                app_label="test-app",
                project_name="Test",
            )

        assert captured["method"] == "POST"
        body = captured["body"]
        assert "cloud=do" in body
        assert "region=nyc3" in body
        assert "instance_type=2GB" in body
        assert "application=wordpress" in body
        assert "server_label=test-server" in body

    @pytest.mark.asyncio
    async def test_create_server_returns_operation_id(self) -> None:
        """create_server() returns response with operation_id."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/server") and request.method == "POST":
                return httpx.Response(200, json=_make_create_server_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.create_server(
                cloud="do", region="nyc3", instance_type="2GB",
                application="wordpress", app_version="6.5",
                server_label="s", app_label="a", project_name="P",
            )

        assert result["operation_id"] == 98765
        assert result["server"]["id"] == "1234567"

    @pytest.mark.asyncio
    async def test_create_server_api_error_raises_provisioning_error(self) -> None:
        """4xx response on create_server() raises ProvisioningError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/server") and request.method == "POST":
                return httpx.Response(422, text="Insufficient quota")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            with pytest.raises(ProvisioningError, match="Server creation failed"):
                await client.create_server(
                    cloud="do", region="nyc3", instance_type="2GB",
                    application="wordpress", app_version="6.5",
                    server_label="s", app_label="a", project_name="P",
                )

    @pytest.mark.asyncio
    async def test_create_app_sends_post_with_all_params(self) -> None:
        """create_app() sends POST /app with all params as form data."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/app") and request.method == "POST":
                captured["body"] = request.content.decode()
                captured["method"] = request.method
                return httpx.Response(200, json=_make_create_app_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            await client.create_app(
                server_id=999999,
                application="wordpress",
                app_version="6.5",
                app_label="my-app",
                project_name="Default",
            )

        assert captured["method"] == "POST"
        body = captured["body"]
        assert "server_id=999999" in body
        assert "application=wordpress" in body
        assert "app_label=my-app" in body

    @pytest.mark.asyncio
    async def test_create_app_returns_operation_id(self) -> None:
        """create_app() returns response with operation_id."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/app") and request.method == "POST":
                return httpx.Response(200, json=_make_create_app_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.create_app(
                server_id=999999, application="wordpress",
                app_version="6.5", app_label="a", project_name="P",
            )

        assert result["operation_id"] == 98766
        assert result["app_id"] == "9876543"

    @pytest.mark.asyncio
    async def test_create_app_api_error_raises_provisioning_error(self) -> None:
        """4xx response on create_app() raises ProvisioningError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/app") and request.method == "POST":
                return httpx.Response(422, text="Invalid server")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            with pytest.raises(ProvisioningError, match="App creation failed"):
                await client.create_app(
                    server_id=999999, application="wordpress",
                    app_version="6.5", app_label="a", project_name="P",
                )


# ------------------------------------------------------------------
# Phase 4A: Post-creation configuration tests
# ------------------------------------------------------------------


class TestClientPostCreationConfig:
    """Tests for update_php_version() and add_domain()."""

    @pytest.mark.asyncio
    async def test_update_php_version_sends_put_with_params(self) -> None:
        """update_php_version() sends PUT to /app/manage/fpm_setting."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/manage/fpm_setting" in str(request.url):
                captured["method"] = request.method
                captured["body"] = request.content.decode()
                return httpx.Response(200, json={"status": True})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.update_php_version(
                server_id=999999, app_id="1234567", php_version="8.2"
            )

        assert captured["method"] == "PUT"
        assert "server_id=999999" in captured["body"]
        assert "app_id=1234567" in captured["body"]
        assert "php_version=8.2" in captured["body"]
        assert result["status"] is True

    @pytest.mark.asyncio
    async def test_add_domain_sends_post_with_params(self) -> None:
        """add_domain() sends POST to /app/manage/cname."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/manage/cname" in str(request.url):
                captured["method"] = request.method
                captured["body"] = request.content.decode()
                return httpx.Response(200, json={"status": True})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.add_domain(
                server_id=999999, app_id="1234567", domain="example.com"
            )

        assert captured["method"] == "POST"
        assert "server_id=999999" in captured["body"]
        assert "app_id=1234567" in captured["body"]
        assert "cname=example.com" in captured["body"]
        assert result["status"] is True


# ------------------------------------------------------------------
# Phase 4A: Operation polling tests
# ------------------------------------------------------------------


class TestClientOperationPolling:
    """Tests for get_operation_status() and wait_for_operation()."""

    @pytest.mark.asyncio
    async def test_get_operation_status_returns_operation_dict(self) -> None:
        """get_operation_status() calls GET /operation/{id}."""
        captured_url = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                captured_url["url"] = str(request.url)
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=True)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.get_operation_status(98765)

        assert result["operation"]["id"] == 98765
        assert result["operation"]["is_completed"] is True
        assert "/operation/98765" in captured_url["url"]

    @pytest.mark.asyncio
    async def test_wait_for_operation_returns_on_immediate_completion(self) -> None:
        """wait_for_operation() returns immediately if first poll shows completed."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=True)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com", api_key="test_key", transport=transport
            ) as client:
                result = await client.wait_for_operation(98765)

        assert result["operation"]["is_completed"] is True

    @pytest.mark.asyncio
    async def test_wait_for_operation_polls_until_complete(self) -> None:
        """wait_for_operation() polls multiple times until completed."""
        poll_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal poll_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                poll_count += 1
                is_done = poll_count >= 3
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=is_done)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com", api_key="test_key", transport=transport
            ) as client:
                result = await client.wait_for_operation(98765)

        assert result["operation"]["is_completed"] is True
        assert poll_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_operation_raises_timeout(self) -> None:
        """wait_for_operation() raises OperationTimeoutError on timeout."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=False)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        # Make time.monotonic() advance rapidly to trigger timeout
        start_time = time.monotonic()
        call_count = 0

        def mock_monotonic():
            nonlocal call_count
            call_count += 1
            # Each call advances time by 100 seconds
            return start_time + (call_count * 100)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.client.time.monotonic", side_effect=mock_monotonic):
                async with CloudwaysClient(
                    email="test@example.com", api_key="test_key", transport=transport
                ) as client:
                    with pytest.raises(OperationTimeoutError) as exc_info:
                        await client.wait_for_operation(98765, max_wait=600)

        assert exc_info.value.operation_id == 98765
        assert exc_info.value.max_wait == 600

    @pytest.mark.asyncio
    async def test_wait_for_operation_initial_delay_5_seconds(self) -> None:
        """wait_for_operation() sleeps 5 seconds before first poll."""
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=True)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", side_effect=mock_sleep):
            async with CloudwaysClient(
                email="test@example.com", api_key="test_key", transport=transport
            ) as client:
                await client.wait_for_operation(98765)

        # First sleep should be 5 seconds (initial delay)
        assert sleep_calls[0] == 5

    @pytest.mark.asyncio
    async def test_wait_for_operation_polls_at_interval(self) -> None:
        """wait_for_operation() sleeps poll_interval between polls."""
        sleep_calls = []
        poll_count = 0

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal poll_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                poll_count += 1
                is_done = poll_count >= 2
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=is_done)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", side_effect=mock_sleep):
            async with CloudwaysClient(
                email="test@example.com", api_key="test_key", transport=transport
            ) as client:
                await client.wait_for_operation(98765, poll_interval=15)

        # First: 5s initial delay, second: 15s poll interval
        assert sleep_calls[0] == 5
        assert sleep_calls[1] == 15

    @pytest.mark.asyncio
    async def test_wait_for_operation_custom_timeout_and_interval(self) -> None:
        """wait_for_operation() respects custom max_wait and poll_interval."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/operation/" in str(request.url):
                return httpx.Response(
                    200, json=_make_operation_response(is_completed=False)
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        start_time = time.monotonic()
        call_count = 0

        def mock_monotonic():
            nonlocal call_count
            call_count += 1
            return start_time + (call_count * 50)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.client.time.monotonic", side_effect=mock_monotonic):
                async with CloudwaysClient(
                    email="test@example.com", api_key="test_key", transport=transport
                ) as client:
                    with pytest.raises(OperationTimeoutError) as exc_info:
                        await client.wait_for_operation(
                            98765, max_wait=120, poll_interval=5
                        )

        assert exc_info.value.max_wait == 120

    @pytest.mark.asyncio
    async def test_create_server_retry_on_server_error_preserves_data(self) -> None:
        """500 then success on create_server preserves POST data."""
        attempt_count = 0
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if str(request.url).endswith("/server") and request.method == "POST":
                attempt_count += 1
                captured_bodies.append(request.content.decode())
                if attempt_count == 1:
                    return httpx.Response(500)
                return httpx.Response(200, json=_make_create_server_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            async with CloudwaysClient(
                email="test@example.com", api_key="test_key", transport=transport
            ) as client:
                result = await client.create_server(
                    cloud="do", region="nyc3", instance_type="2GB",
                    application="wordpress", app_version="6.5",
                    server_label="s", app_label="a", project_name="P",
                )

        assert attempt_count == 2
        assert result["operation_id"] == 98765
        # Verify data was preserved in retry
        assert "cloud=do" in captured_bodies[0]
        assert "cloud=do" in captured_bodies[1]


# ------------------------------------------------------------------
# Phase 6B: Additional auth and request error coverage
# ------------------------------------------------------------------


class TestClientAuthEdgeCases:
    """Tests for uncovered auth error paths."""

    @pytest.mark.asyncio
    async def test_http_error_during_auth_raises_api_error(self) -> None:
        """Generic httpx.HTTPError during auth raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                raise httpx.ReadTimeout("Read timed out")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="HTTP error during authentication"):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_unexpected_status_500_during_auth_raises_api_error(self) -> None:
        """Non-401, non-200 status during auth raises APIError with status code."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(500, text="Internal Server Error")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="Unexpected status 500"):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_double_401_reauth_raises_authentication_error(self) -> None:
        """401 on API call after re-authentication raises AuthenticationError."""
        auth_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_count
            if "/oauth/access_token" in str(request.url):
                auth_count += 1
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url) and "settings" not in str(request.url):
                # Always return 401 - both first try and re-auth retry
                return httpx.Response(401, json={"error": "invalid_token"})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(AuthenticationError, match="re-authentication"):
                await client.get_servers()

        # Should have authenticated twice (initial + re-auth)
        assert auth_count == 2


class TestClientRequestEdgeCases:
    """Tests for uncovered API request error paths."""

    @pytest.mark.asyncio
    async def test_http_error_during_api_request_raises_api_error(self) -> None:
        """Generic httpx.HTTPError during API request raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url):
                raise httpx.ReadTimeout("Read timed out")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="HTTP error"):
                await client.get_servers()

    @pytest.mark.asyncio
    async def test_connect_error_during_api_request_raises_api_error(self) -> None:
        """ConnectError during API request (not auth) raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url):
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="connect"):
                await client.get_servers()

    @pytest.mark.asyncio
    async def test_4xx_non_retry_raises_api_error(self) -> None:
        """Non-401/429 4xx status raises APIError immediately (no retry)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/server" in str(request.url):
                return httpx.Response(
                    403, text="Forbidden: insufficient permissions"
                )
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com",
            api_key="test_key",
            transport=transport,
        ) as client:
            with pytest.raises(APIError, match="403"):
                await client.get_servers()


# ------------------------------------------------------------------
# Phase 1 (REQ-API-009): Staging and reset_permissions client methods
# ------------------------------------------------------------------


def _make_staging_app_response() -> dict:
    """Return staging app creation response body."""
    return {
        "app": {"id": "5551234"},
        "operation_id": 77001,
        "status": True,
    }


class TestCreateStagingApp:
    """Tests for create_staging_app() method (REQ-009-1.1)."""

    @pytest.mark.asyncio
    async def test_create_staging_app_success(self) -> None:
        """create_staging_app() sends POST /app/clone with correct body fields."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/clone" in str(request.url) and request.method == "POST":
                captured["body"] = request.content.decode()
                captured["method"] = request.method
                return httpx.Response(200, json=_make_staging_app_response())
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.create_staging_app(
                server_id=999999,
                app_id=1234567,
                app_label="staging-production",
                project_name="Default",
            )

        assert captured["method"] == "POST"
        body = captured["body"]
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "app_label=staging-production" in body
        assert "project_name=Default" in body
        assert result["app"]["id"] == "5551234"
        assert result["operation_id"] == 77001

    @pytest.mark.asyncio
    async def test_create_staging_app_4xx_raises_provisioning_error(self) -> None:
        """4xx response on create_staging_app() raises ProvisioningError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/clone" in str(request.url) and request.method == "POST":
                return httpx.Response(422, text="Invalid staging request")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            with pytest.raises(ProvisioningError, match="Staging app creation failed"):
                await client.create_staging_app(
                    server_id=999999,
                    app_id=1,
                    app_label="bad",
                    project_name="P",
                )


class TestResetPermissions:
    """Tests for reset_permissions() method (REQ-009-1.2)."""

    @pytest.mark.asyncio
    async def test_reset_permissions_success(self) -> None:
        """reset_permissions() sends POST with correct params and data."""
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/manage/reset_permissions" in str(request.url) and request.method == "POST":
                captured["url"] = str(request.url)
                captured["body"] = request.content.decode()
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            result = await client.reset_permissions(
                server_id=999999, app_id=1234567
            )

        # Verify query params
        assert "ownership=sys_user" in captured["url"]
        # Verify form body
        assert "server_id=999999" in captured["body"]
        assert "app_id=1234567" in captured["body"]
        assert result == {}

    @pytest.mark.asyncio
    async def test_reset_permissions_api_error(self) -> None:
        """4xx response on reset_permissions() raises APIError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=_make_auth_response())
            if "/app/manage/reset_permissions" in str(request.url):
                return httpx.Response(400, text="Bad request")
            return httpx.Response(404)

        transport = _build_transport(handler)
        async with CloudwaysClient(
            email="test@example.com", api_key="test_key", transport=transport
        ) as client:
            with pytest.raises(APIError, match="400"):
                await client.reset_permissions(server_id=999, app_id=111)
