"""Manage application webroot on Cloudways.

Provides set-webroot and get-webroot commands for updating or inspecting
the application webroot path via the Cloudways API v2.

Usage::

    cloudways app set-webroot production
    cloudways app set-webroot staging --path public_html
    cloudways app get-webroot production
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

# Bedrock webroot: where the web-facing index.php lives.
# Intentionally different from DEFAULT_WEBROOT ("public_html/current") in
# _shared.py, which represents the Capistrano deploy path.
BEDROCK_WEBROOT = "public_html/current/web"

app_group = typer.Typer(help="Manage Cloudways application settings.")


@app_group.command(name="set-webroot")
@handle_cli_errors
def set_webroot(
    environment: str = typer.Argument(help="Environment name from project config"),
    path: str = typer.Option(
        BEDROCK_WEBROOT,
        "--path",
        help="Webroot path to set",
    ),
) -> None:
    """Update the application webroot via the Cloudways API."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_set_webroot(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            webroot=path,
            environment=environment,
        )
    )


async def _execute_set_webroot(
    creds: dict,
    server_id: int,
    app_id: int | str,
    webroot: str,
    environment: str,
) -> None:
    """Execute set-webroot workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_webroot(
            server_id=server_id,
            app_id=app_id,
            webroot=webroot,
        )
        console.print(f"Webroot updated to '{webroot}' for {environment}")


@app_group.command(name="get-webroot")
@handle_cli_errors
def get_webroot(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """Display the current application webroot from server info."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = str(env_config["app_id"])

    asyncio.run(
        _execute_get_webroot(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            environment=environment,
        )
    )


async def _execute_get_webroot(
    creds: dict,
    server_id: int,
    app_id: str,
    environment: str,
) -> None:
    """Execute get-webroot workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        servers = await client.get_servers()

        # Find the matching server and app
        webroot = _find_webroot(servers, server_id, app_id)
        if webroot is None:
            err_console.print(
                f"[bold red]Error:[/bold red] Could not find app "
                f"(server_id={server_id}, app_id={app_id}) in server list. "
                "Check Cloudways dashboard for current webroot."
            )
            raise typer.Exit(code=1)

        console.print(f"Current webroot for {environment}: {webroot}")


def _find_webroot(
    servers: list[dict],
    server_id: int,
    app_id: str,
) -> str | None:
    """Find the webroot for a specific app in the server list.

    The Cloudways API returns ``webroot`` as a top-level field on each
    app object (alongside ``application`` which is a *string* such as
    ``"wordpress"``).  We read ``app_info["webroot"]`` directly.

    Args:
        servers: List of server dicts from get_servers().
        server_id: Target server ID.
        app_id: Target application ID.

    Returns:
        The webroot string if found, None otherwise.
    """
    for server in servers:
        if str(server.get("id")) != str(server_id):
            continue
        for app_info in server.get("apps", []):
            if str(app_info.get("id")) != str(app_id):
                continue
            return app_info.get("webroot")
    return None
