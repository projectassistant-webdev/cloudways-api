"""Manage CloudwaysBot alerts and notification channels.

Provides alert list, mark-as-read, and mark-all-read commands
for account-level CloudwaysBot alerts, plus notification channel
(integration) management via the Cloudways API v2.

Usage::

    cloudways alerts list [--page LAST_ID]
    cloudways alerts read <alert-id>
    cloudways alerts read-all
    cloudways alerts channels list
    cloudways alerts channels available
    cloudways alerts channels add --name <name> --channel <id> --events <ids>
        [--to <email>] [--url <url>] [--active/--no-active]
    cloudways alerts channels update <channel-id> --name <name> --channel <id>
        --events <ids> [--to <email>] [--url <url>] [--active/--no-active]
    cloudways alerts channels delete <channel-id>
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

alerts_group = typer.Typer(help="Manage CloudwaysBot alerts and notification channels.")
channels_group = typer.Typer(help="Manage alert notification channels (integrations).")
alerts_group.add_typer(channels_group, name="channels")


# ------------------------------------------------------------------
# alerts list
# ------------------------------------------------------------------


@alerts_group.command(name="list")
@handle_cli_errors
def alerts_list(
    page: int = typer.Option(
        None,
        "--page",
        help="Alert ID cursor for pagination (returns alerts older than this ID)",
    ),
) -> None:
    """List CloudwaysBot alerts for the account."""
    creds, config = load_creds()
    asyncio.run(_execute_alerts_list(creds=creds, page=page))


async def _execute_alerts_list(creds: dict, page: int | None) -> None:
    """Fetch and display alerts."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        if page is not None:
            alerts = await client.get_alerts_page(page)
        else:
            alerts = await client.get_alerts()
        for alert in alerts:
            details = alert.get("details", {})
            console.print(f"ID: {alert.get('id')}")
            console.print(f"  Subject: {details.get('subject', 'N/A')}")
            console.print(f"  Description: {details.get('desc', 'N/A')}")
            console.print()


# ------------------------------------------------------------------
# alerts read
# ------------------------------------------------------------------


@alerts_group.command(name="read")
@handle_cli_errors
def alerts_read(
    alert_id: int = typer.Argument(help="ID of the alert to mark as read"),
) -> None:
    """Mark a single alert as read."""
    creds, config = load_creds()
    asyncio.run(_execute_alerts_read(creds=creds, alert_id=alert_id))


async def _execute_alerts_read(creds: dict, alert_id: int) -> None:
    """Mark a single alert as read."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.mark_alert_read(alert_id)
        console.print(f"Alert {alert_id} marked as read.")


# ------------------------------------------------------------------
# alerts read-all
# ------------------------------------------------------------------


@alerts_group.command(name="read-all")
@handle_cli_errors
def alerts_read_all() -> None:
    """Mark all account alerts as read."""
    creds, config = load_creds()
    asyncio.run(_execute_alerts_read_all(creds=creds))


async def _execute_alerts_read_all(creds: dict) -> None:
    """Mark all alerts as read."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.mark_all_alerts_read()
        console.print("All alerts marked as read.")


# ------------------------------------------------------------------
# Helper: parse events CSV
# ------------------------------------------------------------------


def _parse_events(events_str: str) -> list[int]:
    """Parse comma-separated event IDs to a list of ints.

    Validates that all parts are non-empty integers.

    Args:
        events_str: Comma-separated string (e.g., "1,2,3").

    Returns:
        List of integer event IDs.

    Raises:
        typer.Exit: On invalid or empty input.
    """
    stripped = events_str.strip()
    if not stripped:
        console.print("Error: --events cannot be empty")
        raise typer.Exit(code=1)
    parts = [p.strip() for p in stripped.split(",")]
    result = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            console.print(f"Error: Invalid event ID '{part}'")
            raise typer.Exit(code=1)
    return result


# ------------------------------------------------------------------
# alerts channels list
# ------------------------------------------------------------------


@channels_group.command(name="list")
@handle_cli_errors
def channels_list() -> None:
    """List configured alert notification channels."""
    creds, config = load_creds()
    asyncio.run(_execute_channels_list(creds=creds))


