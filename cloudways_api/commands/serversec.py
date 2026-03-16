"""Server security suite management commands.

Provides commands for IP firewall management, country geoblocking,
security statistics, infected domain management, firewall settings,
and app security inventory via the Cloudways server-level security API.

Usage::

    cloudways serversec incidents
    cloudways serversec ips
    cloudways serversec ip-add --ip <ip> --mode allow|block [--ttl N] [--ttl-type T]
    cloudways serversec ip-remove --ip <ip> --mode allow|block
    cloudways serversec country-block --country <code> [--reason TEXT]
    cloudways serversec country-unblock --country <code>
    cloudways serversec stats --data-types <types> --group-by <g> --start <t> --end <t>
    cloudways serversec infected-domains [--offset N] [--limit N]
    cloudways serversec infected-domains-sync
    cloudways serversec firewall-settings
    cloudways serversec firewall-update [--request-limit N] [--weak-password/--no-weak-password]
    cloudways serversec apps [--page N] [--page-limit N] [--filter-by TEXT]
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

serversec_group = typer.Typer(help="Manage server-level security via Cloudways API.")


# ------------------------------------------------------------------
# serversec incidents
# ------------------------------------------------------------------


@serversec_group.command(name="incidents")
@handle_cli_errors
def serversec_incidents() -> None:
    """Get server security incidents."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_incidents(creds=creds, server_id=server_id))


async def _execute_incidents(creds: dict, server_id: int) -> None:
    """Fetch server security incidents."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_security_incidents(server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# serversec ips
# ------------------------------------------------------------------


@serversec_group.command(name="ips")
@handle_cli_errors
def serversec_ips() -> None:
    """List server security IP allow/blocklist."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_ips(creds=creds, server_id=server_id))


async def _execute_ips(creds: dict, server_id: int) -> None:
    """Fetch server security IPs."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_security_ips(server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# serversec ip-add
# ------------------------------------------------------------------


@serversec_group.command(name="ip-add")
@handle_cli_errors
def serversec_ip_add(
    ip: str = typer.Option(..., "--ip", help="IP address to add"),
    mode: str = typer.Option(..., "--mode", help="Mode: allow or block"),
    ttl: int = typer.Option(0, "--ttl", help="Time-to-live (0 = permanent)"),
    ttl_type: str = typer.Option(
        "minutes", "--ttl-type", help="TTL unit: minutes or hours"
    ),
) -> None:
    """Add an IP to the server security allow/blocklist."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_ip_add(
            creds=creds,
            server_id=server_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            ttl_type=ttl_type,
        )
    )


async def _execute_ip_add(
    creds: dict,
    server_id: int,
    ip: str,
    mode: str,
    ttl: int,
    ttl_type: str,
) -> None:
    """Add IP to server security allow/blocklist."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.update_server_security_ips(
            server_id=server_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            ttl_type=ttl_type,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec ip-remove
# ------------------------------------------------------------------


@serversec_group.command(name="ip-remove")
@handle_cli_errors
def serversec_ip_remove(
    ip: str = typer.Option(..., "--ip", help="IP address to remove"),
    mode: str = typer.Option(..., "--mode", help="Mode: allow or block"),
) -> None:
    """Remove an IP from the server security allow/blocklist."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_ip_remove(
            creds=creds,
            server_id=server_id,
            ip=ip,
            mode=mode,
        )
    )


async def _execute_ip_remove(
    creds: dict,
    server_id: int,
    ip: str,
    mode: str,
) -> None:
    """Remove IP from server security allow/blocklist."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.delete_server_security_ips(
            server_id=server_id,
            ip=ip,
            mode=mode,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec country-block
# ------------------------------------------------------------------


@serversec_group.command(name="country-block")
@handle_cli_errors
def serversec_country_block(
    country: str = typer.Option(
        ..., "--country", help="Two-letter country code to block"
    ),
    reason: str | None = typer.Option(
        None, "--reason", help="Reason for blocking the country"
    ),
) -> None:
    """Add a country to the server security geoblocking list."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_country_block(
            creds=creds,
            server_id=server_id,
            country=country,
            reason=reason,
        )
    )


async def _execute_country_block(
    creds: dict,
    server_id: int,
    country: str,
    reason: str | None,
) -> None:
    """Add country to geoblocking list."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.add_server_blacklist_countries(
            server_id=server_id,
            country=country,
            reason=reason,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec country-unblock
# ------------------------------------------------------------------


@serversec_group.command(name="country-unblock")
@handle_cli_errors
def serversec_country_unblock(
    country: str = typer.Option(
        ..., "--country", help="Two-letter country code to unblock"
    ),
) -> None:
    """Remove a country from the server security geoblocking list."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_country_unblock(
            creds=creds,
            server_id=server_id,
            country=country,
        )
    )


