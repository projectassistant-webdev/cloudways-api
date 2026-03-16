"""Provision staging command - clone a staging app from an existing environment."""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.prompt import Prompt
from rich.table import Table

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)


@handle_cli_errors
def provision_staging(
    source_environment: str = typer.Argument(
        ..., help="Environment name in config to clone from (e.g., production)"
    ),
    label: str | None = typer.Option(
        None, "--label", "-l", help="Label for the new staging app"
    ),
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for staging creation (seconds)"
    ),
) -> None:
    """Clone a staging application from an existing environment."""
    asyncio.run(
        _provision_staging_async(
            source_environment=source_environment,
            label=label,
            timeout=timeout,
        )
    )


async def _provision_staging_async(
    *,
    source_environment: str,
    label: str | None,
    timeout: int,
) -> None:
    """Async implementation of the provision staging workflow."""
    creds, config = load_creds()
    env_config = validate_environment(config, source_environment)
    server_id = int(config["server"]["id"])
    source_app_id = env_config["app_id"]

    # Non-interactive check
    is_interactive = sys.stdin.isatty()
    if not label and not is_interactive:
        raise typer.BadParameter("--label is required in non-interactive mode.")

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Interactive prompt for missing label
        if not label:
            label = Prompt.ask(
                "Staging app label",
                default=f"staging-{source_environment}",
            )

        with console.status("[bold green]Cloning staging app...[/bold green]"):
            result = await client.create_staging_app(
                server_id=server_id,
                app_id=source_app_id,
                app_label=label,
                project_name="Default",
            )

        operation_id = result.get("operation_id")
        if operation_id:
            with console.status("[bold green]Waiting for staging app...[/bold green]"):
                await client.wait_for_operation(operation_id, max_wait=timeout)

        app_info = result.get("app", {})

        # Display success
        table = Table(title="Staging App Created Successfully")
        table.add_column("Property", style="bold")
        table.add_column("Value")
        table.add_row("App ID", str(app_info.get("id", "N/A")))
        table.add_row("Label", label)
        table.add_row("Source Environment", source_environment)
        table.add_row("Server ID", str(server_id))
        console.print(table)
