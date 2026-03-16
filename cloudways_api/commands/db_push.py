"""Push a local Docker database to a remote Cloudways server.

Supports two transfer modes:
- Stream (default): Pipes local mysqldump through SSH into remote mysql
- File (--safe): Dumps locally, uploads via SCP, then imports remotely

Usage::

    cloudways db-push production
    cloudways db-push production --safe
    cloudways db-push staging --skip-backup --no-replace
    cloudways db-push production --yes --skip-transients
"""

import asyncio
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

import typer

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_phase2_config
from cloudways_api.db import (
    TRANSIENT_TABLES,
    build_local_mysqldump_docker_command,
    build_remote_backup_command,
    build_remote_import_command,
    build_wp_config_db_name_command,
    parse_db_name_from_wp_config,
)
from cloudways_api.exceptions import (
    DatabaseError,
    SSHError,
)
from cloudways_api.ssh import (
    run_ssh_command,
    sftp_upload,
    stream_local_to_remote,
    validate_ssh_connection,
)
from cloudways_api.url_replace import get_url_replacer

_PRODUCTION_NAMES = {"production", "prod", "live"}


@handle_cli_errors
def db_push(
    environment: str = typer.Argument(
        help="Target environment to push to (e.g., production, staging)"
    ),
    safe: bool = typer.Option(
        False, "--safe", help="Use file mode (SCP upload) instead of stream mode"
    ),
    skip_backup: bool = typer.Option(
        False, "--skip-backup", help="Skip automatic backup of remote database"
    ),
    no_replace: bool = typer.Option(
        False, "--no-replace", help="Skip URL replacement after import"
    ),
    skip_transients: bool = typer.Option(
        False,
        "--skip-transients",
        help="Exclude cache/session tables from dump",
    ),
    local_container: str = typer.Option(
        None, "--local-container", help="Override local Docker MySQL container name"
    ),
    local_db: str = typer.Option(
        None, "--local-db", help="Override local database name"
    ),
    local_domain: str = typer.Option(
        "localhost",
        "--local-domain",
        help="Local domain to replace in URL replacement (default: localhost)",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip production confirmation prompt"
    ),
) -> None:
    """Push a local database to a remote Cloudways server."""
    config = load_config()
    validate_phase2_config(config)
    env_config = validate_environment(config, environment)

    # Resolve local config with overrides
    database = config["database"]
    resolved_container = local_container or database["local_container"]
    resolved_db = local_db or database["local_db_name"]

    # Production confirmation
    if environment.lower() in _PRODUCTION_NAMES and not yes:
        domain = env_config.get("domain", environment)
        confirmed = typer.confirm(
            f"\nWARNING: You are about to push to PRODUCTION ({domain}).\n"
            f"This will replace ALL database content on the remote server.\n"
            f"Continue?"
        )
        if not confirmed:
            console.print("Push cancelled.")
            raise typer.Exit(code=0)

    asyncio.run(
        _execute_db_push(
            config=config,
            env_config=env_config,
            environment=environment,
            safe=safe,
            skip_backup=skip_backup,
            no_replace=no_replace,
            skip_transients=skip_transients,
            local_container=resolved_container,
            local_db=resolved_db,
            local_domain=local_domain,
        )
    )


