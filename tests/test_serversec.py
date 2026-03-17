"""Tests for server security suite commands and client methods.

Covers IP firewall management, country geoblocking, security statistics,
infected domain management, firewall settings, and app security inventory
via the Cloudways server-level security API.
"""

import asyncio
import re
from urllib.parse import parse_qs

import httpx
import pytest
from typer.testing import CliRunner
from unittest.mock import patch

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Handler factory ---


def _make_serversec_handler(
    # Phase 1 flags
    incidents_response=None,
    incidents_error=False,
    ips_get_response=None,
    ips_get_error=False,
    ips_put_response=None,
    ips_put_error=False,
    ips_delete_response=None,
    ips_delete_error=False,
    # Phase 2 flags
    country_block_response=None,
    country_block_error=False,
    country_unblock_response=None,
    country_unblock_error=False,
    # Phase 3 flags
    stats_response=None,
    stats_error=False,
    infected_domains_response=None,
    infected_domains_error=False,
    infected_domains_sync_response=None,
    infected_domains_sync_error=False,
    firewall_settings_get_response=None,
    firewall_settings_get_error=False,
    firewall_settings_put_response=None,
    firewall_settings_put_error=False,
    apps_response=None,
    apps_error=False,
):
    """Build httpx mock handler for all serversec API calls.

    Returns a (handler, captured) tuple where captured is a mutable list
    that accumulates every httpx.Request seen by the handler.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        url = str(request.url)
        method = request.method

        # 1. OAuth
        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        # 2. /infected-domains/sync (POST) — BEFORE bare /infected-domains
        if re.search(r"/server/security/(\d+)/infected-domains/sync", url):
            if infected_domains_sync_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=infected_domains_sync_response or {"status": True},
            )

        # 3. /infected-domains (GET)
        if re.search(r"/server/security/(\d+)/infected-domains", url):
            if infected_domains_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=infected_domains_response
                or {"domains": [], "total": 0},
            )

        # 4. /blacklist-countries (PUT/DELETE)
        if re.search(r"/server/security/(\d+)/blacklist-countries", url):
            if method == "PUT":
                if country_block_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=country_block_response or {"status": True},
                )
            elif method == "DELETE":
                if country_unblock_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=country_unblock_response or {"status": True},
                )

        # 5. /firewall-settings (GET/PUT)
        if re.search(r"/server/security/(\d+)/firewall-settings", url):
            if method == "GET":
                if firewall_settings_get_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=firewall_settings_get_response
                    or {"settings": {}},
                )
            elif method == "PUT":
                if firewall_settings_put_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=firewall_settings_put_response or {"status": True},
                )

        # 6. /incidents (GET)
        if re.search(r"/server/security/(\d+)/incidents", url):
            if incidents_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=incidents_response or {"incidents": []},
            )

        # 7. /stats (GET)
        if re.search(r"/server/security/(\d+)/stats", url):
            if stats_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=stats_response or {"stats": {}},
            )

        # 8. /apps (GET)
        if re.search(r"/server/security/(\d+)/apps", url):
            if apps_error:
                return httpx.Response(
                    400, text="API request failed with status 400"
                )
            return httpx.Response(
                200,
                json=apps_response or {"apps": []},
            )

        # 9. /ips (GET/PUT/DELETE)
        if re.search(r"/server/security/(\d+)/ips", url):
            if method == "GET":
                if ips_get_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=ips_get_response or {"ips": []},
                )
            elif method == "PUT":
                if ips_put_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=ips_put_response or {"status": True},
                )
            elif method == "DELETE":
                if ips_delete_error:
                    return httpx.Response(
                        400, text="API request failed with status 400"
                    )
                return httpx.Response(
                    200,
                    json=ips_delete_response or {"status": True},
                )

        return httpx.Response(404, text="Not found")

    return handler, captured


# --- Env helper ---


# --- Helper for async client calls ---


async def _async_client_call(PatchedClient, method_name, **kwargs):
    """Helper to call an async client method by name."""
    async with PatchedClient("test@example.com", "key") as client:
        method = getattr(client, method_name)
        return await method(**kwargs)


# ===================================================================
# Phase 1 Tests -- Incidents & IP Firewall
# ===================================================================


class TestGetServerIncidents:
    """Tests for get_server_security_incidents client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/incidents returns incidents dict."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_security_incidents(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/server/security/1089270/incidents" in url
        assert "server_id=" in url

    def test_error(self, set_env):
        """GET /server/security/{id}/incidents error raises APIError."""
        handler, captured = _make_serversec_handler(incidents_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_server_security_incidents",
                    server_id=1089270,
                )
            )


