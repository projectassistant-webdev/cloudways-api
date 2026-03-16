"""Manage SSH public keys on Cloudways app users.

Provides add and delete commands for SSH keys attached to SSH/SFTP
credentials via the Cloudways API v2.

Usage::

    cloudways ssh-key add production --username bitbucket --key-file ~/.ssh/id_ed25519.pub --name "my-key"
    cloudways ssh-key add production --username bitbucket --name "pipe-key" --stdin
    cloudways ssh-key delete production --key-id 12345
"""

import asyncio
import sys
from pathlib import Path

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

ssh_key_group = typer.Typer(help="Manage SSH keys on Cloudways app users.")

# Valid SSH public key prefixes
_VALID_KEY_PREFIXES = (
    "ssh-rsa",
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
)


def _validate_ssh_key(key: str) -> bool:
    """Validate that a string looks like an SSH public key.

    Args:
        key: The public key string to validate.

    Returns:
        True if the key starts with a recognized prefix.
    """
    return any(key.strip().startswith(prefix) for prefix in _VALID_KEY_PREFIXES)


@ssh_key_group.command(name="add")
@handle_cli_errors
def ssh_key_add(
    environment: str = typer.Argument(help="Environment name from project config"),
    username: str = typer.Option(..., "--username", help="SSH user to attach key to"),
    key_file: str | None = typer.Option(
        None, "--key-file", help="Path to public key file"
    ),
    name: str = typer.Option(..., "--name", help="Label for the SSH key"),
    stdin_flag: bool = typer.Option(
        False, "--stdin", help="Read public key from stdin"
    ),
) -> None:
    """Add an SSH public key to a Cloudways app user."""
    # Validate mutual exclusivity
    if key_file is not None and stdin_flag:
        err_console.print(
            "[bold red]Error:[/bold red] --key-file and --stdin are "
            "mutually exclusive. Provide one or the other."
        )
        raise typer.Exit(code=1)

    if key_file is None and not stdin_flag:
        err_console.print(
            "[bold red]Error:[/bold red] Provide --key-file <path> or "
            "--stdin to specify the SSH public key."
        )
        raise typer.Exit(code=1)

    # Read public key
    if stdin_flag:
        public_key = sys.stdin.read().strip()
    else:
        key_path = Path(key_file).expanduser()  # type: ignore[arg-type]
        if not key_path.is_file():
            err_console.print(
                f"[bold red]Error:[/bold red] Key file not found: {key_file}"
            )
            raise typer.Exit(code=1)
        public_key = key_path.read_text().strip()

    # Validate key format
    if not _validate_ssh_key(public_key):
        err_console.print(
            "[bold red]Error:[/bold red] Invalid SSH public key format. "
            "Expected: ssh-rsa, ssh-ed25519, or ecdsa-sha2-*"
        )
        raise typer.Exit(code=1)

    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssh_key_add(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            username=username,
            public_key=public_key,
            key_name=name,
        )
    )


async def _execute_ssh_key_add(
    creds: dict,
    server_id: int,
    app_id: int | str,
    username: str,
    public_key: str,
    key_name: str,
) -> None:
    """Execute ssh-key add workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Find credential ID for username
        existing = await client.get_app_credentials(server_id, app_id)
        cred_id = None
        for cred in existing:
            if cred.get("sys_user") == username:
                cred_id = cred["id"]
                break

        if cred_id is None:
            err_console.print(
                f"[bold red]Error:[/bold red] User '{username}' not found. "
                f"Create with: cloudways ssh-user create <env> --username {username}"
            )
            raise typer.Exit(code=1)

        await client.add_ssh_key(
            server_id=server_id,
            app_creds_id=cred_id,
            key_name=key_name,
            public_key=public_key,
        )
        console.print(f"SSH key '{key_name}' added to user '{username}'")


@ssh_key_group.command(name="delete")
@handle_cli_errors
def ssh_key_delete(
    environment: str = typer.Argument(help="Environment name from project config"),
    key_id: int = typer.Option(..., "--key-id", help="SSH key ID to delete"),
) -> None:
    """Delete an SSH key by ID."""
    creds, config = load_creds()
    validate_environment(config, environment)  # Validates environment exists

    server_id = int(config["server"]["id"])

    asyncio.run(
        _execute_ssh_key_delete(
            creds=creds,
            server_id=server_id,
            key_id=key_id,
        )
    )


async def _execute_ssh_key_delete(
    creds: dict,
    server_id: int,
    key_id: int,
) -> None:
    """Execute ssh-key delete workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.delete_ssh_key(server_id=server_id, ssh_key_id=key_id)
        console.print(f"Deleted SSH key {key_id}")


@ssh_key_group.command(name="rename")
@handle_cli_errors
def ssh_key_rename(
    environment: str = typer.Argument(help="Environment name from project config"),
    key_id: int = typer.Option(..., "--key-id", help="SSH key ID to rename"),
    name: str = typer.Option(..., "--name", help="New label for the SSH key"),
) -> None:
    """Rename an SSH key label."""
    if not name.strip():
        err_console.print("[bold red]Error:[/bold red] --name cannot be blank.")
        raise typer.Exit(code=1)

    creds, config = load_creds()
    validate_environment(config, environment)

    server_id = int(config["server"]["id"])

    asyncio.run(
        _execute_ssh_key_rename(
            creds=creds,
            server_id=server_id,
            key_id=key_id,
            key_name=name.strip(),
        )
    )


async def _execute_ssh_key_rename(
    creds: dict,
    server_id: int,
    key_id: int,
    key_name: str,
) -> None:
    """Execute ssh-key rename workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_ssh_key(
            server_id=server_id, ssh_key_id=key_id, key_name=key_name
        )
        console.print(f"Renamed SSH key {key_id} to '{key_name}'")
