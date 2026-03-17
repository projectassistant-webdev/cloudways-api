"""Tests for ssh-key command group and SSH key client methods.

Covers SSH key add and delete commands with mocked Cloudways API
responses, plus client method tests for SSH key operations.
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
    ]
}

MOCK_CREDS_EMPTY_RESPONSE = {
    "app_creds": []
}

MOCK_SSH_KEY_ADD_RESPONSE = {
    "ssh_key": {
        "id": 5001,
        "label": "my-key",
    },
    "status": True,
}

MOCK_SSH_KEY_DELETE_RESPONSE = {}

VALID_SSH_RSA_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 user@host"
VALID_SSH_ED25519_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH user@host"
VALID_ECDSA_KEY = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTY user@host"
INVALID_SSH_KEY = "not-a-valid-key data here"


# --- API handler factories ---


def _make_ssh_key_handler(
    creds_response=None,
    add_response=None,
    delete_response=None,
    rename_response=None,
    add_error=False,
    delete_error=False,
    rename_error=False,
):
    """Build httpx mock handler for ssh-key API calls."""
    if creds_response is None:
        creds_response = MOCK_CREDS_LIST_RESPONSE
    if add_response is None:
        add_response = MOCK_SSH_KEY_ADD_RESPONSE
    if delete_response is None:
        delete_response = MOCK_SSH_KEY_DELETE_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/app/creds" in url and method == "GET":
            return httpx.Response(200, json=creds_response)

        if "/ssh_key" in url:
            if method == "POST":
                if add_error:
                    return httpx.Response(
                        422, json={"error": True, "error_msg": "Key error"}
                    )
                return httpx.Response(200, json=add_response)
            if method == "DELETE":
                if delete_error:
                    return httpx.Response(404, text="Not found")
                return httpx.Response(200, json=delete_response)
            if method == "PUT":
                if rename_error:
                    return httpx.Response(404, text="Not found")
                return httpx.Response(200, json=rename_response or {})

        return httpx.Response(404)

    return handler


# --- Helper ---


# --- Client method tests ---


class TestAddSshKey:
    """Tests for CloudwaysClient.add_ssh_key()."""

    @pytest.mark.asyncio
    async def test_add_ssh_key_success(self) -> None:
        """Sends POST /ssh_key with correct parameters."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json=MOCK_SSH_KEY_ADD_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.add_ssh_key(
                server_id=1089270,
                app_creds_id=100,
                key_name="my-key",
                public_key=VALID_SSH_RSA_KEY,
            )

        assert result["ssh_key"]["id"] == 5001

    @pytest.mark.asyncio
    async def test_add_ssh_key_api_error(self) -> None:
        """Raises APIError on API failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key" in str(request.url):
                return httpx.Response(422, text="Key error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.add_ssh_key(
                    server_id=1089270,
                    app_creds_id=100,
                    key_name="test",
                    public_key=VALID_SSH_RSA_KEY,
                )


class TestDeleteSshKey:
    """Tests for CloudwaysClient.delete_ssh_key()."""

    @pytest.mark.asyncio
    async def test_delete_ssh_key_success(self) -> None:
        """Sends DELETE /ssh_key/{id} and returns empty dict."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_ssh_key(server_id=1089270, ssh_key_id=5001)

        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_ssh_key_api_error(self) -> None:
        """Raises APIError when key not found."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(404, text="Not found")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.delete_ssh_key(server_id=1089270, ssh_key_id=99999)

    @pytest.mark.asyncio
    async def test_delete_ssh_key_empty_body(self) -> None:
        """Returns {} when DELETE returns 200 with empty body."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_ssh_key(server_id=1089270, ssh_key_id=5001)

        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_ssh_key_204(self) -> None:
        """Returns {} when DELETE returns 204 No Content."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "DELETE":
                return httpx.Response(204, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.delete_ssh_key(server_id=1089270, ssh_key_id=5001)

        assert result == {}


# --- CLI command tests: ssh-key add ---


class TestSshKeyAdd:
    """Tests for `cloudways ssh-key add` command."""

    def test_ssh_key_add_from_file(self, tmp_path, set_env) -> None:
        """AC-13: Adds SSH key from file, prints success."""
        key_file = tmp_path / "id_rsa.pub"
        key_file.write_text(VALID_SSH_RSA_KEY)

        handler = _make_ssh_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "add", "production",
                    "--username", "bitbucket",
                    "--key-file", str(key_file),
                    "--name", "my-key",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "my-key" in result.output
        assert "bitbucket" in result.output

    def test_ssh_key_add_from_stdin(self, set_env) -> None:
        """AC-14: Adds SSH key from stdin."""
        handler = _make_ssh_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "add", "production",
                    "--username", "bitbucket",
                    "--name", "stdin-key",
                    "--stdin",
                ],
                input=VALID_SSH_ED25519_KEY,
            )

        assert result.exit_code == 0, result.output
        assert "stdin-key" in result.output

    def test_ssh_key_add_invalid_format(self, tmp_path, set_env) -> None:
        """AC-15/16: Invalid key format exits with code 1."""
        key_file = tmp_path / "bad.pub"
        key_file.write_text(INVALID_SSH_KEY)

        result = runner.invoke(
            app,
            [
                "ssh-key", "add", "production",
                "--username", "bitbucket",
                "--key-file", str(key_file),
                "--name", "bad-key",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid SSH public key format" in result.output

    def test_ssh_key_add_user_not_found(self, tmp_path, set_env) -> None:
        """AC-17: User not found exits with code 1."""
        key_file = tmp_path / "id_rsa.pub"
        key_file.write_text(VALID_SSH_RSA_KEY)

        handler = _make_ssh_key_handler(creds_response=MOCK_CREDS_EMPTY_RESPONSE)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "add", "production",
                    "--username", "nonexistent",
                    "--key-file", str(key_file),
                    "--name", "my-key",
                ],
            )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_ssh_key_add_mutually_exclusive(self, tmp_path, set_env) -> None:
        """AC-18: --key-file and --stdin together exits with code 1."""
        key_file = tmp_path / "id_rsa.pub"
        key_file.write_text(VALID_SSH_RSA_KEY)

        result = runner.invoke(
            app,
            [
                "ssh-key", "add", "production",
                "--username", "bitbucket",
                "--key-file", str(key_file),
                "--name", "my-key",
                "--stdin",
            ],
        )

        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_ssh_key_add_no_key_source(self, set_env) -> None:
        """AC-19: Neither --key-file nor --stdin exits with code 1."""
        result = runner.invoke(
            app,
            [
                "ssh-key", "add", "production",
                "--username", "bitbucket",
                "--name", "my-key",
            ],
        )

        assert result.exit_code == 1
        assert "Provide --key-file" in result.output

    def test_ssh_key_add_ecdsa_key(self, tmp_path, set_env) -> None:
        """ECDSA keys are accepted as valid format."""
        key_file = tmp_path / "id_ecdsa.pub"
        key_file.write_text(VALID_ECDSA_KEY)

        handler = _make_ssh_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "add", "production",
                    "--username", "bitbucket",
                    "--key-file", str(key_file),
                    "--name", "ecdsa-key",
                ],
            )

        assert result.exit_code == 0, result.output


# --- CLI command tests: ssh-key delete ---


class TestSshKeyDelete:
    """Tests for `cloudways ssh-key delete` command."""

    def test_ssh_key_delete_success(self, set_env) -> None:
        """AC-20/21: Deletes key by ID, exits 0."""
        handler = _make_ssh_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["ssh-key", "delete", "production", "--key-id", "5001"],
            )

        assert result.exit_code == 0, result.output
        assert "Deleted" in result.output
        assert "5001" in result.output

    def test_ssh_key_delete_api_error(self, set_env) -> None:
        """AC-22: API failure exits with code 1."""
        handler = _make_ssh_key_handler(delete_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                ["ssh-key", "delete", "production", "--key-id", "99999"],
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_ssh_key_delete_invalid_environment(self, set_env) -> None:
        """Invalid environment exits with code 1."""
        result = runner.invoke(
            app,
            ["ssh-key", "delete", "nonexistent", "--key-id", "5001"],
        )
        assert result.exit_code == 1
        assert "not found" in result.output


# --- CLI registration tests ---


class TestSshKeyRegistration:
    """Tests for ssh-key command registration in CLI."""

    def test_ssh_key_in_help(self) -> None:
        """ssh-key appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "ssh-key" in result.output

    def test_ssh_key_help(self) -> None:
        """ssh-key --help shows subcommands."""
        result = runner.invoke(app, ["ssh-key", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "delete" in result.output
        assert "rename" in result.output


# --- Client method tests: update_ssh_key ---


class TestUpdateSshKey:
    """Tests for CloudwaysClient.update_ssh_key()."""

    @pytest.mark.asyncio
    async def test_update_ssh_key_success(self) -> None:
        """Sends PUT /ssh_key/{id} with correct parameters."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "PUT":
                return httpx.Response(200, json={})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_ssh_key(
                server_id=1089270, ssh_key_id=5001, key_name="deploy-key"
            )

        assert result == {}
        # Find the PUT request in captured requests
        request = [r for r in captured if r.method == "PUT"][0]
        assert request.method == "PUT"
        assert "/ssh_key/5001" in str(request.url)
        decoded_body = request.content.decode()
        assert "server_id" in decoded_body
        assert "ssh_key_name" in decoded_body

    @pytest.mark.asyncio
    async def test_update_ssh_key_api_error(self) -> None:
        """Raises APIError when key not found."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "PUT":
                return httpx.Response(404, text="Not found")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_ssh_key(
                    server_id=1089270, ssh_key_id=99999, key_name="test"
                )

    @pytest.mark.asyncio
    async def test_update_ssh_key_empty_body(self) -> None:
        """Returns {} when PUT returns 200 with empty body."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "PUT":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_ssh_key(
                server_id=1089270, ssh_key_id=5001, key_name="deploy-key"
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_update_ssh_key_204(self) -> None:
        """Returns {} when PUT returns 204 No Content."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/ssh_key/" in str(request.url) and request.method == "PUT":
                return httpx.Response(204, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_ssh_key(
                server_id=1089270, ssh_key_id=5001, key_name="deploy-key"
            )

        assert result == {}


# --- CLI command tests: ssh-key rename ---


class TestSshKeyRename:
    """Tests for `cloudways ssh-key rename` command."""

    def test_ssh_key_rename_success(self, set_env) -> None:
        """AC-4/5: Renames key by ID, prints confirmation, exits 0."""
        handler = _make_ssh_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "rename", "production",
                    "--key-id", "5001",
                    "--name", "deploy-key",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Renamed SSH key 5001 to 'deploy-key'" in result.output

    def test_ssh_key_rename_blank_name(self, set_env) -> None:
        """AC-6: Blank --name exits with code 1."""
        result = runner.invoke(
            app,
            [
                "ssh-key", "rename", "production",
                "--key-id", "5001",
                "--name", "",
            ],
        )

        assert result.exit_code == 1
        assert "--name cannot be blank" in result.output

    def test_ssh_key_rename_whitespace_name(self, set_env) -> None:
        """AC-7: Whitespace-only --name exits with code 1."""
        result = runner.invoke(
            app,
            [
                "ssh-key", "rename", "production",
                "--key-id", "5001",
                "--name", "   ",
            ],
        )

        assert result.exit_code == 1
        assert "--name cannot be blank" in result.output

    def test_ssh_key_rename_api_error(self, set_env) -> None:
        """AC-8: API 404 exits with code 1."""
        handler = _make_ssh_key_handler(rename_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.ssh_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-key", "rename", "production",
                    "--key-id", "5001",
                    "--name", "deploy-key",
                ],
            )

        assert result.exit_code == 1
        assert "API request failed with status 404" in result.output

    def test_ssh_key_rename_invalid_environment(self, set_env) -> None:
        """AC-9: Invalid environment exits with code 1."""
        result = runner.invoke(
            app,
            [
                "ssh-key", "rename", "nonexistent",
                "--key-id", "5001",
                "--name", "deploy-key",
            ],
        )

        assert result.exit_code == 1
        assert "Environment 'nonexistent' not found" in result.output
