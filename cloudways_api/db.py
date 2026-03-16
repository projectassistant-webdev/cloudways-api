"""Database utilities for mysqldump, import, and wp-config parsing.

Provides command builders for remote mysqldump and local mysql import,
a transient table exclusion list, wp-config.php DB_NAME extraction,
and database size estimation queries.
"""

from cloudways_api.env_detect import (
    capture_bedrock_env,
    detect_env_type,
    parse_dotenv_content,
    parse_wp_config_defines,
)
from cloudways_api.exceptions import DatabaseError
from cloudways_api.ssh import run_ssh_command

_MYSQLDUMP_FLAGS: list[str] = [
    "--single-transaction",
    "--quick",
    "--routines",
    "--triggers",
    "--set-gtid-purged=OFF",
    "--no-tablespaces",
    "--column-statistics=0",
]

TRANSIENT_TABLES: list[str] = [
    "wp_wfKnownFileList",
    "wp_wfFileMods",
    "wp_wfHits",
    "wp_wfLiveTrafficHuman",
    "wp_actionscheduler_actions",
    "wp_actionscheduler_claims",
    "wp_actionscheduler_groups",
    "wp_actionscheduler_logs",
    "wp_wc_sessions",
    "wp_yoast_indexable",
    "wp_yoast_indexable_hierarchy",
    "wp_yoast_migrations",
    "wp_yoast_primary_term",
    "wp_yoast_seo_links",
    "wp_statistics_visitor",
    "wp_statistics_visit",
    "wp_statistics_pages",
]


def build_mysqldump_command(
    db_name: str,
    skip_tables: list[str] | None = None,
    compress: bool = True,
    db_user: str = "",
    db_password: str = "",
) -> str:
    """Build a mysqldump command string with optimization flags.

    Args:
        db_name: Name of the database to dump.
        skip_tables: Tables to exclude via --ignore-table.
        compress: Whether to pipe through gzip -1.
        db_user: Database username (optional, uses .my.cnf if empty).
        db_password: Database password (optional).

    Returns:
        The full mysqldump command string.
    """
    parts = ["mysqldump", *_MYSQLDUMP_FLAGS]

    if db_user:
        parts.append(f"-u{db_user}")
    if db_password:
        parts.append(f"-p'{db_password}'")

    if skip_tables:
        for table in skip_tables:
            parts.append(f"--ignore-table={db_name}.{table}")

    parts.append(db_name)

    cmd = " ".join(parts)

    if compress:
        cmd += " | gzip -1"

    return cmd


def build_import_command(
    db_name: str,
    container_name: str = "",
    db_user: str = "",
    db_password: str = "",
) -> str:
    """Build a mysql import command with performance optimizations.

    The generated command disables autocommit, foreign key checks,
    and unique checks before the import, then runs COMMIT after.

    When *container_name* is provided the ``mysql`` invocations are
    wrapped with ``docker exec -i <container>`` so that the import
    runs inside the local Docker container where the MySQL client
    is available.

    Args:
        db_name: Local database name for import.
        container_name: Optional Docker container name.  When set,
            the mysql commands are executed inside this container.
        db_user: Local database username (optional).
        db_password: Local database password (optional).

    Returns:
        The full import command string.
    """
    auth = ""
    if db_user:
        auth += f" -u{db_user}"
    if db_password:
        auth += f" -p'{db_password}'"

    if container_name:
        mysql = f"docker exec -i {container_name} mysql{auth} {db_name}"
    else:
        mysql = f"mysql{auth} {db_name}"

    return (
        f'(echo "SET autocommit=0; SET foreign_key_checks=0; '
        f'SET unique_checks=0;" && cat) | {mysql} && '
        f'echo "COMMIT;" | {mysql}'
    )


def build_wp_config_db_name_command(
    app_path: str = "public_html/current",
) -> str:
    """Build SSH command to extract DB_NAME from wp-config.php.

    Args:
        app_path: Path to the WordPress installation on the remote server.

    Returns:
        Shell command to grep DB_NAME from wp-config.php.
    """
    return f'grep "DB_NAME" {app_path}/wp-config.php | head -1'


def parse_db_name_from_wp_config(output: str) -> str:
    """Extract the database name from wp-config.php grep output.

    Delegates to :func:`cloudways_api.env_detect.parse_wp_config_defines`
    for the actual ``define()`` parsing, then extracts the ``DB_NAME``
    key from the returned dict.

    Args:
        output: Raw output from grepping wp-config.php.

    Returns:
        The extracted database name.

    Raises:
        DatabaseError: If the DB_NAME pattern cannot be found.
    """
    defines = parse_wp_config_defines(output)
    db_name = defines.get("DB_NAME")
    if not db_name:
        raise DatabaseError(
            "Could not detect database name from wp-config.php. "
            "Verify the file exists on the remote server."
        )
    return db_name


