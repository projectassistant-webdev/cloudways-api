"""Pre-deploy readiness check for Capistrano deployment.

Validates all prerequisites for a successful ``cap deploy``:
SSH connectivity, shared directory, .env file, linked files/dirs,
and git remote accessibility.

Usage::

    cloudways verify-setup staging
    cloudways verify-setup production --verbose
"""

import asyncio

import typer

from cloudways_api.capistrano_parser import (
    get_linked_dirs_for_environment,
    get_linked_files_for_environment,
)
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.ssh import run_ssh_command

# Minimum required .env keys for a Bedrock deployment
_REQUIRED_ENV_KEYS = ["DB_NAME", "WP_HOME", "AUTH_KEY"]
_MIN_REQUIRED_KEY_COUNT = len(_REQUIRED_ENV_KEYS)


@handle_cli_errors
def verify_setup(
    environment: str = typer.Argument(
        help="Environment name from project config (e.g., staging, production)"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Show detailed output for each check"
    ),
) -> None:
    """Pre-deploy readiness check for Capistrano deployment."""
    config = load_config()
    validate_ssh_config(config)
    env_config = validate_environment(config, environment)

    passed, total = asyncio.run(
        _execute_verify_setup(
            config=config,
            env_config=env_config,
            environment=environment,
            verbose=verbose,
        )
    )

    if passed < total:
        raise typer.Exit(code=1)


async def _execute_verify_setup(
    config: dict,
    env_config: dict,
    environment: str,
    verbose: bool,
) -> tuple[int, int]:
    """Execute all verification checks and return (passed, total)."""
    server_config = config["server"]
    ssh_host = server_config["ssh_host"]
    ssh_user = env_config.get("ssh_user", server_config["ssh_user"])

    # Get linked files and dirs from Capistrano config or defaults
    linked_files = get_linked_files_for_environment(environment)
    linked_dirs = get_linked_dirs_for_environment()

    # Filter .env from linked files -- it gets its own dedicated checks
    non_env_files = [f for f in linked_files if f != ".env"]

    passed = 0
    total = 0

    console.print()

    # ---- Check 1: SSH connectivity ----
    total += 1
    check_name = f"SSH connectivity: {ssh_user}@{ssh_host}"
    cmd = "echo ok"
    try:
        stdout, _, rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            cmd,
            raise_on_error=False,
        )
        ok = rc == 0 and "ok" in stdout
    except Exception:
        ok = False

    _print_check(ok, check_name, verbose, cmd)
    if ok:
        passed += 1

    # ---- Check 2: Shared directory exists ----
    total += 1
    check_name = "Shared directory: ~/public_html/shared"
    cmd = "test -d ~/public_html/shared"
    try:
        _, _, rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            cmd,
            raise_on_error=False,
        )
        ok = rc == 0
    except Exception:
        ok = False
    _print_check(ok, check_name, verbose, cmd)
    if ok:
        passed += 1

    # ---- Check 3: .env file exists ----
    total += 1
    check_name = ".env file: ~/public_html/shared/.env"
    cmd = "test -f ~/public_html/shared/.env"
    try:
        _, _, rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            cmd,
            raise_on_error=False,
        )
        env_exists = rc == 0
    except Exception:
        env_exists = False
    _print_check(env_exists, check_name, verbose, cmd)
    if env_exists:
        passed += 1

    # ---- Check 4: .env has required keys ----
    total += 1
    grep_pattern = r"\|".join(_REQUIRED_ENV_KEYS)
    cmd = f"grep -c '{grep_pattern}' ~/public_html/shared/.env"
    check_name = f".env required keys: {', '.join(_REQUIRED_ENV_KEYS)}"
    try:
        stdout, _, rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            cmd,
            raise_on_error=False,
        )
    except Exception:
        stdout = "0"
    try:
        key_count = int(stdout.strip())
    except (ValueError, AttributeError):
        key_count = 0
    ok = key_count >= _MIN_REQUIRED_KEY_COUNT
    detail = f"Found {key_count}/{_MIN_REQUIRED_KEY_COUNT} required keys"
    _print_check(ok, check_name, verbose, cmd, detail)
    if ok:
        passed += 1

    # ---- Check 5: Linked files exist ----
    for file_path in non_env_files:
        total += 1
        remote_path = f"~/public_html/shared/{file_path}"
        cmd = f"test -f {remote_path}"
        check_name = f"Linked file: {file_path}"
        try:
            _, _, rc = await run_ssh_command(
                ssh_host,
                ssh_user,
                cmd,
                raise_on_error=False,
            )
            ok = rc == 0
        except Exception:
            ok = False
        _print_check(ok, check_name, verbose, cmd)
        if ok:
            passed += 1

    # ---- Check 6: Linked dirs exist ----
    for dir_path in linked_dirs:
        total += 1
        remote_path = f"~/public_html/shared/{dir_path}"
        cmd = f"test -d {remote_path}"
        check_name = f"Linked directory: {dir_path}"
        try:
            _, _, rc = await run_ssh_command(
                ssh_host,
                ssh_user,
                cmd,
                raise_on_error=False,
            )
            ok = rc == 0
        except Exception:
            ok = False
        _print_check(ok, check_name, verbose, cmd)
        if ok:
            passed += 1

    # ---- Check 7: Git remote accessible ----
    total += 1
    cmd = "ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -T git@bitbucket.org"
    check_name = "Git remote: bitbucket.org"
    try:
        _, _, rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            cmd,
            raise_on_error=False,
        )
        # Exit code 0 = full access, exit code 1 = authenticated (no shell)
        # Both are acceptable -- means SSH keys are configured
        ok = rc in (0, 1)
    except Exception:
        ok = False
    _print_check(ok, check_name, verbose, cmd)
    if ok:
        passed += 1

    # ---- Summary ----
    console.print()
    if passed == total:
        console.print(
            f"  Result: {passed}/{total} checks passed. "
            f"[bold green]Ready to deploy![/bold green]"
        )
    else:
        console.print(
            f"  Result: {passed}/{total} checks passed. "
            f"[bold red]Not ready to deploy.[/bold red]"
        )
    console.print()

    return passed, total


def _print_check(
    ok: bool,
    name: str,
    verbose: bool,
    command: str,
    detail: str | None = None,
) -> None:
    """Print a single check result with optional verbose detail."""
    if ok:
        console.print(f"  [green]OK[/green]     {name}")
    else:
        console.print(f"  [red]FAIL[/red]   {name}")

    if verbose:
        console.print(f"           Command: {command}")
        if detail:
            console.print(f"           Detail: {detail}")
