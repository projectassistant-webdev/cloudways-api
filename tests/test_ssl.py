"""Tests for SSL certificate management commands and client methods.

Covers Let's Encrypt install/renew/auto/revoke, wildcard DNS two-step flow,
custom SSL install/remove commands with mocked Cloudways API responses,
plus client method tests for all eight SSL operations.
"""

import json as json_lib
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Handler factory ---


def _make_ssl_handler(
    install_le_response=None,
    create_dns_response=None,
    verify_dns_response=None,
    renew_le_response=None,
    auto_le_response=None,
    revoke_le_response=None,
    install_custom_response=None,
    remove_custom_response=None,
    # error flags
    install_le_error=False,
    create_dns_error=False,
    verify_dns_error=False,
    renew_le_error=False,
    auto_le_error=False,
    revoke_le_error=False,
    install_custom_error=False,
    remove_custom_error=False,
):
    """Build httpx mock handler for SSL certificate API calls.

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

        # URL matching order: longer paths first to avoid substring collisions
        if "/security/lets_encrypt_manual_renew" in url and method == "POST":
            if renew_le_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=renew_le_response or {"operation_id": 12345}
            )

        if "/security/lets_encrypt_install" in url and method == "POST":
            if install_le_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=install_le_response or {"operation_id": 12345}
            )

        if "/security/lets_encrypt_auto" in url and method == "POST":
            if auto_le_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=auto_le_response or {})

        if "/security/lets_encrypt_revoke" in url and method == "POST":
            if revoke_le_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=revoke_le_response or {"operation_id": 12345}
            )

        if "/security/createDNS" in url and method == "POST":
            if create_dns_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200,
                json=create_dns_response
                or {
                    "wildcard_ssl": {
                        "message": "DNS records created",
                        "status": True,
                        "wildcard": {
                            "app_prefix": "woocommerce-111-160.cloudwaysapps.com",
                            "ssl_domains": ["example.com"],
                            "ssl_email": "admin@example.com",
                        },
                    }
                },
            )

        if "/security/verifyDNS" in url and method == "POST":
            if verify_dns_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200,
                json=verify_dns_response
                or {
                    "wildcard_ssl": {
                        "message": "Your domain is mapped, kindly proceed",
                        "status": True,
                        "wildcard": {
                            "app_prefix": "woocommerce-111-160.cloudwaysapps.com",
                            "ssl_domains": ["example.com"],
                            "ssl_email": "admin@example.com",
                        },
                    }
                },
            )

        if "/security/ownSSL" in url and method == "POST":
            if install_custom_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=install_custom_response or {})

        if "/security/removeCustomSSL" in url and method == "DELETE":
            if remove_custom_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=remove_custom_response or {"operation_id": 12345}
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests
# ===================================================================


class TestInstallLetsEncrypt:
    """Tests for CloudwaysClient.install_lets_encrypt()."""

    @pytest.mark.asyncio
    async def test_install_lets_encrypt_success(self) -> None:
        """POST /security/lets_encrypt_install with all required fields."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_install" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.install_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com"],
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_install" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/security/lets_encrypt_install" in str(request.url)
        data = json_lib.loads(request.content.decode())
        assert data["server_id"] == 1089270
        assert data["app_id"] == 3937401
        assert "admin" in data["ssl_email"]
        assert data["ssl_domains"] == ["example.com"]
        assert data["wild_card"] is False

    @pytest.mark.asyncio
    async def test_install_lets_encrypt_empty_domains(self) -> None:
        """POST with empty domains list still succeeds (API-level validation)."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_install" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.install_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=[],
            )

        assert result == {"operation_id": 12345}

    @pytest.mark.asyncio
    async def test_install_lets_encrypt_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/lets_encrypt_install" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.install_lets_encrypt(
                    server_id=1089270,
                    app_id=3937401,
                    ssl_email="admin@example.com",
                    ssl_domains=["example.com"],
                )


class TestInstallLetsEncryptArrayEncoding:
    """Tests for ssl_domains JSON array encoding."""

    @pytest.mark.asyncio
    async def test_install_lets_encrypt_array_encoding(self) -> None:
        """POST with two domains produces JSON array body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_install" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.install_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com", "www.example.com"],
            )

        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_install" in str(r.url)
        ][0]
        assert request.headers["content-type"] == "application/json"
        data = json_lib.loads(request.content.decode())
        assert data["ssl_domains"] == ["example.com", "www.example.com"]


