"""Manage Cloudways account team members.

Provides commands for listing, adding, updating, and removing
team members via the Cloudways API v2.

Usage::

    cloudways team list
    cloudways team add --email <email> --name <name> [--role <role>]
    cloudways team update <member-id> [--name <name>] [--role <role>]
    cloudways team remove <member-id>
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
)

team_group = typer.Typer(help="Manage Cloudways account team members.")


# ------------------------------------------------------------------
# team list
# ------------------------------------------------------------------


@team_group.command(name="list")
@handle_cli_errors
def team_list() -> None:
    """List all team members."""
    creds, config = load_creds()
    asyncio.run(_execute_team_list(creds=creds))


async def _execute_team_list(creds: dict) -> None:
    """Fetch and display all team members."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_members()
        members = result.get("contents", {}).get("members", {})
        for member in members.values():
            console.print(f"ID: {member.get('id')}")
            console.print(f"  Name: {member.get('name', 'N/A')}")
            console.print(f"  Email: {member.get('email', 'N/A')}")
            console.print(f"  Role: {member.get('role', 'N/A')}")
            console.print(f"  Status: {member.get('status', 'N/A')}")
            console.print(
                f"  Permissions (is_full): "
                f"{member.get('permissions', {}).get('is_full', False)}"
            )
            console.print()


# ------------------------------------------------------------------
# team add
# ------------------------------------------------------------------


@team_group.command(name="add")
@handle_cli_errors
def team_add(
    email: str = typer.Option(..., "--email", help="Email address for the new member"),
    name: str = typer.Option(..., "--name", help="Display name for the new member"),
    role: str = typer.Option("", "--role", help="Optional role string"),
) -> None:
    """Add a new team member."""
    creds, config = load_creds()
    asyncio.run(_execute_team_add(creds=creds, name=name, email=email, role=role))


async def _execute_team_add(creds: dict, name: str, email: str, role: str) -> None:
    """Add a new team member to the account."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.add_member(name=name, email=email, role=role)
        console.print("Success: Team member added.")


# ------------------------------------------------------------------
# team update
# ------------------------------------------------------------------


@team_group.command(name="update")
@handle_cli_errors
def team_update(
    member_id: int = typer.Argument(help="ID of the team member to update"),
    name: str = typer.Option("", "--name", help="New display name"),
    role: str = typer.Option("", "--role", help="New role string"),
) -> None:
    """Update an existing team member."""
    if not name and not role:
        console.print("At least one of --name or --role is required")
        raise typer.Exit(code=1)
    creds, config = load_creds()
    asyncio.run(
        _execute_team_update(creds=creds, member_id=member_id, name=name, role=role)
    )


async def _execute_team_update(
    creds: dict, member_id: int, name: str, role: str
) -> None:
    """Update an existing team member."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.update_member(member_id, name=name, role=role)
        console.print("Success: Team member updated.")


# ------------------------------------------------------------------
# team remove
# ------------------------------------------------------------------


@team_group.command(name="remove")
@handle_cli_errors
def team_remove(
    member_id: int = typer.Argument(help="ID of the team member to remove"),
) -> None:
    """Remove a team member from the account."""
    creds, config = load_creds()
    asyncio.run(_execute_team_remove(creds=creds, member_id=member_id))


async def _execute_team_remove(creds: dict, member_id: int) -> None:
    """Remove a team member from the account."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.delete_member(member_id)
        console.print("Success: Team member removed.")
