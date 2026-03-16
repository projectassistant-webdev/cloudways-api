"""Manage Cloudways server disk cleanup.

Provides disk settings get, disk settings set, and disk cleanup commands
for the configured project server via the Cloudways API v2.

Usage::

    cloudways disk settings get
    cloudways disk settings set --automate-cleanup enable|disable
        --remove-tmp yes|no --remove-private-html yes|no
        --rotate-system-log yes|no --rotate-app-log yes|no
        --remove-local-backup yes|no
    cloudways disk cleanup [--wait] [--timeout SECS]
        --remove-tmp yes|no --remove-private-html yes|no
        --rotate-system-log yes|no --rotate-app-log yes|no
        --remove-local-backup yes|no
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

disk_group = typer.Typer(help="Manage server disk cleanup.")
disk_settings_group = typer.Typer(help="View and update disk cleanup settings.")
disk_group.add_typer(disk_settings_group, name="settings")


# ------------------------------------------------------------------
# disk settings get
# ------------------------------------------------------------------


@disk_settings_group.command(name="get")
@handle_cli_errors
def disk_settings_get() -> None:
    """Display current disk cleanup settings."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_disk_settings_get(creds=creds, server_id=server_id))


async def _execute_disk_settings_get(creds: dict, server_id: int) -> None:
    """Fetch and display disk cleanup settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_disk_settings(server_id=server_id)
        settings = result.get("settings", {})
        for key, value in settings.items():
            console.print(f"{key}: {value}")


# ------------------------------------------------------------------
# disk settings set
# ------------------------------------------------------------------


@disk_settings_group.command(name="set")
@handle_cli_errors
def disk_settings_set(
    automate_cleanup: str = typer.Option(
        ..., "--automate-cleanup", help="enable or disable automated cleanup"
    ),
    remove_tmp: str = typer.Option(
        ..., "--remove-tmp", help="Remove app tmp files (yes/no)"
    ),
    remove_private_html: str = typer.Option(
        ..., "--remove-private-html", help="Remove private_html files (yes/no)"
    ),
    rotate_system_log: str = typer.Option(
        ..., "--rotate-system-log", help="Rotate system logs (yes/no)"
    ),
    rotate_app_log: str = typer.Option(
        ..., "--rotate-app-log", help="Rotate application logs (yes/no)"
    ),
    remove_local_backup: str = typer.Option(
        ..., "--remove-local-backup", help="Remove local backup files (yes/no)"
    ),
) -> None:
    """Update disk cleanup settings (all six fields required)."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_disk_settings_set(
            creds=creds,
            server_id=server_id,
            automate_cleanup=automate_cleanup,
            remove_tmp=remove_tmp,
            remove_private_html=remove_private_html,
            rotate_system_log=rotate_system_log,
            rotate_app_log=rotate_app_log,
            remove_local_backup=remove_local_backup,
        )
    )


async def _execute_disk_settings_set(
    creds: dict,
    server_id: int,
    automate_cleanup: str,
    remove_tmp: str,
    remove_private_html: str,
    rotate_system_log: str,
    rotate_app_log: str,
    remove_local_backup: str,
) -> None:
    """Execute disk settings update workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_disk_settings(
            server_id=server_id,
            automate_cleanup=automate_cleanup,
            remove_app_tmp=remove_tmp,
            remove_app_private_html=remove_private_html,
            rotate_system_log=rotate_system_log,
            rotate_app_log=rotate_app_log,
            remove_app_local_backup=remove_local_backup,
        )
        console.print("Disk settings updated.")


# ------------------------------------------------------------------
# disk cleanup
# ------------------------------------------------------------------


@disk_group.command(name="cleanup")
@handle_cli_errors
def disk_cleanup(
    wait: bool = typer.Option(False, "--wait", help="Wait for cleanup to complete"),
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for operation (seconds)"
    ),
    remove_tmp: str = typer.Option(
        ..., "--remove-tmp", help="Remove app tmp files (yes/no)"
    ),
    remove_private_html: str = typer.Option(
        ..., "--remove-private-html", help="Remove private_html files (yes/no)"
    ),
    rotate_system_log: str = typer.Option(
        ..., "--rotate-system-log", help="Rotate system logs (yes/no)"
    ),
    rotate_app_log: str = typer.Option(
        ..., "--rotate-app-log", help="Rotate application logs (yes/no)"
    ),
    remove_local_backup: str = typer.Option(
        ..., "--remove-local-backup", help="Remove local backup files (yes/no)"
    ),
) -> None:
    """Trigger a one-time disk cleanup operation."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_disk_cleanup(
            creds=creds,
            server_id=server_id,
            wait=wait,
            timeout=timeout,
            remove_tmp=remove_tmp,
            remove_private_html=remove_private_html,
            rotate_system_log=rotate_system_log,
            rotate_app_log=rotate_app_log,
            remove_local_backup=remove_local_backup,
        )
    )


async def _execute_disk_cleanup(
    creds: dict,
    server_id: int,
    wait: bool,
    timeout: int,
    remove_tmp: str,
    remove_private_html: str,
    rotate_system_log: str,
    rotate_app_log: str,
    remove_local_backup: str,
) -> None:
    """Execute disk cleanup workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.trigger_disk_cleanup(
            server_id=server_id,
            remove_app_tmp=remove_tmp,
            remove_app_private_html=remove_private_html,
            rotate_system_log=rotate_system_log,
            rotate_app_log=rotate_app_log,
            remove_app_local_backup=remove_local_backup,
        )
        operation_id = result.get("operation_id")
        if not wait:
            console.print(f"Disk cleanup triggered. Operation ID: {operation_id}")
            return
        with console.status(
            "[bold green]Waiting for disk cleanup to complete...[/bold green]"
        ):
            await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print("Disk cleanup complete.")
