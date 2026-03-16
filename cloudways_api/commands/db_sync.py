"""Sync a database between two Cloudways environments.

Pulls from the source environment and pushes to the target environment,
with automatic URL replacement of source domain to target domain.

Supports two transfer modes:
- Stream (default): Pipes mysqldump through SSH between environments
- File (--safe): Dumps to local temp file, then uploads to target

Usage::

    cloudways db-sync production staging
    cloudways db-sync production staging --safe
    cloudways db-sync production staging --no-replace
    cloudways db-sync staging production --force
"""

import asyncio
import shutil
import tempfile
import time
from datetime import datetime, timezone

import typer

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    console,
    err_console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_phase2_config
from cloudways_api.db import (
    TRANSIENT_TABLES,
    build_mysqldump_command,
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
    sftp_download,
    sftp_upload,
    stream_local_to_remote,
    validate_ssh_connection,
)
from cloudways_api.url_replace import get_url_replacer

_PRODUCTION_NAMES = {"production", "prod", "live"}


@handle_cli_errors
def db_sync(
    source_env: str = typer.Argument(help="Source environment to pull database from"),
    target_env: str = typer.Argument(help="Target environment to push database to"),
    safe: bool = typer.Option(
        False, "--safe", help="Use file-based transfer instead of streaming"
    ),
    no_replace: bool = typer.Option(
        False, "--no-replace", help="Skip URL search-replace after push"
    ),
    skip_transients: bool = typer.Option(
        False,
        "--skip-transients",
        help="Exclude transient/cache tables from dump",
    ),
    skip_backup: bool = typer.Option(
        False, "--skip-backup", help="Skip automatic backup of target database"
    ),
    replace_method: str = typer.Option(
        "wp-cli",
        "--replace-method",
        help="URL replacement method: wp-cli or sql-replace",
    ),
    force: bool = typer.Option(
        False, "--force", help="Required when target is a production environment"
    ),
) -> None:
    """Sync a database from source to target environment."""
    config = load_config()
    validate_phase2_config(config)

    # Validate source environment
    source_config = validate_environment(config, source_env)

    # Validate source != target before validating target environment
    if source_env == target_env:
        err_console.print(
            "[bold red]Error:[/bold red] Source and target environments "
            "cannot be the same."
        )
        raise typer.Exit(code=1)

    # Validate target environment
    target_config = validate_environment(config, target_env)

    # Production safety check (target only)
    if target_env.lower() in _PRODUCTION_NAMES and not force:
        err_console.print(
            "[bold red]Error:[/bold red] Target is production. Use --force to confirm."
        )
        raise typer.Exit(code=1)

    asyncio.run(
        _execute_db_sync(
            config=config,
            source_config=source_config,
            target_config=target_config,
            source_env=source_env,
            target_env=target_env,
            safe=safe,
            no_replace=no_replace,
            skip_transients=skip_transients,
            skip_backup=skip_backup,
            replace_method=replace_method,
        )
    )


