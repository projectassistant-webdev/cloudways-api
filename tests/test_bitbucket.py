"""Tests for BitbucketClient helper and git remote detection.

Covers credential loading from ~/.bitbucket-credentials, deploy key
CRUD operations, git remote URL parsing, and config fallback.
"""

from unittest.mock import patch

import httpx
import pytest

from cloudways_api.exceptions import BitbucketError


# --- Mock Bitbucket API response data ---

MOCK_DEPLOY_KEY_ADD_RESPONSE = {
    "id": 9001,
    "key": "ssh-rsa AAAAB3... user@host",
    "label": "cloudways-production",
    "type": "deploy_key",
}

MOCK_DEPLOY_KEYS_LIST_RESPONSE = {
    "values": [
        {
            "id": 9001,
            "key": "ssh-rsa AAAAB3... user@host",
            "label": "cloudways-production",
        },
        {
            "id": 9002,
            "key": "ssh-ed25519 AAAAC3... deploy@server",
            "label": "cloudways-staging",
        },
    ]
}

MOCK_DEPLOY_KEYS_EMPTY_RESPONSE = {
    "values": []
}


# --- Bitbucket API mock handler ---


def _make_bb_handler(
    add_response=None,
    list_response=None,
    add_error=False,
    delete_error=False,
):
    """Build httpx mock handler for Bitbucket API calls."""
    if add_response is None:
        add_response = MOCK_DEPLOY_KEY_ADD_RESPONSE
    if list_response is None:
        list_response = MOCK_DEPLOY_KEYS_LIST_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        method = request.method

        if "/deploy-keys" in url:
            if method == "POST":
                if add_error:
                    return httpx.Response(
                        400,
                        json={"error": {"message": "Key already exists"}},
                    )
                return httpx.Response(200, json=add_response)
            if method == "GET":
                return httpx.Response(200, json=list_response)
            if method == "DELETE":
                if delete_error:
                    return httpx.Response(404, json={"error": {"message": "Not found"}})
                return httpx.Response(204, content=b"")

        return httpx.Response(404)

    return handler


# --- BitbucketClient credential loading tests ---


