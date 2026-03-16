"""Manage Cloudways Copilot subscription, billing, and Insights.

Provides commands for listing plans, subscribing, cancelling,
changing plans, viewing billing, managing server settings, and
accessing Copilot Insights data via the Cloudways API v2.

Usage::

    cloudways copilot plans
    cloudways copilot status
    cloudways copilot subscribe --plan-id <id>
    cloudways copilot cancel
    cloudways copilot change-plan --plan-id <id> [--touchpoint <value>]
    cloudways copilot billing [--billing-cycle YYYY-MM]
    cloudways copilot server-settings
    cloudways copilot enable-insights --server-id <id>
    cloudways copilot disable-insights --server-id <id>
    cloudways copilot insights
    cloudways copilot insight <alert-id>
"""

import asyncio
import re

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

copilot_group = typer.Typer(
    help="Manage Cloudways Copilot subscription, billing, and Insights."
)


# ------------------------------------------------------------------
# copilot plans
# ------------------------------------------------------------------


@copilot_group.command(name="plans")
@handle_cli_errors
def copilot_plans() -> None:
    """List available Copilot subscription plans."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_plans(creds=creds))


async def _execute_copilot_plans(creds: dict) -> None:
    """Fetch and display available Copilot plans."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_copilot_plans()
        for plan in result.get("data", []):
            console.print(f"ID: {plan.get('id')}")
            console.print(f"  Name: {plan.get('name', 'N/A')}")
            console.print(f"  Price: {plan.get('price', 'N/A')}")
            console.print()
        if result.get("pending_downgrade_request"):
            console.print("Note: Pending downgrade request exists.")


# ------------------------------------------------------------------
# copilot status
# ------------------------------------------------------------------


@copilot_group.command(name="status")
@handle_cli_errors
def copilot_status() -> None:
    """Show current Copilot subscription status."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_status(creds=creds))


async def _execute_copilot_status(creds: dict) -> None:
    """Fetch and display current Copilot subscription status."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_copilot_status()
        data = result.get("data", {})
        console.print(f"Plan: {data.get('plan_name', 'N/A')}")
        console.print(f"Status: {data.get('status', 'N/A')}")
        console.print(f"Expires: {data.get('expires_at', 'N/A')}")


# ------------------------------------------------------------------
# copilot subscribe
# ------------------------------------------------------------------


@copilot_group.command(name="subscribe")
@handle_cli_errors
def copilot_subscribe(
    plan_id: int = typer.Option(..., "--plan-id", help="Plan ID to subscribe to"),
) -> None:
    """Subscribe to a Copilot plan."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_subscribe(creds=creds, plan_id=plan_id))


async def _execute_copilot_subscribe(creds: dict, plan_id: int) -> None:
    """Subscribe to a Copilot plan."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.subscribe_copilot_plan(plan_id=plan_id)
        console.print("Success: Subscribed to Copilot plan.")


# ------------------------------------------------------------------
# copilot cancel
# ------------------------------------------------------------------


@copilot_group.command(name="cancel")
@handle_cli_errors
def copilot_cancel() -> None:
    """Cancel the current Copilot subscription."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_cancel(creds=creds))


async def _execute_copilot_cancel(creds: dict) -> None:
    """Cancel the current Copilot subscription."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.cancel_copilot_plan()
        console.print("Success: Copilot plan cancelled.")


# ------------------------------------------------------------------
# copilot change-plan
# ------------------------------------------------------------------


@copilot_group.command(name="change-plan")
@handle_cli_errors
def copilot_change_plan(
    plan_id: int = typer.Option(..., "--plan-id", help="New plan ID"),
    touchpoint: str = typer.Option(
        None, "--touchpoint", help="Optional analytics touchpoint"
    ),
) -> None:
    """Change the current Copilot subscription plan."""
    creds, config = load_creds()
    asyncio.run(
        _execute_copilot_change_plan(
            creds=creds, plan_id=plan_id, touchpoint=touchpoint
        )
    )