class TestGetServerSecurityIps:
    """Tests for get_server_security_ips client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/ips returns IPs dict."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_security_ips(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "/server/security/1089270/ips" in url
        assert "server_id=" in url

    def test_error(self, set_env):
        """GET /server/security/{id}/ips error raises APIError."""
        handler, captured = _make_serversec_handler(ips_get_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_server_security_ips",
                    server_id=1089270,
                )
            )


class TestAddServerIp:
    """Tests for update_server_security_ips client method."""

    def test_success(self, set_env):
        """PUT /server/security/{id}/ips sends correct body with mode=white."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.update_server_security_ips(
                    server_id=1089270, ip="1.2.3.4", mode="allow"
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        assert req.method == "PUT"
        body = req.content.decode()
        assert "server_id=1089270" in body
        assert "iplist%5B%5D=1.2.3.4" in body  # iplist[] URL-encoded
        assert "mode=white" in body
        assert "ttl=0" in body
        assert "ttl_type=minutes" in body

    def test_error(self, set_env):
        """PUT /server/security/{id}/ips error raises APIError."""
        handler, captured = _make_serversec_handler(ips_put_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "update_server_security_ips",
                    server_id=1089270,
                    ip="1.2.3.4",
                    mode="allow",
                )
            )


class TestRemoveServerIp:
    """Tests for delete_server_security_ips client method."""

    def test_success(self, set_env):
        """DELETE /server/security/{id}/ips sends body without ttl fields."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.delete_server_security_ips(
                    server_id=1089270, ip="1.2.3.4", mode="allow"
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        assert req.method == "DELETE"
        body = req.content.decode()
        assert "server_id=1089270" in body
        assert "iplist%5B%5D=1.2.3.4" in body  # iplist[] URL-encoded
        assert "mode=white" in body
        assert "ttl" not in body
        assert "ttl_type" not in body

    def test_error(self, set_env):
        """DELETE /server/security/{id}/ips error raises APIError."""
        handler, captured = _make_serversec_handler(ips_delete_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "delete_server_security_ips",
                    server_id=1089270,
                    ip="1.2.3.4",
                    mode="allow",
                )
            )


# ===================================================================
# Phase 1 CLI Tests
# ===================================================================


def test_incidents_success(set_env):
    """serversec incidents exits 0."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app, ["serversec", "incidents"], catch_exceptions=False
        )

    assert result.exit_code == 0


def test_incidents_error(set_env):
    """serversec incidents exits 1 on API error."""
    handler, captured = _make_serversec_handler(incidents_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(app, ["serversec", "incidents"])

    assert result.exit_code == 1


def test_ips_success(set_env):
    """serversec ips exits 0."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app, ["serversec", "ips"], catch_exceptions=False
        )

    assert result.exit_code == 0


def test_ips_error(set_env):
    """serversec ips exits 1 on API error."""
    handler, captured = _make_serversec_handler(ips_get_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(app, ["serversec", "ips"])

    assert result.exit_code == 1


def test_ip_add_allow_mode(set_env):
    """serversec ip-add --mode allow sends mode=white with defaults."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "ip-add", "--ip", "1.2.3.4", "--mode", "allow"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["mode"] == ["white"]
    assert parsed["iplist[]"] == ["1.2.3.4"]
    assert parsed["server_id"] == ["1089270"]
    assert parsed["ttl"] == ["0"]
    assert parsed["ttl_type"] == ["minutes"]


def test_ip_add_block_mode(set_env):
    """serversec ip-add --mode block sends mode=black."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "ip-add", "--ip", "1.2.3.4", "--mode", "block"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["mode"] == ["black"]


def test_ip_add_with_ttl(set_env):
    """serversec ip-add with --ttl and --ttl-type sends custom values."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "ip-add",
                "--ip",
                "1.2.3.4",
                "--mode",
                "allow",
                "--ttl",
                "24",
                "--ttl-type",
                "hours",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["ttl"] == ["24"]
    assert parsed["ttl_type"] == ["hours"]


def test_ip_add_error(set_env):
    """serversec ip-add exits 1 on API error."""
    handler, captured = _make_serversec_handler(ips_put_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "ip-add", "--ip", "1.2.3.4", "--mode", "allow"],
        )

    assert result.exit_code == 1


