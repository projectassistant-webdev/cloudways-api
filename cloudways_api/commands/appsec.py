"""App security suite (Imunify360) management commands.

Provides commands for security status, scans, events, incidents,
file operations, lifecycle management, and IP allow/blocklist
operations via the Cloudways Imunify360 API.

Usage::

    cloudways appsec status <env>
    cloudways appsec scans <env> [--offset N] [--limit N]
    cloudways appsec scan <env> [--wait]
    cloudways appsec scan-status <env>
    cloudways appsec scan-detail <env> <scan-id>
    cloudways appsec events <env>
    cloudways appsec incidents <env>
    cloudways appsec files <env> [--offset N] [--limit N]
    cloudways appsec restore <env> --db <db> --files <files>
    cloudways appsec cleaned-diff <env>
    cloudways appsec activate <env> [--mp-offer / --no-mp-offer]
    cloudways appsec deactivate <env> --app-name <name> [--feedback <text>]
    cloudways appsec ip-add <env> --ip <ip> --mode allow|block --reason <r> [--ttl N]
    cloudways appsec ip-remove <env> --ip <ip> --mode allow|block --reason <r> [--ttl N]
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

appsec_group = typer.Typer(help="Manage app security (Imunify360) via Cloudways API.")


# ------------------------------------------------------------------
# appsec status
# ------------------------------------------------------------------


@appsec_group.command(name="status")
@handle_cli_errors
def appsec_status(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
) -> None:
    """Get Imunify360 security status for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(_execute_status(creds=creds, server_id=server_id, app_id=app_id))


async def _execute_status(creds: dict, server_id: int, app_id: int) -> None:
    """Fetch security status."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_app_security_status(
            app_id=app_id, server_id=server_id
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec scans
# ------------------------------------------------------------------


@appsec_group.command(name="scans")
@handle_cli_errors
def appsec_scans(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    limit: int = typer.Option(20, "--limit", help="Page size"),
) -> None:
    """List security scans for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_scans(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            offset=offset,
            limit=limit,
        )
    )


async def _execute_scans(
    creds: dict,
    server_id: int,
    app_id: int,
    offset: int,
    limit: int,
) -> None:
    """Fetch security scan list."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.list_security_scans(
            app_id=app_id,
            server_id=server_id,
            offset=offset,
            limit=limit,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec scan
# ------------------------------------------------------------------


@appsec_group.command(name="scan")
@handle_cli_errors
def appsec_scan(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    wait: bool = typer.Option(False, "--wait", help="Wait for scan to complete"),
) -> None:
    """Initiate a security scan for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_scan(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            wait=wait,
        )
    )


async def _execute_scan(creds: dict, server_id: int, app_id: int, wait: bool) -> None:
    """Initiate security scan, optionally waiting for completion."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.initiate_security_scan(app_id=app_id, server_id=server_id)

        if not wait:
            console.print(result)
            console.print("Use `appsec scan-status <env>` to check progress.")
            return

        # Wait path: check for task_id first, then fall back to polling
        if "task_id" in result:
            final = await client.wait_for_task(result["task_id"])
            console.print(final)
            return

        # Manual status-polling fallback (no task_id in response)
        poll_interval = 5
        max_attempts = 60
        for _ in range(max_attempts):
            await asyncio.sleep(poll_interval)
            status_result = await client.get_security_scan_status(
                app_id=app_id, server_id=server_id
            )
            scan_status = status_result.get("status")
            if scan_status == "completed":
                console.print(status_result)
                return
            if scan_status in ("failed", "error"):
                err_console.print(f"[bold red]Error:[/bold red] Scan {scan_status}.")
                raise typer.Exit(code=1)

        err_console.print(
            "Scan did not complete within 300s. "
            "Use `appsec scan-status <env>` to check progress."
        )
        raise typer.Exit(code=1)


# ------------------------------------------------------------------
# appsec scan-status
# ------------------------------------------------------------------


@appsec_group.command(name="scan-status")
@handle_cli_errors
def appsec_scan_status(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
) -> None:
    """Get current scan status for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(_execute_scan_status(creds=creds, server_id=server_id, app_id=app_id))


async def _execute_scan_status(creds: dict, server_id: int, app_id: int) -> None:
    """Fetch scan status."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_security_scan_status(
            app_id=app_id, server_id=server_id
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec scan-detail
# ------------------------------------------------------------------


@appsec_group.command(name="scan-detail")
@handle_cli_errors
def appsec_scan_detail(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    scan_id: int = typer.Argument(..., help="Scan ID to retrieve"),
) -> None:
    """Get detailed results for a specific scan."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_scan_detail(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            scan_id=scan_id,
        )
    )


async def _execute_scan_detail(
    creds: dict, server_id: int, app_id: int, scan_id: int
) -> None:
    """Fetch scan detail."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_security_scan_detail(
            app_id=app_id, scan_id=scan_id, server_id=server_id
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec events
# ------------------------------------------------------------------


@appsec_group.command(name="events")
@handle_cli_errors
def appsec_events(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
) -> None:
    """Get security events for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(_execute_events(creds=creds, server_id=server_id, app_id=app_id))


async def _execute_events(creds: dict, server_id: int, app_id: int) -> None:
    """Fetch security events."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_security_events(app_id=app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# appsec incidents
# ------------------------------------------------------------------


@appsec_group.command(name="incidents")
@handle_cli_errors
def appsec_incidents(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
) -> None:
    """Get security incidents for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(_execute_incidents(creds=creds, server_id=server_id, app_id=app_id))