async def _execute_country_unblock(
    creds: dict,
    server_id: int,
    country: str,
) -> None:
    """Remove country from geoblocking list."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.remove_server_blacklist_countries(
            server_id=server_id,
            country=country,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec stats
# ------------------------------------------------------------------


@serversec_group.command(name="stats")
@handle_cli_errors
def serversec_stats(
    data_types: str = typer.Option(
        ..., "--data-types", help="Comma-separated data types (e.g. bandwidth,requests)"
    ),
    group_by: str = typer.Option(
        ..., "--group-by", help="Grouping interval (e.g. day)"
    ),
    start: int = typer.Option(..., "--start", help="Start timestamp (epoch seconds)"),
    end: int = typer.Option(..., "--end", help="End timestamp (epoch seconds)"),
) -> None:
    """Get server security statistics."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    types_list = [s.strip() for s in data_types.split(",") if s.strip()]
    asyncio.run(
        _execute_stats(
            creds=creds,
            server_id=server_id,
            data_types=types_list,
            group_by=group_by,
            start=start,
            end=end,
        )
    )


async def _execute_stats(
    creds: dict,
    server_id: int,
    data_types: list[str],
    group_by: str,
    start: int,
    end: int,
) -> None:
    """Fetch server security statistics."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_security_stats(
            server_id=server_id,
            data_types=data_types,
            group_by=group_by,
            start=start,
            end=end,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec infected-domains
# ------------------------------------------------------------------


@serversec_group.command(name="infected-domains")
@handle_cli_errors
def serversec_infected_domains(
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    limit: int = typer.Option(20, "--limit", help="Page size"),
) -> None:
    """List infected domains on the server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_infected_domains(
            creds=creds,
            server_id=server_id,
            offset=offset,
            limit=limit,
        )
    )


async def _execute_infected_domains(
    creds: dict,
    server_id: int,
    offset: int,
    limit: int,
) -> None:
    """Fetch infected domains list."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.list_server_infected_domains(
            server_id=server_id,
            offset=offset,
            limit=limit,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec infected-domains-sync
# ------------------------------------------------------------------


@serversec_group.command(name="infected-domains-sync")
@handle_cli_errors
def serversec_infected_domains_sync() -> None:
    """Sync infected domains on the server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_infected_domains_sync(
            creds=creds,
            server_id=server_id,
        )
    )


async def _execute_infected_domains_sync(
    creds: dict,
    server_id: int,
) -> None:
    """Trigger infected domains sync."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.sync_server_infected_domains(
            server_id=server_id,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec firewall-settings
# ------------------------------------------------------------------


@serversec_group.command(name="firewall-settings")
@handle_cli_errors
def serversec_firewall_settings() -> None:
    """Get server firewall settings."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_firewall_settings(
            creds=creds,
            server_id=server_id,
        )
    )


async def _execute_firewall_settings(
    creds: dict,
    server_id: int,
) -> None:
    """Fetch firewall settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_firewall_settings(
            server_id=server_id,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec firewall-update
# ------------------------------------------------------------------


@serversec_group.command(name="firewall-update")
@handle_cli_errors
def serversec_firewall_update(
    request_limit: int | None = typer.Option(
        None, "--request-limit", help="Maximum request limit"
    ),
    weak_password: bool | None = typer.Option(
        None,
        "--weak-password/--no-weak-password",
        help="Enable/disable weak password detection",
    ),
) -> None:
    """Update server firewall settings."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_firewall_update(
            creds=creds,
            server_id=server_id,
            request_limit=request_limit,
            weak_password=weak_password,
        )
    )


async def _execute_firewall_update(
    creds: dict,
    server_id: int,
    request_limit: int | None,
    weak_password: bool | None,
) -> None:
    """Update firewall settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.update_server_firewall_settings(
            server_id=server_id,
            request_limit=request_limit,
            weak_password=weak_password,
        )
        console.print(result)


# ------------------------------------------------------------------
# serversec apps
# ------------------------------------------------------------------


@serversec_group.command(name="apps")
@handle_cli_errors
def serversec_apps(
    page: int = typer.Option(1, "--page", help="Page number"),
    page_limit: int = typer.Option(20, "--page-limit", help="Page size"),
    app_name: str | None = typer.Option(
        None, "--app-name", help="Filter by application name"
    ),
    filter_by: str | None = typer.Option(
        None, "--filter-by", help="Filter by status (e.g. infected)"
    ),
) -> None:
    """List server security app inventory."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_apps(
            creds=creds,
            server_id=server_id,
            page=page,
            page_limit=page_limit,
            app_name=app_name,
            filter_by=filter_by,
        )
    )


async def _execute_apps(
    creds: dict,
    server_id: int,
    page: int,
    page_limit: int,
    app_name: str | None,
    filter_by: str | None,
) -> None:
    """Fetch server security apps."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_server_security_apps(
            server_id=server_id,
            page=page,
            page_limit=page_limit,
            app_name=app_name,
            filter_by=filter_by,
        )
        console.print(result)
