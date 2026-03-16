"""Composite first-deploy command for Bedrock on Cloudways.

Orchestrates env-generate, set-webroot, init-shared, and verify-setup
into a single command for streamlined first-time deployment setup.

Usage::

    cloudways setup-bedrock staging
    cloudways setup-bedrock production --dry-run
    cloudways setup-bedrock staging --with-cache-plugins
    cloudways setup-bedrock staging --webroot public_html/current/web
"""

import asyncio

import typer

from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.commands.app_webroot import BEDROCK_WEBROOT
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.credentials import load_credentials
from cloudways_api.ssh import run_ssh_command


# Step labels for summary output
_STEP_ENV_GENERATE = "Generate .env file"
_STEP_SET_WEBROOT = "Set application webroot"
_STEP_INIT_SHARED = "Create shared directories and linked files"
_STEP_VERIFY_SETUP = "Verify deployment readiness"


async def _env_exists_on_server(
    ssh_host: str,
    ssh_user: str,
) -> bool:
    """Check if .env already exists on the remote server.

    Args:
        ssh_host: SSH host address.
        ssh_user: SSH username.

    Returns:
        True if ~/public_html/shared/.env exists, False otherwise.
    """
    _, _, rc = await run_ssh_command(
        ssh_host,
        ssh_user,
        "test -f ~/public_html/shared/.env",
        raise_on_error=False,
    )
    return rc == 0


async def _run_env_generate(
    config: dict,
    env_config: dict,
    environment: str,
) -> None:
    """Run the env-generate step programmatically.

    Imports and calls the async execution function from env_generate
    to avoid subprocess invocation.

    Args:
        config: Full hosting config dict.
        env_config: Environment-specific config.
        environment: Environment name.
    """
    from cloudways_api.commands.env_generate import _execute_env_generate

    await _execute_env_generate(
        config=config,
        env_config=env_config,
        environment=environment,
        output=None,
        stdout_flag=False,
        no_salts=False,
        db_prefix="wp_",
    )


async def _run_set_webroot(
    config: dict,
    env_config: dict,
    environment: str,
    webroot: str,
) -> None:
    """Run the set-webroot step programmatically.

    Args:
        config: Full hosting config dict.
        env_config: Environment-specific config.
        environment: Environment name.
        webroot: Webroot path to set.
    """
    from cloudways_api.commands.app_webroot import _execute_set_webroot

    account_name = config["account"]
    creds = load_credentials(account_name)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    await _execute_set_webroot(
        creds=creds,
        server_id=server_id,
        app_id=app_id,
        webroot=webroot,
        environment=environment,
    )


async def _run_init_shared(
    config: dict,
    env_config: dict,
    environment: str,
    with_cache_plugins: bool = False,
    force: bool = False,
) -> None:
    """Run the init-shared step programmatically.

    Args:
        config: Full hosting config dict.
        env_config: Environment-specific config.
        environment: Environment name.
        with_cache_plugins: Whether to create cache plugin placeholders.
        force: Whether to overwrite existing files.
    """
    from cloudways_api.commands.init_shared import _execute_init_shared

    await _execute_init_shared(
        config=config,
        env_config=env_config,
        environment=environment,
        dry_run=False,
        with_cache_plugins=with_cache_plugins,
        empty_htaccess=False,
        force=force,
    )


async def _run_verify_setup(
    config: dict,
    env_config: dict,
    environment: str,
) -> tuple[int, int]:
    """Run the verify-setup step programmatically.

    Args:
        config: Full hosting config dict.
        env_config: Environment-specific config.
        environment: Environment name.

    Returns:
        Tuple of (passed, total) check counts.
    """
    from cloudways_api.commands.verify_setup import _execute_verify_setup

    return await _execute_verify_setup(
        config=config,
        env_config=env_config,
        environment=environment,
        verbose=False,
    )


@handle_cli_errors
def setup_bedrock(
    environment: str = typer.Argument(
        help="Environment name from project config (e.g., staging, production)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without executing"
    ),
    with_cache_plugins: bool = typer.Option(
        False, "--with-cache-plugins", help="Include cache plugin placeholder files"
    ),
    webroot: str = typer.Option(
        BEDROCK_WEBROOT,
        "--webroot",
        help="Webroot path for set-webroot step",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing linked files in init-shared"
    ),
) -> None:
    """First-time Bedrock deployment setup (env-generate + set-webroot + init-shared + verify-setup)."""
    config = load_config()
    env_config = validate_environment(config, environment)

    if dry_run:
        _print_dry_run(environment, webroot, with_cache_plugins)
        return

    validate_ssh_config(config)

    asyncio.run(
        _execute_setup_bedrock(
            config=config,
            env_config=env_config,
            environment=environment,
            webroot=webroot,
            with_cache_plugins=with_cache_plugins,
            force=force,
        )
    )