class TestBitbucketClientInit:
    """Tests for BitbucketClient credential loading."""

    def test_init_app_password_auth(self, tmp_path) -> None:
        """Loads App Password credentials from ~/.bitbucket-credentials."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxxxxxxxxxx\n"
        )

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
            )

        assert client._auth_username == "anthony"
        assert client._auth_password == "ATBBxxxxxxxxxxxx"

    def test_init_token_auth(self, tmp_path) -> None:
        """Loads Personal Access Token credentials from ~/.bitbucket-credentials."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_EMAIL=anthony@example.com\n"
            "BITBUCKET_TOKEN=ATATTxxxxxxxxxx\n"
        )

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
            )

        assert client._auth_username == "anthony@example.com"
        assert client._auth_password == "ATATTxxxxxxxxxx"

    def test_init_missing_credentials_file(self, tmp_path) -> None:
        """Raises BitbucketError when credentials file is missing."""
        missing_path = tmp_path / ".bitbucket-credentials"

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=missing_path,
        ):
            with pytest.raises(BitbucketError, match="credentials not found"):
                BitbucketClient(workspace="ws", repo_slug="repo")

    def test_init_incomplete_credentials(self, tmp_path) -> None:
        """Raises BitbucketError when credentials file has neither auth method."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text("SOME_OTHER_VAR=value\n")

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            with pytest.raises(BitbucketError, match="credentials"):
                BitbucketClient(workspace="ws", repo_slug="repo")

    def test_init_export_prefix_app_password(self, tmp_path) -> None:
        """Strips 'export ' prefix from credential lines (bash format)."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "export BITBUCKET_USERNAME=anthony\n"
            "export BITBUCKET_APP_PASSWORD=ATBBxxxxxxxxxxxx\n"
        )

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
            )

        assert client._auth_username == "anthony"
        assert client._auth_password == "ATBBxxxxxxxxxxxx"

    def test_init_export_prefix_quoted_values(self, tmp_path) -> None:
        """Strips quotes around values in 'export KEY="value"' format."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            'export BITBUCKET_EMAIL="anthony@example.com"\n'
            'export BITBUCKET_TOKEN="ATATTxxxxxxxxxx"\n'
        )

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
            )

        assert client._auth_username == "anthony@example.com"
        assert client._auth_password == "ATATTxxxxxxxxxx"


# --- BitbucketClient API method tests ---


class TestBitbucketClientAddDeployKey:
    """Tests for BitbucketClient.add_deploy_key()."""

    @pytest.mark.asyncio
    async def test_add_deploy_key_success(self, tmp_path) -> None:
        """Sends POST to deploy-keys endpoint with key and label."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler()
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            result = await client.add_deploy_key(
                key="ssh-rsa AAAAB3... user@host",
                label="cloudways-production",
            )

        assert result["id"] == 9001
        assert result["label"] == "cloudways-production"

    @pytest.mark.asyncio
    async def test_add_deploy_key_api_error(self, tmp_path) -> None:
        """Raises BitbucketError on API failure."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler(add_error=True)
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            with pytest.raises(BitbucketError):
                await client.add_deploy_key(
                    key="ssh-rsa AAAAB3...",
                    label="test",
                )


class TestBitbucketClientListDeployKeys:
    """Tests for BitbucketClient.list_deploy_keys()."""

    @pytest.mark.asyncio
    async def test_list_deploy_keys_success(self, tmp_path) -> None:
        """Returns list of deploy keys from Bitbucket."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler()
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            result = await client.list_deploy_keys()

        assert len(result) == 2
        assert result[0]["id"] == 9001

    @pytest.mark.asyncio
    async def test_list_deploy_keys_empty(self, tmp_path) -> None:
        """Returns empty list when no deploy keys exist."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler(list_response=MOCK_DEPLOY_KEYS_EMPTY_RESPONSE)
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            result = await client.list_deploy_keys()

        assert result == []


class TestBitbucketClientDeleteDeployKey:
    """Tests for BitbucketClient.delete_deploy_key()."""

    @pytest.mark.asyncio
    async def test_delete_deploy_key_success(self, tmp_path) -> None:
        """Sends DELETE to deploy-keys endpoint."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler()
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            # Should not raise
            await client.delete_deploy_key(key_id=9001)

    @pytest.mark.asyncio
    async def test_delete_deploy_key_not_found(self, tmp_path) -> None:
        """Raises BitbucketError when key not found."""
        creds_file = tmp_path / ".bitbucket-credentials"
        creds_file.write_text(
            "BITBUCKET_USERNAME=anthony\n"
            "BITBUCKET_APP_PASSWORD=ATBBxxxx\n"
        )
        handler = _make_bb_handler(delete_error=True)
        transport = httpx.MockTransport(handler)

        from cloudways_api.bitbucket import BitbucketClient

        with patch.object(
            BitbucketClient,
            "_credentials_path",
            return_value=creds_file,
        ):
            client = BitbucketClient(
                workspace="myworkspace",
                repo_slug="myrepo",
                transport=transport,
            )
            with pytest.raises(BitbucketError):
                await client.delete_deploy_key(key_id=99999)


# --- detect_bitbucket_repo() tests ---


