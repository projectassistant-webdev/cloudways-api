"""Reset file permissions command - reset ownership to application user."""

from __future__ import annotations

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)


@handle_cli_errors
def reset_permissions(
    environment: str = typer.Argument(..., help="Environment name (e.g., production)"),
) -> None:
    """Reset file ownership to application user."""
    asyncio.run(_reset_permissions_async(environment=environment))


async def _reset_permissions_async(*, environment: str) -> None:
    """Async implementation of the reset-permissions workflow."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        with console.status("[bold green]Resetting file permissions...[/bold green]"):
            await client.reset_permissions(server_id=server_id, app_id=app_id)

    console.print(
        f"[bold green]Permissions reset successfully for {environment}.[/bold green]"
    )
