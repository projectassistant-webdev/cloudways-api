"""Project configuration loader.

Loads the hosting.cloudways section from .prism/project-config.yml.
Supports path override via CLOUDWAYS_PROJECT_CONFIG env var and
automatic path discovery walking up from the current directory.
"""

import os
from pathlib import Path

import yaml

from cloudways_api.exceptions import ConfigError

_MAX_DISCOVERY_DEPTH = 5


def load_config(
    path: str | None = None,
    search_from: str | None = None,
) -> dict:
    """Load the hosting.cloudways section from project config.

    Resolution order for finding the config file:
    1. Explicit ``path`` parameter (highest priority)
    2. ``CLOUDWAYS_PROJECT_CONFIG`` environment variable
    3. Walk up from ``search_from`` (or cwd) looking for
       ``.prism/project-config.yml``

    Args:
        path: Explicit path to the YAML config file.
        search_from: Directory to start upward search from.
            Defaults to the current working directory.

    Returns:
        The ``hosting.cloudways`` dict from the config file.

    Raises:
        ConfigError: If the file is missing, unparseable, or
            lacks the required ``hosting.cloudways`` section.
    """
    config_path = _resolve_path(path, search_from)
    raw = _load_yaml(config_path)
    return _extract_cloudways_section(raw, config_path)


def _resolve_path(explicit: str | None, search_from: str | None) -> Path:
    """Determine the config file path using the resolution order."""
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigError(
                f"Could not find configuration file at: {explicit}"
            )
        return p

    env_path = os.environ.get("CLOUDWAYS_PROJECT_CONFIG")
    if env_path is not None:
        p = Path(env_path)
        if not p.is_file():
            raise ConfigError(
                f"Could not find configuration file at: {env_path} "
                "(set via CLOUDWAYS_PROJECT_CONFIG)"
            )
        return p

    return _discover_config(search_from)


def _discover_config(search_from: str | None) -> Path:
    """Walk up directories looking for .prism/project-config.yml."""
    start = Path(search_from) if search_from else Path.cwd()
    current = start.resolve()

    for _ in range(_MAX_DISCOVERY_DEPTH + 1):
        candidate = current / ".prism" / "project-config.yml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    raise ConfigError(
        "Could not find .prism/project-config.yml. "
        f"Searched up {_MAX_DISCOVERY_DEPTH} directories from {start}.\n"
        "Hint: Run from your project root, or set "
        "CLOUDWAYS_PROJECT_CONFIG=/path/to/file"
    )