class TestDetectBitbucketRepo:
    """Tests for detect_bitbucket_repo() git remote parsing."""

    def test_detect_ssh_url(self, tmp_path) -> None:
        """Parses workspace/repo from SSH git remote URL."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        config = git_dir / "config"
        config.write_text(
            '[remote "origin"]\n'
            "\turl = git@bitbucket.org:projectassistant/my-project.git\n"
            "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        )

        from cloudways_api.bitbucket import detect_bitbucket_repo

        with patch("cloudways_api.bitbucket.Path") as MockPath:
            # Make Path(".git/config") resolve to our temp file
            mock_path_instance = MockPath.return_value
            mock_path_instance.is_file.return_value = True
            mock_path_instance.read_text.return_value = config.read_text()

            workspace, repo_slug = detect_bitbucket_repo()

        assert workspace == "projectassistant"
        assert repo_slug == "my-project"

    def test_detect_https_url(self, tmp_path) -> None:
        """Parses workspace/repo from HTTPS git remote URL."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        config = git_dir / "config"
        config.write_text(
            '[remote "origin"]\n'
            "\turl = https://bitbucket.org/projectassistant/my-project\n"
            "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        )

        from cloudways_api.bitbucket import detect_bitbucket_repo

        with patch("cloudways_api.bitbucket.Path") as MockPath:
            mock_path_instance = MockPath.return_value
            mock_path_instance.is_file.return_value = True
            mock_path_instance.read_text.return_value = config.read_text()

            workspace, repo_slug = detect_bitbucket_repo()

        assert workspace == "projectassistant"
        assert repo_slug == "my-project"

    def test_detect_https_url_with_git_suffix(self, tmp_path) -> None:
        """Parses workspace/repo from HTTPS URL with .git suffix."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        config = git_dir / "config"
        config.write_text(
            '[remote "origin"]\n'
            "\turl = https://user@bitbucket.org/projectassistant/my-project.git\n"
        )

        from cloudways_api.bitbucket import detect_bitbucket_repo

        with patch("cloudways_api.bitbucket.Path") as MockPath:
            mock_path_instance = MockPath.return_value
            mock_path_instance.is_file.return_value = True
            mock_path_instance.read_text.return_value = config.read_text()

            workspace, repo_slug = detect_bitbucket_repo()

        assert workspace == "projectassistant"
        assert repo_slug == "my-project"

    def test_detect_no_git_remote(self) -> None:
        """Raises BitbucketError when .git/config does not exist."""
        from cloudways_api.bitbucket import detect_bitbucket_repo

        with patch("cloudways_api.bitbucket.Path") as MockPath:
            mock_path_instance = MockPath.return_value
            mock_path_instance.is_file.return_value = False

            with pytest.raises(BitbucketError, match="Cannot detect"):
                detect_bitbucket_repo()

    def test_detect_non_bitbucket_url(self) -> None:
        """Raises BitbucketError for non-Bitbucket URLs (e.g., GitHub)."""
        from cloudways_api.bitbucket import detect_bitbucket_repo

        with patch("cloudways_api.bitbucket.Path") as MockPath:
            mock_path_instance = MockPath.return_value
            mock_path_instance.is_file.return_value = True
            mock_path_instance.read_text.return_value = (
                '[remote "origin"]\n'
                "\turl = git@github.com:user/repo.git\n"
            )

            with pytest.raises(BitbucketError, match="Cannot detect"):
                detect_bitbucket_repo()


# --- load_bitbucket_config() tests ---


class TestLoadBitbucketConfig:
    """Tests for load_bitbucket_config() fallback."""

    def test_load_config_with_bitbucket_section(self, tmp_path) -> None:
        """Loads workspace and repo_slug from project config."""
        config_file = tmp_path / "project-config.yml"
        config_file.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "bitbucket:\n"
            "  workspace: myworkspace\n"
            "  repo_slug: myrepo\n"
        )

        from cloudways_api.bitbucket import load_bitbucket_config

        result = load_bitbucket_config(path=str(config_file))

        assert result["workspace"] == "myworkspace"
        assert result["repo_slug"] == "myrepo"

    def test_load_config_without_bitbucket_section(self, tmp_path) -> None:
        """Returns empty dict when no bitbucket section exists."""
        config_file = tmp_path / "project-config.yml"
        config_file.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
        )

        from cloudways_api.bitbucket import load_bitbucket_config

        result = load_bitbucket_config(path=str(config_file))

        assert result == {}

    def test_load_config_file_not_found(self) -> None:
        """Returns empty dict when config file does not exist."""
        from cloudways_api.bitbucket import load_bitbucket_config

        result = load_bitbucket_config(path="/nonexistent/path/config.yml")

        assert result == {}

    def test_load_config_discovers_prism_config(self, tmp_path, monkeypatch) -> None:
        """Discovers .prism/project-config.yml via upward directory walk."""
        # Create .prism/project-config.yml in tmp_path
        prism_dir = tmp_path / ".prism"
        prism_dir.mkdir()
        config_file = prism_dir / "project-config.yml"
        config_file.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "bitbucket:\n"
            "  workspace: discovered-ws\n"
            "  repo_slug: discovered-repo\n"
        )

        # Unset env var and set cwd to tmp_path
        monkeypatch.delenv("CLOUDWAYS_PROJECT_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)

        from cloudways_api.bitbucket import load_bitbucket_config

        result = load_bitbucket_config()

        assert result["workspace"] == "discovered-ws"
        assert result["repo_slug"] == "discovered-repo"