class TestCreateWildcardDns:
    """Tests for CloudwaysClient.create_wildcard_dns()."""

    @pytest.mark.asyncio
    async def test_create_wildcard_dns_success(self) -> None:
        """POST /security/createDNS with body and response assertions."""
        captured = []
        dns_response = {
            "wildcard_ssl": {
                "message": "DNS records created",
                "status": True,
                "wildcard": {
                    "app_prefix": "woocommerce-111-160.cloudwaysapps.com",
                    "ssl_domains": ["example.com"],
                    "ssl_email": "admin@example.com",
                },
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/createDNS" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json=dns_response)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.create_wildcard_dns(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com"],
            )

        assert result == dns_response
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/createDNS" in str(r.url)
        ][0]
        data = json_lib.loads(request.content.decode())
        assert data["server_id"] == 1089270
        assert data["app_id"] == 3937401
        assert data["wild_card"] is True
        assert data["ssl_domains"] == ["example.com"]

    @pytest.mark.asyncio
    async def test_create_wildcard_dns_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/createDNS" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.create_wildcard_dns(
                    server_id=1089270,
                    app_id=3937401,
                    ssl_email="admin@example.com",
                    ssl_domains=["example.com"],
                )

    @pytest.mark.asyncio
    async def test_create_wildcard_dns_wild_card_always_true(self) -> None:
        """Method always sends wild_card=True regardless of caller."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/createDNS" in str(request.url) and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "wildcard_ssl": {"message": "", "status": True, "wildcard": {}}
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.create_wildcard_dns(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com"],
            )

        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/createDNS" in str(r.url)
        ][0]
        data = json_lib.loads(request.content.decode())
        assert data["wild_card"] is True


class TestVerifyWildcardDns:
    """Tests for CloudwaysClient.verify_wildcard_dns()."""

    @pytest.mark.asyncio
    async def test_verify_wildcard_dns_success(self) -> None:
        """POST /security/verifyDNS with body and response assertions."""
        captured = []
        verify_response = {
            "wildcard_ssl": {
                "message": "Your domain is mapped, kindly proceed",
                "status": True,
                "wildcard": {
                    "app_prefix": "woocommerce-111-160.cloudwaysapps.com",
                    "ssl_domains": ["example.com"],
                    "ssl_email": "admin@example.com",
                },
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/verifyDNS" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json=verify_response)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.verify_wildcard_dns(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com"],
            )

        assert (
            result["wildcard_ssl"]["message"] == "Your domain is mapped, kindly proceed"
        )
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/verifyDNS" in str(r.url)
        ][0]
        data = json_lib.loads(request.content.decode())
        assert data["server_id"] == 1089270
        assert data["app_id"] == 3937401
        assert data["wild_card"] is True
        assert data["ssl_domains"] == ["example.com"]

    @pytest.mark.asyncio
    async def test_verify_wildcard_dns_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/verifyDNS" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.verify_wildcard_dns(
                    server_id=1089270,
                    app_id=3937401,
                    ssl_email="admin@example.com",
                    ssl_domains=["example.com"],
                )

    @pytest.mark.asyncio
    async def test_verify_wildcard_dns_wild_card_always_true(self) -> None:
        """Method always sends wild_card=True regardless of caller."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/verifyDNS" in str(request.url) and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "wildcard_ssl": {"message": "", "status": True, "wildcard": {}}
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.verify_wildcard_dns(
                server_id=1089270,
                app_id=3937401,
                ssl_email="admin@example.com",
                ssl_domains=["example.com"],
            )

        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/verifyDNS" in str(r.url)
        ][0]
        data = json_lib.loads(request.content.decode())
        assert data["wild_card"] is True


class TestRenewLetsEncrypt:
    """Tests for CloudwaysClient.renew_lets_encrypt()."""

    @pytest.mark.asyncio
    async def test_renew_lets_encrypt_standard(self) -> None:
        """POST with no email/domain sends only required fields."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_manual_renew" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.renew_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/security/lets_encrypt_manual_renew" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=1089270" in body
        assert "app_id=3937401" in body
        assert "wild_card=false" in body
        assert "ssl_email" not in body
        assert "domain" not in body

    @pytest.mark.asyncio
    async def test_renew_lets_encrypt_wildcard(self) -> None:
        """POST with wildcard sends email and domain when provided."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_manual_renew" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.renew_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                wild_card=True,
                ssl_email="admin@example.com",
                domain="example.com",
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/security/lets_encrypt_manual_renew" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "wild_card=true" in body
        assert "ssl_email=admin" in body
        assert "domain=example.com" in body

    @pytest.mark.asyncio
    async def test_renew_lets_encrypt_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/lets_encrypt_manual_renew" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.renew_lets_encrypt(
                    server_id=1089270,
                    app_id=3937401,
                )


