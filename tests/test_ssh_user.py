"""Tests for ssh-user command group and credential client methods.

Covers SSH/SFTP user create, list, and delete commands with mocked
Cloudways API responses, plus client method tests for credential CRUD.
"""

import os
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from tests.conftest import make_auth_response, make_patched_client_class

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# --- Mock API response data ---

MOCK_CREDS_LIST_RESPONSE = {
    "app_creds": [
        {
            "id": 100,
            "sys_user": "bitbucket",
            "ip": "159.223.142.14",
        },
        {
            "id": 101,
            "sys_user": "deploy",
            "ip": "159.223.142.14",
        },
    ]
}

MOCK_CREDS_EMPTY_RESPONSE = {
    "app_creds": []
}

MOCK_CRED_CREATE_RESPONSE = {
    "app_cred": {
        "id": 102,
        "sys_user": "newuser",
    },
    "status": True,
}

MOCK_CRED_DELETE_RESPONSE = {}


# --- API handler factories ---


def _make_creds_handler(
    creds_response=None,
    create_response=None,
    delete_response=None,
    create_error=False,
    delete_error=False,
):
    """Build httpx mock handler for ssh-user API calls."""
    if creds_response is None:
        creds_response = MOCK_CREDS_LIST_RESPONSE
    if create_response is None:
        create_response = MOCK_CRED_CREATE_RESPONSE
    if delete_response is None:
        delete_response = MOCK_CRED_DELETE_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/app/creds" in url:
            if method == "GET":
                return httpx.Response(200, json=creds_response)
            if method == "POST":
                if create_error:
                    return httpx.Response(
                        422, json={"error": True, "error_msg": "Validation failed"}
                    )
                return httpx.Response(200, json=create_response)
            if method == "DELETE":
                if delete_error:
                    return httpx.Response(
                        404, json={"error": True, "error_msg": "Not found"}
                    )
                return httpx.Response(200, json=delete_response)

        return httpx.Response(404)

    return handler


# --- Helper to set env vars ---


# --- Client method tests ---


class TestCreateAppCredential:
    """Tests for CloudwaysClient.create_app_credential()."""

    @pytest.mark.asyncio
    async def test_create_app_credential_success(self) -> None:
        """Sends POST /app/creds with correct parameters."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json=MOCK_CRED_CREATE_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.create_app_credential(
                server_id=1089270, app_id=3937401, username="newuser", password="pass123"
            )

        assert result["app_cred"]["id"] == 102
        post_reqs = [r for r in captured if r.method == "POST" and "/app/creds" in str(r.url)]
        assert len(post_reqs) == 1

    @pytest.mark.asyncio
    async def test_create_app_credential_api_error(self) -> None:
        """Raises APIError on API failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in str(request.url):
                return httpx.Response(422, text="Validation failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.create_app_credential(
                    server_id=1089270, app_id=3937401, username="newuser", password="p"
                )


class TestGetAppCredentials:
    """Tests for CloudwaysClient.get_app_credentials()."""

    @pytest.mark.asyncio
    async def test_get_app_credentials_success(self) -> None:
        """Returns list of credentials from API."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in str(request.url) and request.method == "GET":
                return httpx.Response(200, json=MOCK_CREDS_LIST_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_credentials(
                server_id=1089270, app_id=3937401
            )

        assert len(result) == 2
        assert result[0]["sys_user"] == "bitbucket"

    @pytest.mark.asyncio
    async def test_get_app_credentials_empty(self) -> None:
        """Returns empty list when no credentials exist."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in str(request.url) and request.method == "GET":
                return httpx.Response(200, json=MOCK_CREDS_EMPTY_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_app_credentials(
                server_id=1089270, app_id=3937401
            )

        assert result == []


class TestDeleteAppCredential:
    """Tests for CloudwaysClient.delete_app_credential()."""

    @pytest.mark.asyncio
    async def test_delete_app_credential_success(self) -> None:
        """Sends DELETE /app/creds/{id} with correct parameters."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_app_credential(
                server_id=1089270, app_id=3937401, app_cred_id=100
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_app_credential_not_found(self) -> None:
        """Raises APIError when credential not found."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(404, text="Not found")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.delete_app_credential(
                    server_id=1089270, app_id=3937401, app_cred_id=99999
                )

    @pytest.mark.asyncio
    async def test_delete_app_credential_empty_body(self) -> None:
        """Returns {} when DELETE returns 200 with empty body."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_app_credential(
                server_id=1089270, app_id=3937401, app_cred_id=100
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_app_credential_204(self) -> None:
        """Returns {} when DELETE returns 204 No Content."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(204, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_app_credential(
                server_id=1089270, app_id=3937401, app_cred_id=100
            )

        assert result == {}


