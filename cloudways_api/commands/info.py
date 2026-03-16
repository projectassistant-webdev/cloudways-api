"""Show server and application details for configured environments.

Wires together config loading, credential resolution, and the async
Cloudways API client to produce a Rich-formatted summary.
"""

import asyncio

import typer
from rich.table import Table

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)
from cloudways_api.exceptions import (
    CloudwaysError,
)

PROVIDER_NAMES: dict[str, str] = {
    "do": "DigitalOcean",
    "vultr": "Vultr",
    "amazon": "Amazon Web Services",
    "gce": "Google Cloud",
    "linode": "Linode",
}


@handle_cli_errors
def info(
    environment: str | None = typer.Argument(
        None, help="Filter to a specific environment (e.g. production, staging)."
    ),
) -> None:
    """Show server and application details."""
    creds, config = load_creds()

    environments = config.get("environments", {})

    # Validate environment filter if provided
    if environment is not None:
        validate_environment(config, environment)
        environments = {environment: environments[environment]}

    result = asyncio.run(_fetch_info(creds, config, environments))

    _render_output(result)


async def _fetch_info(creds: dict, config: dict, environments: dict) -> dict:
    """Fetch server and app data from the Cloudways API.

    Returns a dict with server info, settings, and matched environments.
    """
    server_id = config["server"]["id"]

    async with CloudwaysClient(
        email=creds["email"], api_key=creds["api_key"]
    ) as client:
        servers = await client.get_servers()

        # Find matching server by ID (API returns IDs as strings, config as int)
        server = None
        try:
            config_server_id = int(server_id)
        except (TypeError, ValueError):
            raise CloudwaysError(
                f"Invalid server ID '{server_id}' in config. Expected an integer."
            )

        for s in servers:
            try:
                if int(s.get("id", 0)) == config_server_id:
                    server = s
                    break
            except (TypeError, ValueError):
                continue

        if server is None:
            raise CloudwaysError(
                f"Server ID {server_id} not found in your Cloudways account. "
                "Check the server.id in your project-config.yml."
            )

        settings = await client.get_server_settings(int(server_id))

    # Match app IDs from config to apps on the server using int coercion
    matched_envs = {}
    apps_on_server: dict[int, dict] = {}
    for a in server.get("apps", []):
        try:
            apps_on_server[int(a["id"])] = a
        except (TypeError, ValueError, KeyError):
            continue

    for env_name, env_config in environments.items():
        raw_app_id = env_config.get("app_id", "")
        try:
            app_id_int = int(raw_app_id)
        except (TypeError, ValueError):
            raise CloudwaysError(
                f"Invalid app_id '{raw_app_id}' for environment '{env_name}'. "
                "Expected an integer."
            )
        app_data = apps_on_server.get(app_id_int)
        if app_data is None:
            raise CloudwaysError(
                f"App ID {app_id_int} not found on server {server_id} "
                f"(environment: {env_name}). "
                "Check your project-config.yml."
            )
        matched_envs[env_name] = {
            "config": env_config,
            "app": app_data,
        }

    return {
        "server": server,
        "settings": settings,
        "environments": matched_envs,
    }


def _render_output(data: dict) -> None:
    """Render the fetched data as Rich-formatted terminal output."""
    server = data["server"]
    settings = data["settings"]
    envs = data["environments"]

    pkg = settings.get("settings", {}).get("package_versions", {})

    # Server info table
    server_table = Table(title="Server Info", show_header=False, pad_edge=False)
    server_table.add_column("Field", style="bold cyan", no_wrap=True)
    server_table.add_column("Value")

    # M-2: Status color coding
    raw_status = server.get("status", "")
    if raw_status == "running":
        status_display = f"[green]{raw_status}[/green]"
    elif raw_status == "stopped":
        status_display = f"[red]{raw_status}[/red]"
    else:
        status_display = f"[yellow]{raw_status}[/yellow]"

    # M-1: Provider code to display name
    cloud_code = server.get("cloud", "")
    provider_display = PROVIDER_NAMES.get(cloud_code, cloud_code)

    server_table.add_row("Server ID", str(server.get("id", "")))
    server_table.add_row("Label", server.get("label", ""))
    server_table.add_row("Status", status_display)
    server_table.add_row("Provider", provider_display)
    server_table.add_row("Region", server.get("region", ""))
    server_table.add_row("IP Address", server.get("public_ip", ""))
    server_table.add_row("PHP", pkg.get("php", "N/A"))
    server_table.add_row("MariaDB", pkg.get("mariadb", "N/A"))

    console.print(server_table)
    console.print()

    # Environment details
    for env_name, env_data in envs.items():
        app = env_data["app"]
        cfg = env_data["config"]

        env_table = Table(
            title=f"Environment: {env_name.capitalize()}",
            show_header=False,
            pad_edge=False,
        )
        env_table.add_column("Field", style="bold cyan", no_wrap=True)
        env_table.add_column("Value")

        env_table.add_row("App ID", str(app.get("id", "")))
        env_table.add_row("Label", app.get("label", ""))
        env_table.add_row("Application", app.get("application", ""))
        env_table.add_row("Version", app.get("app_version", ""))
        env_table.add_row("Domain", app.get("cname", cfg.get("domain", "")))
        env_table.add_row("System User", app.get("sys_user", ""))
        env_table.add_row("Database", app.get("mysql_db_name", ""))
        env_table.add_row("Webroot", app.get("webroot", ""))

        console.print(env_table)
        console.print()