def _load_yaml(path: Path) -> dict:
    """Parse a YAML file, raising ConfigError on failure."""
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid YAML in {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")

    return data


def _extract_cloudways_section(raw: dict, path: Path) -> dict:
    """Extract and validate the hosting.cloudways section."""
    hosting = raw.get("hosting")
    if not isinstance(hosting, dict):
        raise ConfigError(
            f"Missing 'hosting' section in {path}.\n"
            "Hint: See docs/strategy/project-config-hosting-schema.md "
            "for the expected format."
        )

    cloudways = hosting.get("cloudways")
    if not isinstance(cloudways, dict):
        raise ConfigError(
            f"Missing 'hosting.cloudways' section in {path}.\n"
            "Hint: See docs/strategy/project-config-hosting-schema.md "
            "for the expected format."
        )

    _validate_phase1_fields(cloudways, path)
    return cloudways


def validate_ssh_config(config: dict) -> None:
    """Validate SSH-related config fields only.

    Required for env-capture, ssh, and capistrano commands.
    Subset of :func:`validate_phase2_config` without the
    database section check.

    Args:
        config: The ``hosting.cloudways`` dict from :func:`load_config`.

    Raises:
        ConfigError: If ``server.ssh_user`` or ``server.ssh_host``
            is missing.
    """
    server = config.get("server", {})

    if not server.get("ssh_user"):
        raise ConfigError(
            "Missing 'server.ssh_user' in project-config.yml. "
            "Required for SSH access. Set to your Cloudways master "
            "username (e.g., master_xxxxx)."
        )

    if not server.get("ssh_host"):
        raise ConfigError(
            "Missing 'server.ssh_host' in project-config.yml. "
            "Required for SSH access. Set to your server IP address."
        )


def validate_phase2_config(config: dict) -> None:
    """Validate Phase 2 required fields.

    Called by db_pull command before operations begin.
    Does NOT run during load_config() to avoid breaking info command.
    Validates SSH config first (superset), then database-specific fields.

    Args:
        config: The hosting.cloudways dict from load_config().

    Raises:
        ConfigError: If required Phase 2 fields are missing.
    """
    validate_ssh_config(config)

    database = config.get("database")
    if not isinstance(database, dict):
        raise ConfigError(
            "Missing 'database' section in project-config.yml. "
            "Required for db-pull. Add database.local_container, "
            "database.local_db_name, and database.url_replace_method."
        )

    if not database.get("local_container"):
        raise ConfigError(
            "Missing 'database.local_container' in project-config.yml. "
            "Set to your local MariaDB Docker container name."
        )

    if not database.get("local_db_name"):
        raise ConfigError(
            "Missing 'database.local_db_name' in project-config.yml. "
            "Set to your local database name."
        )

    if not database.get("url_replace_method"):
        raise ConfigError(
            "Missing 'database.url_replace_method' in project-config.yml. "
            "Set to one of: wp-cli, env-file, sql-replace."
        )


def _validate_phase1_fields(config: dict, path: Path) -> None:
    """Validate Phase 1 required fields in hosting.cloudways section.

    Required:
    - account (string)
    - server.id (integer)
    - At least one environment with app_id and domain
    """
    # Validate account
    account = config.get("account")
    if not isinstance(account, str) or not account:
        raise ConfigError(
            f"Missing or invalid 'hosting.cloudways.account' in {path}.\n"
            "Hint: Set 'account' to the name of your account entry "
            "in ~/.cloudways/accounts.yml (e.g., 'primary')."
        )

    # Validate server.id
    server = config.get("server")
    if not isinstance(server, dict):
        raise ConfigError(
            f"Missing 'hosting.cloudways.server' section in {path}.\n"
            "Hint: Add a 'server' section with at least 'id' (integer)."
        )

    server_id = server.get("id")
    if server_id is None:
        raise ConfigError(
            f"Missing 'hosting.cloudways.server.id' in {path}.\n"
            "Hint: Set 'server.id' to your Cloudways server ID (integer)."
        )

    try:
        int(server_id)
    except (TypeError, ValueError):
        raise ConfigError(
            f"Invalid 'hosting.cloudways.server.id' in {path}: "
            f"expected integer, got '{server_id}'.\n"
            "Hint: Set 'server.id' to your Cloudways numeric server ID."
        )

    # Validate environments
    environments = config.get("environments")
    if not isinstance(environments, dict) or not environments:
        raise ConfigError(
            f"Missing or empty 'hosting.cloudways.environments' in {path}.\n"
            "Hint: Add at least one environment (e.g., 'production') with "
            "'app_id' and 'domain'."
        )

    for env_name, env_config in environments.items():
        if not isinstance(env_config, dict):
            raise ConfigError(
                f"Invalid environment '{env_name}' in {path}: "
                "expected a mapping with 'app_id' and 'domain'."
            )

        if "app_id" not in env_config:
            raise ConfigError(
                f"Missing 'app_id' for environment '{env_name}' in {path}.\n"
                "Hint: Set 'environments.{env_name}.app_id' to the Cloudways "
                "application ID (integer)."
            )

        if "domain" not in env_config:
            raise ConfigError(
                f"Missing 'domain' for environment '{env_name}' in {path}.\n"
                "Hint: Set 'environments.{env_name}.domain' to the primary "
                "domain for this environment."
            )