async def _execute_setup_bedrock(
    config: dict,
    env_config: dict,
    environment: str,
    webroot: str,
    with_cache_plugins: bool,
    force: bool,
) -> None:
    """Execute the full setup-bedrock workflow."""
    server_config = config["server"]
    ssh_host = server_config["ssh_host"]
    ssh_user = env_config.get("ssh_user", server_config["ssh_user"])

    results: dict[str, str] = {}

    console.print()
    console.print(f"[bold]Setting up Bedrock for {environment}...[/bold]")
    console.print()

    # ------------------------------------------------------------------
    # Step 1: env-generate (skip if .env already exists)
    # ------------------------------------------------------------------
    env_exists = await _env_exists_on_server(ssh_host, ssh_user)
    if env_exists:
        results[_STEP_ENV_GENERATE] = "SKIPPED"
        console.print(
            f"  [yellow]SKIP[/yellow]   {_STEP_ENV_GENERATE} (.env already exists)"
        )
    else:
        try:
            await _run_env_generate(config, env_config, environment)
            results[_STEP_ENV_GENERATE] = "OK"
        except Exception as exc:
            results[_STEP_ENV_GENERATE] = "FAIL"
            _print_summary(results, environment)
            err_console.print(
                f"\n[bold red]Error:[/bold red] Step 1 ({_STEP_ENV_GENERATE}) "
                f"failed: {exc}"
            )
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 2: set-webroot
    # ------------------------------------------------------------------
    try:
        await _run_set_webroot(config, env_config, environment, webroot)
        results[_STEP_SET_WEBROOT] = "OK"
    except Exception as exc:
        results[_STEP_SET_WEBROOT] = "FAIL"
        _print_summary(results, environment)
        err_console.print(
            f"\n[bold red]Error:[/bold red] Step 2 ({_STEP_SET_WEBROOT}) failed: {exc}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 3: init-shared
    # ------------------------------------------------------------------
    try:
        await _run_init_shared(
            config,
            env_config,
            environment,
            with_cache_plugins=with_cache_plugins,
            force=force,
        )
        results[_STEP_INIT_SHARED] = "OK"
    except Exception as exc:
        results[_STEP_INIT_SHARED] = "FAIL"
        _print_summary(results, environment)
        err_console.print(
            f"\n[bold red]Error:[/bold red] Step 3 ({_STEP_INIT_SHARED}) failed: {exc}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Step 4: verify-setup (reports failures but does not stop summary)
    # ------------------------------------------------------------------
    try:
        passed, total = await _run_verify_setup(config, env_config, environment)
        if passed == total:
            results[_STEP_VERIFY_SETUP] = "OK"
        else:
            results[_STEP_VERIFY_SETUP] = f"WARN ({passed}/{total})"
    except Exception as exc:
        results[_STEP_VERIFY_SETUP] = f"FAIL ({exc})"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _print_summary(results, environment)

    # Exit code: 1 if any step failed or verify had warnings
    has_failure = any(
        v.startswith("FAIL") or v.startswith("WARN") for v in results.values()
    )
    if has_failure:
        raise typer.Exit(code=1)


def _print_summary(results: dict[str, str], environment: str) -> None:
    """Print the setup summary with step statuses.

    Args:
        results: Dict mapping step name to status string.
        environment: Environment name.
    """
    console.print()
    console.print("[bold]Setup Summary:[/bold]")
    for step, status in results.items():
        if status == "OK":
            console.print(f"  [green]OK[/green]     {step}")
        elif status == "SKIPPED":
            console.print(f"  [yellow]SKIP[/yellow]   {step}")
        elif status.startswith("WARN"):
            detail = status.replace("WARN ", "").strip("()")
            console.print(f"  [yellow]WARN[/yellow]   {step} ({detail})")
        else:
            console.print(f"  [red]FAIL[/red]   {step}")

    # Ready to deploy message (only if no failures/warnings)
    all_ok = all(v in ("OK", "SKIPPED") for v in results.values())
    console.print()
    if all_ok:
        console.print(
            f"  [bold green]Ready to deploy:[/bold green] "
            f"bundle exec cap {environment} deploy"
        )
    else:
        console.print(
            "  [bold yellow]Setup incomplete.[/bold yellow] "
            "Address the issues above before deploying."
        )
    console.print()


def _print_dry_run(
    environment: str,
    webroot: str,
    with_cache_plugins: bool,
) -> None:
    """Print what setup-bedrock would do without executing.

    Args:
        environment: Environment name.
        webroot: Webroot path.
        with_cache_plugins: Whether cache plugins flag is set.
    """
    console.print()
    console.print("[bold yellow]Dry Run[/bold yellow] - No changes will be made")
    console.print()
    console.print(f"[bold]Planned steps for {environment}:[/bold]")
    console.print()
    console.print(f"  Step 1: {_STEP_ENV_GENERATE}")
    console.print("          -> Fetch DB creds, generate salts, upload .env")
    console.print("          -> Skip if .env already exists on server")
    console.print()
    console.print(f"  Step 2: {_STEP_SET_WEBROOT}")
    console.print(f"          -> Set webroot to '{webroot}'")
    console.print()
    console.print(f"  Step 3: {_STEP_INIT_SHARED}")
    console.print("          -> Create shared dirs, .htaccess, robots.txt")
    if with_cache_plugins:
        console.print("          -> Include cache plugin placeholder files")
    console.print()
    console.print(f"  Step 4: {_STEP_VERIFY_SETUP}")
    console.print("          -> Validate SSH, .env, shared dirs, git remote")
    console.print()