def test_ip_remove_success(set_env):
    """serversec ip-remove sends DELETE with body, no ttl fields."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "ip-remove",
                "--ip",
                "1.2.3.4",
                "--mode",
                "allow",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    assert req.method == "DELETE"
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]
    assert parsed["iplist[]"] == ["1.2.3.4"]
    assert parsed["mode"] == ["white"]
    assert "ttl" not in parsed
    assert "ttl_type" not in parsed


def test_ip_remove_error(set_env):
    """serversec ip-remove exits 1 on API error."""
    handler, captured = _make_serversec_handler(ips_delete_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "ip-remove",
                "--ip",
                "1.2.3.4",
                "--mode",
                "allow",
            ],
        )

    assert result.exit_code == 1


# ===================================================================
# Phase 2 Tests -- Country Geoblocking
# ===================================================================


class TestAddBlacklistCountry:
    """Tests for add_server_blacklist_countries client method."""

    def test_success(self, set_env):
        """PUT /server/security/{id}/blacklist-countries sends uppercased country."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.add_server_blacklist_countries(
                    server_id=1089270, country="cn"
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        assert req.method == "PUT"
        body = req.content.decode()
        assert "countrylist%5B%5D=CN" in body  # countrylist[] URL-encoded, uppercased
        assert "server_id=1089270" in body
        assert "reason" not in body  # reason not provided

    def test_error(self, set_env):
        """PUT /server/security/{id}/blacklist-countries error raises APIError."""
        handler, captured = _make_serversec_handler(country_block_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "add_server_blacklist_countries",
                    server_id=1089270,
                    country="cn",
                )
            )


class TestRemoveBlacklistCountry:
    """Tests for remove_server_blacklist_countries client method."""

    def test_success(self, set_env):
        """DELETE /server/security/{id}/blacklist-countries sends uppercased country."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.remove_server_blacklist_countries(
                    server_id=1089270, country="cn"
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        assert req.method == "DELETE"
        body = req.content.decode()
        assert "countrylist%5B%5D=CN" in body  # countrylist[] URL-encoded, uppercased
        assert "server_id=1089270" in body

    def test_error(self, set_env):
        """DELETE /server/security/{id}/blacklist-countries error raises APIError."""
        handler, captured = _make_serversec_handler(
            country_unblock_error=True
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "remove_server_blacklist_countries",
                    server_id=1089270,
                    country="cn",
                )
            )


# ===================================================================
# Phase 2 CLI Tests
# ===================================================================


def test_country_block_success(set_env):
    """serversec country-block --country cn sends PUT with countrylist[]=CN."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "country-block", "--country", "cn"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    assert req.method == "PUT"
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["countrylist[]"] == ["CN"]
    assert parsed["server_id"] == ["1089270"]
    assert "reason" not in parsed


def test_country_block_with_reason(set_env):
    """serversec country-block --country cn --reason 'spam traffic' includes reason."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "country-block",
                "--country",
                "cn",
                "--reason",
                "spam traffic",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["countrylist[]"] == ["CN"]
    assert parsed["reason"] == ["spam traffic"]


def test_country_block_error(set_env):
    """serversec country-block exits 1 on API error."""
    handler, captured = _make_serversec_handler(country_block_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "country-block", "--country", "cn"],
        )

    assert result.exit_code == 1


def test_country_unblock_success(set_env):
    """serversec country-unblock --country CN sends DELETE with countrylist[]=CN."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "country-unblock", "--country", "CN"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    assert req.method == "DELETE"
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["countrylist[]"] == ["CN"]
    assert parsed["server_id"] == ["1089270"]


def test_country_unblock_error(set_env):
    """serversec country-unblock exits 1 on API error."""
    handler, captured = _make_serversec_handler(country_unblock_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "country-unblock", "--country", "CN"],
        )

    assert result.exit_code == 1


# ===================================================================
# Phase 3 Tests -- Stats, Infected Domains, Firewall Settings & Apps
# ===================================================================