async def detect_remote_db_name(
    ssh_host: str,
    ssh_user: str,
    webroot: str,
) -> str:
    """Detect the remote database name, supporting Bedrock and traditional WP.

    Checks for a ``.env`` file first (Bedrock).  If found, parses
    ``DB_NAME`` from it.  Otherwise falls back to grepping
    ``wp-config.php`` (traditional WordPress).

    Args:
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        webroot: Path to the WordPress installation root.

    Returns:
        The detected database name.

    Raises:
        DatabaseError: If the database name cannot be determined.
    """
    creds = await detect_remote_db_credentials(ssh_host, ssh_user, webroot)
    return creds["db_name"]


async def detect_remote_db_credentials(
    ssh_host: str,
    ssh_user: str,
    webroot: str,
) -> dict[str, str]:
    """Detect remote database credentials (name, user, password, host).

    Checks for a ``.env`` file first (Bedrock).  If found, parses
    DB credentials from it.  Otherwise falls back to grepping
    ``wp-config.php`` (traditional WordPress).

    Args:
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        webroot: Path to the WordPress installation root.

    Returns:
        Dictionary with keys ``db_name``, ``db_user``, ``db_password``,
        ``db_host``, and ``env_type``.

    Raises:
        DatabaseError: If the database name cannot be determined.
    """
    env_type = await detect_env_type(ssh_host, ssh_user, webroot)

    if env_type == "bedrock":
        env_content = await capture_bedrock_env(ssh_host, ssh_user, webroot)
        env_vars = parse_dotenv_content(env_content)
        db_name = env_vars.get("DB_NAME")
        if not db_name:
            raise DatabaseError(
                "Could not detect database name from .env file. "
                "Verify DB_NAME is set in the Bedrock .env file."
            )
        return {
            "db_name": db_name,
            "db_user": env_vars.get("DB_USER", ""),
            "db_password": env_vars.get("DB_PASSWORD", ""),
            "db_host": env_vars.get("DB_HOST", "localhost"),
            "env_type": "bedrock",
        }

    # Traditional WordPress: grep wp-config.php
    wp_config_cmd = build_wp_config_db_name_command(webroot)
    wp_output, _, _ = await run_ssh_command(ssh_host, ssh_user, wp_config_cmd)
    db_name = parse_db_name_from_wp_config(wp_output)
    return {
        "db_name": db_name,
        "db_user": "",
        "db_password": "",
        "db_host": "localhost",
        "env_type": "traditional",
    }


def build_db_size_query(db_name: str) -> str:
    """Build SQL query to estimate database size from information_schema.

    Args:
        db_name: Database name to query size for.

    Returns:
        SQL query string.
    """
    return (
        f"SELECT SUM(data_length + index_length) "
        f"FROM information_schema.tables "
        f"WHERE table_schema = '{db_name}';"
    )


def build_mysql_command(
    query: str,
    db_user: str = "",
    db_password: str = "",
) -> str:
    """Build a mysql command with optional credentials.

    Args:
        query: SQL query to execute.
        db_user: Database username (optional).
        db_password: Database password (optional).

    Returns:
        The full mysql command string.
    """
    parts = ["mysql"]
    if db_user:
        parts.append(f"-u{db_user}")
    if db_password:
        parts.append(f"-p'{db_password}'")
    parts.append(f'-N -e "{query}"')
    return " ".join(parts)


def build_local_mysqldump_docker_command(
    container_name: str,
    db_name: str,
    skip_tables: list[str] | None = None,
    compress: bool = True,
) -> str:
    """Build a mysqldump command that runs inside a local Docker container.

    Wraps the mysqldump command with ``docker exec {container_name}``.

    Args:
        container_name: Local Docker container name.
        db_name: Local database name to dump.
        skip_tables: Tables to exclude via --ignore-table.
        compress: Whether to pipe through gzip -1.

    Returns:
        The full docker exec mysqldump command string.
    """
    parts = ["mysqldump", *_MYSQLDUMP_FLAGS]

    if skip_tables:
        for table in skip_tables:
            parts.append(f"--ignore-table={db_name}.{table}")

    parts.append(db_name)

    mysqldump_cmd = " ".join(parts)

    if compress:
        mysqldump_cmd += " | gzip -1"

    return f"docker exec {container_name} sh -c \"{mysqldump_cmd}\""


def build_remote_import_command(
    db_name: str,
) -> str:
    """Build a mysql import command for the remote Cloudways server.

    Delegates to :func:`build_import_command` since the generated
    SQL is identical for both local and remote contexts.

    Args:
        db_name: Remote database name for import.

    Returns:
        The full import command string.
    """
    return build_import_command(db_name)


def build_remote_backup_command(
    db_name: str,
    backup_path: str,
    db_user: str = "",
    db_password: str = "",
) -> str:
    """Build a remote mysqldump command that writes to a file on the server.

    Args:
        db_name: Remote database name to back up.
        backup_path: Full remote path for the backup file.
        db_user: Database username (optional, uses .my.cnf if empty).
        db_password: Database password (optional).

    Returns:
        The full mysqldump command string that writes to a file.
    """
    parts = ["mysqldump", *_MYSQLDUMP_FLAGS]

    if db_user:
        parts.append(f"-u{db_user}")
    if db_password:
        parts.append(f"-p'{db_password}'")

    parts.append(db_name)

    cmd = " ".join(parts)
    return f"{cmd} | gzip -1 > {backup_path}"
