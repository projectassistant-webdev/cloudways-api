"""Manage Cloudways server backup operations.

Provides backup run, backup settings get, and backup settings set commands
for the configured project server via the Cloudways API v2.

Usage::

    cloudways backup run [--wait] [--timeout SECS]
    cloudways backup settings get
    cloudways backup settings set [--frequency H] [--retention N]
        [--time HH:MM] [--local-backups/--no-local-backups]
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

backup_group = typer.Typer(help="Manage server backups.")
backup_settings_group = typer.Typer(help="View and update backup settings.")
backup_group.add_typer(backup_settings_group, name="settings")


# ------------------------------------------------------------------
# backup run
# ------------------------------------------------------------------


@backup_group.command(name="run")
@handle_cli_errors
def backup_run(
    wait: bool = typer.Option(False, "--wait", help="Wait for backup to complete"),
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for operation (seconds)"
    ),
) -> None:
    """Trigger an on-demand server backup."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_backup_run(
            creds=creds, server_id=server_id, wait=wait, timeout=timeout
        )
    )


async def _execute_backup_run(
    creds: dict, server_id: int, wait: bool, timeout: int
) -> None:
    """Execute backup run workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.trigger_backup(server_id=server_id)
        operation_id = result.get("operation_id")
        if not wait:
            console.print(f"Backup triggered. Operation ID: {operation_id}")
            return
        with console.status(
            "[bold green]Waiting for backup to complete...[/bold green]"
        ):
            await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print("Backup complete.")


# ------------------------------------------------------------------
# backup settings get
# ------------------------------------------------------------------


@backup_settings_group.command(name="get")
@handle_cli_errors
def backup_settings_get() -> None:
    """Display current backup settings from the server object."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_backup_settings_get(creds=creds, server_id=server_id))


async def _execute_backup_settings_get(creds: dict, server_id: int) -> None:
    """Fetch server list and extract backup fields for this server."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        servers = await client.get_servers()
        server = next(
            (s for s in servers if str(s.get("id")) == str(server_id)),
            None,
        )
        if server is None:
            err_console.print(f"Error: Server {server_id} not found in account.")
            raise typer.Exit(code=1)
        backup_fields = [
            "backup_frequency",
            "local_backups",
            "snapshot_frequency",
        ]
        for field in backup_fields:
            if field in server:
                console.print(f"{field}: {server[field]}")


# ------------------------------------------------------------------
# backup settings set
# ------------------------------------------------------------------


@backup_settings_group.command(name="set")
@handle_cli_errors
def backup_settings_set(
    frequency: str = typer.Option(
        None, "--frequency", help="Backup frequency in hours (e.g. 24)"
    ),
    retention: int = typer.Option(
        None, "--retention", help="Number of backups to retain"
    ),
    time: str = typer.Option(None, "--time", help="Backup time of day (e.g. 00:10)"),
    local_backups: bool = typer.Option(
        True,
        "--local-backups/--no-local-backups",
        help="Enable or disable local backups",
    ),
) -> None:
    """Update automated backup settings."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_backup_settings_set(
            creds=creds,
            server_id=server_id,
            frequency=frequency,
            retention=retention,
            time=time,
            local_backups=local_backups,
        )
    )


async def _execute_backup_settings_set(
    creds: dict,
    server_id: int,
    frequency: str | None,
    retention: int | None,
    time: str | None,
    local_backups: bool,
) -> None:
    """Execute backup settings update workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_backup_settings(
            server_id=server_id,
            local_backups=local_backups,
            backup_frequency=frequency,
            backup_retention=retention,
            backup_time=time,
        )
        console.print("Backup settings updated.")