async def _execute_db_sync(
    config: dict,
    source_config: dict,
    target_config: dict,
    source_env: str,
    target_env: str,
    safe: bool,
    no_replace: bool,
    skip_transients: bool,
    skip_backup: bool,
    replace_method: str,
) -> None:
    """Execute the full db-sync workflow.

    Args:
        config: The hosting.cloudways config dict.
        source_config: Source environment-specific config.
        target_config: Target environment-specific config.
        source_env: Source environment name.
        target_env: Target environment name.
        safe: Use file mode instead of stream mode.
        no_replace: Skip URL replacement.
        skip_transients: Exclude transient tables.
        skip_backup: Skip auto-backup of target DB.
        replace_method: URL replacement method (wp-cli or sql-replace).
    """
    server = config["server"]
    ssh_host = server["ssh_host"]
    source_ssh_user = source_config.get("ssh_user", server["ssh_user"])
    target_ssh_user = target_config.get("ssh_user", server["ssh_user"])
    source_domain = source_config.get("domain", "")
    target_domain = target_config.get("domain", "")
    source_webroot = source_config.get("webroot", DEFAULT_WEBROOT)
    target_webroot = target_config.get("webroot", DEFAULT_WEBROOT)

    start_time = time.monotonic()

    # Step 1: Validate SSH connections to both environments
    console.print("[bold]Connecting to source server...[/bold]")
    await validate_ssh_connection(ssh_host, source_ssh_user)
    console.print("[bold]Connecting to target server...[/bold]")
    await validate_ssh_connection(ssh_host, target_ssh_user)

    # Step 2: Detect remote DB names on both environments
    console.print("[bold]Detecting source database name...[/bold]")
    src_wp_cmd = build_wp_config_db_name_command(source_webroot)
    src_output, _, _ = await run_ssh_command(ssh_host, source_ssh_user, src_wp_cmd)
    source_db = parse_db_name_from_wp_config(src_output)

    console.print("[bold]Detecting target database name...[/bold]")
    tgt_wp_cmd = build_wp_config_db_name_command(target_webroot)
    tgt_output, _, _ = await run_ssh_command(ssh_host, target_ssh_user, tgt_wp_cmd)
    target_db = parse_db_name_from_wp_config(tgt_output)

    # Step 3: Auto-backup target DB
    backup_path = None
    if not skip_backup:
        console.print("[bold]Backing up target database...[/bold]")
        now = datetime.now(tz=timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        backup_path = f"/tmp/cloudways_backup_{target_db}_{timestamp}.sql.gz"
        backup_cmd = build_remote_backup_command(target_db, backup_path)
        await run_ssh_command(ssh_host, target_ssh_user, backup_cmd, timeout=300)
        # Verify backup exists and is non-zero
        _, _, verify_rc = await run_ssh_command(
            ssh_host,
            target_ssh_user,
            f"test -s {backup_path}",
            timeout=10,
            raise_on_error=False,
        )
        if verify_rc != 0:
            raise DatabaseError(f"Backup file not found or empty: {backup_path}")
        console.print(f"  Backup saved to: {backup_path}")

    # Step 4: Build mysqldump command for source
    skip_tables = TRANSIENT_TABLES if skip_transients else None
    mysqldump_cmd = build_mysqldump_command(
        source_db, skip_tables=skip_tables, compress=True
    )

    # Step 5: Execute transfer
    if safe:
        await _execute_file_mode(
            ssh_host=ssh_host,
            source_ssh_user=source_ssh_user,
            target_ssh_user=target_ssh_user,
            mysqldump_cmd=mysqldump_cmd,
            target_db=target_db,
        )
    else:
        await _execute_stream_mode(
            ssh_host=ssh_host,
            source_ssh_user=source_ssh_user,
            target_ssh_user=target_ssh_user,
            mysqldump_cmd=mysqldump_cmd,
            target_db=target_db,
        )

    # Step 6: URL replacement
    url_replaced = False
    if not no_replace:
        console.print(f"[bold]Replacing URLs ({replace_method})...[/bold]")
        replacer = get_url_replacer(replace_method, remote=True)
        await replacer(
            source_domain=source_domain,
            target_domain=target_domain,
            ssh_host=ssh_host,
            ssh_user=target_ssh_user,
            webroot=target_webroot,
            db_name=target_db,
        )
        url_replaced = True

    # Step 7: Report completion
    elapsed = time.monotonic() - start_time
    mode = "file" if safe else "stream"
    tables_skipped = len(TRANSIENT_TABLES) if skip_transients else 0

    console.print()
    console.print("[bold green]Database Sync Complete[/bold green]")
    console.print(f"  Source: {source_env} (DB: {source_db})")
    console.print(f"  Target: {target_env} (DB: {target_db})")
    console.print(f"  Mode: {mode}")
    console.print(f"  Time: {elapsed:.1f}s")
    if backup_path:
        console.print(f"  Backup: {backup_path}")
    else:
        console.print("  Backup: skipped (--skip-backup)")
    if url_replaced:
        console.print(
            f"  URL Replace: {replace_method} ({source_domain} -> {target_domain})"
        )
    elif no_replace:
        console.print("  URL Replace: skipped (--no-replace)")
    console.print(f"  Tables Skipped: {tables_skipped}")


async def _execute_stream_mode(
    ssh_host: str,
    source_ssh_user: str,
    target_ssh_user: str,
    mysqldump_cmd: str,
    target_db: str,
) -> None:
    """Execute database sync in stream mode.

    Pipes source mysqldump through SSH into a local pipe,
    then streams locally into the target via SSH.
    """
    console.print("[bold]Streaming database (source -> target)...[/bold]")
    remote_import_cmd = f"gunzip | {build_remote_import_command(target_db)}"

    # Pipe source mysqldump through a local SSH relay into target import.
    # The local command SSHes to the source server and runs mysqldump,
    # whose output feeds directly into the target via stream_local_to_remote.
    local_relay_cmd = (
        f"ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes "
        f"{source_ssh_user}@{ssh_host} '{mysqldump_cmd}'"
    )

    try:
        push_returncode = await stream_local_to_remote(
            host=ssh_host,
            user=target_ssh_user,
            local_cmd=local_relay_cmd,
            remote_cmd=remote_import_cmd,
        )
    except SSHError as exc:
        raise DatabaseError(f"Database push failed (stream mode): {exc}") from exc

    if push_returncode != 0:
        raise DatabaseError(
            f"Database push failed (stream mode, exit code {push_returncode})."
        )


async def _execute_file_mode(
    ssh_host: str,
    source_ssh_user: str,
    target_ssh_user: str,
    mysqldump_cmd: str,
    target_db: str,
) -> None:
    """Execute database sync in file mode.

    Dumps source to remote file, downloads locally, uploads to target,
    then imports on target.
    """
    timestamp = int(time.time())
    source_remote_path = f"/tmp/cloudways_sync_src_{timestamp}.sql.gz"
    target_remote_path = f"/tmp/cloudways_sync_tgt_{timestamp}.sql.gz"
    local_dir = tempfile.mkdtemp(prefix="cloudways_sync_")
    local_path = f"{local_dir}/sync_dump_{timestamp}.sql.gz"

    try:
        # Step 1: Remote dump on source
        console.print("[bold]Dumping database on source server...[/bold]")
        dump_cmd = f"{mysqldump_cmd} > {source_remote_path}"
        await run_ssh_command(ssh_host, source_ssh_user, dump_cmd, timeout=300)

        # Step 2: Download to local
        console.print("[bold]Downloading dump file...[/bold]")
        await sftp_download(ssh_host, source_ssh_user, source_remote_path, local_path)

        # Step 3: Upload to target
        console.print("[bold]Uploading dump file to target...[/bold]")
        await sftp_upload(ssh_host, target_ssh_user, local_path, target_remote_path)

        # Step 4: Remote import on target
        console.print("[bold]Importing database on target server...[/bold]")
        import_cmd = build_remote_import_command(target_db)
        full_cmd = f"gunzip < {target_remote_path} | {import_cmd}"
        await run_ssh_command(ssh_host, target_ssh_user, full_cmd, timeout=300)

    finally:
        # Cleanup: best-effort removal of temp files
        try:
            await run_ssh_command(
                ssh_host,
                source_ssh_user,
                f"rm -f {source_remote_path}",
                timeout=10,
            )
        except SSHError:
            pass

        try:
            await run_ssh_command(
                ssh_host,
                target_ssh_user,
                f"rm -f {target_remote_path}",
                timeout=10,
            )
        except SSHError:
            pass

        shutil.rmtree(local_dir, ignore_errors=True)