class TestSetLetsEncryptAuto:
    """Tests for CloudwaysClient.set_lets_encrypt_auto()."""

    @pytest.mark.asyncio
    async def test_set_lets_encrypt_auto_enable(self) -> None:
        """POST with auto=True returns empty dict."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_auto" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.set_lets_encrypt_auto(
                server_id=1089270,
                app_id=3937401,
                auto=True,
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_auto" in str(r.url)
        ][0]
        assert "auto=true" in request.content.decode()

    @pytest.mark.asyncio
    async def test_set_lets_encrypt_auto_disable(self) -> None:
        """POST with auto=False returns empty dict."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_auto" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.set_lets_encrypt_auto(
                server_id=1089270,
                app_id=3937401,
                auto=False,
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_auto" in str(r.url)
        ][0]
        assert "auto=false" in request.content.decode()

    @pytest.mark.asyncio
    async def test_set_lets_encrypt_auto_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/lets_encrypt_auto" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.set_lets_encrypt_auto(
                    server_id=1089270,
                    app_id=3937401,
                    auto=True,
                )


class TestRevokeLetsEncrypt:
    """Tests for CloudwaysClient.revoke_lets_encrypt()."""

    @pytest.mark.asyncio
    async def test_revoke_lets_encrypt_standard(self) -> None:
        """POST /security/lets_encrypt_revoke with standard (non-wildcard) cert."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_revoke" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.revoke_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                ssl_domain="example.com",
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_revoke" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=1089270" in body
        assert "app_id=3937401" in body
        assert "ssl_domain=example.com" in body
        assert "wild_card=false" in body

    @pytest.mark.asyncio
    async def test_revoke_lets_encrypt_wildcard(self) -> None:
        """POST /security/lets_encrypt_revoke with wildcard cert."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/lets_encrypt_revoke" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.revoke_lets_encrypt(
                server_id=1089270,
                app_id=3937401,
                ssl_domain="example.com",
                wild_card=True,
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/lets_encrypt_revoke" in str(r.url)
        ][0]
        assert "wild_card=true" in request.content.decode()

    @pytest.mark.asyncio
    async def test_revoke_lets_encrypt_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/lets_encrypt_revoke" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.revoke_lets_encrypt(
                    server_id=1089270,
                    app_id=3937401,
                    ssl_domain="example.com",
                )


class TestInstallCustomSsl:
    """Tests for CloudwaysClient.install_custom_ssl()."""

    @pytest.mark.asyncio
    async def test_install_custom_ssl_success(self) -> None:
        """POST /security/ownSSL with cert and key."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/ownSSL" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.install_custom_ssl(
                server_id=1089270,
                app_id=3937401,
                ssl_crt="-----BEGIN CERTIFICATE-----\nMIIB...",
                ssl_key="-----BEGIN PRIVATE KEY-----\nMIIB...",
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/ownSSL" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=1089270" in body
        assert "app_id=3937401" in body
        assert "ssl_crt=" in body
        assert "ssl_key=" in body
        assert "password" not in body

    @pytest.mark.asyncio
    async def test_install_custom_ssl_with_password(self) -> None:
        """POST /security/ownSSL with optional password."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/ownSSL" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.install_custom_ssl(
                server_id=1089270,
                app_id=3937401,
                ssl_crt="CERT",
                ssl_key="KEY",
                password="secret",
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/ownSSL" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "password=secret" in body

    @pytest.mark.asyncio
    async def test_install_custom_ssl_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/ownSSL" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.install_custom_ssl(
                    server_id=1089270,
                    app_id=3937401,
                    ssl_crt="CERT",
                    ssl_key="KEY",
                )


