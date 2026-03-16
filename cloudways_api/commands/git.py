"""Manage git deployment operations on Cloudways applications.

Provides clone, pull, branches, and history commands for
managing git-based code deployments via the Cloudways API v2.

Usage::

    cloudways git clone <env> --repo <url> --branch <name>
    cloudways git pull <env> --branch <name> [--wait] [--timeout SECS]
    cloudways git branches <env> --repo <url>
    cloudways git history <env>
"""

import asyncio

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

git_group = typer.Typer(help="Git deployment operations.")


# ------------------------------------------------------------------
# git clone
# ------------------------------------------------------------------


@git_group.command(name="clone")
@handle_cli_errors
def git_clone_cmd(
    environment: str = typer.Argument(help="Environment name from project config"),
    repo: str = typer.Option(..., "--repo", help="Git repository URL"),
    branch: str = typer.Option(..., "--branch", help="Branch name to clone"),
) -> None:
    """Clone a git repository to the application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_git_clone(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            git_url=repo,
            branch_name=branch,
        )
    )


async def _execute_git_clone(
    creds: dict,
    server_id: int,
    app_id: int | str,
    git_url: str,
    branch_name: str,
) -> None:
    """Execute git clone workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.git_clone(
            server_id=server_id,
            app_id=app_id,
            git_url=git_url,
            branch_name=branch_name,
        )
        operation_id = result.get("operation_id")
        console.print(f"Git clone initiated. Operation ID: {operation_id}")


# ------------------------------------------------------------------
# git pull
# ------------------------------------------------------------------


@git_group.command(name="pull")
@handle_cli_errors
def git_pull_cmd(
    environment: str = typer.Argument(help="Environment name from project config"),
    branch: str = typer.Option(..., "--branch", help="Branch name to pull"),
    wait: bool = typer.Option(False, "--wait", help="Wait for pull to complete"),
    timeout: int = typer.Option(300, "--timeout", help="Max wait time (seconds)"),
) -> None:
    """Pull latest changes from the git repository."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_git_pull(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            branch_name=branch,
            wait=wait,
            timeout=timeout,
        )
    )


async def _execute_git_pull(
    creds: dict,
    server_id: int,
    app_id: int | str,
    branch_name: str,
    wait: bool,
    timeout: int,
) -> None:
    """Execute git pull workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.git_pull(
            server_id=server_id,
            app_id=app_id,
            branch_name=branch_name,
        )
        operation_id = result.get("operation_id")
        if not wait:
            console.print(f"Git pull initiated. Operation ID: {operation_id}")
            return
        with console.status(
            "[bold green]Waiting for git pull to complete...[/bold green]"
        ):
            await client.wait_for_operation(operation_id, max_wait=timeout)
        console.print("Git pull complete.")


# ------------------------------------------------------------------
# git branches
# ------------------------------------------------------------------


@git_group.command(name="branches")
@handle_cli_errors
def git_branches_cmd(
    environment: str = typer.Argument(help="Environment name from project config"),
    repo: str = typer.Option(..., "--repo", help="Git repository URL"),
) -> None:
    """List available branches for a git repository."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_git_branches(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            git_url=repo,
        )
    )


async def _execute_git_branches(
    creds: dict,
    server_id: int,
    app_id: int | str,
    git_url: str,
) -> None:
    """Execute git branches listing workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.git_branch_names(
            server_id=server_id,
            app_id=app_id,
            git_url=git_url,
        )
        branches = result.get("branches", [])
        if not branches:
            console.print("No branches found.")
            return
        for branch in branches:
            console.print(branch)


# ------------------------------------------------------------------
# git history
# ------------------------------------------------------------------


@git_group.command(name="history")
@handle_cli_errors
def git_history_cmd(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """View git deployment history for the application."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_git_history(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
        )
    )


async def _execute_git_history(
    creds: dict,
    server_id: int,
    app_id: int | str,
) -> None:
    """Execute git history listing workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.git_history(
            server_id=server_id,
            app_id=app_id,
        )
        logs = result.get("logs", [])
        if not logs:
            console.print("No deployment history found.")
            return
        for entry in logs:
            console.print(f"{entry['branch_name']} - {entry['datetime']}")
