"""Restore a remote database from backup on a Cloudways server.

Supports three modes:
- Auto (default): Finds and restores the most recent backup
- Specific (--backup-file): Restores from a specified backup file
- List (--list): Lists available backup files without restoring

Usage::

    cloudways db-restore production
    cloudways db-restore production --list
    cloudways db-restore production --backup-file /tmp/cloudways_backup_mydb_20260206.sql.gz
"""

import asyncio
import time

import typer
from rich.table import Table

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_phase2_config
from cloudways_api.db import (
    build_remote_import_command,
    build_wp_config_db_name_command,
    parse_db_name_from_wp_config,
)
from cloudways_api.exceptions import (
    DatabaseError,
)
from cloudways_api.ssh import run_ssh_command, validate_ssh_connection


@handle_cli_errors
def db_restore(
    environment: str = typer.Argument(
        help="Target environment to restore on (e.g., production, staging)"
    ),
    list_backups: bool = typer.Option(
        False, "--list", help="List available backup files and exit"
    ),
    backup_file: str = typer.Option(
        None,
        "--backup-file",
        help="Path to specific backup file on remote server",
    ),
) -> None:
    """Restore a remote database from a backup file."""
    config = load_config()
    validate_phase2_config(config)
    env_config = validate_environment(config, environment)

    asyncio.run(
        _execute_db_restore(
            config=config,
            env_config=env_config,
            environment=environment,
            list_backups=list_backups,
            backup_file=backup_file,
        )
    )


async def _execute_db_restore(
    config: dict,
    env_config: dict,
    environment: str,
    list_backups: bool,
    backup_file: str | None,
) -> None:
    """Execute the full db-restore workflow."""
    server = config["server"]
    ssh_user = server["ssh_user"]
    ssh_host = server["ssh_host"]
    webroot = env_config.get("webroot", DEFAULT_WEBROOT)

    start_time = time.monotonic()

    # Step 1: Validate SSH connection
    console.print("[bold]Connecting to server...[/bold]")
    await validate_ssh_connection(ssh_host, ssh_user)

    # Step 2: Detect remote DB name
    console.print("[bold]Detecting remote database name...[/bold]")
    wp_config_cmd = build_wp_config_db_name_command(webroot)
    wp_output, _, _ = await run_ssh_command(ssh_host, ssh_user, wp_config_cmd)
    remote_db = parse_db_name_from_wp_config(wp_output)

    # Step 3: Handle --list mode
    if list_backups:
        await _list_backups(ssh_host, ssh_user, remote_db)
        return

    # Step 4: Determine backup file to restore
    if backup_file:
        restore_path = backup_file
    else:
        # Find most recent backup
        console.print("[bold]Finding most recent backup...[/bold]")
        ls_cmd = (
            f"ls -t /tmp/cloudways_backup_{remote_db}_*.sql.gz 2>/dev/null | head -1"
        )
        stdout, _, _ = await run_ssh_command(ssh_host, ssh_user, ls_cmd)
        restore_path = stdout.strip()
        if not restore_path:
            raise DatabaseError(
                f"No backup files found for database '{remote_db}' "
                f"in /tmp/. Run 'db-push' first or specify --backup-file."
            )

    # Step 5: Verify backup file exists and is non-empty
    console.print("[bold]Verifying backup file...[/bold]")
    verify_stdout, verify_stderr, verify_rc = await run_ssh_command(
        ssh_host,
        ssh_user,
        f"test -s {restore_path}",
        timeout=10,
        raise_on_error=False,
    )
    if verify_rc != 0:
        raise DatabaseError(f"Backup file not found or empty: {restore_path}")

    # Step 6: Import backup
    console.print("[bold]Restoring database...[/bold]")
    import_cmd = build_remote_import_command(remote_db)
    full_cmd = f"gunzip < {restore_path} | {import_cmd}"
    await run_ssh_command(ssh_host, ssh_user, full_cmd, timeout=300)

    # Step 7: Report completion
    elapsed = time.monotonic() - start_time
    console.print()
    console.print("[bold green]Database Restore Complete[/bold green]")
    console.print(f"  Environment: {environment}")
    console.print(f"  Remote DB: {remote_db}")
    console.print(f"  Backup: {restore_path}")
    console.print(f"  Time: {elapsed:.1f}s")


async def _list_backups(
    ssh_host: str,
    ssh_user: str,
    remote_db: str,
) -> None:
    """List available backup files on the remote server."""
    ls_cmd = f"ls -lah /tmp/cloudways_backup_{remote_db}_*.sql.gz 2>/dev/null"
    stdout, _, rc = await run_ssh_command(
        ssh_host,
        ssh_user,
        ls_cmd,
        raise_on_error=False,
    )

    if rc != 0 or not stdout or not stdout.strip():
        console.print(
            f"[bold yellow]No backup files found[/bold yellow] "
            f"for database '{remote_db}' in /tmp/."
        )
        return

    # Parse ls -lah output into table
    table = Table(title=f"Available Backups ({remote_db})")
    table.add_column("Filename", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Date", style="yellow")

    for line in stdout.strip().split("\n"):
        # Skip total line and empty lines
        if line.startswith("total") or not line.strip():
            continue

        parts = line.split()
        if len(parts) >= 9:
            size = parts[4]
            date = f"{parts[5]} {parts[6]} {parts[7]}"
            filename = parts[8]
            table.add_row(filename, size, date)

    console.print(table)