async def _execute_db_push(
    config: dict,
    env_config: dict,
    environment: str,
    safe: bool,
    skip_backup: bool,
    no_replace: bool,
    skip_transients: bool,
    local_container: str,
    local_db: str,
    local_domain: str,
) -> None:
    """Execute the full db-push workflow."""
    server = config["server"]
    database = config["database"]
    ssh_user = server["ssh_user"]
    ssh_host = server["ssh_host"]
    domain = env_config.get("domain", "")
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

    # Step 3: Auto-backup remote DB
    backup_path = None
    if not skip_backup:
        console.print("[bold]Backing up remote database...[/bold]")
        now = datetime.now(tz=timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        backup_path = f"/tmp/cloudways_backup_{remote_db}_{timestamp}.sql.gz"
        backup_cmd = build_remote_backup_command(remote_db, backup_path)
        await run_ssh_command(ssh_host, ssh_user, backup_cmd, timeout=300)
        # Verify backup exists and is non-zero
        _, _, verify_rc = await run_ssh_command(
            ssh_host,
            ssh_user,
            f"test -s {backup_path}",
            timeout=10,
            raise_on_error=False,
        )
        if verify_rc != 0:
            raise DatabaseError(f"Backup file not found or empty: {backup_path}")
        console.print(f"  Backup saved to: {backup_path}")

    # Step 4: Build local mysqldump command
    skip_tables = TRANSIENT_TABLES if skip_transients else None
    local_mysqldump_cmd = build_local_mysqldump_docker_command(
        local_container, local_db, skip_tables=skip_tables, compress=True
    )

    # Step 5: Execute transfer
    if safe:
        await _execute_file_mode(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            local_mysqldump_cmd=local_mysqldump_cmd,
            remote_db=remote_db,
        )
    else:
        await _execute_stream_mode(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            local_mysqldump_cmd=local_mysqldump_cmd,
            remote_db=remote_db,
        )

    # Step 6: URL replacement
    url_replaced = False
    url_method = database.get("url_replace_method", "wp-cli")
    if not no_replace:
        if url_method == "env-file":
            # env-file method not supported for remote push
            console.print(
                "[bold yellow]Warning:[/bold yellow] "
                "URL replacement method 'env-file' is not supported "
                "for remote push. Skipping URL replacement."
            )
        else:
            replacer = get_url_replacer(url_method, remote=True)
            console.print(f"[bold]Replacing URLs ({url_method})...[/bold]")
            await replacer(
                source_domain=local_domain,
                target_domain=domain,
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                webroot=webroot,
                db_name=remote_db,
            )
            url_replaced = True

    # Step 7: Report completion
    elapsed = time.monotonic() - start_time
    mode = "file" if safe else "stream"
    tables_skipped = len(TRANSIENT_TABLES) if skip_transients else 0

    console.print()
    console.print("[bold green]Database Push Complete[/bold green]")
    console.print(f"  Environment: {environment}")
    console.print(f"  Remote DB: {remote_db}")
    console.print(f"  Local DB: {local_db}")
    console.print(f"  Mode: {mode}")
    console.print(f"  Time: {elapsed:.1f}s")
    if backup_path:
        console.print(f"  Backup: {backup_path}")
    else:
        console.print("  Backup: skipped (--skip-backup)")
    if url_replaced:
        console.print(
            f"  URL Replace: {url_method} (http://{local_domain} -> https://{domain})"
        )
    elif no_replace:
        console.print("  URL Replace: skipped (--no-replace)")
    else:
        console.print("  URL Replace: skipped (method not supported for push)")
    console.print(f"  Tables Skipped: {tables_skipped}")


async def _execute_stream_mode(
    ssh_host: str,
    ssh_user: str,
    local_mysqldump_cmd: str,
    remote_db: str,
) -> None:
    """Execute database push in stream mode.

    Pipes local mysqldump through SSH directly into remote mysql.
    """
    console.print("[bold]Streaming database (local -> remote)...[/bold]")

    remote_import_cmd = f"gunzip | {build_remote_import_command(remote_db)}"

    try:
        returncode = await stream_local_to_remote(
            host=ssh_host,
            user=ssh_user,
            local_cmd=local_mysqldump_cmd,
            remote_cmd=remote_import_cmd,
        )
    except SSHError as exc:
        raise DatabaseError(
            f"Remote database import failed (stream mode): {exc}"
        ) from exc

    if returncode != 0:
        raise DatabaseError(
            f"Remote database import failed (stream mode, exit code {returncode})."
        )


async def _execute_file_mode(
    ssh_host: str,
    ssh_user: str,
    local_mysqldump_cmd: str,
    remote_db: str,
) -> None:
    """Execute database push in file mode.

    Dumps locally, uploads via SCP, then imports remotely.
    """
    timestamp = int(time.time())
    local_dir = tempfile.mkdtemp(prefix="cloudways_push_")
    local_path = f"{local_dir}/push_dump_{timestamp}.sql.gz"
    remote_path = f"/tmp/cloudways_push_{timestamp}.sql.gz"

    try:
        # Step 1: Local dump to file
        console.print("[bold]Exporting local database...[/bold]")
        dump_cmd = f"{local_mysqldump_cmd} > {local_path}"
        proc = subprocess.run(
            ["sh", "-c", dump_cmd],
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise DatabaseError(
                f"Local database export failed: {stderr}. "
                f"Is the Docker container running?"
            )

        # Step 2: Upload via SCP
        console.print("[bold]Uploading dump file...[/bold]")
        await sftp_upload(ssh_host, ssh_user, local_path, remote_path)

        # Step 3: Remote import
        console.print("[bold]Importing database on remote server...[/bold]")
        import_cmd = build_remote_import_command(remote_db)
        full_cmd = f"gunzip < {remote_path} | {import_cmd}"
        await run_ssh_command(ssh_host, ssh_user, full_cmd, timeout=300)

    finally:
        # Cleanup (best-effort)
        try:
            await run_ssh_command(
                ssh_host, ssh_user, f"rm -f {remote_path}", timeout=10
            )
        except SSHError:
            pass

        shutil.rmtree(local_dir, ignore_errors=True)
