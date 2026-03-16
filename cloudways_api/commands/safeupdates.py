"""Manage WordPress SafeUpdates via the Cloudways API.

Provides commands for checking available updates, listing apps,
enabling/disabling SafeUpdate, viewing and configuring schedule
settings, viewing update history, and triggering on-demand updates.

Usage::

    cloudways safeupdates check --server-id <id> --app-id <id>
    cloudways safeupdates list --server-id <id>
    cloudways safeupdates status <app-id> --server-id <id>
    cloudways safeupdates enable --server-id <id> --app-id <id>
    cloudways safeupdates disable --server-id <id> --app-id <id>
    cloudways safeupdates settings get <app-id> --server-id <id>
    cloudways safeupdates settings set --server-id <id> --app-id <id> --day <day> --time <time>
    cloudways safeupdates schedule <app-id> --server-id <id>
    cloudways safeupdates history <app-id> --server-id <id>
    cloudways safeupdates run <app-id> --server-id <id> [--core] [--plugin <slug>]... [--theme <slug>]...
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

safeupdates_group = typer.Typer(help="Manage WordPress SafeUpdates via Cloudways API.")

settings_group = typer.Typer(help="Manage SafeUpdate schedule settings.")
safeupdates_group.add_typer(settings_group, name="settings")


# ------------------------------------------------------------------
# safeupdates check
# ------------------------------------------------------------------


@safeupdates_group.command(name="check")
@handle_cli_errors
def safeupdates_check(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    app_id: int = typer.Option(..., "--app-id", help="Application ID"),
) -> None:
    """Check available SafeUpdates for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_check(creds=creds, server_id=server_id, app_id=app_id)
    )


async def _execute_safeupdates_check(creds: dict, server_id: int, app_id: int) -> None:
    """Check available SafeUpdates."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_safeupdates_available(
            server_id=server_id, app_id=app_id
        )
        console.print(result)


# ------------------------------------------------------------------
# safeupdates list
# ------------------------------------------------------------------


@safeupdates_group.command(name="list")
@handle_cli_errors
def safeupdates_list(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
) -> None:
    """List apps with SafeUpdate information for a server."""
    creds, config = load_creds()
    asyncio.run(_execute_safeupdates_list(creds=creds, server_id=server_id))


async def _execute_safeupdates_list(creds: dict, server_id: int) -> None:
    """List apps with SafeUpdate info."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.list_safeupdates_apps(server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# safeupdates status
# ------------------------------------------------------------------


@safeupdates_group.command(name="status")
@handle_cli_errors
def safeupdates_status(
    app_id: int = typer.Argument(..., help="Application ID"),
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
) -> None:
    """Get SafeUpdate status for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_status(creds=creds, app_id=app_id, server_id=server_id)
    )


async def _execute_safeupdates_status(creds: dict, app_id: int, server_id: int) -> None:
    """Get SafeUpdate status."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_safeupdate_status(app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# safeupdates enable
# ------------------------------------------------------------------


@safeupdates_group.command(name="enable")
@handle_cli_errors
def safeupdates_enable(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    app_id: int = typer.Option(..., "--app-id", help="Application ID"),
) -> None:
    """Enable SafeUpdate for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_enable(creds=creds, server_id=server_id, app_id=app_id)
    )


async def _execute_safeupdates_enable(creds: dict, server_id: int, app_id: int) -> None:
    """Enable SafeUpdate."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.set_safeupdate_status(server_id=server_id, app_id=app_id, status=1)
        console.print("Success: SafeUpdate enabled.")


# ------------------------------------------------------------------
# safeupdates disable
# ------------------------------------------------------------------


@safeupdates_group.command(name="disable")
@handle_cli_errors
def safeupdates_disable(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    app_id: int = typer.Option(..., "--app-id", help="Application ID"),
) -> None:
    """Disable SafeUpdate for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_disable(creds=creds, server_id=server_id, app_id=app_id)
    )


async def _execute_safeupdates_disable(
    creds: dict, server_id: int, app_id: int
) -> None:
    """Disable SafeUpdate."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.set_safeupdate_status(server_id=server_id, app_id=app_id, status=0)
        console.print("Success: SafeUpdate disabled.")


