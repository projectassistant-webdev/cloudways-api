"""Integration tests for CloudwaysClient against the live Cloudways API.

These tests require real API credentials and will self-skip when
CLOUDWAYS_TEST_EMAIL and CLOUDWAYS_TEST_API_KEY are not set.
"""

import pytest

from cloudways_api.client import CloudwaysClient
from cloudways_api.exceptions import AuthenticationError

from .conftest import has_cloudways_credentials

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not has_cloudways_credentials(),
        reason="CLOUDWAYS_TEST_EMAIL and CLOUDWAYS_TEST_API_KEY not set",
    ),
]


class TestLiveAuthentication:
    """Test real OAuth authentication against Cloudways API."""

    @pytest.mark.asyncio
    async def test_authenticate_returns_token(
        self, cloudways_email, cloudways_api_key
    ):
        """Verify real OAuth token acquisition returns a non-empty string."""
        async with CloudwaysClient(cloudways_email, cloudways_api_key) as client:
            token = await client.authenticate()
            assert isinstance(token, str)
            assert len(token) > 0

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises_auth_error(self):
        """Verify that invalid credentials raise AuthenticationError."""
        async with CloudwaysClient(
            "invalid@example.com", "not-a-real-key"
        ) as client:
            with pytest.raises(AuthenticationError):
                await client.authenticate()


class TestLiveServerList:
    """Test real server listing against Cloudways API."""

    @pytest.mark.asyncio
    async def test_get_servers_returns_list(
        self, cloudways_email, cloudways_api_key
    ):
        """Verify real server list retrieval returns a list."""
        async with CloudwaysClient(cloudways_email, cloudways_api_key) as client:
            await client.authenticate()
            servers = await client.get_servers()
            assert isinstance(servers, list)

    @pytest.mark.asyncio
    async def test_get_server_details(
        self, cloudways_email, cloudways_api_key
    ):
        """Verify real server detail fetching returns expected structure."""
        async with CloudwaysClient(cloudways_email, cloudways_api_key) as client:
            await client.authenticate()
            servers = await client.get_servers()
            if servers:
                server = servers[0]
                assert "id" in server
                assert "label" in server