# --- CLI command tests: ssh-user create ---


class TestSshUserCreate:
    """Tests for `cloudways ssh-user create` command."""

    def test_ssh_user_create_success(self, set_env) -> None:
        """AC-1/2/3: Creates user, prints cred_id and password, exits 0."""
        handler = _make_creds_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
            create_response=MOCK_CRED_CREATE_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "create", "production", "--username", "newuser"]
            )

        assert result.exit_code == 0, result.output
        assert "newuser" in result.output
        assert "102" in result.output  # cred_id
        assert "Password:" in result.output

    def test_ssh_user_create_duplicate(self, set_env) -> None:
        """AC-3 (error path): Duplicate user exits with code 1."""
        handler = _make_creds_handler(creds_response=MOCK_CREDS_LIST_RESPONSE)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "create", "production", "--username", "bitbucket"]
            )

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_ssh_user_create_api_error(self, set_env) -> None:
        """AC-4: API failure exits with code 1."""
        handler = _make_creds_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
            create_error=True,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "create", "production", "--username", "newuser"]
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_ssh_user_create_already_exists_on_server(self, set_env) -> None:
        """Username already exists on server returns helpful suggestion."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in url:
                if request.method == "GET":
                    return httpx.Response(200, json=MOCK_CREDS_EMPTY_RESPONSE)
                if request.method == "POST":
                    # Cloudways API returns 599 with "Username already exists."
                    return httpx.Response(
                        599,
                        text='{"message":"Username already exists."}',
                    )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["ssh-user", "create", "production", "--username", "bitbucket"],
            )

        assert result.exit_code == 1
        assert "already exists on this server" in result.output
        assert "shared servers" in result.output.lower()
        assert "bitbucket-stg" in result.output
        assert "bitbucket-prod" in result.output

    def test_ssh_user_create_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(
            app, ["ssh-user", "create", "nonexistent", "--username", "test"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output


# --- CLI command tests: ssh-user list ---


class TestSshUserList:
    """Tests for `cloudways ssh-user list` command."""

    def test_ssh_user_list_success(self, set_env) -> None:
        """AC-5/6/8: Lists users in table format, exits 0."""
        handler = _make_creds_handler(creds_response=MOCK_CREDS_LIST_RESPONSE)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["ssh-user", "list", "production"])

        assert result.exit_code == 0, result.output
        assert "bitbucket" in result.output
        assert "deploy" in result.output

    def test_ssh_user_list_empty(self, set_env) -> None:
        """AC-7: Prints 'No SSH/SFTP users found' when empty."""
        handler = _make_creds_handler(creds_response=MOCK_CREDS_EMPTY_RESPONSE)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(app, ["ssh-user", "list", "production"])

        assert result.exit_code == 0, result.output
        assert "No SSH/SFTP users found" in result.output

    def test_ssh_user_list_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(app, ["ssh-user", "list", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# --- CLI command tests: ssh-user delete ---


class TestSshUserDelete:
    """Tests for `cloudways ssh-user delete` command."""

    def test_ssh_user_delete_success(self, set_env) -> None:
        """AC-9/10/12: Deletes user by username, exits 0."""
        handler = _make_creds_handler(
            creds_response=MOCK_CREDS_LIST_RESPONSE,
            delete_response=MOCK_CRED_DELETE_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "delete", "production", "--username", "bitbucket"]
            )

        assert result.exit_code == 0, result.output
        assert "Deleted" in result.output
        assert "bitbucket" in result.output

    def test_ssh_user_delete_not_found(self, set_env) -> None:
        """AC-11: User not found prints available users."""
        handler = _make_creds_handler(creds_response=MOCK_CREDS_LIST_RESPONSE)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "delete", "production", "--username", "nonexistent"]
            )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_ssh_user_delete_api_error(self, set_env) -> None:
        """API failure exits with code 1."""
        handler = _make_creds_handler(
            creds_response=MOCK_CREDS_LIST_RESPONSE,
            delete_error=True,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_user.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["ssh-user", "delete", "production", "--username", "bitbucket"]
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_ssh_user_delete_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(
            app, ["ssh-user", "delete", "nonexistent", "--username", "test"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output


# --- CLI registration tests ---


class TestSshUserRegistration:
    """Tests for ssh-user command registration in CLI."""

    def test_ssh_user_in_help(self) -> None:
        """ssh-user appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "ssh-user" in result.output

    def test_ssh_user_help(self) -> None:
        """ssh-user --help shows subcommands."""
        result = runner.invoke(app, ["ssh-user", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "delete" in result.output