class TestGetServerSecurityStats:
    """Tests for get_server_security_stats client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/stats with all params."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_security_stats(
                    server_id=1089270,
                    data_types=["bandwidth", "requests"],
                    group_by="day",
                    start=1700000000,
                    end=1700086400,
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "data_types%5B%5D=bandwidth" in url
        assert "data_types%5B%5D=requests" in url
        assert "group_by=day" in url
        assert "start=1700000000" in url
        assert "end=1700086400" in url

    def test_error(self, set_env):
        """GET /server/security/{id}/stats 400 raises APIError."""
        handler, captured = _make_serversec_handler(stats_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_server_security_stats",
                    server_id=1089270,
                    data_types=["bandwidth"],
                    group_by="day",
                    start=1700000000,
                    end=1700086400,
                )
            )


class TestGetInfectedDomains:
    """Tests for list_server_infected_domains client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/infected-domains with offset/limit."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.list_server_infected_domains(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "offset=0" in url
        assert "limit=20" in url

    def test_error(self, set_env):
        """GET /server/security/{id}/infected-domains 400 raises APIError."""
        handler, captured = _make_serversec_handler(
            infected_domains_error=True
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "list_server_infected_domains",
                    server_id=1089270,
                )
            )


class TestSyncInfectedDomains:
    """Tests for sync_server_infected_domains client method."""

    def test_success(self, set_env):
        """POST /server/security/{id}/infected-domains/sync."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.sync_server_infected_domains(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        assert req.method == "POST"
        body = req.content.decode()
        assert "server_id=1089270" in body

    def test_error(self, set_env):
        """POST /server/security/{id}/infected-domains/sync 400 raises APIError."""
        handler, captured = _make_serversec_handler(
            infected_domains_sync_error=True
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "sync_server_infected_domains",
                    server_id=1089270,
                )
            )


class TestGetFirewallSettings:
    """Tests for get_server_firewall_settings client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/firewall-settings returns dict."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_firewall_settings(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)

    def test_error(self, set_env):
        """GET /server/security/{id}/firewall-settings 400 raises APIError."""
        handler, captured = _make_serversec_handler(
            firewall_settings_get_error=True
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_server_firewall_settings",
                    server_id=1089270,
                )
            )


class TestUpdateFirewallSettings:
    """Tests for update_server_firewall_settings client method."""

    def test_success(self, set_env):
        """PUT /server/security/{id}/firewall-settings with both fields."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.update_server_firewall_settings(
                    server_id=1089270,
                    request_limit=100,
                    weak_password=True,
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        req = captured[-1]
        body = req.content.decode()
        parsed = parse_qs(body)
        assert parsed["server_id"] == ["1089270"]
        assert parsed["request_limit"] == ["100"]
        assert parsed["weak_password"] == ["1"]

    def test_error(self, set_env):
        """PUT /server/security/{id}/firewall-settings 400 raises APIError."""
        handler, captured = _make_serversec_handler(
            firewall_settings_put_error=True
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "update_server_firewall_settings",
                    server_id=1089270,
                    request_limit=100,
                    weak_password=True,
                )
            )


class TestGetServerSecurityApps:
    """Tests for get_server_security_apps client method."""

    def test_success(self, set_env):
        """GET /server/security/{id}/apps with page/page_limit."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_security_apps(
                    server_id=1089270
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "page=1" in url
        assert "page_limit=20" in url
        assert "server_id=1089270" in url

    def test_error(self, set_env):
        """GET /server/security/{id}/apps 400 raises APIError."""
        handler, captured = _make_serversec_handler(apps_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with pytest.raises(APIError):
            asyncio.run(
                _async_client_call(
                    PatchedClient,
                    "get_server_security_apps",
                    server_id=1089270,
                )
            )

    def test_filter_by(self, set_env):
        """GET /server/security/{id}/apps with filter_by (no bracket suffix)."""
        handler, captured = _make_serversec_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async def _run():
            async with PatchedClient("test@example.com", "key") as client:
                return await client.get_server_security_apps(
                    server_id=1089270, filter_by="infected"
                )

        result = asyncio.run(_run())
        assert isinstance(result, dict)
        url = str(captured[-1].url)
        assert "filter_by=infected" in url
        assert "filter_by%5B%5D" not in url  # filter_by[] absent


# ===================================================================
# Phase 3 CLI Tests
# ===================================================================


def test_stats_success(set_env):
    """serversec stats exits 0 and sends correct params."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "stats",
                "--data-types",
                "bandwidth,requests",
                "--group-by",
                "day",
                "--start",
                "1700000000",
                "--end",
                "1700086400",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    url = str(captured[-1].url)
    assert "data_types%5B%5D=bandwidth" in url
    assert "data_types%5B%5D=requests" in url
    assert "group_by=day" in url
    assert "start=1700000000" in url
    assert "end=1700086400" in url


def test_stats_error(set_env):
    """serversec stats exits 1 on API error."""
    handler, captured = _make_serversec_handler(stats_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "stats",
                "--data-types",
                "bandwidth",
                "--group-by",
                "day",
                "--start",
                "1700000000",
                "--end",
                "1700086400",
            ],
        )

    assert result.exit_code == 1


def test_infected_domains_success(set_env):
    """serversec infected-domains uses offset/limit (not page/page_limit)."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "infected-domains"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    url = str(captured[-1].url)
    assert "offset=0" in url
    assert "limit=20" in url


def test_infected_domains_error(set_env):
    """serversec infected-domains exits 1 on API error."""
    handler, captured = _make_serversec_handler(
        infected_domains_error=True
    )
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "infected-domains"],
        )

    assert result.exit_code == 1