class TestRemoveCustomSsl:
    """Tests for CloudwaysClient.remove_custom_ssl()."""

    @pytest.mark.asyncio
    async def test_remove_custom_ssl_success(self) -> None:
        """DELETE /security/removeCustomSSL with form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/removeCustomSSL" in str(request.url)
                and request.method == "DELETE"
            ):
                return httpx.Response(200, json={"operation_id": 12345})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.remove_custom_ssl(
                server_id=1089270,
                app_id=3937401,
            )

        assert result == {"operation_id": 12345}
        request = [
            r
            for r in captured
            if r.method == "DELETE" and "/security/removeCustomSSL" in str(r.url)
        ][0]
        assert request.method == "DELETE"
        assert "/security/removeCustomSSL" in str(request.url)
        body = request.content.decode()
        assert "server_id=1089270" in body
        assert "app_id=3937401" in body

    @pytest.mark.asyncio
    async def test_remove_custom_ssl_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/removeCustomSSL" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.remove_custom_ssl(
                    server_id=1089270,
                    app_id=3937401,
                )


# ===================================================================
# CLI command tests
# ===================================================================


class TestSslInstall:
    """Tests for `cloudways security ssl install` command."""

    def test_ssl_install_success(self, set_env) -> None:
        """Standard install prints operation ID."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "SSL installation started." in result.output
        assert "12345" in result.output

    def test_ssl_install_wildcard_success(self, set_env) -> None:
        """Wildcard install runs two-step flow with user confirmation."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com",
                    "--wildcard",
                ],
                input="y\n",
            )

        assert result.exit_code == 0, result.output
        assert "Wildcard SSL installation started." in result.output

    def test_ssl_install_domains_parsed_correctly(self, set_env) -> None:
        """Comma-separated domains are split and whitespace stripped."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com, www.example.com",
                ],
            )

        assert result.exit_code == 0, result.output
        # Find the install request and check body
        install_req = [
            r
            for r in captured
            if "/security/lets_encrypt_install" in str(r.url) and r.method == "POST"
        ][0]
        data = json_lib.loads(install_req.content.decode())
        assert data["ssl_domains"] == ["example.com", "www.example.com"]

    def test_ssl_install_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_ssl_handler(install_le_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_ssl_install_wildcard_verify_fails(self, set_env) -> None:
        """Wildcard install exits 1 when DNS verification fails."""
        handler, captured = _make_ssl_handler(
            verify_dns_response={
                "wildcard_ssl": {
                    "message": "DNS not propagated",
                    "status": False,
                    "wildcard": {},
                }
            }
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com",
                    "--wildcard",
                ],
                input="y\n",
            )

        assert result.exit_code == 1
        assert "DNS verification failed." in result.output
        # install_lets_encrypt should NOT have been called
        assert not any("/security/lets_encrypt_install" in str(r.url) for r in captured)

    def test_ssl_install_wildcard_user_declines(self, set_env) -> None:
        """Wildcard install aborts when user declines confirmation."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "example.com",
                    "--wildcard",
                ],
                input="n\n",
            )

        assert result.exit_code != 0
        assert "Wildcard SSL installation started." not in result.output

    def test_ssl_install_empty_domains_error(self, set_env) -> None:
        """Whitespace-only domains input exits 1 with error message."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install",
                    "production",
                    "--email",
                    "admin@example.com",
                    "--domains",
                    "   ",
                ],
            )

        assert result.exit_code == 1
        assert "No valid domains provided." in result.output


