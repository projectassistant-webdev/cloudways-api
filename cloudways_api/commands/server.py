"""Manage Cloudways server lifecycle.

Provides stop, start, restart, delete, and rename commands for the
configured project server via the Cloudways API v2.

Usage::

    cloudways server stop
    cloudways server start
    cloudways server restart
    cloudways server delete --confirm
    cloudways server rename --label "new-name"
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
)

server_group = typer.Typer(help="Manage Cloudways server lifecycle.")


@server_group.command(name="stop")
@handle_cli_errors
def server_stop(
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Stop the configured server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_server_stop(creds=creds, server_id=server_id, timeout=timeout))


async def _execute_server_stop(creds: dict, server_id: int, timeout: int) -> None:
    """Execute server stop workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.stop_server(server_id=server_id)
        operation_id = result.get("operation_id")
        if operation_id:
            with console.status(
                "[bold green]Waiting for server to stop...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print(f"Server {server_id} stopped.")


@server_group.command(name="start")
@handle_cli_errors
def server_start(
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Start the configured server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_server_start(creds=creds, server_id=server_id, timeout=timeout)
    )


async def _execute_server_start(creds: dict, server_id: int, timeout: int) -> None:
    """Execute server start workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.start_server(server_id=server_id)
        operation_id = result.get("operation_id")
        if operation_id:
            with console.status(
                "[bold green]Waiting for server to start...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print(f"Server {server_id} started.")


@server_group.command(name="restart")
@handle_cli_errors
def server_restart(
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Restart the configured server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_server_restart(creds=creds, server_id=server_id, timeout=timeout)
    )


async def _execute_server_restart(creds: dict, server_id: int, timeout: int) -> None:
    """Execute server restart workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.restart_server(server_id=server_id)
        operation_id = result.get("operation_id")
        if operation_id:
            with console.status(
                "[bold green]Waiting for server to restart...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print(f"Server {server_id} restarted.")


@server_group.command(name="delete")
@handle_cli_errors
def server_delete(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm server deletion"),
    timeout: int = typer.Option(
        600, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Delete the configured server."""
    if not confirm:
        err_console.print(
            "[bold red]Error:[/bold red] --confirm flag required. "
            "This will permanently delete the server."
        )
        raise typer.Exit(code=1)
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_server_delete(creds=creds, server_id=server_id, timeout=timeout)
    )


async def _execute_server_delete(creds: dict, server_id: int, timeout: int) -> None:
    """Execute server delete workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.delete_server(server_id=server_id)
        operation_id = result.get("operation_id")
        if operation_id:
            with console.status(
                "[bold green]Waiting for server to be deleted...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print(f"Server {server_id} deleted.")


@server_group.command(name="rename")
@handle_cli_errors
def server_rename(
    label: str = typer.Option(..., "--label", help="New label for the server"),
) -> None:
    """Rename the configured server."""
    if not label.strip():
        err_console.print("[bold red]Error:[/bold red] --label cannot be blank.")
        raise typer.Exit(code=1)
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_server_rename(creds=creds, server_id=server_id, label=label.strip())
    )


async def _execute_server_rename(creds: dict, server_id: int, label: str) -> None:
    """Execute server rename workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_server(server_id=server_id, label=label)
        console.print(f"Renamed server {server_id} to '{label}'.")


@server_group.command(name="upgrade-php")
@handle_cli_errors
def server_upgrade_php(
    version: str = typer.Option(
        ..., "--version", help="Target PHP version (e.g., '8.3')"
    ),
    timeout: int = typer.Option(
        600, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Upgrade PHP to the specified version on the configured server."""
    if not version.strip():
        err_console.print("[bold red]Error:[/bold red] --version cannot be blank.")
        raise typer.Exit(code=1)
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_server_upgrade_php(
            creds=creds, server_id=server_id, version=version.strip(), timeout=timeout
        )
    )


async def _execute_server_upgrade_php(
    creds: dict, server_id: int, version: str, timeout: int
) -> None:
    """Execute PHP upgrade workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.manage_server_package(
            server_id=server_id, package_name="php", package_version=version
        )
        operation_id = result.get("operation_id")
        if operation_id:
            with console.status(
                "[bold green]Waiting for PHP upgrade to complete...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print(f"PHP upgraded to {version} on server {server_id}.")
