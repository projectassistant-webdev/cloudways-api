"""Pull a remote WordPress database to a local Docker container.

Supports two transfer modes:
- Stream (default): Pipes mysqldump directly through SSH into local mysql
- File (--safe): Dumps to remote file, downloads via SCP, then imports

Usage::

    cloudways db-pull production
    cloudways db-pull production --safe
    cloudways db-pull production --skip-transients --no-replace
"""

import asyncio
import shutil
import tempfile
import time

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
    build_db_size_query,
    build_import_command,
    build_mysql_command,
    build_mysqldump_command,
    detect_remote_db_credentials,
)
from cloudways_api.exceptions import (
    DatabaseError,
    SSHError,
)
from cloudways_api.ssh import (
    run_ssh_command,
    sftp_download,
    stream_ssh_pipe,
    validate_ssh_connection,
)
from cloudways_api.url_replace import get_url_replacer


@handle_cli_errors
def db_pull(
    environment: str = typer.Argument(
        help="Environment to pull from (production, staging)"
    ),
    safe: bool = typer.Option(
        False, "--safe", help="Use file mode (SFTP) instead of stream mode"
    ),
    no_replace: bool = typer.Option(
        False, "--no-replace", help="Skip URL replacement after import"
    ),
    skip_transients: bool = typer.Option(
        False,
        "--skip-transients",
        help="Exclude cache/session tables from dump",
    ),
) -> None:
    """Pull a remote database to a local Docker container."""
    config = load_config()
    validate_phase2_config(config)
    env_config = validate_environment(config, environment)

    asyncio.run(
        _execute_db_pull(
            config=config,
            env_config=env_config,
            environment=environment,
            safe=safe,
            no_replace=no_replace,
            skip_transients=skip_transients,
        )
    )


async def _execute_db_pull(
    config: dict,
    env_config: dict,
    environment: str,
    safe: bool,
    no_replace: bool,
    skip_transients: bool,
) -> None:
    """Execute the full db-pull workflow.

    Args:
        config: The hosting.cloudways config dict.
        env_config: Environment-specific config.
        environment: Environment name (e.g., 'production').
        safe: Use file mode instead of stream mode.
        no_replace: Skip URL replacement.
        skip_transients: Exclude transient tables.
    """
    server = config["server"]
    database = config["database"]
    ssh_user = env_config.get("ssh_user", server["ssh_user"])
    ssh_host = server["ssh_host"]
    local_db = database["local_db_name"]
    local_container = database["local_container"]
    local_db_user = database.get("local_db_user", "")
    local_db_password = database.get("local_db_password", "")
    domain = env_config.get("domain", "")
    webroot = env_config.get("webroot", DEFAULT_WEBROOT)

    start_time = time.monotonic()

    # Step 1: Validate SSH connection
    console.print("[bold]Connecting to server...[/bold]")
    await validate_ssh_connection(ssh_host, ssh_user)

    # Step 2: Detect remote DB credentials (Bedrock .env or traditional wp-config.php)
    console.print("[bold]Detecting remote database credentials...[/bold]")
    db_creds = await detect_remote_db_credentials(ssh_host, ssh_user, webroot)
    remote_db = db_creds["db_name"]
    remote_db_user = db_creds["db_user"]
    remote_db_password = db_creds["db_password"]
    console.print(f"  Detected: {remote_db} ({db_creds['env_type']})")

    # Step 3: Estimate DB size (for reporting)
    db_size_bytes = 0
    try:
        size_query = build_db_size_query(remote_db)
        size_cmd = build_mysql_command(
            size_query, db_user=remote_db_user, db_password=remote_db_password
        )
        size_output, _, _ = await run_ssh_command(ssh_host, ssh_user, size_cmd)
        size_str = size_output.strip()
        if size_str and size_str != "NULL":
            db_size_bytes = int(float(size_str))
    except (SSHError, ValueError):
        # Non-fatal: size estimation is best-effort
        pass

    # Step 4: Build mysqldump command
    skip_tables = TRANSIENT_TABLES if skip_transients else None
    mysqldump_cmd = build_mysqldump_command(
        remote_db,
        skip_tables=skip_tables,
        compress=True,
        db_user=remote_db_user,
        db_password=remote_db_password,
    )

    # Step 5: Execute transfer
    if safe:
        await _execute_file_mode(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            mysqldump_cmd=mysqldump_cmd,
            local_db=local_db,
            local_container=local_container,
            local_db_user=local_db_user,
            local_db_password=local_db_password,
        )
    else:
        await _execute_stream_mode(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            mysqldump_cmd=mysqldump_cmd,
            local_db=local_db,
            local_container=local_container,
            local_db_user=local_db_user,
            local_db_password=local_db_password,
        )

    # Step 6: URL replacement
    if not no_replace:
        method = database["url_replace_method"]
        console.print(f"[bold]Replacing URLs ({method})...[/bold]")
        replacer = get_url_replacer(method)
        await replacer(
            source_domain=domain,
            target_domain="localhost",
            container_name=local_container,
            db_name=local_db,
        )

    # Step 7: Report completion
    elapsed = time.monotonic() - start_time
    mode = "file" if safe else "stream"
    tables_skipped = len(TRANSIENT_TABLES) if skip_transients else 0
    size_mb = f"{db_size_bytes / (1024 * 1024):.0f} MB" if db_size_bytes else "unknown"

    console.print()
    console.print("[bold green]Database Pull Complete[/bold green]")
    console.print(f"  Environment: {environment}")
    console.print(f"  Remote DB: {remote_db}")
    console.print(f"  Local DB: {local_db}")
    console.print(f"  Mode: {mode}")
    console.print(f"  Size: {size_mb}")
    console.print(f"  Time: {elapsed:.1f}s")
    if not no_replace:
        console.print(
            f"  URL Replace: {database['url_replace_method']} "
            f"(https://{domain} -> http://localhost)"
        )
    console.print(f"  Tables Skipped: {tables_skipped}")