def test_infected_domains_sync_success(set_env):
    """serversec infected-domains-sync sends POST with server_id body."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "infected-domains-sync"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    assert req.method == "POST"
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]


def test_infected_domains_sync_error(set_env):
    """serversec infected-domains-sync exits 1 on API error."""
    handler, captured = _make_serversec_handler(
        infected_domains_sync_error=True
    )
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "infected-domains-sync"],
        )

    assert result.exit_code == 1


def test_firewall_settings_success(set_env):
    """serversec firewall-settings exits 0."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "firewall-settings"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0


def test_firewall_settings_error(set_env):
    """serversec firewall-settings exits 1 on API error."""
    handler, captured = _make_serversec_handler(
        firewall_settings_get_error=True
    )
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "firewall-settings"],
        )

    assert result.exit_code == 1


def test_firewall_update_full(set_env):
    """serversec firewall-update with both options sends full body."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "firewall-update",
                "--request-limit",
                "100",
                "--weak-password",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]
    assert parsed["request_limit"] == ["100"]
    assert parsed["weak_password"] == ["1"]


def test_firewall_update_partial(set_env):
    """serversec firewall-update with only request_limit (no weak_password key)."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "firewall-update",
                "--request-limit",
                "50",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]
    assert parsed["request_limit"] == ["50"]
    assert "weak_password" not in parsed


def test_firewall_update_no_weak_password(set_env):
    """serversec firewall-update --no-weak-password sends weak_password=0."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "firewall-update",
                "--no-weak-password",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]
    assert parsed["weak_password"] == ["0"]
    assert "request_limit" not in parsed


def test_firewall_update_no_flags(set_env):
    """serversec firewall-update with no flags sends only server_id."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "firewall-update"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    req = captured[-1]
    body = req.content.decode()
    parsed = parse_qs(body)
    assert parsed["server_id"] == ["1089270"]
    assert "request_limit" not in parsed
    assert "weak_password" not in parsed


def test_firewall_update_error(set_env):
    """serversec firewall-update exits 1 on API error."""
    handler, captured = _make_serversec_handler(
        firewall_settings_put_error=True
    )
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            [
                "serversec",
                "firewall-update",
                "--request-limit",
                "100",
            ],
        )

    assert result.exit_code == 1


def test_apps_success(set_env):
    """serversec apps uses page/page_limit (not offset/limit)."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "apps"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    url = str(captured[-1].url)
    assert "page=1" in url
    assert "page_limit=20" in url
    assert "server_id=1089270" in url


def test_apps_with_filter_by(set_env):
    """serversec apps --filter-by infected sends filter_by (no brackets)."""
    handler, captured = _make_serversec_handler()
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "apps", "--filter-by", "infected"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    url = str(captured[-1].url)
    assert "filter_by=infected" in url
    assert "filter_by%5B%5D" not in url  # filter_by[] absent


def test_apps_error(set_env):
    """serversec apps exits 1 on API error."""
    handler, captured = _make_serversec_handler(apps_error=True)
    transport = httpx.MockTransport(handler)
    PatchedClient = make_patched_client_class(transport)

    with patch(
        "cloudways_api.commands.serversec.CloudwaysClient", PatchedClient
    ):
        result = runner.invoke(
            app,
            ["serversec", "apps"],
        )

    assert result.exit_code == 1