async def _execute_incidents(creds: dict, server_id: int, app_id: int) -> None:
    """Fetch security incidents."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_security_incidents(app_id=app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# appsec files
# ------------------------------------------------------------------


@appsec_group.command(name="files")
@handle_cli_errors
def appsec_files(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    limit: int = typer.Option(20, "--limit", help="Page size"),
) -> None:
    """List quarantined files for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_files(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            offset=offset,
            limit=limit,
        )
    )


async def _execute_files(
    creds: dict,
    server_id: int,
    app_id: int,
    offset: int,
    limit: int,
) -> None:
    """Fetch quarantined file list."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.list_security_files(
            app_id=app_id,
            server_id=server_id,
            offset=offset,
            limit=limit,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec restore
# ------------------------------------------------------------------


@appsec_group.command(name="restore")
@handle_cli_errors
def appsec_restore(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    db: str = typer.Option(..., "--db", help="Database identifier"),
    files: str = typer.Option(
        ..., "--files", help="Comma-separated list of files to restore"
    ),
) -> None:
    """Restore quarantined files for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_restore(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            db=db,
            files=files,
        )
    )


async def _execute_restore(
    creds: dict,
    server_id: int,
    app_id: int,
    db: str,
    files: str,
) -> None:
    """Restore quarantined files."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.restore_security_files(
            app_id=app_id,
            server_id=server_id,
            db=db,
            files=files,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec cleaned-diff
# ------------------------------------------------------------------


@appsec_group.command(name="cleaned-diff")
@handle_cli_errors
def appsec_cleaned_diff(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
) -> None:
    """View cleaned diff for quarantined files."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(_execute_cleaned_diff(creds=creds, server_id=server_id, app_id=app_id))


async def _execute_cleaned_diff(creds: dict, server_id: int, app_id: int) -> None:
    """Fetch cleaned diff."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_cleaned_diff(app_id=app_id, server_id=server_id)
        console.print(result)


# ------------------------------------------------------------------
# appsec activate
# ------------------------------------------------------------------


@appsec_group.command(name="activate")
@handle_cli_errors
def appsec_activate(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    mp_offer: bool = typer.Option(
        False, "--mp-offer/--no-mp-offer", help="Marketplace offer availed"
    ),
) -> None:
    """Activate Imunify360 security suite for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_activate(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            mp_offer_availed=mp_offer,
        )
    )


async def _execute_activate(
    creds: dict, server_id: int, app_id: int, mp_offer_availed: bool
) -> None:
    """Activate security suite."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.activate_security_suite(
            app_id=app_id,
            server_id=server_id,
            mp_offer_availed=mp_offer_availed,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec deactivate
# ------------------------------------------------------------------


@appsec_group.command(name="deactivate")
@handle_cli_errors
def appsec_deactivate(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    app_name: str = typer.Option(..., "--app-name", help="Application name"),
    feedback: str | None = typer.Option(
        None, "--feedback", help="Optional deactivation feedback"
    ),
) -> None:
    """Deactivate Imunify360 security suite for an application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_deactivate(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            app_name=app_name,
            feedback_text=feedback,
        )
    )


async def _execute_deactivate(
    creds: dict,
    server_id: int,
    app_id: int,
    app_name: str,
    feedback_text: str | None,
) -> None:
    """Deactivate security suite."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.deactivate_security_suite(
            app_id=app_id,
            server_id=server_id,
            app_name=app_name,
            feedback_text=feedback_text,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec ip-add
# ------------------------------------------------------------------


@appsec_group.command(name="ip-add")
@handle_cli_errors
def appsec_ip_add(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    ip: str = typer.Option(..., "--ip", help="IP address to add"),
    mode: str = typer.Option(..., "--mode", help="Mode: allow or block"),
    ttl: int = typer.Option(0, "--ttl", help="Time-to-live in seconds (0 = permanent)"),
    reason: str = typer.Option(..., "--reason", help="Reason for adding the IP"),
) -> None:
    """Add an IP to the security allow/blocklist."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_ip_add(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            reason=reason,
        )
    )


async def _execute_ip_add(
    creds: dict,
    server_id: int,
    app_id: int,
    ip: str,
    mode: str,
    ttl: int,
    reason: str,
) -> None:
    """Add IP to allow/blocklist."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.add_security_ip(
            app_id=app_id,
            server_id=server_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            reason=reason,
        )
        console.print(result)


# ------------------------------------------------------------------
# appsec ip-remove
# ------------------------------------------------------------------


@appsec_group.command(name="ip-remove")
@handle_cli_errors
def appsec_ip_remove(
    environment: str = typer.Argument(..., help="Environment name (e.g. production)"),
    ip: str = typer.Option(..., "--ip", help="IP address to remove"),
    mode: str = typer.Option(..., "--mode", help="Mode: allow or block"),
    ttl: int = typer.Option(0, "--ttl", help="Time-to-live in seconds (0 = permanent)"),
    reason: str = typer.Option(..., "--reason", help="Reason for removing the IP"),
) -> None:
    """Remove an IP from the security allow/blocklist."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])
    asyncio.run(
        _execute_ip_remove(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            reason=reason,
        )
    )


async def _execute_ip_remove(
    creds: dict,
    server_id: int,
    app_id: int,
    ip: str,
    mode: str,
    ttl: int,
    reason: str,
) -> None:
    """Remove IP from allow/blocklist."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.remove_security_ip(
            app_id=app_id,
            server_id=server_id,
            ip=ip,
            mode=mode,
            ttl=ttl,
            reason=reason,
        )
        console.print(result)
