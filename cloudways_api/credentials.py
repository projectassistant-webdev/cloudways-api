"""Account credential loader with environment variable resolution.

Loads credentials from ~/.cloudways/accounts.yml (or a path override)
and resolves ${ENV_VAR} references in field values.
"""

import os
import re
from pathlib import Path

import yaml

from cloudways_api.exceptions import CredentialsError

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DEFAULT_ACCOUNTS_PATH = Path.home() / ".cloudways" / "accounts.yml"


def load_credentials(
    account_name: str,
    path: str | None = None,
) -> dict:
    """Load credentials for the given account name.

    Resolution order for the accounts file:
    1. Explicit ``path`` parameter (highest priority)
    2. ``CLOUDWAYS_ACCOUNTS_FILE`` environment variable
    3. Default ``~/.cloudways/accounts.yml``

    After loading, ``${ENV_VAR}`` references in the ``api_key`` field
    are resolved from the process environment. If resolution fails,
    a fallback lookup in ``~/.cloudways/.env`` is attempted.

    If the account file provides empty or missing ``email`` / ``api_key``
    values, ``CLOUDWAYS_EMAIL`` and ``CLOUDWAYS_API_KEY`` env vars are
    used as fallbacks.  Account-specific values from the file always
    take precedence when present.

    Args:
        account_name: Account key to look up in accounts.yml.
        path: Optional explicit path to accounts.yml.

    Returns:
        A dict with ``email`` and ``api_key`` keys.

    Raises:
        CredentialsError: On missing file, missing account, or
            unresolvable environment variable references.
    """
    accounts_path = _resolve_accounts_path(path)
    raw = _load_accounts_yaml(accounts_path)
    account = _get_account(raw, account_name, accounts_path)

    email = account.get("email", "")
    api_key = account.get("api_key", "")

    # Resolve ${ENV_VAR} references in api_key
    api_key = _resolve_env_vars(api_key, accounts_path, account_name)

    # Env vars are FALLBACK, not override, when account file provides values
    if not email:
        email = os.environ.get("CLOUDWAYS_EMAIL", "")
    if not api_key:
        api_key = os.environ.get("CLOUDWAYS_API_KEY", "")

    # M-5: Validate non-empty fields after resolution
    if not email or not isinstance(email, str):
        raise CredentialsError(
            f"Empty or missing 'email' for account '{account_name}' in {accounts_path}.\n"
            "Hint: Ensure the account has a valid email address, or set "
            "CLOUDWAYS_EMAIL environment variable."
        )

    if not api_key or not isinstance(api_key, str):
        raise CredentialsError(
            f"Empty or missing 'api_key' for account '{account_name}' in {accounts_path}.\n"
            "Hint: Ensure the account has an api_key value (or ${ENV_VAR} reference), "
            "or set CLOUDWAYS_API_KEY environment variable."
        )

    return {"email": email, "api_key": api_key}


def _resolve_accounts_path(explicit: str | None) -> Path:
    """Determine the accounts file path."""
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise CredentialsError(
                f"Could not find credentials file at: {explicit}"
            )
        return p

    env_path = os.environ.get("CLOUDWAYS_ACCOUNTS_FILE")
    if env_path is not None:
        p = Path(env_path)
        if not p.is_file():
            raise CredentialsError(
                f"Could not find credentials file at: {env_path} "
                "(set via CLOUDWAYS_ACCOUNTS_FILE)"
            )
        return p

    if not _DEFAULT_ACCOUNTS_PATH.is_file():
        raise CredentialsError(
            f"Could not find credentials file at: {_DEFAULT_ACCOUNTS_PATH}\n"
            "Hint: Create the file with your account email and API key reference."
        )
    return _DEFAULT_ACCOUNTS_PATH


def _load_accounts_yaml(path: Path) -> dict:
    """Parse the accounts YAML file."""
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise CredentialsError(
            f"Invalid YAML in {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise CredentialsError(f"Expected a YAML mapping in {path}")

    return data


def _get_account(raw: dict, name: str, path: Path) -> dict:
    """Extract a named account from the parsed YAML."""
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        raise CredentialsError(
            f"Missing 'accounts' section in {path}"
        )

    account = accounts.get(name)
    if not isinstance(account, dict):
        raise CredentialsError(
            f"Account '{name}' not found in {path}. "
            f"Available accounts: {', '.join(accounts.keys())}"
        )

    return account


def _resolve_env_vars(value: str, path: Path, account_name: str) -> str:
    """Resolve ${ENV_VAR} references in a string value.

    Tries os.environ first, then falls back to ~/.cloudways/.env.
    """
    if not isinstance(value, str):
        return str(value) if value is not None else ""

    dotenv_vars: dict[str, str] | None = None

    def replacer(match: re.Match) -> str:
        nonlocal dotenv_vars
        var_name = match.group(1)

        # Try os.environ first
        env_val = os.environ.get(var_name)
        if env_val is not None:
            return env_val

        # Fallback: try ~/.cloudways/.env
        if dotenv_vars is None:
            dotenv_vars = _load_dotenv()

        env_val = dotenv_vars.get(var_name)
        if env_val is not None:
            return env_val

        raise CredentialsError(
            f"Environment variable '{var_name}' is not set.\n"
            f"Referenced in: {path} (account: {account_name}, field: api_key)\n"
            f"Hint: Set the variable or add it to ~/.cloudways/.env"
        )

    return _ENV_VAR_PATTERN.sub(replacer, value)


def _load_dotenv() -> dict[str, str]:
    """Load KEY=VALUE pairs from ~/.cloudways/.env if it exists."""
    dotenv_path = Path.home() / ".cloudways" / ".env"
    result: dict[str, str] = {}

    if not dotenv_path.is_file():
        return result

    with open(dotenv_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()

    return result