class TestSslRenew:
    """Tests for `cloudways security ssl renew` command."""

    def test_ssl_renew_success(self, set_env) -> None:
        """Standard renewal prints operation ID."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "ssl", "renew", "production"])

        assert result.exit_code == 0, result.output
        assert "SSL renewal started." in result.output
        assert "12345" in result.output

    def test_ssl_renew_wildcard_with_email(self, set_env) -> None:
        """Wildcard renewal with email succeeds."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "renew",
                    "production",
                    "--wildcard",
                    "--email",
                    "admin@example.com",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "SSL renewal started." in result.output

    def test_ssl_renew_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_ssl_handler(renew_le_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "ssl", "renew", "production"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_ssl_renew_wildcard_missing_email_error(self, set_env) -> None:
        """Wildcard renew without email exits 1."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "renew", "production", "--wildcard"]
            )

        assert result.exit_code == 1
        assert "--email is required for wildcard renewal." in result.output


class TestSslAuto:
    """Tests for `cloudways security ssl auto` command."""

    def test_ssl_auto_enable_success(self, set_env) -> None:
        """Enable auto-renewal prints confirmation."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "auto", "production", "--enable"]
            )

        assert result.exit_code == 0, result.output
        assert "Auto-renewal enabled." in result.output

    def test_ssl_auto_disable_success(self, set_env) -> None:
        """Disable auto-renewal prints confirmation."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "auto", "production", "--disable"]
            )

        assert result.exit_code == 0, result.output
        assert "Auto-renewal disabled." in result.output

    def test_ssl_auto_both_flags_error(self, set_env) -> None:
        """Both --enable and --disable exits 1."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                ["security", "ssl", "auto", "production", "--enable", "--disable"],
            )

        assert result.exit_code == 1
        assert "Specify exactly one of --enable or --disable." in result.output

    def test_ssl_auto_neither_flag_error(self, set_env) -> None:
        """Neither --enable nor --disable exits 1."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "ssl", "auto", "production"])

        assert result.exit_code == 1
        assert "Specify exactly one of --enable or --disable." in result.output

    def test_ssl_auto_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_ssl_handler(auto_le_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "auto", "production", "--enable"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestSslRevoke:
    """Tests for `cloudways security ssl revoke` command."""

    def test_ssl_revoke_success(self, set_env) -> None:
        """Standard revocation prints operation ID."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "revoke",
                    "production",
                    "--domain",
                    "example.com",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "SSL revocation started." in result.output
        assert "12345" in result.output

    def test_ssl_revoke_wildcard(self, set_env) -> None:
        """Wildcard revocation prints operation ID."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "revoke",
                    "production",
                    "--domain",
                    "example.com",
                    "--wildcard",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "SSL revocation started." in result.output

    def test_ssl_revoke_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_ssl_handler(revoke_le_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "revoke",
                    "production",
                    "--domain",
                    "example.com",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestSslInstallCustom:
    """Tests for `cloudways security ssl install-custom` command."""

    def test_ssl_install_custom_success(self, set_env, tmp_path) -> None:
        """Install custom SSL with cert and key files."""
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_text("-----BEGIN CERTIFICATE-----\nMIIB...")
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nMIIB...")

        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install-custom",
                    "production",
                    "--cert-file",
                    str(cert_file),
                    "--key-file",
                    str(key_file),
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Custom SSL certificate installed successfully." in result.output

    def test_ssl_install_custom_with_password(self, set_env, tmp_path) -> None:
        """Install custom SSL with optional password."""
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_text("CERT")
        key_file.write_text("KEY")

        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install-custom",
                    "production",
                    "--cert-file",
                    str(cert_file),
                    "--key-file",
                    str(key_file),
                    "--password",
                    "secret",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Custom SSL certificate installed successfully." in result.output

    def test_ssl_install_custom_file_not_found(self, set_env) -> None:
        """Missing cert file exits 1 with error."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install-custom",
                    "production",
                    "--cert-file",
                    "/nonexistent/cert.pem",
                    "--key-file",
                    "/some/key.pem",
                ],
            )

        assert result.exit_code == 1
        assert "No such file or directory" in result.output

    def test_ssl_install_custom_api_error(self, set_env, tmp_path) -> None:
        """API 422 exits with code 1."""
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_text("CERT")
        key_file.write_text("KEY")

        handler, captured = _make_ssl_handler(install_custom_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "ssl",
                    "install-custom",
                    "production",
                    "--cert-file",
                    str(cert_file),
                    "--key-file",
                    str(key_file),
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestSslRemoveCustom:
    """Tests for `cloudways security ssl remove-custom` command."""

    def test_ssl_remove_custom_success(self, set_env) -> None:
        """Remove custom SSL prints operation ID."""
        handler, captured = _make_ssl_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "remove-custom", "production"]
            )

        assert result.exit_code == 0, result.output
        assert "Custom SSL removal started." in result.output

    def test_ssl_remove_custom_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_ssl_handler(remove_custom_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "remove-custom", "production"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_ssl_remove_custom_output_contains_operation_id(self, set_env) -> None:
        """Output includes the numeric operation ID."""
        handler, captured = _make_ssl_handler(
            remove_custom_response={"operation_id": 99999}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "ssl", "remove-custom", "production"]
            )

        assert result.exit_code == 0, result.output
        assert "99999" in result.output


# ===================================================================
# CLI registration tests
# ===================================================================


class TestSslRegistration:
    """Tests for SSL command registration in CLI."""

    def test_ssl_registration_help(self) -> None:
        """security ssl --help shows all subcommands."""
        result = runner.invoke(app, ["security", "ssl", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output
        assert "renew" in result.output
        assert "auto" in result.output
        assert "revoke" in result.output
        assert "install-custom" in result.output
        assert "remove-custom" in result.output

    def test_security_help_shows_ssl(self) -> None:
        """security --help shows ssl subgroup."""
        result = runner.invoke(app, ["security", "--help"])
        assert "ssl" in result.output
