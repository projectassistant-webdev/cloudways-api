"""Async Bitbucket API v2 client for deploy key management.

Loads credentials from ~/.bitbucket-credentials using the same
patterns as scripts/lib/bitbucket-auth.sh.

Provides deploy key CRUD operations and git remote detection for
automatic workspace/repo discovery.

Usage::

    from cloudways_api.bitbucket import BitbucketClient, detect_bitbucket_repo

    workspace, repo = detect_bitbucket_repo()
    client = BitbucketClient(workspace=workspace, repo_slug=repo)
    await client.add_deploy_key(key="ssh-rsa ...", label="cloudways-production")
"""

import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from cloudways_api.exceptions import BitbucketError

_REQUEST_TIMEOUT = 30.0


class BitbucketClient:
    """Async Bitbucket API v2 client for deploy key management.

    Loads credentials from ~/.bitbucket-credentials using the same
    patterns as scripts/lib/bitbucket-auth.sh.
    """

    BASE_URL = "https://api.bitbucket.org"

    def __init__(
        self,
        workspace: str,
        repo_slug: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize with target repository coordinates.

        Credentials loaded from ~/.bitbucket-credentials:
        - App Password: BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD
        - Personal Access Token: BITBUCKET_EMAIL + BITBUCKET_TOKEN (ATATT prefix)

        Args:
            workspace: Bitbucket workspace slug.
            repo_slug: Repository slug.
            transport: Optional httpx transport for testing.

        Raises:
            BitbucketError: If credentials file is missing or incomplete.
        """
        self.workspace = workspace
        self.repo_slug = repo_slug

        creds = self._load_credentials()
        self._auth_username = creds["username"]
        self._auth_password = creds["password"]

        client_kwargs: dict[str, Any] = {
            "timeout": _REQUEST_TIMEOUT,
            "base_url": self.BASE_URL,
            "auth": (self._auth_username, self._auth_password),
        }
        if transport is not None:
            client_kwargs["transport"] = transport

        self._http_client = httpx.AsyncClient(**client_kwargs)

    @classmethod
    def _credentials_path(cls) -> Path:
        """Return the path to ~/.bitbucket-credentials."""
        return Path.home() / ".bitbucket-credentials"

    def _load_credentials(self) -> dict[str, str]:
        """Load credentials from ~/.bitbucket-credentials.

        Supports two auth methods (same as scripts/lib/bitbucket-auth.sh):
        1. App Password: BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD
        2. Personal Access Token: BITBUCKET_EMAIL + BITBUCKET_TOKEN

        Returns:
            Dict with 'username' and 'password' keys for HTTP Basic auth.

        Raises:
            BitbucketError: If file is missing or incomplete.
        """
        creds_path = self._credentials_path()

        if not creds_path.is_file():
            raise BitbucketError(
                "Bitbucket credentials not found. "
                f"Create {creds_path} with "
                "BITBUCKET_USERNAME and BITBUCKET_APP_PASSWORD."
            )

        # Parse KEY=VALUE format
        values: dict[str, str] = {}
        try:
            content = creds_path.read_text()
        except OSError as exc:
            raise BitbucketError(
                f"Cannot read Bitbucket credentials file: {exc}"
            ) from exc

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip optional 'export ' prefix (bash credential files
            # commonly use 'export KEY=VALUE' which source handles
            # natively, but Python needs to strip the prefix).
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes from values (e.g., export KEY="value")
                stripped_value = value.strip()
                if (
                    len(stripped_value) >= 2
                    and stripped_value[0] in ('"', "'")
                    and stripped_value[-1] == stripped_value[0]
                ):
                    stripped_value = stripped_value[1:-1]
                values[key.strip()] = stripped_value

        # Try App Password auth first
        username = values.get("BITBUCKET_USERNAME")
        app_password = values.get("BITBUCKET_APP_PASSWORD")
        if username and app_password:
            return {"username": username, "password": app_password}

        # Try Personal Access Token auth
        email = values.get("BITBUCKET_EMAIL")
        token = values.get("BITBUCKET_TOKEN")
        if email and token:
            return {"username": email, "password": token}

        raise BitbucketError(
            "Incomplete Bitbucket credentials. "
            f"Ensure {creds_path} contains either "
            "BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD "
            "or BITBUCKET_EMAIL + BITBUCKET_TOKEN."
        )

    # ------------------------------------------------------------------
    # Deploy Key CRUD
    # ------------------------------------------------------------------

    async def add_deploy_key(self, key: str, label: str) -> dict:
        """Add a deploy key to the repository.

        Args:
            key: SSH public key string.
            label: Human-readable label for the key.

        Returns:
            API response dict with key details.

        Raises:
            BitbucketError: On API failure.
        """
        url = f"/2.0/repositories/{self.workspace}/{self.repo_slug}/deploy-keys"
        try:
            response = await self._http_client.post(
                url,
                json={"key": key, "label": label},
            )
        except httpx.HTTPError as exc:
            raise BitbucketError(f"Bitbucket API error: {exc}") from exc

        if response.status_code >= 400:
            raise BitbucketError(
                f"Bitbucket API error ({response.status_code}): "
                f"{response.text}"
            )

        return response.json()

    async def list_deploy_keys(self) -> list[dict]:
        """List deploy keys for the repository.

        Returns:
            List of deploy key dicts.

        Raises:
            BitbucketError: On API failure.
        """
        url = f"/2.0/repositories/{self.workspace}/{self.repo_slug}/deploy-keys"
        try:
            response = await self._http_client.get(url)
        except httpx.HTTPError as exc:
            raise BitbucketError(f"Bitbucket API error: {exc}") from exc

        if response.status_code >= 400:
            raise BitbucketError(
                f"Bitbucket API error ({response.status_code}): "
                f"{response.text}"
            )

        data = response.json()
        return data.get("values", [])

    async def delete_deploy_key(self, key_id: int) -> None:
        """Delete a deploy key from the repository.

        Args:
            key_id: Deploy key ID to delete.

        Raises:
            BitbucketError: On API failure.
        """
        url = (
            f"/2.0/repositories/{self.workspace}/{self.repo_slug}"
            f"/deploy-keys/{key_id}"
        )
        try:
            response = await self._http_client.delete(url)
        except httpx.HTTPError as exc:
            raise BitbucketError(f"Bitbucket API error: {exc}") from exc

        if response.status_code >= 400:
            raise BitbucketError(
                f"Bitbucket API error ({response.status_code}): "
                f"{response.text}"
            )


# ------------------------------------------------------------------
# Git Remote Detection
# ------------------------------------------------------------------

# Patterns for Bitbucket remote URLs
_SSH_PATTERN = re.compile(
    r"git@bitbucket\.org:([^/]+)/([^/]+?)(?:\.git)?$"
)
_HTTPS_PATTERN = re.compile(
    r"https?://(?:[^@]+@)?bitbucket\.org/([^/]+)/([^/]+?)(?:\.git)?/?$"
)


def detect_bitbucket_repo() -> tuple[str, str]:
    """Detect Bitbucket workspace and repo from git remote origin.

    Parses .git/config to find the remote origin URL and extracts
    workspace/repo_slug from SSH or HTTPS Bitbucket URLs.

    Returns:
        Tuple of (workspace, repo_slug).

    Raises:
        BitbucketError: If .git/config is missing, has no origin,
            or origin is not a Bitbucket URL.
    """
    git_config_path = Path(".git/config")

    if not git_config_path.is_file():
        raise BitbucketError(
            "Cannot detect Bitbucket repository. "
            "No .git/config found. "
            "Set bitbucket.workspace and bitbucket.repo_slug "
            "in .prism/project-config.yml."
        )

    try:
        content = git_config_path.read_text()
    except OSError as exc:
        raise BitbucketError(
            f"Cannot read .git/config: {exc}"
        ) from exc

    # Find remote origin URL
    origin_url = _extract_origin_url(content)
    if origin_url is None:
        raise BitbucketError(
            "Cannot detect Bitbucket repository. "
            "No remote 'origin' found in .git/config. "
            "Set bitbucket.workspace and bitbucket.repo_slug "
            "in .prism/project-config.yml."
        )

    # Try SSH pattern
    match = _SSH_PATTERN.match(origin_url)
    if match:
        return match.group(1), match.group(2)

    # Try HTTPS pattern
    match = _HTTPS_PATTERN.match(origin_url)
    if match:
        return match.group(1), match.group(2)

    raise BitbucketError(
        "Cannot detect Bitbucket repository. "
        f"Remote origin URL is not a Bitbucket URL: {origin_url}. "
        "Set bitbucket.workspace and bitbucket.repo_slug "
        "in .prism/project-config.yml."
    )


def _extract_origin_url(git_config_content: str) -> str | None:
    """Extract the remote origin URL from .git/config content.

    Args:
        git_config_content: Contents of .git/config file.

    Returns:
        The origin URL string, or None if not found.
    """
    in_origin = False
    for line in git_config_content.splitlines():
        stripped = line.strip()
        if stripped == '[remote "origin"]':
            in_origin = True
            continue
        if in_origin:
            if stripped.startswith("["):
                break
            match = re.match(r"url\s*=\s*(.+)", stripped)
            if match:
                return match.group(1).strip()
    return None


# ------------------------------------------------------------------
# Project Config Bitbucket Section
# ------------------------------------------------------------------


_BITBUCKET_CONFIG_DISCOVERY_DEPTH = 5


def load_bitbucket_config(path: str | None = None) -> dict:
    """Load the bitbucket section from project-config.yml.

    Does NOT use load_config() to avoid modifying the existing config
    loader. Reads the raw YAML and extracts only the 'bitbucket' section.

    Resolution order matches load_config():
    1. Explicit ``path`` parameter
    2. ``CLOUDWAYS_PROJECT_CONFIG`` environment variable
    3. Walk up from cwd looking for ``.prism/project-config.yml``

    Args:
        path: Explicit path to the config file. If None, uses
            CLOUDWAYS_PROJECT_CONFIG env var, then upward discovery.

    Returns:
        The 'bitbucket' section dict, or empty dict if not found.
    """
    import os

    if path is None:
        path = os.environ.get("CLOUDWAYS_PROJECT_CONFIG")

    if path is None:
        # Walk up from cwd looking for .prism/project-config.yml
        # (same discovery logic as config._discover_config)
        current = Path.cwd().resolve()
        for _ in range(_BITBUCKET_CONFIG_DISCOVERY_DEPTH + 1):
            candidate = current / ".prism" / "project-config.yml"
            if candidate.is_file():
                path = str(candidate)
                break
            parent = current.parent
            if parent == current:
                break
            current = parent

    if path is None:
        return {}

    config_path = Path(path)
    if not config_path.is_file():
        return {}

    try:
        with open(config_path) as fh:
            data = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    bitbucket = data.get("bitbucket")
    if not isinstance(bitbucket, dict):
        return {}

    return bitbucket
