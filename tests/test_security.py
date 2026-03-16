"""Tests for security/IP whitelist commands and client methods.

Covers whitelist list/add/remove, blacklist-check, whitelist-siab,
whitelist-adminer commands with mocked Cloudways API responses,
plus client method tests for all six security operations.
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


def _make_security_handler(
    whitelisted_response=None,
    whitelisted_mysql_response=None,
    update_whitelisted_response=None,
    is_blacklisted_response=None,
    siab_response=None,
    adminer_response=None,
    whitelisted_error=False,
    whitelisted_mysql_error=False,
    update_whitelisted_error=False,
    is_blacklisted_error=False,
    siab_error=False,
    adminer_error=False,
):
    """Build httpx mock handler for security/IP whitelist API calls.

    Returns a (handler, captured) tuple where captured is a mutable list
    that accumulates every httpx.Request seen by the handler. Tests that
    verify a POST to /security/whitelisted was NOT made use captured to
    assert that no such request appears in the list.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        # Check whitelistedIpsMysql BEFORE whitelisted (longer path first)
        if "/security/whitelistedIpsMysql" in url and method == "GET":
            if whitelisted_mysql_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=whitelisted_mysql_response or {"ip_list": []}
            )

        if "/security/whitelisted" in url and method == "GET":
            if whitelisted_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=whitelisted_response or {"ip_list": []})

        if "/security/whitelisted" in url and method == "POST":
            if update_whitelisted_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=update_whitelisted_response or {})

        if "/security/isBlacklisted" in url and method == "GET":
            if is_blacklisted_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(
                200, json=is_blacklisted_response or {"ip_list": False}
            )

        if "/security/siab" in url and method == "POST":
            if siab_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=siab_response or {})

        if "/security/adminer" in url and method == "POST":
            if adminer_error:
                return httpx.Response(422, text="Server error")
            return httpx.Response(200, json=adminer_response or {})

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests
# ===================================================================


class TestGetWhitelistedIps:
    """Tests for CloudwaysClient.get_whitelisted_ips()."""

    @pytest.mark.asyncio
    async def test_get_whitelisted_ips_success(self) -> None:
        """GET /security/whitelisted with server_id in query string."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                request.url.path.endswith("/security/whitelisted")
                and request.method == "GET"
            ):
                return httpx.Response(200, json={"ip_list": ["1.1.1.1"]})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_whitelisted_ips(server_id=999999)

        assert result == ["1.1.1.1"]
        request = [
            r
            for r in captured
            if r.method == "GET" and r.url.path.endswith("/security/whitelisted")
        ][0]
        assert request.method == "GET"
        assert request.url.path.endswith("/security/whitelisted")
        assert "server_id=999999" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_whitelisted_ips_empty(self) -> None:
        """Returns empty list when API returns empty ip_list."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if request.url.path.endswith("/security/whitelisted"):
                return httpx.Response(200, json={"ip_list": []})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_whitelisted_ips(server_id=999999)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_whitelisted_ips_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if request.url.path.endswith("/security/whitelisted"):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_whitelisted_ips(server_id=999999)


