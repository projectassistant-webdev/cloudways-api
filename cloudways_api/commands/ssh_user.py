"""Manage SSH/SFTP users on Cloudways applications.

Provides create, list, and delete commands for SSH/SFTP user credentials
via the Cloudways API v2.

Usage::

    cloudways ssh-user create production --username bitbucket
    cloudways ssh-user list production
    cloudways ssh-user delete production --username bitbucket
"""

import asyncio
import secrets

import typer
from rich.table import Table

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)
from cloudways_api.exceptions import APIError

ssh_user_group = typer.Typer(help="Manage SSH/SFTP users on Cloudways apps.")


@ssh_user_group.command(name="create")
@handle_cli_errors
def ssh_user_create(
    environment: str = typer.Argument(help="Environment name from project config"),
    username: str = typer.Option(
        ..., "--username", help="Username for the SSH/SFTP user"
    ),
) -> None:
    """Create an SSH/SFTP user with auto-generated password."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssh_user_create(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            username=username,
        )
    )


async def _execute_ssh_user_create(
    creds: dict,
    server_id: int,
    app_id: int | str,
    username: str,
) -> None:
    """Execute ssh-user create workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Check if username already exists
        existing = await client.get_app_credentials(server_id, app_id)
        for cred in existing:
            if cred.get("sys_user") == username:
                err_console.print(
                    f"[bold red]Error:[/bold red] User '{username}' already "
                    f"exists (cred_id: {cred['id']}). "
                    "Use ssh-key add to manage keys."
                )
                raise typer.Exit(code=1)

        # Generate password and create user
        password = secrets.token_urlsafe(24)
        try:
            result = await client.create_app_credential(
                server_id=server_id,
                app_id=app_id,
                username=username,
                password=password,
            )
        except APIError as exc:
            if "already exists" in str(exc).lower():
                err_console.print(
                    f"[bold red]Error:[/bold red] User '{username}' already "
                    "exists on this server."
                )
                err_console.print(
                    "On shared servers (multiple apps on same server), "
                    "usernames must be unique."
                )
                err_console.print(
                    f"Suggested: Use environment-suffixed names like "
                    f"'{username}-stg' or '{username}-prod'."
                )
                raise typer.Exit(code=1)
            raise

        cred_id = result.get("app_cred", {}).get("id", "unknown")
        console.print(f"Created SSH user '{username}' (cred_id: {cred_id})")
        console.print(f"Password: {password}")


@ssh_user_group.command(name="list")
@handle_cli_errors
def ssh_user_list(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """List SSH/SFTP users for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssh_user_list(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
        )
    )


async def _execute_ssh_user_list(
    creds: dict,
    server_id: int,
    app_id: int | str,
) -> None:
    """Execute ssh-user list workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        credentials = await client.get_app_credentials(server_id, app_id)

        if not credentials:
            console.print("No SSH/SFTP users found.")
            return

        table = Table(title="SSH/SFTP Users")
        table.add_column("Username", style="cyan")
        table.add_column("Cred ID", style="green")
        table.add_column("IP Address", style="yellow")

        for cred in credentials:
            table.add_row(
                str(cred.get("sys_user", "")),
                str(cred.get("id", "")),
                str(cred.get("ip", "")),
            )

        console.print(table)


@ssh_user_group.command(name="delete")
@handle_cli_errors
def ssh_user_delete(
    environment: str = typer.Argument(help="Environment name from project config"),
    username: str = typer.Option(..., "--username", help="Username to delete"),
) -> None:
    """Delete an SSH/SFTP user by username."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssh_user_delete(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            username=username,
        )
    )


async def _execute_ssh_user_delete(
    creds: dict,
    server_id: int,
    app_id: int | str,
    username: str,
) -> None:
    """Execute ssh-user delete workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Find credential ID for username
        existing = await client.get_app_credentials(server_id, app_id)
        cred_id = None
        for cred in existing:
            if cred.get("sys_user") == username:
                cred_id = cred["id"]
                break

        if cred_id is None:
            available = [c.get("sys_user", "") for c in existing]
            available_str = ", ".join(available) if available else "none"
            err_console.print(
                f"[bold red]Error:[/bold red] User '{username}' not found. "
                f"Available users: {available_str}"
            )
            raise typer.Exit(code=1)

        await client.delete_app_credential(
            server_id=server_id,
            app_id=app_id,
            app_cred_id=cred_id,
        )
        console.print(f"Deleted SSH user '{username}'")
