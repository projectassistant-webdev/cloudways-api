"""Tests for the ssh-setup composite command.

Covers the full workflow: user creation, SSH key addition, deploy key
generation, and Bitbucket registration. All API calls are mocked via
httpx.MockTransport and unittest.mock patches.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import BitbucketError
from tests.conftest import make_auth_response, make_patched_client_class

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# --- Mock API response data ---

MOCK_CREDS_EMPTY_RESPONSE = {"app_creds": []}

MOCK_CREDS_LIST_RESPONSE = {
    "app_creds": [
        {
            "id": 100,
            "sys_user": "bitbucket",
            "ip": "159.223.142.14",
        },
    ]
}

MOCK_CRED_CREATE_RESPONSE = {
    "app_cred": {
        "id": 102,
        "sys_user": "bitbucket",
    },
    "status": True,
}

MOCK_SSH_KEY_ADD_RESPONSE = {
    "ssh_key": {
        "id": 500,
    },
    "status": True,
}

MOCK_GENERATE_KEY_RESPONSE = {"status": True}

MOCK_GET_KEY_RESPONSE = {
    "public_key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 deploy@server",
}

MOCK_BB_ADD_KEY_RESPONSE = {
    "id": 900,
    "key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 deploy@server",
    "label": "cloudways-production",
}

# Valid SSH key for --key-file
VALID_SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGtest test@machine"


# --- API handler factories ---


def _make_ssh_setup_handler(
    creds_response=None,
    create_response=None,
    ssh_key_response=None,
    generate_response=None,
    get_key_response=None,
    create_error=False,
    ssh_key_error=False,
    generate_error=False,
    get_key_error=False,
):
    """Build httpx mock handler for the full ssh-setup workflow."""
    if creds_response is None:
        creds_response = MOCK_CREDS_EMPTY_RESPONSE
    if create_response is None:
        create_response = MOCK_CRED_CREATE_RESPONSE
    if ssh_key_response is None:
        ssh_key_response = MOCK_SSH_KEY_ADD_RESPONSE
    if generate_response is None:
        generate_response = MOCK_GENERATE_KEY_RESPONSE
    if get_key_response is None:
        get_key_response = MOCK_GET_KEY_RESPONSE

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
                        422, json={"error": True, "error_msg": "Create failed"}
                    )
                return httpx.Response(200, json=create_response)

        if "/ssh_key" in url and method == "POST":
            if ssh_key_error:
                return httpx.Response(
                    422, json={"error": True, "error_msg": "SSH key failed"}
                )
            return httpx.Response(200, json=ssh_key_response)

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


def _make_key_file(tmp_path: Path) -> str:
    """Create a temporary SSH public key file and return its path."""
    key_file = tmp_path / "id_ed25519.pub"
    key_file.write_text(VALID_SSH_KEY)
    return str(key_file)


def _mock_bb_client():
    """Create a mock BitbucketClient that succeeds."""
    mock = MagicMock()
    mock.add_deploy_key = AsyncMock(return_value=MOCK_BB_ADD_KEY_RESPONSE)
    return mock


# --- Tests: Full success path ---


class TestSshSetupSuccess:
    """Tests for successful ssh-setup execution."""

    def test_full_success_user_created(self, set_env, tmp_path) -> None:
        """AC-35/37/38/40/41: Full path - creates user, adds key, sets up deploy key."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = _mock_bb_client()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Created" in result.output or "bitbucket" in result.output
        assert "SSH key" in result.output
        assert "Deploy key" in result.output or "deploy" in result.output.lower()
        mock_bb.add_deploy_key.assert_called_once()

    def test_user_already_exists(self, set_env, tmp_path) -> None:
        """AC-36: Skips user creation when user already exists."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_LIST_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = _mock_bb_client()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 0, result.output
        # Should indicate user already exists (skipped creation)
        assert "exists" in result.output.lower() or "found" in result.output.lower()
        # Should still add key and deploy key
        assert "SSH key" in result.output
        mock_bb.add_deploy_key.assert_called_once()


# --- Tests: --skip-deploy-key flag ---


class TestSshSetupSkipDeployKey:
    """Tests for --skip-deploy-key flag."""

    def test_skip_deploy_key(self, set_env, tmp_path) -> None:
        """AC-39: --skip-deploy-key skips deploy key generation and registration."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb_cls = MagicMock()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                mock_bb_cls,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                    "--skip-deploy-key",
                ],
            )

        assert result.exit_code == 0, result.output
        # BitbucketClient should never be instantiated
        mock_bb_cls.assert_not_called()
        # Output should mention skipping deploy key
        assert "skip" in result.output.lower() or "SSH key" in result.output