async def _execute_copilot_change_plan(
    creds: dict, plan_id: int, touchpoint: str | None
) -> None:
    """Change the current Copilot subscription plan."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.change_copilot_plan(plan_id=plan_id, touchpoint=touchpoint)
        console.print("Success: Copilot plan changed.")


# ------------------------------------------------------------------
# copilot billing
# ------------------------------------------------------------------


@copilot_group.command(name="billing")
@handle_cli_errors
def copilot_billing(
    billing_cycle: str = typer.Option(
        None,
        "--billing-cycle",
        help="Billing cycle in YYYY-MM format (e.g., 2026-01)",
    ),
) -> None:
    """Retrieve real-time Copilot billing data."""
    if billing_cycle is not None and not re.match(r"^\d{4}-\d{2}$", billing_cycle):
        console.print(
            "Error: --billing-cycle must be in YYYY-MM format (e.g., 2026-01)"
        )
        raise typer.Exit(code=1)
    creds, config = load_creds()
    asyncio.run(_execute_copilot_billing(creds=creds, billing_cycle=billing_cycle))


async def _execute_copilot_billing(creds: dict, billing_cycle: str | None) -> None:
    """Fetch and display Copilot billing data."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_copilot_billing(billing_cycle=billing_cycle)
        data = result.get("data", {})
        console.print(f"Cycle Start: {data.get('cycle_start', 'N/A')}")
        console.print(f"Cycle End: {data.get('cycle_end', 'N/A')}")
        console.print(f"Credits Used: {data.get('credits_used', 'N/A')}")


# ------------------------------------------------------------------
# copilot server-settings
# ------------------------------------------------------------------


@copilot_group.command(name="server-settings")
@handle_cli_errors
def copilot_server_settings() -> None:
    """Show Copilot server settings."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_server_settings(creds=creds))


async def _execute_copilot_server_settings(creds: dict) -> None:
    """Fetch and display Copilot server settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_copilot_server_settings()
        for server in result.get("data", []):
            console.print(f"Server ID: {server.get('server_id')}")
            console.print(f"  Insights Enabled: {server.get('insights_enabled')}")
            console.print()


# ------------------------------------------------------------------
# copilot enable-insights
# ------------------------------------------------------------------


@copilot_group.command(name="enable-insights")
@handle_cli_errors
def copilot_enable_insights(
    server_id: int = typer.Option(
        ..., "--server-id", help="Server ID to enable insights for"
    ),
) -> None:
    """Enable Copilot Insights for a server."""
    creds, config = load_creds()
    asyncio.run(
        _execute_update_copilot_server_settings(
            creds=creds, server_id=server_id, insights_enabled=True
        )
    )


# ------------------------------------------------------------------
# copilot disable-insights
# ------------------------------------------------------------------


@copilot_group.command(name="disable-insights")
@handle_cli_errors
def copilot_disable_insights(
    server_id: int = typer.Option(
        ..., "--server-id", help="Server ID to disable insights for"
    ),
) -> None:
    """Disable Copilot Insights for a server."""
    creds, config = load_creds()
    asyncio.run(
        _execute_update_copilot_server_settings(
            creds=creds, server_id=server_id, insights_enabled=False
        )
    )


async def _execute_update_copilot_server_settings(
    creds: dict, server_id: int, insights_enabled: bool
) -> None:
    """Update Copilot server settings."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_copilot_server_settings(
            server_id=server_id, insights_enabled=insights_enabled
        )
        state = "enabled" if insights_enabled else "disabled"
        console.print(f"Success: Insights {state} for server {server_id}.")


# ------------------------------------------------------------------
# copilot insights
# ------------------------------------------------------------------


@copilot_group.command(name="insights")
@handle_cli_errors
def copilot_insights() -> None:
    """List all Copilot Insights."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_insights(creds=creds))


async def _execute_copilot_insights(creds: dict) -> None:
    """Fetch and display all Copilot Insights."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_insights()
        for insight in result.get("insights", []):
            console.print(f"Alert ID: {insight.get('alert_id')}")
            console.print(f"  Type: {insight.get('type', 'N/A')}")
            console.print(f"  Severity: {insight.get('severity', 'N/A')}")
            console.print(f"  Subject: {insight.get('subject', 'N/A')}")
            console.print()


# ------------------------------------------------------------------
# copilot insight
# ------------------------------------------------------------------


@copilot_group.command(name="insight")
@handle_cli_errors
def copilot_insight(
    alert_id: int = typer.Argument(help="ID of the insight alert to retrieve"),
) -> None:
    """Retrieve detail for a specific Copilot Insight."""
    creds, config = load_creds()
    asyncio.run(_execute_copilot_insight(creds=creds, alert_id=alert_id))


async def _execute_copilot_insight(creds: dict, alert_id: int) -> None:
    """Fetch and display a specific Copilot Insight."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_insight(alert_id=alert_id)
        console.print(f"Alert ID: {result.get('alert_id')}")
        console.print(f"Server: {result.get('server_label', 'N/A')}")
        console.print(f"Type: {result.get('type', 'N/A')}")
        console.print(f"Subject: {result.get('subject', 'N/A')}")
        console.print(f"Status: {result.get('status', 'N/A')}")
        console.print(f"Fix Status: {result.get('fix_status', 'N/A')}")
        console.print(f"Severity: {result.get('severity', 'N/A')}")
        console.print(f"Description: {result.get('description', 'N/A')}")
