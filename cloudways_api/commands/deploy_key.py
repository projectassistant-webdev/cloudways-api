"""Manage server-to-repo deploy keys for git operations.

Provides generate, show, register, and setup commands for managing
SSH deploy keypairs on Cloudways servers and registering them as
Bitbucket Access Keys.

Usage::

    cloudways deploy-key generate production
    cloudways deploy-key show production
    cloudways deploy-key register production --label "my-key"
    cloudways deploy-key setup production
"""

import asyncio

import typer

from cloudways_api.bitbucket import (
    BitbucketClient,
    detect_bitbucket_repo,
    load_bitbucket_config,
)
from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)
from cloudways_api.exceptions import BitbucketError

deploy_key_group = typer.Typer(help="Manage server-to-repo deploy keys.")


@deploy_key_group.command(name="generate")
@handle_cli_errors
def deploy_key_generate(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """Generate an SSH keypair on the Cloudways server."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_generate(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            environment=environment,
        )
    )


async def _execute_generate(
    creds: dict,
    server_id: int,
    app_id: int | str,
    environment: str,
) -> None:
    """Execute deploy-key generate workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.generate_deploy_key(server_id=server_id, app_id=app_id)
        console.print(f"Deploy key generated for {environment}")


@deploy_key_group.command(name="show")
@handle_cli_errors
def deploy_key_show(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """Display the server's current public deploy key."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_show(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
        )
    )


async def _execute_show(
    creds: dict,
    server_id: int,
    app_id: int | str,
) -> None:
    """Execute deploy-key show workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.get_deploy_key(server_id=server_id, app_id=app_id)
        public_key = result.get("public_key", "")

        if not public_key:
            err_console.print(
                "[bold red]Error:[/bold red] No deploy key found. "
                "Generate one with: cloudways deploy-key generate <environment>"
            )
            raise typer.Exit(code=1)

        console.print(public_key)


@deploy_key_group.command(name="register")
@handle_cli_errors
def deploy_key_register(
    environment: str = typer.Argument(help="Environment name from project config"),
    label: str | None = typer.Option(
        None, "--label", help="Label for the Bitbucket Access Key"
    ),
) -> None:
    """Register the server's deploy key in Bitbucket."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    # Default label
    if label is None:
        label = f"cloudways-{environment}"

    asyncio.run(
        _execute_register(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            label=label,
        )
    )


async def _execute_register(
    creds: dict,
    server_id: int,
    app_id: int | str,
    label: str,
) -> None:
    """Execute deploy-key register workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Get server's public key
        result = await client.get_deploy_key(server_id=server_id, app_id=app_id)
        public_key = result.get("public_key", "")

        if not public_key:
            err_console.print(
                "[bold red]Error:[/bold red] No deploy key found on server. "
                "Generate one first with: cloudways deploy-key generate <environment>"
            )
            raise typer.Exit(code=1)

    # Detect workspace and repo
    workspace, repo_slug = _resolve_bitbucket_repo()

    # Register in Bitbucket
    bb_client = BitbucketClient(workspace=workspace, repo_slug=repo_slug)
    await bb_client.add_deploy_key(key=public_key, label=label)

    console.print(f"Deploy key registered in Bitbucket repo '{workspace}/{repo_slug}'")


def _resolve_bitbucket_repo() -> tuple[str, str]:
    """Resolve Bitbucket workspace and repo from git remote or config.

    Tries git remote detection first, then falls back to project config.

    Returns:
        Tuple of (workspace, repo_slug).

    Raises:
        BitbucketError: If neither detection method succeeds.
    """
    try:
        return detect_bitbucket_repo()
    except BitbucketError:
        pass

    # Fallback to project config
    bb_config = load_bitbucket_config()
    workspace = bb_config.get("workspace")
    repo_slug = bb_config.get("repo_slug")

    if workspace and repo_slug:
        return workspace, repo_slug

    raise BitbucketError(
        "Cannot detect Bitbucket repository. "
        "Set bitbucket.workspace and bitbucket.repo_slug "
        "in .prism/project-config.yml."
    )


@deploy_key_group.command(name="setup")
@handle_cli_errors
def deploy_key_setup(
    environment: str = typer.Argument(help="Environment name from project config"),
    label: str | None = typer.Option(
        None, "--label", help="Label for the Bitbucket Access Key"
    ),
) -> None:
    """Generate deploy key and register in Bitbucket (composite)."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    # Default label
    if label is None:
        label = f"cloudways-{environment}"

    asyncio.run(
        _execute_setup(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            environment=environment,
            label=label,
        )
    )


async def _execute_setup(
    creds: dict,
    server_id: int,
    app_id: int | str,
    environment: str,
    label: str,
) -> None:
    """Execute deploy-key setup composite workflow.

    1. Generate keypair on server
    2. Get public key
    3. Register in Bitbucket
    """
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # Step 1: Generate keypair
        console.print(f"Generating deploy key for {environment}...")
        await client.generate_deploy_key(server_id=server_id, app_id=app_id)
        console.print(f"Deploy key generated for {environment}")

        # Step 2: Get public key
        result = await client.get_deploy_key(server_id=server_id, app_id=app_id)
        public_key = result.get("public_key", "")

        if not public_key:
            err_console.print(
                "[bold red]Error:[/bold red] Deploy key generation "
                "succeeded but no public key was returned."
            )
            raise typer.Exit(code=1)

    # Step 3: Register in Bitbucket
    workspace, repo_slug = _resolve_bitbucket_repo()
    bb_client = BitbucketClient(workspace=workspace, repo_slug=repo_slug)
    await bb_client.add_deploy_key(key=public_key, label=label)

    console.print(f"Deploy key registered in Bitbucket repo '{workspace}/{repo_slug}'")
