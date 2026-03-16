"""Monitor and analytics for Cloudways servers and apps.

Provides commands for server bandwidth/disk summaries, server usage
analytics, server monitoring graphs, app bandwidth/database summaries,
traffic analytics, traffic details, PHP/MySQL/cron analytics.

Usage::

    cloudways monitor server-summary --server-id <id> --type bandwidth|disk
    cloudways monitor server-usage --server-id <id> [--wait]
    cloudways monitor server-graph --server-id <id> --target <target> --duration 15m|30m|1h|1d [--storage] [--timezone <tz>] [--format json|svg] [--wait]
    cloudways monitor app-summary <env> --type bw|db
    cloudways monitor traffic <env> --duration ... --resource ... [--wait]
    cloudways monitor traffic-details <env> --from ... --until ... --resource ... [--resource-list]... [--wait]
    cloudways monitor php <env> --duration ... --resource ... [--wait]
    cloudways monitor mysql <env> --duration ... --resource ... [--wait]
    cloudways monitor cron <env> [--wait]
"""

import asyncio

import click
import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

monitor_group = typer.Typer(help="Monitor and analytics for servers and apps.")


# ------------------------------------------------------------------
# monitor server-summary
# ------------------------------------------------------------------


@monitor_group.command(name="server-summary")
@handle_cli_errors
def server_summary(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    summary_type: str = typer.Option(
        ...,
        "--type",
        help="Summary type",
        click_type=click.Choice(["bandwidth", "disk"]),
    ),
) -> None:
    """Get bandwidth or disk summary for a server."""
    creds, config = load_creds()
    asyncio.run(
        _execute_server_summary(
            creds=creds, server_id=server_id, summary_type=summary_type
        )
    )


async def _execute_server_summary(
    creds: dict, server_id: int, summary_type: str
) -> None:
    """Fetch server monitor summary."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_monitor_summary(server_id, summary_type)
        console.print(result)


# ------------------------------------------------------------------
# monitor server-usage
# ------------------------------------------------------------------


@monitor_group.command(name="server-usage")
@handle_cli_errors
def server_usage(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get server usage analytics (task-based)."""
    creds, config = load_creds()
    asyncio.run(_execute_server_usage(creds=creds, server_id=server_id, wait=wait))


async def _execute_server_usage(creds: dict, server_id: int, wait: bool) -> None:
    """Fetch server usage analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_usage(server_id)
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor server-graph
# ------------------------------------------------------------------


@monitor_group.command(name="server-graph")
@handle_cli_errors
def server_graph(
    server_id: int = typer.Option(..., "--server-id", help="Server ID"),
    target: str = typer.Option(..., "--target", help="Monitor target (e.g., cpu, mem)"),
    duration: str = typer.Option(
        ...,
        "--duration",
        help="Time window",
        click_type=click.Choice(["15m", "30m", "1h", "1d"]),
    ),
    storage: bool = typer.Option(False, "--storage", help="Include storage data"),
    timezone: str = typer.Option("UTC", "--timezone", help="Timezone string"),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format",
        click_type=click.Choice(["json", "svg"]),
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get server monitor detail graph (task-based)."""
    creds, config = load_creds()
    asyncio.run(
        _execute_server_graph(
            creds=creds,
            server_id=server_id,
            target=target,
            duration=duration,
            storage=storage,
            timezone=timezone,
            output_format=output_format,
            wait=wait,
        )
    )


async def _execute_server_graph(
    creds: dict,
    server_id: int,
    target: str,
    duration: str,
    storage: bool,
    timezone: str,
    output_format: str,
    wait: bool,
) -> None:
    """Fetch server monitor detail graph."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_monitor_detail(
            server_id=server_id,
            target=target,
            duration=duration,
            storage=storage,
            timezone=timezone,
            output_format=output_format,
        )
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor app-summary
# ------------------------------------------------------------------


@monitor_group.command(name="app-summary")
@handle_cli_errors
def app_summary(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    summary_type: str = typer.Option(
        ...,
        "--type",
        help="Summary type",
        click_type=click.Choice(["bw", "db"]),
    ),
) -> None:
    """Get bandwidth or database summary for an app."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_app_summary(
            creds=creds, server_id=server_id, app_id=app_id, summary_type=summary_type
        )
    )