class TestGetWhitelistedIpsMysql:
    """Tests for CloudwaysClient.get_whitelisted_ips_mysql()."""

    @pytest.mark.asyncio
    async def test_get_whitelisted_ips_mysql_success(self) -> None:
        """GET /security/whitelistedIpsMysql with server_id in query string."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/security/whitelistedIpsMysql" in str(request.url)
                and request.method == "GET"
            ):
                return httpx.Response(200, json={"ip_list": ["1.1.1.1"]})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_whitelisted_ips_mysql(server_id=999999)

        assert result == ["1.1.1.1"]
        request = [
            r
            for r in captured
            if r.method == "GET" and "/security/whitelistedIpsMysql" in str(r.url)
        ][0]
        assert request.method == "GET"
        assert "/security/whitelistedIpsMysql" in str(request.url)
        assert "server_id=999999" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_whitelisted_ips_mysql_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/whitelistedIpsMysql" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_whitelisted_ips_mysql(server_id=999999)


class TestUpdateWhitelistedIps:
    """Tests for CloudwaysClient.update_whitelisted_ips()."""

    @pytest.mark.asyncio
    async def test_update_whitelisted_ips_success(self) -> None:
        """POST /security/whitelisted with all required fields."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/whitelisted" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_whitelisted_ips(
                server_id=999999, ip_list=["1.1.1.1"]
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/whitelisted" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/security/whitelisted" in str(request.url)
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "tab=sftp" in body
        assert "type=sftp" in body
        assert "ipPolicy=allow_all" in body
        assert "ip=1.1.1.1" in body

    @pytest.mark.asyncio
    async def test_update_whitelisted_ips_array_encoding(self) -> None:
        """POST with two IPs produces repeated keys: ip=1.1.1.1&ip=2.2.2.2."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/whitelisted" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.update_whitelisted_ips(
                server_id=999999, ip_list=["1.1.1.1", "2.2.2.2"]
            )

        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/whitelisted" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "ip=1.1.1.1" in body
        assert "ip=2.2.2.2" in body

    @pytest.mark.asyncio
    async def test_update_whitelisted_ips_empty_list(self) -> None:
        """POST with empty IP list has no ip= keys."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/whitelisted" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_whitelisted_ips(server_id=999999, ip_list=[])

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/whitelisted" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id" in body
        assert "tab" in body
        assert "ip=" not in body

    @pytest.mark.asyncio
    async def test_update_whitelisted_ips_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/whitelisted" in str(request.url) and request.method == "POST":
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_whitelisted_ips(
                    server_id=999999, ip_list=["1.1.1.1"]
                )


class TestCheckIpBlacklisted:
    """Tests for CloudwaysClient.check_ip_blacklisted()."""

    @pytest.mark.asyncio
    async def test_check_ip_blacklisted_true(self) -> None:
        """Returns True when API responds with ip_list: true."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/isBlacklisted" in str(request.url):
                return httpx.Response(200, json={"ip_list": True})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.check_ip_blacklisted(server_id=999999, ip="1.1.1.1")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_ip_blacklisted_false(self) -> None:
        """Returns False when API responds with ip_list: false."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/isBlacklisted" in str(request.url):
                return httpx.Response(200, json={"ip_list": False})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.check_ip_blacklisted(server_id=999999, ip="1.1.1.1")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_ip_blacklisted_request(self) -> None:
        """GET /security/isBlacklisted with server_id and ip in query."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/isBlacklisted" in str(request.url):
                return httpx.Response(200, json={"ip_list": False})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.check_ip_blacklisted(server_id=999999, ip="1.1.1.1")

        request = [r for r in captured if "/security/isBlacklisted" in str(r.url)][0]
        assert request.method == "GET"
        assert "/security/isBlacklisted" in str(request.url)
        assert "server_id=999999" in str(request.url)
        assert "ip=1.1.1.1" in str(request.url)

    @pytest.mark.asyncio
    async def test_check_ip_blacklisted_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/isBlacklisted" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.check_ip_blacklisted(server_id=999999, ip="1.1.1.1")


class TestWhitelistSiab:
    """Tests for CloudwaysClient.whitelist_siab()."""

    @pytest.mark.asyncio
    async def test_whitelist_siab_success(self) -> None:
        """POST /security/siab with server_id and ip in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/siab" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.whitelist_siab(server_id=999999, ip="1.1.1.1")

        assert result == {}
        request = [
            r for r in captured if r.method == "POST" and "/security/siab" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/security/siab" in str(request.url)
        assert request.content.decode() == "server_id=999999&ip=1.1.1.1"

    @pytest.mark.asyncio
    async def test_whitelist_siab_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/siab" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.whitelist_siab(server_id=999999, ip="1.1.1.1")


class TestWhitelistAdminer:
    """Tests for CloudwaysClient.whitelist_adminer()."""

    @pytest.mark.asyncio
    async def test_whitelist_adminer_success(self) -> None:
        """POST /security/adminer with server_id and ip in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/adminer" in str(request.url) and request.method == "POST":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.whitelist_adminer(server_id=999999, ip="1.1.1.1")

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST" and "/security/adminer" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/security/adminer" in str(request.url)
        assert request.content.decode() == "server_id=999999&ip=1.1.1.1"

    @pytest.mark.asyncio
    async def test_whitelist_adminer_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/security/adminer" in str(request.url):
                return httpx.Response(422, text="Server error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.whitelist_adminer(server_id=999999, ip="1.1.1.1")


# ===================================================================
# CLI command tests
# ===================================================================


class TestWhitelistList:
    """Tests for `cloudways security whitelist list` command."""

    def test_whitelist_list_sftp_with_ips(self, set_env) -> None:
        """Default type lists SFTP whitelisted IPs."""
        handler, captured = _make_security_handler(
            whitelisted_response={"ip_list": ["1.1.1.1", "2.2.2.2"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "whitelist", "list"])

        assert result.exit_code == 0, result.output
        assert "1.1.1.1" in result.output
        assert "2.2.2.2" in result.output

    def test_whitelist_list_sftp_empty(self, set_env) -> None:
        """Empty list prints 'No IPs whitelisted.'."""
        handler, captured = _make_security_handler(whitelisted_response={"ip_list": []})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "whitelist", "list"])

        assert result.exit_code == 0, result.output
        assert "No IPs whitelisted." in result.output

    def test_whitelist_list_mysql(self, set_env) -> None:
        """--type mysql lists MySQL whitelisted IPs."""
        handler, captured = _make_security_handler(
            whitelisted_mysql_response={"ip_list": ["1.1.1.1"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "list", "--type", "mysql"]
            )

        assert result.exit_code == 0, result.output
        assert "1.1.1.1" in result.output

    def test_whitelist_list_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_security_handler(whitelisted_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["security", "whitelist", "list"])

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestWhitelistAdd:
    """Tests for `cloudways security whitelist add` command."""

    def test_whitelist_add_success(self, set_env) -> None:
        """Add IP to empty list succeeds with read-modify-write."""
        handler, captured = _make_security_handler(whitelisted_response={"ip_list": []})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "add", "--ip", "3.3.3.3"]
            )

        assert result.exit_code == 0, result.output
        assert "Added 3.3.3.3 to sftp whitelist." in result.output
        post_req = next(
            r
            for r in captured
            if r.url.path.endswith("/security/whitelisted") and r.method == "POST"
        )
        assert "tab=sftp" in post_req.content.decode()
        assert "ip=3.3.3.3" in post_req.content.decode()

    def test_whitelist_add_idempotent(self, set_env) -> None:
        """IP already in list prints idempotent message."""
        handler, captured = _make_security_handler(
            whitelisted_response={"ip_list": ["1.1.1.1"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "add", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "IP 1.1.1.1 is already whitelisted." in result.output

    def test_whitelist_add_mysql(self, set_env) -> None:
        """--type mysql uses MySQL GET endpoint and sends tab=mysql."""
        handler, captured = _make_security_handler(
            whitelisted_mysql_response={"ip_list": []}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                ["security", "whitelist", "add", "--ip", "3.3.3.3", "--type", "mysql"],
            )

        assert result.exit_code == 0, result.output
        assert "Added 3.3.3.3 to mysql whitelist." in result.output
        get_req = next(
            r
            for r in captured
            if r.method == "GET"
            and "/security" in str(r.url)
            and "oauth" not in str(r.url)
        )
        assert get_req.url.path.endswith("/security/whitelistedIpsMysql")
        post_req = next(
            r
            for r in captured
            if r.url.path.endswith("/security/whitelisted") and r.method == "POST"
        )
        assert "tab=mysql" in post_req.content.decode()
        assert "ip=3.3.3.3" in post_req.content.decode()

    def test_whitelist_add_api_error(self, set_env) -> None:
        """API 422 on POST exits with code 1."""
        handler, captured = _make_security_handler(update_whitelisted_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "add", "--ip", "3.3.3.3"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_whitelist_add_no_post_when_idempotent(self, set_env) -> None:
        """POST NOT called when IP already in list."""
        handler, captured = _make_security_handler(
            whitelisted_response={"ip_list": ["1.1.1.1"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "add", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0
        assert not any(
            request.url.path.endswith("/security/whitelisted")
            and request.method == "POST"
            for request in captured
        )


class TestWhitelistRemove:
    """Tests for `cloudways security whitelist remove` command."""

    def test_whitelist_remove_success(self, set_env) -> None:
        """Remove IP from list succeeds with read-modify-write."""
        handler, captured = _make_security_handler(
            whitelisted_response={"ip_list": ["1.1.1.1", "2.2.2.2"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "remove", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "Removed 1.1.1.1 from sftp whitelist." in result.output
        post_req = next(
            r
            for r in captured
            if r.url.path.endswith("/security/whitelisted") and r.method == "POST"
        )
        assert "tab=sftp" in post_req.content.decode()
        assert "ip=1.1.1.1" not in post_req.content.decode()

    def test_whitelist_remove_not_in_list(self, set_env) -> None:
        """IP not in list prints informational message."""
        handler, captured = _make_security_handler(whitelisted_response={"ip_list": []})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "remove", "--ip", "9.9.9.9"]
            )

        assert result.exit_code == 0, result.output
        assert "IP 9.9.9.9 is not in the whitelist." in result.output

    def test_whitelist_remove_last_ip(self, set_env) -> None:
        """Remove last IP sends POST with empty list."""
        handler, captured = _make_security_handler(
            whitelisted_response={"ip_list": ["1.1.1.1"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "remove", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "Removed 1.1.1.1 from sftp whitelist." in result.output
        post_req = next(
            r
            for r in captured
            if r.url.path.endswith("/security/whitelisted") and r.method == "POST"
        )
        assert "tab=sftp" in post_req.content.decode()
        assert "ip=" not in post_req.content.decode()

    def test_whitelist_remove_mysql(self, set_env) -> None:
        """--type mysql uses MySQL GET endpoint and sends tab=mysql."""
        handler, captured = _make_security_handler(
            whitelisted_mysql_response={"ip_list": ["1.1.1.1"]}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "security",
                    "whitelist",
                    "remove",
                    "--ip",
                    "1.1.1.1",
                    "--type",
                    "mysql",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Removed 1.1.1.1 from mysql whitelist." in result.output
        get_req = next(
            r
            for r in captured
            if r.method == "GET"
            and "/security" in str(r.url)
            and "oauth" not in str(r.url)
        )
        assert get_req.url.path.endswith("/security/whitelistedIpsMysql")
        post_req = next(
            r
            for r in captured
            if r.url.path.endswith("/security/whitelisted") and r.method == "POST"
        )
        assert "tab=mysql" in post_req.content.decode()

    def test_whitelist_remove_api_error(self, set_env) -> None:
        """API 422 on GET exits with code 1."""
        handler, captured = _make_security_handler(whitelisted_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "remove", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output

    def test_whitelist_remove_no_post_when_not_in_list(self, set_env) -> None:
        """POST NOT called when IP not in list."""
        handler, captured = _make_security_handler(whitelisted_response={"ip_list": []})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist", "remove", "--ip", "9.9.9.9"]
            )

        assert result.exit_code == 0
        assert not any(
            request.url.path.endswith("/security/whitelisted")
            and request.method == "POST"
            for request in captured
        )


class TestBlacklistCheck:
    """Tests for `cloudways security blacklist-check` command."""

    def test_blacklist_check_blacklisted(self, set_env) -> None:
        """IP is blacklisted prints confirmation."""
        handler, captured = _make_security_handler(
            is_blacklisted_response={"ip_list": True}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "blacklist-check", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "IP 1.1.1.1 is blacklisted." in result.output

    def test_blacklist_check_not_blacklisted(self, set_env) -> None:
        """IP is not blacklisted prints confirmation."""
        handler, captured = _make_security_handler(
            is_blacklisted_response={"ip_list": False}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "blacklist-check", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "IP 1.1.1.1 is not blacklisted." in result.output

    def test_blacklist_check_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_security_handler(is_blacklisted_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "blacklist-check", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestWhitelistSiabCli:
    """Tests for `cloudways security whitelist-siab` command."""

    def test_whitelist_siab_success(self, set_env) -> None:
        """Whitelist IP for Web SSH prints confirmation."""
        handler, captured = _make_security_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist-siab", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "Whitelisted 1.1.1.1 for Web SSH (Shell-in-a-Box)." in result.output

    def test_whitelist_siab_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_security_handler(siab_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist-siab", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


class TestWhitelistAdminerCli:
    """Tests for `cloudways security whitelist-adminer` command."""

    def test_whitelist_adminer_success(self, set_env) -> None:
        """Whitelist IP for Adminer prints confirmation."""
        handler, captured = _make_security_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist-adminer", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 0, result.output
        assert "Whitelisted 1.1.1.1 for Adminer (database manager)." in result.output

    def test_whitelist_adminer_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_security_handler(adminer_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.security.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["security", "whitelist-adminer", "--ip", "1.1.1.1"]
            )

        assert result.exit_code == 1
        assert "API request failed with status 422" in result.output


# ===================================================================
# CLI registration tests
# ===================================================================


class TestSecurityRegistration:
    """Tests for security command registration in CLI."""

    def test_security_in_help(self) -> None:
        """security appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "security" in result.output

    def test_security_help(self) -> None:
        """security --help shows all subcommands."""
        result = runner.invoke(app, ["security", "--help"])
        assert result.exit_code == 0
        assert "whitelist" in result.output
        assert "blacklist-check" in result.output
        assert "whitelist-siab" in result.output
        assert "whitelist-adminer" in result.output

    def test_security_whitelist_help(self) -> None:
        """security whitelist --help shows sub-subcommands."""
        result = runner.invoke(app, ["security", "whitelist", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "add" in result.output
        assert "remove" in result.output
