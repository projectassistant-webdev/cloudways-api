"""Composite ssh-setup command for one-shot deployment SSH setup.

Orchestrates SSH user creation, SSH key addition, deploy key generation,
and Bitbucket Access Key registration in a single command.

Usage::

    cloudways ssh-setup production --username bitbucket --key-file ~/.ssh/id_ed25519.pub
    cloudways ssh-setup production --username bitbucket --key-file key.pub --key-name "my-key"
    cloudways ssh-setup production --username bitbucket --key-file key.pub --skip-deploy-key
"""

import asyncio
import secrets
from pathlib import Path

import typer

from cloudways_api.bitbucket import BitbucketClient, detect_bitbucket_repo
from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)
from cloudways_api.commands.ssh_key import _validate_ssh_key


@handle_cli_errors
def ssh_setup(
    environment: str = typer.Argument(help="Environment name from project config"),
    username: str = typer.Option(..., "--username", help="SSH username to create/use"),
    key_file: str = typer.Option(
        ..., "--key-file", help="Path to personal SSH public key file"
    ),
    key_name: str | None = typer.Option(
        None,
        "--key-name",
        help="Label for the SSH key (default: <username>-<environment>)",
    ),
    skip_deploy_key: bool = typer.Option(
        False,
        "--skip-deploy-key",
        help="Skip deploy key generation and Bitbucket registration",
    ),
) -> None:
    """One-shot composite command for full deployment SSH setup.

    Creates SSH user (if needed), adds personal SSH key, generates
    deploy key on server, and registers it in Bitbucket.
    """
    # Validate key file exists
    key_path = Path(key_file).expanduser()
    if not key_path.is_file():
        err_console.print(f"[bold red]Error:[/bold red] Key file not found: {key_file}")
        raise typer.Exit(code=1)

    # Read and validate key format
    public_key = key_path.read_text().strip()
    if not _validate_ssh_key(public_key):
        err_console.print(
            "[bold red]Error:[/bold red] Invalid SSH public key format. "
            "Expected: ssh-rsa, ssh-ed25519, or ecdsa-sha2-*"
        )
        raise typer.Exit(code=1)

    # Load config
    creds, config = load_creds()
    env_config = validate_environment(config, environment)

    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    # Default key name
    if key_name is None:
        key_name = f"{username}-{environment}"

    asyncio.run(
        _execute_ssh_setup(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            environment=environment,
            username=username,
            public_key=public_key,
            key_name=key_name,
            skip_deploy_key=skip_deploy_key,
        )
    )


async def _execute_ssh_setup(
    creds: dict,
    server_id: int,
    app_id: int | str,
    environment: str,
    username: str,
    public_key: str,
    key_name: str,
    skip_deploy_key: bool,
) -> None:
    """Execute the composite ssh-setup workflow.

    Steps:
    1. Check if user exists; create if not
    2. Add personal SSH key to user
    3. Generate deploy key on server (unless --skip-deploy-key)
    4. Get server public key (unless --skip-deploy-key)
    5. Register in Bitbucket (unless --skip-deploy-key)
    6. Display summary
    """
    summary: list[str] = []

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # --- Step 1: SSH User ---
        console.print(f"[bold]Step 1:[/bold] Checking SSH user '{username}'...")
        existing = await client.get_app_credentials(server_id, app_id)
        cred_id = None
        for cred in existing:
            if cred.get("sys_user") == username:
                cred_id = cred["id"]
                break

        if cred_id is not None:
            console.print(f"  User '{username}' already exists (cred_id: {cred_id})")
            summary.append(f"SSH user '{username}': already exists (found)")
        else:
            password = secrets.token_urlsafe(24)
            result = await client.create_app_credential(
                server_id=server_id,
                app_id=app_id,
                username=username,
                password=password,
            )
            cred_id = result.get("app_cred", {}).get("id")
            if cred_id is None:
                err_console.print(
                    "[bold red]Error:[/bold red] User creation succeeded "
                    "but no credential ID was returned."
                )
                raise typer.Exit(code=1)
            console.print(f"  Created SSH user '{username}' (cred_id: {cred_id})")
            console.print(f"  Password: {password}")
            summary.append(f"SSH user '{username}': created (cred_id: {cred_id})")

        # --- Step 2: SSH Key ---
        console.print(
            f"[bold]Step 2:[/bold] Adding SSH key '{key_name}' to user '{username}'..."
        )
        await client.add_ssh_key(
            server_id=server_id,
            app_creds_id=cred_id,
            key_name=key_name,
            public_key=public_key,
        )
        console.print(f"  SSH key '{key_name}' added to user '{username}'")
        summary.append(f"SSH key '{key_name}': added to user '{username}'")

        if skip_deploy_key:
            console.print(
                "[bold]Step 3:[/bold] Deploy key setup skipped (--skip-deploy-key)"
            )
            summary.append("Deploy key: skipped (--skip-deploy-key)")
        else:
            # --- Step 3: Generate deploy key ---
            console.print(
                f"[bold]Step 3:[/bold] Generating deploy key for {environment}..."
            )
            await client.generate_deploy_key(server_id=server_id, app_id=app_id)
            console.print(f"  Deploy key generated for {environment}")

            # --- Step 4: Get public key ---
            console.print("[bold]Step 4:[/bold] Retrieving server public key...")
            key_result = await client.get_deploy_key(server_id=server_id, app_id=app_id)
            server_public_key = key_result.get("public_key", "")
            if not server_public_key:
                err_console.print(
                    "[bold red]Error:[/bold red] Deploy key generation "
                    "succeeded but no public key was returned."
                )
                raise typer.Exit(code=1)
            console.print("  Server public key retrieved")

    # --- Step 5: Register in Bitbucket (outside CloudwaysClient context) ---
    if not skip_deploy_key:
        console.print("[bold]Step 5:[/bold] Registering deploy key in Bitbucket...")
        workspace, repo_slug = detect_bitbucket_repo()

        label = f"cloudways-{environment}"
        bb_client = BitbucketClient(workspace=workspace, repo_slug=repo_slug)
        await bb_client.add_deploy_key(key=server_public_key, label=label)
        console.print(
            f"  Deploy key registered in Bitbucket repo '{workspace}/{repo_slug}'"
        )
        summary.append(
            f"Deploy key: generated and registered in {workspace}/{repo_slug}"
        )

    # --- Summary ---
    console.print()
    console.print("[bold green]SSH Setup Complete[/bold green]")
    console.print()
    for item in summary:
        console.print(f"  {item}")