# --- Tests: Failure at each step ---


class TestSshSetupFailures:
    """Tests for failure at each step of the ssh-setup workflow."""

    def test_user_creation_failure(self, set_env, tmp_path) -> None:
        """AC-42: User creation failure stops execution."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
            create_error=True,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        with patch(
            "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 1

    def test_ssh_key_add_failure(self, set_env, tmp_path) -> None:
        """AC-42: SSH key add failure stops execution."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
            ssh_key_error=True,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        with patch(
            "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 1

    def test_deploy_key_generate_failure(self, set_env, tmp_path) -> None:
        """AC-42: Deploy key generation failure stops execution."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
            generate_error=True,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        with patch(
            "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 1

    def test_deploy_key_register_failure(self, set_env, tmp_path) -> None:
        """AC-42: Bitbucket registration failure stops execution."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = MagicMock()
        mock_bb.add_deploy_key = AsyncMock(
            side_effect=BitbucketError("Registration failed")
        )

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 1


# --- Tests: Input validation ---


class TestSshSetupInputValidation:
    """Tests for input validation in ssh-setup."""

    def test_missing_key_file(self, set_env, tmp_path) -> None:
        """Missing key file exits with error."""
        result = runner.invoke(
            app,
            [
                "ssh-setup",
                "production",
                "--username",
                "bitbucket",
                "--key-file",
                "/nonexistent/path/key.pub",
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Error" in result.output

    def test_invalid_key_format(self, set_env, tmp_path) -> None:
        """Invalid SSH key format exits with error."""
        bad_key = tmp_path / "bad_key.pub"
        bad_key.write_text("not-a-valid-ssh-key just random text")

        result = runner.invoke(
            app,
            [
                "ssh-setup",
                "production",
                "--username",
                "bitbucket",
                "--key-file",
                str(bad_key),
            ],
        )

        assert result.exit_code == 1
        assert "Invalid" in result.output or "format" in result.output.lower()

    def test_invalid_environment(self, set_env, tmp_path) -> None:
        """Invalid environment exits with error."""
        key_file = _make_key_file(tmp_path)
        result = runner.invoke(
            app,
            [
                "ssh-setup",
                "nonexistent",
                "--username",
                "bitbucket",
                "--key-file",
                key_file,
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output


# --- Tests: --key-name flag ---


class TestSshSetupKeyName:
    """Tests for --key-name flag behavior."""

    def test_default_key_name(self, set_env, tmp_path) -> None:
        """Default key name is <username>-<environment>."""
        captured_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            url = str(request.url)
            method = request.method

            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in url and method == "GET":
                return httpx.Response(200, json=MOCK_CREDS_EMPTY_RESPONSE)
            if "/app/creds" in url and method == "POST":
                return httpx.Response(200, json=MOCK_CRED_CREATE_RESPONSE)
            if "/ssh_key" in url and method == "POST":
                return httpx.Response(200, json=MOCK_SSH_KEY_ADD_RESPONSE)
            if "/git/generateKey" in url:
                return httpx.Response(200, json=MOCK_GENERATE_KEY_RESPONSE)
            if "/git/key" in url:
                return httpx.Response(200, json=MOCK_GET_KEY_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = _mock_bb_client()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 0, result.output

        # Check that the SSH key POST used the default key name
        ssh_key_reqs = [
            r
            for r in captured_requests
            if "/ssh_key" in str(r.url) and r.method == "POST"
        ]
        assert len(ssh_key_reqs) == 1
        # Body contains the default key name (bitbucket-production)
        body = ssh_key_reqs[0].content.decode()
        assert "bitbucket-production" in body

    def test_custom_key_name(self, set_env, tmp_path) -> None:
        """Custom --key-name is used in the SSH key add call."""
        captured_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            url = str(request.url)
            method = request.method

            if "/oauth/access_token" in url:
                return httpx.Response(200, json=make_auth_response())
            if "/app/creds" in url and method == "GET":
                return httpx.Response(200, json=MOCK_CREDS_EMPTY_RESPONSE)
            if "/app/creds" in url and method == "POST":
                return httpx.Response(200, json=MOCK_CRED_CREATE_RESPONSE)
            if "/ssh_key" in url and method == "POST":
                return httpx.Response(200, json=MOCK_SSH_KEY_ADD_RESPONSE)
            if "/git/generateKey" in url:
                return httpx.Response(200, json=MOCK_GENERATE_KEY_RESPONSE)
            if "/git/key" in url:
                return httpx.Response(200, json=MOCK_GET_KEY_RESPONSE)
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = _mock_bb_client()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                    "--key-name",
                    "my-custom-key",
                ],
            )

        assert result.exit_code == 0, result.output

        ssh_key_reqs = [
            r
            for r in captured_requests
            if "/ssh_key" in str(r.url) and r.method == "POST"
        ]
        assert len(ssh_key_reqs) == 1
        body = ssh_key_reqs[0].content.decode()
        assert "my-custom-key" in body


# --- Tests: Summary output ---


class TestSshSetupSummary:
    """Tests for Rich summary output."""

    def test_summary_shows_all_steps(self, set_env, tmp_path) -> None:
        """AC-40: Summary shows all actions taken."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        mock_bb = _mock_bb_client()

        with (
            patch(
                "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
            ),
            patch(
                "cloudways_api.commands.ssh_setup.detect_bitbucket_repo",
                return_value=("myworkspace", "myrepo"),
            ),
            patch(
                "cloudways_api.commands.ssh_setup.BitbucketClient",
                return_value=mock_bb,
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                ],
            )

        assert result.exit_code == 0, result.output
        output_lower = result.output.lower()
        # Should mention each major step in the summary
        assert "user" in output_lower
        assert "ssh key" in output_lower or "key" in output_lower
        assert "deploy" in output_lower or "bitbucket" in output_lower

    def test_summary_shows_skip_deploy(self, set_env, tmp_path) -> None:
        """Summary reflects skipped deploy key steps."""
        handler = _make_ssh_setup_handler(
            creds_response=MOCK_CREDS_EMPTY_RESPONSE,
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        key_file = _make_key_file(tmp_path)
        with patch(
            "cloudways_api.commands.ssh_setup.CloudwaysClient", PatchedClient
        ):
            result = runner.invoke(
                app,
                [
                    "ssh-setup",
                    "production",
                    "--username",
                    "bitbucket",
                    "--key-file",
                    key_file,
                    "--skip-deploy-key",
                ],
            )

        assert result.exit_code == 0, result.output
        output_lower = result.output.lower()
        assert "user" in output_lower
        assert "ssh key" in output_lower or "key" in output_lower
        # Should mention skip or not mention deploy at all
        assert "skip" in output_lower or "deploy" not in output_lower


# --- Tests: CLI registration ---


class TestSshSetupRegistration:
    """Tests for ssh-setup command registration."""

    def test_ssh_setup_in_help(self) -> None:
        """ssh-setup appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "ssh-setup" in result.output

    def test_ssh_setup_help(self) -> None:
        """ssh-setup --help shows options."""
        result = runner.invoke(app, ["ssh-setup", "--help"])
        assert result.exit_code == 0
        assert "--username" in result.output
        assert "--key-file" in result.output
        assert "--key-name" in result.output
        assert "--skip-deploy-key" in result.output
