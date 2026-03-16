"""Composite project setup command for Cloudways.

Orchestrates provisioning (prod + staging), SSH user creation,
SSH key deployment, services.sh deployment, and permissions reset
into a single command for streamlined new project setup.

Usage::

    cloudways setup-project --ssh-username myuser
    cloudways setup-project --ssh-username myuser --prod-env production --staging-env staging
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
)
from cloudways_api.commands.reset_permissions import _reset_permissions_async
from cloudways_api.commands.services import _services_deploy_async
from cloudways_api.commands.ssh_key import _execute_ssh_key_add, _validate_ssh_key
from cloudways_api.commands.ssh_user import _execute_ssh_user_create
from cloudways_api.config import ConfigError


# Step labels for summary output
_STEP_PROVISION_PROD = "Provision production app"
_STEP_PROVISION_STAGING = "Provision staging app"
_STEP_SSH_USER_PROD = "Create SSH user (prod)"
_STEP_SSH_USER_STAGING = "Create SSH user (staging)"
_STEP_KEY_MY_PROD = "Add my SSH key (prod)"
_STEP_KEY_MY_STAGING = "Add my SSH key (staging)"
_STEP_KEY_PIPELINE_PROD = "Add pipeline SSH key (prod)"
_STEP_KEY_PIPELINE_STAGING = "Add pipeline SSH key (staging)"
_STEP_SERVICES_PROD = "Deploy services.sh (prod)"
_STEP_SERVICES_STAGING = "Deploy services.sh (staging)"
_STEP_PERMISSIONS_PROD = "Reset permissions (prod)"
_STEP_PERMISSIONS_STAGING = "Reset permissions (staging)"


# ---------------------------------------------------------------------------
# _run_* helper functions (one per step, mockable at module level)
# ---------------------------------------------------------------------------


async def _run_provision_prod(config: dict, creds: dict, server_id: int) -> str:
    """Provision production app. Returns prod_app_id. FATAL step.

    Args:
        config: Full hosting config dict.
        creds: API credentials dict.
        server_id: Cloudways server ID.

    Returns:
        The app_id of the newly provisioned production app as a string.
    """
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.create_app(
            server_id=server_id,
            application="wordpress",
            app_version="default",
            app_label="production",
            project_name="Default",
        )
        op_id = result.get("operation_id")
        if op_id:
            await client.wait_for_operation(op_id, max_wait=300)
        return str(result["app"]["id"])


async def _run_provision_staging(
    config: dict,
    creds: dict,
    server_id: int,
    prod_app_id: str,
    staging_label: str,
) -> str:
    """Provision staging app (clone from prod). Returns staging_app_id. FATAL step.

    Args:
        config: Full hosting config dict.
        creds: API credentials dict.
        server_id: Cloudways server ID.
        prod_app_id: The production app_id to clone from.
        staging_label: Human-readable label for the staging app.

    Returns:
        The app_id of the newly provisioned staging app as a string.
    """
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.create_staging_app(
            server_id=server_id,
            app_id=prod_app_id,
            app_label=staging_label,
            project_name="Default",
        )
        op_id = result.get("operation_id")
        if op_id:
            await client.wait_for_operation(op_id, max_wait=300)
        return str(result["app"]["id"])


async def _run_ssh_user_create_prod(
    creds: dict, server_id: int, app_id: str, username: str
) -> None:
    """Create SSH user on production app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Production app ID.
        username: SSH username to create.
    """
    await _execute_ssh_user_create(
        creds=creds, server_id=server_id, app_id=app_id, username=username
    )


async def _run_ssh_user_create_staging(
    creds: dict, server_id: int, app_id: str, username: str
) -> None:
    """Create SSH user on staging app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Staging app ID.
        username: SSH username to create.
    """
    await _execute_ssh_user_create(
        creds=creds, server_id=server_id, app_id=app_id, username=username
    )


async def _run_ssh_key_add_my_prod(
    creds: dict,
    server_id: int,
    app_id: str,
    username: str,
    public_key: str,
) -> None:
    """Add personal SSH key to production app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Production app ID.
        username: SSH username.
        public_key: Public key content.
    """
    await _execute_ssh_key_add(
        creds=creds,
        server_id=server_id,
        app_id=app_id,
        username=username,
        public_key=public_key,
        key_name="my key",
    )


async def _run_ssh_key_add_my_staging(
    creds: dict,
    server_id: int,
    app_id: str,
    username: str,
    public_key: str,
) -> None:
    """Add personal SSH key to staging app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Staging app ID.
        username: SSH username.
        public_key: Public key content.
    """
    await _execute_ssh_key_add(
        creds=creds,
        server_id=server_id,
        app_id=app_id,
        username=username,
        public_key=public_key,
        key_name="my key",
    )


async def _run_ssh_key_add_pipeline_prod(
    creds: dict,
    server_id: int,
    app_id: str,
    username: str,
    public_key: str,
) -> None:
    """Add pipeline SSH key to production app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Production app ID.
        username: SSH username.
        public_key: Public key content.
    """
    await _execute_ssh_key_add(
        creds=creds,
        server_id=server_id,
        app_id=app_id,
        username=username,
        public_key=public_key,
        key_name="pipeline key",
    )


async def _run_ssh_key_add_pipeline_staging(
    creds: dict,
    server_id: int,
    app_id: str,
    username: str,
    public_key: str,
) -> None:
    """Add pipeline SSH key to staging app.

    Args:
        creds: API credentials dict.
        server_id: Cloudways server ID.
        app_id: Staging app ID.
        username: SSH username.
        public_key: Public key content.
    """
    await _execute_ssh_key_add(
        creds=creds,
        server_id=server_id,
        app_id=app_id,
        username=username,
        public_key=public_key,
        key_name="pipeline key",
    )


async def _run_services_deploy_prod(prod_env: str) -> None:
    """Deploy services.sh to production.

    Args:
        prod_env: Production environment name.
    """
    await _services_deploy_async(environment=prod_env, template_override=None)


async def _run_services_deploy_staging(staging_env: str) -> None:
    """Deploy services.sh to staging.

    Args:
        staging_env: Staging environment name.
    """
    await _services_deploy_async(environment=staging_env, template_override=None)


async def _run_reset_permissions_prod(prod_env: str) -> None:
    """Reset permissions on production.

    Args:
        prod_env: Production environment name.
    """
    await _reset_permissions_async(environment=prod_env)


async def _run_reset_permissions_staging(staging_env: str) -> None:
    """Reset permissions on staging.

    Args:
        staging_env: Staging environment name.
    """
    await _reset_permissions_async(environment=staging_env)


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@handle_cli_errors
def setup_project(
    prod_env: str = typer.Option(
        "production", "--prod-env", help="Production environment name"
    ),
    staging_env: str = typer.Option(
        "staging", "--staging-env", help="Staging environment name"
    ),
    ssh_username: str = typer.Option(
        ..., "--ssh-username", help="SSH username to create on both environments"
    ),
    staging_ssh_username: str | None = typer.Option(
        None,
        "--staging-ssh-username",
        help="SSH username for staging (default: {ssh_username}-stg). "
        "Useful on shared servers where usernames must be unique.",
    ),
    my_key_file: str = typer.Option(
        "~/.ssh/id_ed25519.pub",
        "--my-key-file",
        help="Path to personal SSH public key file",
    ),
    pipeline_key_file: str = typer.Option(
        "~/.ssh/id_ed25519_pipeline.pub",
        "--pipeline-key-file",
        help="Path to pipeline SSH public key file",
    ),
) -> None:
    """Full project setup: provision, SSH users, SSH keys, services.sh, permissions."""
    # Preflight: validate SSH key files exist
    for label, path in [
        ("--my-key-file", my_key_file),
        ("--pipeline-key-file", pipeline_key_file),
    ]:
        if not Path(path).expanduser().is_file():
            raise ConfigError(
                f"{label} not found: {path}. "
                "Ensure the public key file exists before running setup-project."
            )

    creds, config = load_creds()
    server_id = int(config["server"]["id"])

    # Read key file contents and validate format
    my_key_content = Path(my_key_file).expanduser().read_text().strip()
    pipeline_key_content = Path(pipeline_key_file).expanduser().read_text().strip()

    for label, content in [
        ("--my-key-file", my_key_content),
        ("--pipeline-key-file", pipeline_key_content),
    ]:
        if not _validate_ssh_key(content):
            raise ConfigError(
                f"{label} does not contain a valid SSH public key. "
                "Expected a key starting with ssh-rsa, ssh-ed25519, or ecdsa-sha2-*."
            )

    # Default staging username to {ssh_username}-stg if not provided
    effective_staging_ssh_username = staging_ssh_username or f"{ssh_username}-stg"

    asyncio.run(
        _execute_setup_project(
            config=config,
            creds=creds,
            server_id=server_id,
            prod_env=prod_env,
            staging_env=staging_env,
            ssh_username=ssh_username,
            staging_ssh_username=effective_staging_ssh_username,
            my_key_content=my_key_content,
            pipeline_key_content=pipeline_key_content,
        )
    )


async def _execute_setup_project(
    config: dict,
    creds: dict,
    server_id: int,
    prod_env: str,
    staging_env: str,
    ssh_username: str,
    my_key_content: str,
    pipeline_key_content: str,
    staging_ssh_username: str | None = None,
) -> None:
    """Execute the full setup-project workflow.

    Args:
        config: Full hosting config dict.
        creds: API credentials dict.
        server_id: Cloudways server ID.
        prod_env: Production environment name.
        staging_env: Staging environment name.
        ssh_username: SSH username to create on production.
        my_key_content: Personal SSH public key content.
        pipeline_key_content: Pipeline SSH public key content.
        staging_ssh_username: SSH username for staging. Defaults to
            ``{ssh_username}-stg`` when ``None``.
    """
    if staging_ssh_username is None:
        staging_ssh_username = f"{ssh_username}-stg"
    results: dict[str, str] = {}

    console.print()
    console.print("[bold]Setting up project...[/bold]")
    console.print()

    # ------------------------------------------------------------------
    # Step 1: Provision production app (FATAL)
    # ------------------------------------------------------------------
    try:
        prod_app_id = await _run_provision_prod(config, creds, server_id)
        results[_STEP_PROVISION_PROD] = "OK"
    except Exception as exc:
        results[_STEP_PROVISION_PROD] = "FAIL"
        _print_summary(results)
        err_console.print(
            f"\n[bold red]Error:[/bold red] Step 1 ({_STEP_PROVISION_PROD}) "
            f"failed: {exc}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 2: Provision staging app (FATAL)
    # ------------------------------------------------------------------
    staging_label = f"{staging_env}"
    try:
        staging_app_id = await _run_provision_staging(
            config, creds, server_id, prod_app_id, staging_label
        )
        results[_STEP_PROVISION_STAGING] = "OK"
    except Exception as exc:
        results[_STEP_PROVISION_STAGING] = "FAIL"
        _print_summary(results)
        err_console.print(
            f"\n[bold red]Error:[/bold red] Step 2 ({_STEP_PROVISION_STAGING}) "
            f"failed: {exc}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Steps 3-12: Non-fatal (catch, log, continue)
    # ------------------------------------------------------------------
    non_fatal_steps: list[tuple[str, object]] = [
        (
            f"{_STEP_SSH_USER_PROD} [{ssh_username}]",
            _run_ssh_user_create_prod(creds, server_id, prod_app_id, ssh_username),
        ),
        (
            f"{_STEP_SSH_USER_STAGING} [{staging_ssh_username}]",
            _run_ssh_user_create_staging(
                creds, server_id, staging_app_id, staging_ssh_username
            ),
        ),
        (
            f"{_STEP_KEY_MY_PROD} [{ssh_username}]",
            _run_ssh_key_add_my_prod(
                creds, server_id, prod_app_id, ssh_username, my_key_content
            ),
        ),
        (
            f"{_STEP_KEY_MY_STAGING} [{staging_ssh_username}]",
            _run_ssh_key_add_my_staging(
                creds, server_id, staging_app_id, staging_ssh_username, my_key_content
            ),
        ),
        (
            f"{_STEP_KEY_PIPELINE_PROD} [{ssh_username}]",
            _run_ssh_key_add_pipeline_prod(
                creds, server_id, prod_app_id, ssh_username, pipeline_key_content
            ),
        ),
        (
            f"{_STEP_KEY_PIPELINE_STAGING} [{staging_ssh_username}]",
            _run_ssh_key_add_pipeline_staging(
                creds,
                server_id,
                staging_app_id,
                staging_ssh_username,
                pipeline_key_content,
            ),
        ),
        (
            _STEP_SERVICES_PROD,
            _run_services_deploy_prod(prod_env),
        ),
        (
            _STEP_SERVICES_STAGING,
            _run_services_deploy_staging(staging_env),
        ),
        (
            _STEP_PERMISSIONS_PROD,
            _run_reset_permissions_prod(prod_env),
        ),
        (
            _STEP_PERMISSIONS_STAGING,
            _run_reset_permissions_staging(staging_env),
        ),
    ]

    for step_name, coro in non_fatal_steps:
        try:
            await coro
            results[step_name] = "OK"
        except Exception as exc:
            err_console.print(
                f"[bold yellow]Warning:[/bold yellow] {step_name} failed: {exc}"
            )
            results[step_name] = f"FAIL ({exc})"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _print_summary(results)

    has_failure = any(v.startswith("FAIL") for v in results.values())
    if has_failure:
        raise typer.Exit(code=1)


def _print_summary(results: dict[str, str]) -> None:
    """Print the setup summary with step statuses.

    Args:
        results: Dict mapping step name to status string.
    """
    console.print()
    console.print("[bold]Setup Summary:[/bold]")
    for step, status in results.items():
        if status == "OK":
            console.print(f"  [green]OK[/green]     {step}")
        else:
            console.print(f"  [red]FAIL[/red]   {step}")

    all_ok = all(v == "OK" for v in results.values())
    console.print()
    if all_ok:
        console.print(
            "  [bold green]Project setup complete.[/bold green] All steps succeeded."
        )
    else:
        console.print(
            "  [bold yellow]Setup incomplete.[/bold yellow] Address the issues above."
        )
    console.print()
