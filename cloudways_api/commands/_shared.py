"""Shared utilities for CLI command modules.

Provides centralized console instances, environment validation,
and error handling to eliminate duplication across command modules.
"""

import functools
from collections.abc import Callable
from typing import Any

import click
import typer
from rich.console import Console

from cloudways_api.config import load_config
from cloudways_api.credentials import load_credentials
from cloudways_api.exceptions import (
    AuthenticationError,
    BitbucketError,
    CloudwaysError,
    ConfigError,
    CredentialsError,
    DatabaseError,
    OperationTimeoutError,
    ProvisioningError,
    SSHError,
)

console = Console()
err_console = Console(stderr=True)

DEFAULT_WEBROOT = "public_html/current"


def load_creds() -> tuple[dict, dict]:
    """Load project config and credentials.

    Convenience wrapper that replaces the common 3-line boilerplate::

        config = load_config()
        account_name = config["account"]
        creds = load_credentials(account_name)

    Returns:
        tuple: (credentials dict, config dict)
    """
    config = load_config()
    account_name = config["account"]
    creds = load_credentials(account_name)
    return creds, config


def validate_environment(config: dict, environment: str) -> dict:
    """Validate that an environment exists in config and return its config.

    Args:
        config: The hosting.cloudways dict from load_config().
        environment: Environment name to validate (e.g., 'production').

    Returns:
        The environment-specific configuration dict.

    Raises:
        typer.Exit: If the environment is not found (prints error to stderr).
    """
    environments = config.get("environments", {})
    if environment not in environments:
        available = ", ".join(environments.keys()) if environments else "none"
        err_console.print(
            f"[bold red]Error:[/bold red] Environment '{environment}' "
            f"not found. Available: {available}"
        )
        raise typer.Exit(code=1)
    return environments[environment]


def handle_cli_errors(func: Callable) -> Callable:
    """Decorator that catches common CLI errors and prints them to stderr.

    Catches CloudwaysError (and all subclasses), CredentialsError,
    AuthenticationError, and bare Exception, printing the error message
    to stderr and raising typer.Exit(code=1).

    This replaces the duplicated try/except blocks across all command
    modules.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (click.exceptions.Exit, click.exceptions.Abort):
            # Let typer.Exit and typer.Abort pass through unchanged
            raise
        except OperationTimeoutError as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc}")
            err_console.print(
                "  Hint: Check operation status at https://platform.cloudways.com"
            )
            raise typer.Exit(code=1)
        except (
            ConfigError,
            CredentialsError,
            AuthenticationError,
            SSHError,
            DatabaseError,
            BitbucketError,
            ProvisioningError,
            CloudwaysError,
        ) as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1)
        except Exception as exc:
            err_console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(code=1)

    return wrapper