# ------------------------------------------------------------------
# safeupdates settings get
# ------------------------------------------------------------------


@settings_group.command(name="get")
@handle_cli_errors
def safeupdates_settings_get(
    app_id: int = typer.Argument(..., help="Application ID"),
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
) -> None:
    """Get SafeUpdate schedule settings for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_settings_get(
            creds=creds, app_id=app_id, server_id=server_id
        )
    )


async def _execute_safeupdates_settings_get(
    creds: dict, app_id: int, server_id: int
) -> None:
    """Get SafeUpdate schedule settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_safeupdate_settings(app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# safeupdates settings set
# ------------------------------------------------------------------


@settings_group.command(name="set")
@handle_cli_errors
def safeupdates_settings_set(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    app_id: int = typer.Option(..., "--app-id", help="Application ID"),
    day: str = typer.Option(..., "--day", help="Day of week (e.g., monday)"),
    time: str = typer.Option(..., "--time", help="Time slot (e.g., 02:00)"),
) -> None:
    """Set SafeUpdate schedule settings for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_settings_set(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            day=day,
            time=time,
        )
    )


async def _execute_safeupdates_settings_set(
    creds: dict, server_id: int, app_id: int, day: str, time: str
) -> None:
    """Set SafeUpdate schedule settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_safeupdate_settings(
            server_id=server_id,
            app_id=app_id,
            day_of_week=day,
            time_slot=time,
        )
        console.print("Success: SafeUpdate settings updated.")


# ------------------------------------------------------------------
# safeupdates schedule
# ------------------------------------------------------------------


@safeupdates_group.command(name="schedule")
@handle_cli_errors
def safeupdates_schedule(
    app_id: int = typer.Argument(..., help="Application ID"),
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
) -> None:
    """View queued/scheduled SafeUpdates for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_schedule(creds=creds, app_id=app_id, server_id=server_id)
    )


async def _execute_safeupdates_schedule(
    creds: dict, app_id: int, server_id: int
) -> None:
    """View queued/scheduled SafeUpdates."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_safeupdate_schedule(app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# safeupdates history
# ------------------------------------------------------------------


@safeupdates_group.command(name="history")
@handle_cli_errors
def safeupdates_history(
    app_id: int = typer.Argument(..., help="Application ID"),
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
) -> None:
    """View SafeUpdate history for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_history(creds=creds, app_id=app_id, server_id=server_id)
    )


async def _execute_safeupdates_history(
    creds: dict, app_id: int, server_id: int
) -> None:
    """View SafeUpdate history."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_safeupdate_history(app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# safeupdates run
# ------------------------------------------------------------------


@safeupdates_group.command(name="run")
@handle_cli_errors
def safeupdates_run(
    app_id: int = typer.Argument(..., help="Application ID"),
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    core: bool = typer.Option(False, "--core/--no-core", help="Update WordPress core"),
    plugins: list[str] = typer.Option([], "--plugin", help="Plugin slug to update"),
    themes: list[str] = typer.Option([], "--theme", help="Theme slug to update"),
) -> None:
    """Trigger an on-demand SafeUpdate for an app."""
    creds, config = load_creds()
    asyncio.run(
        _execute_safeupdates_run(
            creds=creds,
            app_id=app_id,
            server_id=server_id,
            core=core,
            plugins=plugins,
            themes=themes,
        )
    )


async def _execute_safeupdates_run(
    creds: dict,
    app_id: int,
    server_id: int,
    core: bool,
    plugins: list[str],
    themes: list[str],
) -> None:
    """Trigger an on-demand SafeUpdate."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.trigger_safeupdate(
            app_id,
            server_id=server_id,
            core=core,
            plugins=plugins or None,
            themes=themes or None,
        )
        console.print("Success: SafeUpdate triggered.")