async def _execute_stream_mode(
    ssh_host: str,
    ssh_user: str,
    mysqldump_cmd: str,
    local_db: str,
    local_container: str = "",
    local_db_user: str = "",
    local_db_password: str = "",
) -> None:
    """Execute database pull in stream mode.

    Pipes remote mysqldump through SSH directly into local mysql.
    When *local_container* is set, the mysql command runs inside
    the Docker container via ``docker exec -i``.
    """
    console.print("[bold]Streaming database (mysqldump -> mysql)...[/bold]")

    auth = ""
    if local_db_user:
        auth += f" -u{local_db_user}"
    if local_db_password:
        auth += f" -p'{local_db_password}'"

    if local_container:
        import_cmd = f"gunzip | docker exec -i {local_container} mysql{auth} {local_db}"
    else:
        import_cmd = f"gunzip | mysql{auth} {local_db}"

    returncode = await stream_ssh_pipe(
        host=ssh_host,
        user=ssh_user,
        remote_cmd=mysqldump_cmd,
        local_cmd=import_cmd,
    )

    if returncode != 0:
        raise DatabaseError(
            f"Database import failed (stream mode, exit code {returncode})."
        )


async def _execute_file_mode(
    ssh_host: str,
    ssh_user: str,
    mysqldump_cmd: str,
    local_db: str,
    local_container: str = "",
    local_db_user: str = "",
    local_db_password: str = "",
) -> None:
    """Execute database pull in file mode.

    Dumps to a remote file, downloads via SCP, then imports locally.
    """
    timestamp = int(time.time())
    remote_path = f"/tmp/cloudways_dump_{timestamp}.sql.gz"
    local_dir = tempfile.mkdtemp(prefix="cloudways_")
    local_path = f"{local_dir}/dump_{timestamp}.sql.gz"

    try:
        # Step 1: Remote dump
        console.print("[bold]Dumping database on remote server...[/bold]")
        dump_cmd = f"{mysqldump_cmd} > {remote_path}"
        await run_ssh_command(ssh_host, ssh_user, dump_cmd, timeout=300)

        # Step 2: Download
        console.print("[bold]Downloading dump file...[/bold]")
        await sftp_download(ssh_host, ssh_user, remote_path, local_path)

        # Step 3: Local import
        console.print("[bold]Importing database locally...[/bold]")
        await _run_local_import(
            local_path,
            local_db,
            local_container,
            local_db_user,
            local_db_password,
        )

    finally:
        # Step 4: Cleanup (best-effort)
        try:
            await run_ssh_command(
                ssh_host, ssh_user, f"rm -f {remote_path}", timeout=10
            )
        except SSHError:
            pass  # Non-fatal: cleanup failure is a warning only

        # Clean up local temp files
        shutil.rmtree(local_dir, ignore_errors=True)


async def _run_local_import(
    local_path: str,
    local_db: str,
    local_container: str = "",
    local_db_user: str = "",
    local_db_password: str = "",
) -> None:
    """Import a gzipped SQL dump into the local database.

    Args:
        local_path: Path to the .sql.gz file.
        local_db: Local database name.
        local_container: Optional Docker container name for mysql.
        local_db_user: Local database username (optional).
        local_db_password: Local database password (optional).
    """
    import_cmd = build_import_command(
        local_db,
        container_name=local_container,
        db_user=local_db_user,
        db_password=local_db_password,
    )
    full_cmd = f"gunzip < {local_path} | {import_cmd}"

    process = await asyncio.create_subprocess_exec(
        "sh",
        "-c",
        full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise DatabaseError(
            f"Database import failed: "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
