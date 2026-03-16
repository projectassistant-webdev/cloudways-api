"""Retrieve Cloudflare analytics for an application.

Provides cache analytics, security analytics, and Logpush data
retrieval commands for app-level Cloudflare metrics via the Cloudways API v2.

Usage::

    cloudways cloudflare analytics <env> [--mins <minutes>]
    cloudways cloudflare security <env> [--mins <minutes>]
    cloudways cloudflare logpush <env> --type analytics|security
"""

import asyncio
import json

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

cloudflare_group = typer.Typer(help="Retrieve Cloudflare analytics for an application.")


# ------------------------------------------------------------------
# cloudflare analytics
# ------------------------------------------------------------------


async def _execute_cloudflare_analytics(
    creds: dict, app_id: int, server_id: int, mins: int
) -> None:
    """Fetch and display Cloudflare cache analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_cloudflare_analytics(app_id, server_id, mins)
        console.print(json.dumps(result, indent=2))


@cloudflare_group.command(name="analytics")
@handle_cli_errors
def cloudflare_analytics(
    environment: str = typer.Argument(help="Environment name (e.g., production)"),
    mins: int = typer.Option(60, "--mins", help="Time window in minutes"),
) -> None:
    """Retrieve Cloudflare cache analytics for an environment."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    app_id = int(env_config["app_id"])
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_cloudflare_analytics(
            creds=creds, app_id=app_id, server_id=server_id, mins=mins
        )
    )


# ------------------------------------------------------------------
# cloudflare security
# ------------------------------------------------------------------


async def _execute_cloudflare_security(
    creds: dict, app_id: int, server_id: int, mins: int
) -> None:
    """Fetch and display Cloudflare security analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_cloudflare_security(app_id, server_id, mins)
        console.print(json.dumps(result, indent=2))


@cloudflare_group.command(name="security")
@handle_cli_errors
def cloudflare_security(
    environment: str = typer.Argument(help="Environment name (e.g., production)"),
    mins: int = typer.Option(60, "--mins", help="Time window in minutes"),
) -> None:
    """Retrieve Cloudflare security analytics for an environment."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    app_id = int(env_config["app_id"])
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_cloudflare_security(
            creds=creds, app_id=app_id, server_id=server_id, mins=mins
        )
    )


# ------------------------------------------------------------------
# cloudflare logpush
# ------------------------------------------------------------------


async def _execute_cloudflare_logpush(
    creds: dict, app_id: int, logpush_type: str
) -> None:
    """Fetch and display Cloudflare Logpush data."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        if logpush_type == "analytics":
            result = await client.get_cloudflare_logpush_analytics(app_id)
        else:
            result = await client.get_cloudflare_logpush_security(app_id)
        console.print(json.dumps(result, indent=2))


@cloudflare_group.command(name="logpush")
@handle_cli_errors
def cloudflare_logpush(
    environment: str = typer.Argument(help="Environment name (e.g., production)"),
    logpush_type: str = typer.Option(
        ...,
        "--type",
        help="Logpush data type: analytics or security",
        metavar="analytics|security",
    ),
) -> None:
    """Retrieve Cloudflare Logpush data for an environment."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_cloudflare_logpush(
            creds=creds, app_id=app_id, logpush_type=logpush_type
        )
    )
