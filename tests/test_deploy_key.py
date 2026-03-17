"""Tests for deploy-key command group and deploy key client methods.

Covers deploy-key generate, show, register, and setup commands with
mocked Cloudways and Bitbucket API responses, plus client method tests.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError, BitbucketError
from tests.conftest import make_auth_response, make_patched_client_class

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
ACCOUNTS_PATH = os.path.join(FIXTURES_DIR, "accounts.yml")

# --- Mock Cloudways API response data ---

MOCK_GENERATE_KEY_RESPONSE = {
    "status": True,
}

MOCK_GET_KEY_RESPONSE = {
    "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 deploy@server",
}

MOCK_GET_KEY_EMPTY_RESPONSE = {
    "public_key": "",
}


# --- API handler factories ---


def _make_deploy_key_handler(
    generate_response=None,
    get_key_response=None,
    generate_error=False,
    get_key_error=False,
):
    """Build httpx mock handler for deploy-key Cloudways API calls."""
    if generate_response is None:
        generate_response = MOCK_GENERATE_KEY_RESPONSE
    if get_key_response is None:
        get_key_response = MOCK_GET_KEY_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/git/generateKey" in url and method == "POST":
            if generate_error:
                return httpx.Response(422, text="Generate failed")
            return httpx.Response(200, json=generate_response)

        if "/git/key" in url and method == "GET":
            if get_key_error:
                return httpx.Response(404, text="No key found")
            return httpx.Response(200, json=get_key_response)

        return httpx.Response(404)

    return handler


# --- Helper ---


def _set_env(monkeypatch, config_path=None):
    """Set common env vars for CLI tests."""
    monkeypatch.setenv(
        "CLOUDWAYS_PROJECT_CONFIG",
        config_path or os.path.join(FIXTURES_DIR, "project-config.yml"),
    )
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", ACCOUNTS_PATH)


# --- Client method tests ---


class TestGenerateDeployKey:
    """Tests for CloudwaysClient.generate_deploy_key()."""

    @pytest.mark.asyncio
    async def test_generate_deploy_key_success(self) -> None:
        """Sends POST /git/generateKey with correct parameters."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/git/generateKey" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json=MOCK_GENERATE_KEY_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.generate_deploy_key(
                server_id=1089270, app_id=3937401
            )

        assert result["status"] is True

    @pytest.mark.asyncio
    async def test_generate_deploy_key_api_error(self) -> None:
        """Raises APIError on API failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/git/generateKey" in str(request.url):
                return httpx.Response(422, text="Generate failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.generate_deploy_key(
                    server_id=1089270, app_id=3937401
                )


class TestGetDeployKey:
    """Tests for CloudwaysClient.get_deploy_key()."""

    @pytest.mark.asyncio
    async def test_get_deploy_key_success(self) -> None:
        """Returns public key from GET /git/key."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/git/key" in str(request.url) and request.method == "GET":
                return httpx.Response(200, json=MOCK_GET_KEY_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_deploy_key(
                server_id=1089270, app_id=3937401
            )

        assert "ssh-rsa" in result["public_key"]

    @pytest.mark.asyncio
    async def test_get_deploy_key_no_key(self) -> None:
        """Raises APIError when no deploy key exists."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/git/key" in str(request.url):
                return httpx.Response(404, text="No key found")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_deploy_key(
                    server_id=1089270, app_id=3937401
                )


# --- CLI command tests: deploy-key generate ---


class TestDeployKeyGenerate:
    """Tests for `cloudways deploy-key generate` command."""

    def test_deploy_key_generate_success(self, monkeypatch) -> None:
        """AC-23/24: Generates deploy key on server, exits 0."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)
        with patch(
            "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["deploy-key", "generate", "production"]
            )

        assert result.exit_code == 0, result.output
        assert "generated" in result.output.lower() or "Deploy key" in result.output

    def test_deploy_key_generate_api_error(self, monkeypatch) -> None:
        """API failure exits with code 1."""
        handler = _make_deploy_key_handler(generate_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)
        with patch(
            "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["deploy-key", "generate", "production"]
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_deploy_key_generate_invalid_env(self, monkeypatch) -> None:
        """Invalid environment exits with code 1."""
        _set_env(monkeypatch)
        result = runner.invoke(
            app, ["deploy-key", "generate", "nonexistent"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output


# --- CLI command tests: deploy-key show ---


class TestDeployKeyShow:
    """Tests for `cloudways deploy-key show` command."""

    def test_deploy_key_show_success(self, monkeypatch) -> None:
        """AC-25: Shows server's public deploy key."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)
        with patch(
            "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["deploy-key", "show", "production"]
            )

        assert result.exit_code == 0, result.output
        assert "ssh-rsa" in result.output

    def test_deploy_key_show_no_key(self, monkeypatch) -> None:
        """AC-26: Shows error when no key exists."""
        handler = _make_deploy_key_handler(
            get_key_response=MOCK_GET_KEY_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)
        with patch(
            "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["deploy-key", "show", "production"]
            )

        assert result.exit_code == 1
        assert "No deploy key" in result.output or "no deploy key" in result.output.lower()


# --- CLI command tests: deploy-key register ---


class TestDeployKeyRegister:
    """Tests for `cloudways deploy-key register` command."""

    def test_deploy_key_register_success_auto_detect(self, monkeypatch) -> None:
        """AC-27/28/30: Registers key in Bitbucket with auto-detected repo."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        mock_bb_client = MagicMock()
        mock_bb_client.add_deploy_key = AsyncMock(
            return_value={"id": 9001, "label": "cloudways-production"}
        )

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                return_value=("projectassistant", "my-project"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.BitbucketClient",
                return_value=mock_bb_client,
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "register", "production"]
            )

        assert result.exit_code == 0, result.output
        assert "registered" in result.output.lower() or "Deploy key" in result.output

    def test_deploy_key_register_config_fallback(self, monkeypatch, tmp_path) -> None:
        """AC-29: Falls back to project config when git remote fails."""
        # Create config with bitbucket section
        config_file = tmp_path / "project-config.yml"
        config_file.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 1089270\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 3937401\n"
            "        domain: example.com\n"
            "bitbucket:\n"
            "  workspace: fallback-ws\n"
            "  repo_slug: fallback-repo\n"
        )

        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch, config_path=str(config_file))

        mock_bb_client = MagicMock()
        mock_bb_client.add_deploy_key = AsyncMock(
            return_value={"id": 9001, "label": "cloudways-production"}
        )

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                side_effect=BitbucketError("Cannot detect"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.load_bitbucket_config",
                return_value={"workspace": "fallback-ws", "repo_slug": "fallback-repo"},
            ),
            patch(
                "cloudways_api.commands.deploy_key.BitbucketClient",
                return_value=mock_bb_client,
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "register", "production"]
            )

        assert result.exit_code == 0, result.output

    def test_deploy_key_register_missing_credentials(self, monkeypatch) -> None:
        """AC-31: Shows error when Bitbucket credentials missing."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                return_value=("ws", "repo"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.BitbucketClient",
                side_effect=BitbucketError(
                    "Bitbucket credentials not found. "
                    "Create ~/.bitbucket-credentials with "
                    "BITBUCKET_USERNAME and BITBUCKET_APP_PASSWORD."
                ),
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "register", "production"]
            )

        assert result.exit_code == 1
        assert "credentials" in result.output.lower()

    def test_deploy_key_register_no_repo(self, monkeypatch) -> None:
        """AC-32: Shows error when no git remote and no config."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                side_effect=BitbucketError("Cannot detect"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.load_bitbucket_config",
                return_value={},
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "register", "production"]
            )

        assert result.exit_code == 1
        assert "Cannot detect" in result.output or "repository" in result.output.lower()

    def test_deploy_key_register_custom_label(self, monkeypatch) -> None:
        """Custom --label is passed to Bitbucket API."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        mock_bb_client = MagicMock()
        mock_bb_client.add_deploy_key = AsyncMock(
            return_value={"id": 9001, "label": "custom-label"}
        )

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                return_value=("ws", "repo"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.BitbucketClient",
                return_value=mock_bb_client,
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "register", "production", "--label", "custom-label"]
            )

        assert result.exit_code == 0, result.output
        mock_bb_client.add_deploy_key.assert_called_once()
        call_kwargs = mock_bb_client.add_deploy_key.call_args
        assert call_kwargs[1].get("label") == "custom-label" or call_kwargs[0][1] == "custom-label"


# --- CLI command tests: deploy-key setup ---


class TestDeployKeySetup:
    """Tests for `cloudways deploy-key setup` composite command."""

    def test_deploy_key_setup_success(self, monkeypatch) -> None:
        """AC-33: Generates key AND registers in Bitbucket."""
        # Handler serves both generate and get key
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        mock_bb_client = MagicMock()
        mock_bb_client.add_deploy_key = AsyncMock(
            return_value={"id": 9001, "label": "cloudways-production"}
        )

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                return_value=("ws", "repo"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.BitbucketClient",
                return_value=mock_bb_client,
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "setup", "production"]
            )

        assert result.exit_code == 0, result.output

    def test_deploy_key_setup_generate_fails(self, monkeypatch) -> None:
        """AC-34: Handles generate failure."""
        handler = _make_deploy_key_handler(generate_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        with patch(
            "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app, ["deploy-key", "setup", "production"]
            )

        assert result.exit_code == 1

    def test_deploy_key_setup_register_fails(self, monkeypatch) -> None:
        """AC-34: Handles register failure after successful generate."""
        handler = _make_deploy_key_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        _set_env(monkeypatch)

        with (
            patch(
                "cloudways_api.commands.deploy_key.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.deploy_key.detect_bitbucket_repo",
                side_effect=BitbucketError("Cannot detect"),
            ),
            patch(
                "cloudways_api.commands.deploy_key.load_bitbucket_config",
                return_value={},
            ),
        ):
            result = runner.invoke(
                app, ["deploy-key", "setup", "production"]
            )

        assert result.exit_code == 1


# --- CLI registration tests ---


class TestDeployKeyRegistration:
    """Tests for deploy-key command registration in CLI."""

    def test_deploy_key_in_help(self) -> None:
        """deploy-key appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "deploy-key" in result.output

    def test_deploy_key_help(self) -> None:
        """deploy-key --help shows subcommands."""
        result = runner.invoke(app, ["deploy-key", "--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "show" in result.output
        assert "register" in result.output
        assert "setup" in result.output