async def _execute_app_summary(
    creds: dict, server_id: int, app_id: int, summary_type: str
) -> None:
    """Fetch app monitor summary."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_monitor_summary(server_id, app_id, summary_type)
        console.print(result)


# ------------------------------------------------------------------
# monitor traffic
# ------------------------------------------------------------------


@monitor_group.command(name="traffic")
@handle_cli_errors
def traffic(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    duration: str = typer.Option(
        ...,
        "--duration",
        help="Time window",
        click_type=click.Choice(["15m", "30m", "1h", "1d"]),
    ),
    resource: str = typer.Option(
        ...,
        "--resource",
        help="Resource type",
        click_type=click.Choice(["top_ips", "top_bots", "top_urls", "top_statuses"]),
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get app traffic analytics (task-based)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_traffic(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            duration=duration,
            resource=resource,
            wait=wait,
        )
    )


async def _execute_traffic(
    creds: dict,
    server_id: int,
    app_id: int,
    duration: str,
    resource: str,
    wait: bool,
) -> None:
    """Fetch app traffic analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_traffic_analytics(
            server_id, app_id, duration, resource
        )
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor traffic-details
# ------------------------------------------------------------------


@monitor_group.command(name="traffic-details")
@handle_cli_errors
def traffic_details(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    from_dt: str = typer.Option(
        ..., "--from", help="Start datetime (DD/MM/YYYY HH:MM)"
    ),
    until_dt: str = typer.Option(
        ..., "--until", help="End datetime (DD/MM/YYYY HH:MM)"
    ),
    resource: str = typer.Option(..., "--resource", help="Resource type"),
    resource_list: list[str] = typer.Option(
        None, "--resource-list", help="Specific resources to filter"
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get detailed traffic analytics for a date range (task-based)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_traffic_details(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            from_dt=from_dt,
            until_dt=until_dt,
            resource=resource,
            resource_list=resource_list if resource_list else None,
            wait=wait,
        )
    )


async def _execute_traffic_details(
    creds: dict,
    server_id: int,
    app_id: int,
    from_dt: str,
    until_dt: str,
    resource: str,
    resource_list: list[str] | None,
    wait: bool,
) -> None:
    """Fetch detailed traffic analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_traffic_details(
            server_id=server_id,
            app_id=app_id,
            from_dt=from_dt,
            until_dt=until_dt,
            resource=resource,
            resource_list=resource_list,
        )
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor php
# ------------------------------------------------------------------


@monitor_group.command(name="php")
@handle_cli_errors
def php(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    duration: str = typer.Option(
        ...,
        "--duration",
        help="Time window",
        click_type=click.Choice(["15m", "30m", "1h", "1d"]),
    ),
    resource: str = typer.Option(
        ...,
        "--resource",
        help="PHP resource type",
        click_type=click.Choice(["url_durations", "processes", "slow_pages"]),
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get PHP-FPM analytics for an app (task-based)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_php(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            duration=duration,
            resource=resource,
            wait=wait,
        )
    )


async def _execute_php(
    creds: dict,
    server_id: int,
    app_id: int,
    duration: str,
    resource: str,
    wait: bool,
) -> None:
    """Fetch PHP-FPM analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_php_analytics(
            server_id, app_id, duration, resource
        )
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor mysql
# ------------------------------------------------------------------


@monitor_group.command(name="mysql")
@handle_cli_errors
def mysql(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    duration: str = typer.Option(
        ...,
        "--duration",
        help="Time window",
        click_type=click.Choice(["15m", "30m", "1h", "1d"]),
    ),
    resource: str = typer.Option(
        ...,
        "--resource",
        help="MySQL resource type",
        click_type=click.Choice(["running_queries", "slow_queries"]),
    ),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get MySQL analytics for an app (task-based)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_mysql(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            duration=duration,
            resource=resource,
            wait=wait,
        )
    )


async def _execute_mysql(
    creds: dict,
    server_id: int,
    app_id: int,
    duration: str,
    resource: str,
    wait: bool,
) -> None:
    """Fetch MySQL analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_mysql_analytics(
            server_id, app_id, duration, resource
        )
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)


# ------------------------------------------------------------------
# monitor cron
# ------------------------------------------------------------------


@monitor_group.command(name="cron")
@handle_cli_errors
def cron(
    environment: str = typer.Argument(..., help="Environment name from project config"),
    wait: bool = typer.Option(False, "--wait", help="Wait for task completion"),
) -> None:
    """Get cron analytics for an app (task-based)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_cron(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            wait=wait,
        )
    )


async def _execute_cron(
    creds: dict,
    server_id: int,
    app_id: int,
    wait: bool,
) -> None:
    """Fetch cron analytics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_cron_analytics(server_id, app_id)
        if wait:
            result = await client.wait_for_task(result["task_id"])
        console.print(result)