async def _execute_channels_list(creds: dict) -> None:
    """Fetch and display configured channels."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        integrations = await client.get_integrations()
        for integration in integrations:
            console.print(f"ID: {integration.get('id')}")
            console.print(f"  Name: {integration.get('name', 'N/A')}")
            console.print(f"  Channel: {integration.get('channel', 'N/A')}")
            console.print(f"  Events: {integration.get('events', [])}")
            console.print(f"  Active: {integration.get('is_active', 'N/A')}")
            console.print()


# ------------------------------------------------------------------
# alerts channels available
# ------------------------------------------------------------------


@channels_group.command(name="available")
@handle_cli_errors
def channels_available() -> None:
    """List available channel types and event types."""
    creds, config = load_creds()
    asyncio.run(_execute_channels_available(creds=creds))


async def _execute_channels_available(creds: dict) -> None:
    """Fetch and display available channel and event types."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        data = await client.get_integration_channels()
        console.print("Channels:")
        for ch in data.get("channels", []):
            console.print(f"  ID: {ch.get('id')}  Name: {ch.get('name')}")
        console.print()
        console.print("Events:")
        for ev in data.get("events", []):
            console.print(
                f"  ID: {ev.get('id')}  Name: {ev.get('name')}"
                f"  Level: {ev.get('level', 'N/A')}"
            )


# ------------------------------------------------------------------
# alerts channels add
# ------------------------------------------------------------------


@channels_group.command(name="add")
@handle_cli_errors
def channels_add(
    name: str = typer.Option(..., "--name", help="Channel label"),
    channel: int = typer.Option(..., "--channel", help="Channel type ID"),
    events: str = typer.Option(
        ..., "--events", help="Comma-separated event type IDs (e.g., '1,2,3')"
    ),
    to: str = typer.Option(None, "--to", help="Email address (for email channels)"),
    url: str = typer.Option(None, "--url", help="Webhook URL (for webhook channels)"),
    active: bool = typer.Option(
        True, "--active/--no-active", help="Whether channel is active"
    ),
) -> None:
    """Create a new alert notification channel."""
    event_ids = _parse_events(events)
    creds, config = load_creds()
    asyncio.run(
        _execute_channels_add(
            creds=creds,
            name=name,
            channel=channel,
            events=event_ids,
            to=to,
            url=url,
            is_active=active,
        )
    )


async def _execute_channels_add(
    creds: dict,
    name: str,
    channel: int,
    events: list[int],
    to: str | None,
    url: str | None,
    is_active: bool,
) -> None:
    """Create a new integration channel."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.create_integration(
            name=name,
            channel=channel,
            events=events,
            to=to,
            url=url,
            is_active=is_active,
        )
        console.print(f"Created channel '{name}' (ID: {result.get('id', 'N/A')}).")


# ------------------------------------------------------------------
# alerts channels update
# ------------------------------------------------------------------


@channels_group.command(name="update")
@handle_cli_errors
def channels_update(
    channel_id: int = typer.Argument(help="Integration ID to update"),
    name: str = typer.Option(..., "--name", help="New channel label"),
    channel: int = typer.Option(..., "--channel", help="New channel type ID"),
    events: str = typer.Option(..., "--events", help="Comma-separated event type IDs"),
    to: str = typer.Option(None, "--to", help="Email address"),
    url: str = typer.Option(None, "--url", help="Webhook URL"),
    active: bool = typer.Option(True, "--active/--no-active", help="Active state"),
) -> None:
    """Update an existing alert notification channel."""
    event_ids = _parse_events(events)
    creds, config = load_creds()
    asyncio.run(
        _execute_channels_update(
            creds=creds,
            channel_id=channel_id,
            name=name,
            channel=channel,
            events=event_ids,
            to=to,
            url=url,
            is_active=active,
        )
    )


async def _execute_channels_update(
    creds: dict,
    channel_id: int,
    name: str,
    channel: int,
    events: list[int],
    to: str | None,
    url: str | None,
    is_active: bool,
) -> None:
    """Update an existing integration channel."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_integration(
            channel_id,
            name=name,
            channel=channel,
            events=events,
            to=to,
            url=url,
            is_active=is_active,
        )
        console.print(f"Channel {channel_id} updated.")


# ------------------------------------------------------------------
# alerts channels delete
# ------------------------------------------------------------------


@channels_group.command(name="delete")
@handle_cli_errors
def channels_delete(
    channel_id: int = typer.Argument(help="Integration ID to delete"),
) -> None:
    """Delete an alert notification channel."""
    creds, config = load_creds()
    asyncio.run(_execute_channels_delete(creds=creds, channel_id=channel_id))


async def _execute_channels_delete(creds: dict, channel_id: int) -> None:
    """Delete an integration channel."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.delete_integration(channel_id)
        console.print(f"Channel {channel_id} deleted.")
