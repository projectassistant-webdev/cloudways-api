"""Provision app command - create a new application on an existing Cloudways server."""

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
    err_console,
    handle_cli_errors,
    load_creds,
)
from cloudways_api.exceptions import (
    CloudwaysError,
    ConfigError,
    ProvisioningError,
)


@handle_cli_errors
def provision_app(
    server_id: int | None = typer.Option(
        None, "--server-id", "-s", help="Target server ID"
    ),
    app_label: str | None = typer.Option(
        None, "--app-label", "-l", help="Application label"
    ),
    app_type: str = typer.Option(
        "wordpress", "--app", help="Application type (e.g., wordpress, laravel)"
    ),
    app_version: str | None = typer.Option(
        None, "--app-version", help="Application version (e.g., 6.5)"
    ),
    project: str | None = typer.Option(None, "--project", "-p", help="Project name"),
    php_version: str | None = typer.Option(
        None, "--php", help="PHP version (e.g., 8.2)"
    ),
    domain: str | None = typer.Option(
        None, "--domain", "-d", help="Domain/CNAME to add"
    ),
    from_template: str | None = typer.Option(
        None, "--from-template", help="YAML template path or name"
    ),
    timeout: int = typer.Option(
        300, "--timeout", help="Max wait time for app creation (seconds)"
    ),
) -> None:
    """Create a new application on an existing server."""
    asyncio.run(
        _provision_app_async(
            server_id=server_id,
            app_label=app_label,
            app_type=app_type,
            app_version=app_version,
            project=project,
            php_version=php_version,
            domain=domain,
            from_template=from_template,
            timeout=timeout,
        )
    )


async def _provision_app_async(
    *,
    server_id: int | None,
    app_label: str | None,
    app_type: str,
    app_version: str | None,
    project: str | None,
    php_version: str | None,
    domain: str | None,
    from_template: str | None,
    timeout: int,
) -> None:
    """Async implementation of the provision app workflow."""
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
        if provision.get("type") != "app":
            raise ConfigError(
                f"Template type is '{provision.get('type')}', expected 'app'"
            )
        # Interpolate variables from CLI flags and env
        cli_vars = {}
        if app_label:
            cli_vars["app_label"] = app_label
        if project:
            cli_vars["project_name"] = project
        template = interpolate_variables(template, cli_vars)
        provision = template.get("provision", {})
        template_values = provision

    # Merge: CLI flags override template values
    if server_id is None and template_values.get("server_id") is not None:
        server_id = int(template_values["server_id"])
    app_label = app_label or template_values.get("app_label")
    project = project or template_values.get("project_name")
    # app_type: CLI default is "wordpress", template can override
    if app_type == "wordpress" and template_values.get("application"):
        app_type = template_values["application"]

    # Handle configure sub-block from templates
    configure = template_values.get("configure", {})
    php_version = (
        php_version
        or configure.get("php_version")
        or template_values.get("php_version")
    )
    domain = domain or configure.get("domain") or template_values.get("domain")

    # Determine if interactive mode is needed
    is_interactive = sys.stdin.isatty()
    needs_prompts = not all([server_id, app_label])

    if needs_prompts and not is_interactive:
        missing = []
        if not server_id:
            missing.append("--server-id")
        if not app_label:
            missing.append("--app-label")
        raise typer.BadParameter(
            f"Missing required flag(s): {', '.join(missing)}. "
            "Provide all flags for non-interactive mode."
        )

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Interactive prompts for missing values
        if needs_prompts and is_interactive:
            if not server_id:
                servers = await client.get_servers()
                if not servers:
                    raise ProvisioningError(
                        "No servers found on your account. "
                        "Create a server first with 'cloudways provision server'."
                    )
                console.print("\n[bold]Available servers:[/bold]")
                for srv in servers:
                    console.print(
                        f"  {srv['id']} - {srv.get('label', 'N/A')} "
                        f"({srv.get('public_ip', 'N/A')})"
                    )
                valid_ids = [str(s["id"]) for s in servers]
                chosen = Prompt.ask(
                    "Select server ID",
                    choices=valid_ids,
                    default=valid_ids[0],
                )
                server_id = int(chosen)

            if not app_label:
                default_label = f"my-app-{int(time.time())}"
                app_label = Prompt.ask("Application label", default=default_label)

        # Apply defaults
        if not project:
            project = "Default"

        # Validate server_id exists
        servers = await client.get_servers()
        matching = [s for s in servers if str(s["id"]) == str(server_id)]
        if not matching:
            raise ProvisioningError(
                f"Server ID '{server_id}' not found on your account. "
                f"Available: {', '.join(str(s['id']) for s in servers)}"
            )

        # Resolve app version if not explicitly provided
        if not app_version:
            app_types = await client.get_app_types()
            type_info = next((a for a in app_types if a["value"] == app_type), None)
            app_version = type_info["versions"][0] if type_info else "6.5"

        # Create application
        start_time = time.monotonic()
        with console.status("[bold green]Creating application...[/bold green]"):
            result = await client.create_app(
                server_id=server_id,
                application=app_type,
                app_version=app_version,
                app_label=app_label,
                project_name=project,
            )

        operation_id = result.get("operation_id")

        # Poll operation
        if operation_id:
            with console.status(
                "[bold green]Waiting for application to be ready...[/bold green]"
            ):
                await client.wait_for_operation(operation_id, max_wait=timeout)

        app_info = result.get("app", {})
        app_id = str(app_info.get("id", ""))

        # Post-creation configuration (non-fatal: warn on failure)
        if php_version and app_id:
            try:
                with console.status(
                    f"[bold green]Setting PHP version to {php_version}...[/bold green]"
                ):
                    await client.update_php_version(
                        server_id=server_id,
                        app_id=app_id,
                        php_version=php_version,
                    )
            except CloudwaysError as exc:
                err_console.print(
                    f"[bold yellow]Warning:[/bold yellow] "
                    f"Failed to set PHP version: {exc}"
                )

        if domain and app_id:
            try:
                with console.status(
                    f"[bold green]Adding domain {domain}...[/bold green]"
                ):
                    await client.add_domain(
                        server_id=server_id,
                        app_id=app_id,
                        domain=domain,
                    )
            except CloudwaysError as exc:
                err_console.print(
                    f"[bold yellow]Warning:[/bold yellow] Failed to add domain: {exc}"
                )

        elapsed = time.monotonic() - start_time
        elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

        # Display success
        table = Table(title="Application Created Successfully")
        table.add_column("Property", style="bold")
        table.add_column("Value")
        table.add_row("App ID", str(app_info.get("id", "N/A")))
        table.add_row("Label", app_label)
        table.add_row("Server ID", str(server_id))
        table.add_row("Application", app_type)
        table.add_row("Version", app_version)
        if php_version:
            table.add_row("PHP Version", php_version)
        if domain:
            table.add_row("Domain", domain)
        table.add_row("Project", project)
        table.add_row("Created in", elapsed_str)
        console.print(table)
