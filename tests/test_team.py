"""Tests for Team Member management commands and client methods.

Covers listing, adding, updating, and removing team members
with mocked Cloudways API responses, plus client method tests
for all Team Member API operations.
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


def _make_team_handler(
    list_response=None,
    list_error=False,
    add_response=None,
    add_error=False,
    update_response=None,
    update_error=False,
    delete_response=None,
    delete_error=False,
):
    """Build httpx mock handler for team member API calls.

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

        # CRITICAL: Match /member/{numeric_id} BEFORE bare /member
        if re.search(r"/member/(\d+)", url):
            if method == "PUT":
                if update_error:
                    return httpx.Response(400, text="Member not found")
                return httpx.Response(
                    200,
                    json=update_response
                    or {
                        "contents": {
                            "members": {
                                "26740": {
                                    "id": 26740,
                                    "name": "Jane Doe",
                                    "email": "jane@example.com",
                                    "role": "Developer",
                                    "status": "active",
                                    "permissions": {"is_full": False},
                                }
                            }
                        }
                    },
                )
            if method == "DELETE":
                if delete_error:
                    return httpx.Response(400, text="Member not found")
                return httpx.Response(
                    200, json=delete_response or {"contents": []}
                )

        # Bare /member path
        if "/member" in url:
            if method == "GET":
                if list_error:
                    return httpx.Response(400, text="Request failed")
                return httpx.Response(
                    200,
                    json=list_response
                    or {
                        "contents": {
                            "members": {
                                "26740": {
                                    "id": 26740,
                                    "name": "Jane Doe",
                                    "email": "jane@example.com",
                                    "role": "Project Manager",
                                    "status": "active",
                                    "permissions": {"is_full": False},
                                }
                            }
                        }
                    },
                )
            if method == "POST":
                if add_error:
                    return httpx.Response(400, text="Member already exists")
                return httpx.Response(
                    200,
                    json=add_response
                    or {
                        "contents": {
                            "members": {
                                "26740": {
                                    "id": 26740,
                                    "name": "Jane Doe",
                                    "email": "jane@example.com",
                                    "role": "Project Manager",
                                    "status": "active",
                                    "permissions": {"is_full": False},
                                }
                            }
                        }
                    },
                )

        return httpx.Response(404)

    return handler, captured


# --- Environment helper ---


# ===================================================================
# Client tests
# ===================================================================


class TestGetMembers:
    """Tests for CloudwaysClient.get_members()."""

    @pytest.mark.asyncio
    async def test_get_members_success(self):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            result = await client.get_members()
        assert result["contents"]["members"]["26740"]["name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_get_members_error(self):
        handler, captured = _make_team_handler(list_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.get_members()
        assert "400" in str(exc_info.value)


class TestAddMember:
    """Tests for CloudwaysClient.add_member()."""

    @pytest.mark.asyncio
    async def test_add_member_success(self):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            await client.add_member(
                name="Jane Doe", email="jane@example.com"
            )
        request = captured[-1]
        body = request.content.decode()
        assert "name" in body
        assert "email" in body

    @pytest.mark.asyncio
    async def test_add_member_error(self):
        handler, captured = _make_team_handler(add_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.add_member(
                    name="Jane Doe", email="jane@example.com"
                )
        assert "400" in str(exc_info.value)


class TestUpdateMember:
    """Tests for CloudwaysClient.update_member()."""

    @pytest.mark.asyncio
    async def test_update_member_success(self):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            await client.update_member(26740, name="Jane Doe")
        request = captured[-1]
        assert "/member/26740" in str(request.url)
        body = request.content.decode()
        assert "name" in body

    @pytest.mark.asyncio
    async def test_update_member_error(self):
        handler, captured = _make_team_handler(update_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.update_member(26740, name="Jane Doe")
        assert "400" in str(exc_info.value)


class TestDeleteMember:
    """Tests for CloudwaysClient.delete_member()."""

    @pytest.mark.asyncio
    async def test_delete_member_success(self):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            await client.delete_member(26740)
        request = captured[-1]
        assert "/member/26740" in str(request.url)
        body = request.content.decode()
        assert "id=26740" in body

    @pytest.mark.asyncio
    async def test_delete_member_error(self):
        handler, captured = _make_team_handler(delete_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        async with PatchedClient("test@example.com", "test-key") as client:
            with pytest.raises(APIError) as exc_info:
                await client.delete_member(26740)
        assert "400" in str(exc_info.value)


# ===================================================================
# CLI tests
# ===================================================================


class TestTeamListCli:
    """Tests for 'cloudways team list' CLI command."""

    def test_team_list_success(self, set_env):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        assert "Jane Doe" in result.output
        assert "jane@example.com" in result.output
        assert "ID:" in result.output

    def test_team_list_error(self, set_env):
        handler, captured = _make_team_handler(list_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 1


class TestTeamAddCli:
    """Tests for 'cloudways team add' CLI command."""

    def test_team_add_success(self, set_env):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "team",
                    "add",
                    "--email",
                    "jane@example.com",
                    "--name",
                    "Jane Doe",
                ],
            )
        assert result.exit_code == 0
        assert "Success: Team member added." in result.output
        # Verify request body
        post_requests = [
            r
            for r in captured
            if "/member" in str(r.url) and r.method == "POST"
        ]
        assert len(post_requests) == 1
        body = post_requests[0].content.decode()
        assert "name" in body
        assert "email" in body

    def test_team_add_error(self, set_env):
        handler, captured = _make_team_handler(add_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "team",
                    "add",
                    "--email",
                    "jane@example.com",
                    "--name",
                    "Jane Doe",
                ],
            )
        assert result.exit_code == 1


class TestTeamUpdateCli:
    """Tests for 'cloudways team update' CLI command."""

    def test_team_update_success(self, set_env):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["team", "update", "26740", "--name", "Jane Doe"]
            )
        assert result.exit_code == 0
        assert "Success: Team member updated." in result.output
        # Verify request URL and body
        put_requests = [
            r
            for r in captured
            if re.search(r"/member/26740", str(r.url)) and r.method == "PUT"
        ]
        assert len(put_requests) == 1
        body = put_requests[0].content.decode()
        assert "name" in body

    def test_team_update_error(self, set_env):
        handler, captured = _make_team_handler(update_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["team", "update", "26740", "--name", "Jane Doe"]
            )
        assert result.exit_code == 1

    def test_team_update_noop(self, set_env):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["team", "update", "26740"])
        assert result.exit_code == 1
        assert "At least one of --name or --role is required" in result.output


class TestTeamRemoveCli:
    """Tests for 'cloudways team remove' CLI command."""

    def test_team_remove_success(self, set_env):
        handler, captured = _make_team_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["team", "remove", "26740"])
        assert result.exit_code == 0
        assert "Success: Team member removed." in result.output
        # Verify request URL and body (DELETE requires id in body)
        delete_requests = [
            r
            for r in captured
            if re.search(r"/member/26740", str(r.url))
            and r.method == "DELETE"
        ]
        assert len(delete_requests) == 1
        body = delete_requests[0].content.decode()
        assert "id=26740" in body

    def test_team_remove_error(self, set_env):
        handler, captured = _make_team_handler(delete_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)
        with patch(
            "cloudways_api.commands.team.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["team", "remove", "26740"])
        assert result.exit_code == 1
