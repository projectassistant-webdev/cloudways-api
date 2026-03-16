"""Provision server command - create a new DigitalOcean server on Cloudways."""

from __future__ import annotations

import asyncio
import sys
import time

import typer
from rich.prompt import Prompt
from rich.table import Table

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)
from cloudways_api.exceptions import (
    ConfigError,
    ProvisioningError,
)


@handle_cli_errors
def provision_server(
    region: str | None = typer.Option(
        None, "--region", "-r", help="Server region (e.g., nyc3)"
    ),
    size: str | None = typer.Option(
        None, "--size", "-s", help="Server size (e.g., 2GB)"
    ),
    label: str | None = typer.Option(None, "--label", "-l", help="Server label"),
    app_label: str | None = typer.Option(
        None, "--app-label", help="Initial application label"
    ),
    project: str | None = typer.Option(None, "--project", "-p", help="Project name"),
    from_template: str | None = typer.Option(
        None, "--from-template", help="YAML template path or name"
    ),
    timeout: int = typer.Option(
        600, "--timeout", help="Max wait time for server creation (seconds)"
    ),
) -> None:
    """Create a new DigitalOcean server on Cloudways."""
    asyncio.run(
        _provision_server_async(
            region=region,
            size=size,
            label=label,
            app_label=app_label,
            project=project,
            from_template=from_template,
            timeout=timeout,
        )
    )


async def _provision_server_async(
    *,
    region: str | None,
    size: str | None,
    label: str | None,
    app_label: str | None,
    project: str | None,
    from_template: str | None,
    timeout: int,
) -> None:
    """Async implementation of the provision server workflow."""
    # Load config and credentials
    creds, config = load_creds()

    # Load template if specified
    template_values: dict = {}
    if from_template is not None:
        from cloudways_api.templates_provision import (
            interpolate_variables,
            load_template,
            validate_template,
        )

        template = load_template(from_template)
        errors = validate_template(template)
        if errors:
            raise ConfigError(
                "Template validation failed:\n  - " + "\n  - ".join(errors)
            )
        provision = template.get("provision", {})
        if provision.get("type") != "server":
            raise ConfigError(
                f"Template type is '{provision.get('type')}', expected 'server'"
            )
        # Interpolate variables from CLI flags and env
        cli_vars = {}
        if label:
            cli_vars["label"] = label
        if project:
            cli_vars["project_name"] = project
        template = interpolate_variables(template, cli_vars)
        provision = template.get("provision", {})
        template_values = provision

    # Merge: CLI flags override template values
    region = region or template_values.get("region")
    size = size or template_values.get("size")
    label = label or template_values.get("server_label")
    app_label = app_label or template_values.get("app_label")
    project = project or template_values.get("project_name")

    # Determine if interactive mode is needed
    is_interactive = sys.stdin.isatty()
    needs_prompts = not all([region, size, label])

    if needs_prompts and not is_interactive:
        missing = []
        if not region:
            missing.append("--region")
        if not size:
            missing.append("--size")
        if not label:
            missing.append("--label")
        raise typer.BadParameter(
            f"Missing required flag(s): {', '.join(missing)}. "
            "Provide all flags for non-interactive mode."
        )

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Fetch metadata for validation and prompts
        if needs_prompts or region or size:
            regions_data = await client.get_region_list("do")
            sizes_data = await client.get_server_sizes("do")
            valid_regions = [r["id"] for r in regions_data]
            valid_sizes = [s["id"] for s in sizes_data]
        else:
            valid_regions = []
            valid_sizes = []

        # Interactive prompts for missing values
        if needs_prompts and is_interactive:
            if not region:
                regions_data = await client.get_region_list("do")
                valid_regions = [r["id"] for r in regions_data]
                choices_display = [f"{r['id']} ({r['name']})" for r in regions_data]
                console.print("\n[bold]Available regions:[/bold]")
                for i, display in enumerate(choices_display, 1):
                    console.print(f"  {i}. {display}")
                region = Prompt.ask(
                    "Select region",
                    choices=valid_regions,
                    default=valid_regions[0] if valid_regions else "nyc3",
                )

            if not size:
                sizes_data = await client.get_server_sizes("do")
                valid_sizes = [s["id"] for s in sizes_data]
                choices_display = [f"{s['id']} ({s['name']})" for s in sizes_data]
                console.print("\n[bold]Available sizes:[/bold]")
                for i, display in enumerate(choices_display, 1):
                    console.print(f"  {i}. {display}")
                size = Prompt.ask(
                    "Select size",
                    choices=valid_sizes,
                    default="2GB",
                )

            if not label:
                default_label = f"my-server-{int(time.time())}"
                label = Prompt.ask("Server label", default=default_label)

        # Apply defaults
        if not app_label:
            app_label = "my-app"
        if not project:
            project = "Default"

        # Validate inputs
        if valid_regions and region not in valid_regions:
            raise ProvisioningError(
                f"Region '{region}' is not valid for DigitalOcean. "
                f"Available: {', '.join(valid_regions)}"
            )
        if valid_sizes and size not in valid_sizes:
            raise ProvisioningError(
                f"Server size '{size}' is not valid for DigitalOcean. "
                f"Available: {', '.join(valid_sizes)}"
            )

        # Get app types for latest WordPress version
        app_types = await client.get_app_types()
        wp_info = next((a for a in app_types if a["value"] == "wordpress"), None)
        app_version = wp_info["versions"][0] if wp_info else "6.5"

        # Create server
        start_time = time.monotonic()
        with console.status("[bold green]Creating server...[/bold green]"):
            result = await client.create_server(
                cloud="do",
                region=region,
                instance_type=size,
                application="wordpress",
                app_version=app_version,
                server_label=label,
                app_label=app_label,
                project_name=project,
            )

        operation_id = result.get("operation_id")

        # Poll operation
        if operation_id:
            with console.status(
                "[bold green]Waiting for server to be ready...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)

        elapsed = time.monotonic() - start_time
        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

        # Display success
        server_info = result.get("server", {})
        table = Table(title="Server Created Successfully")
        table.add_column("Property", style="bold")
        table.add_column("Value")
        table.add_row("Server ID", str(server_info.get("id", "N/A")))
        table.add_row("Label", label)
        table.add_row("Provider", "DigitalOcean")
        table.add_row("Region", region)
        table.add_row("Size", size)
        table.add_row("Public IP", str(server_info.get("public_ip", "N/A")))
        table.add_row("Status", "running")
        table.add_row("Created in", elapsed_str)
        console.print(table)
