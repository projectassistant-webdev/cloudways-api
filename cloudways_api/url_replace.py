"""URL replacement strategies for database sync.

Provides three methods for replacing production URLs with local
development URLs after a database pull:
- wp-cli: WordPress CLI search-replace (runs in Docker container)
- env-file: Replace domains in .env files
- sql-replace: Direct SQL UPDATE statements

Also provides remote variants for db-push operations:
- replace_urls_remote_wp_cli: wp search-replace via SSH on remote server
- replace_urls_remote_sql: SQL UPDATE via SSH on remote server
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from cloudways_api.exceptions import ConfigError
from cloudways_api.ssh import run_ssh_command


def get_url_replacer(
    method: str,
    remote: bool = False,
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Return the URL replacement function for the given method.

    Args:
        method: One of 'wp-cli', 'env-file', 'sql-replace'.
        remote: If True, return the remote-execution variant.

    Returns:
        Async callable that performs URL replacement.

    Raises:
        ConfigError: If method is not recognized.
        ConfigError: If remote=True and method='env-file' (not supported).
    """
    if remote:
        if method == "env-file":
            raise ConfigError(
                "URL replacement method 'env-file' is not supported "
                "for remote push. Use wp-cli or sql-replace."
            )

        remote_strategies: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {
            "wp-cli": replace_urls_remote_wp_cli,
            "sql-replace": replace_urls_remote_sql,
        }

        if method not in remote_strategies:
            raise ConfigError(
                f"Unknown url_replace_method '{method}'. "
                f"Valid options: wp-cli, sql-replace"
            )

        return remote_strategies[method]

    strategies: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {
        "wp-cli": replace_urls_wp_cli,
        "env-file": replace_urls_env_file,
        "sql-replace": replace_urls_sql_replace,
    }

    if method not in strategies:
        raise ConfigError(
            f"Unknown url_replace_method '{method}'. "
            f"Valid options: wp-cli, env-file, sql-replace"
        )

    return strategies[method]


async def replace_urls_wp_cli(
    source_domain: str,
    target_domain: str,
    container_name: str,
    app_path: str = "/var/www/html",
    **kwargs: Any,
) -> None:
    """Replace URLs using WordPress CLI search-replace.

    Runs wp search-replace inside the specified Docker container.

    Args:
        source_domain: The production domain to replace.
        target_domain: The local domain to replace with.
        container_name: Docker container running WordPress.
        app_path: Path to WordPress installation inside container.
        **kwargs: Additional keyword arguments (ignored for forward compatibility).
    """
    process = await asyncio.create_subprocess_exec(
        "docker", "exec", container_name,
        "wp", "search-replace",
        f"https://{source_domain}", f"http://{target_domain}",
        "--all-tables", "--precise", "--skip-columns=guid",
        f"--path={app_path}", "--allow-root",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise ConfigError(
            f"URL replacement failed (wp-cli): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )


async def replace_urls_env_file(
    source_domain: str,
    target_domain: str,
    env_file_path: str = ".env",
    **kwargs: Any,
) -> None:
    """Replace URLs in an environment file.

    Reads the file, replaces occurrences of source_domain with
    target_domain, and writes the file back.

    Args:
        source_domain: The production domain to replace.
        target_domain: The local domain to replace with.
        env_file_path: Path to the .env file.
        **kwargs: Additional keyword arguments (ignored for forward compatibility).
    """
    with open(env_file_path) as fh:
        content = fh.read()

    content = content.replace(source_domain, target_domain)

    with open(env_file_path, "w") as fh:
        fh.write(content)


async def replace_urls_sql_replace(
    source_domain: str,
    target_domain: str,
    db_name: str,
    container_name: str | None = None,
    **kwargs: Any,
) -> None:
    """Replace URLs using direct SQL UPDATE statements.

    Generates and executes UPDATE queries against wp_options,
    wp_posts, and wp_postmeta tables.  Skips the ``guid`` column
    in ``wp_posts`` because WordPress GUIDs must never change after
    publication (consistent with the wp-cli ``--skip-columns=guid``
    behaviour).

    Args:
        source_domain: The production domain to replace.
        target_domain: The local domain to replace with.
        db_name: Local database name.
        container_name: Optional Docker container for mysql client.
        **kwargs: Additional keyword arguments (ignored for forward compatibility).
    """
    # NOTE: wp_posts.guid is intentionally excluded. WordPress GUIDs
    # must never change after publication.  The wp-cli strategy
    # enforces this via --skip-columns=guid; sql-replace mirrors
    # that behaviour by omitting guid from UPDATE statements.
    sql = (
        f"UPDATE wp_options SET option_value = REPLACE(option_value, "
        f"'https://{source_domain}', 'http://{target_domain}') "
        f"WHERE option_name IN ('siteurl', 'home'); "
        f"UPDATE wp_posts SET post_content = REPLACE(post_content, "
        f"'https://{source_domain}', 'http://{target_domain}'); "
        f"UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, "
        f"'https://{source_domain}', 'http://{target_domain}') "
        f"WHERE meta_value LIKE '%{source_domain}%';"
    )

    cmd = ["mysql", db_name, "-e", sql]
    if container_name:
        cmd = ["docker", "exec", container_name] + cmd

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise ConfigError(
            f"URL replacement failed (sql-replace): "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )


async def replace_urls_remote_wp_cli(
    source_domain: str,
    target_domain: str,
    ssh_host: str,
    ssh_user: str,
    webroot: str = "public_html/current",
    **kwargs: Any,
) -> None:
    """Replace URLs using WordPress CLI on the remote server via SSH.

    Runs ``wp search-replace`` on the remote Cloudways server.  This
    is the remote-execution counterpart of :func:`replace_urls_wp_cli`
    which runs inside a local Docker container.

    Args:
        source_domain: The local domain to replace (e.g., ``"localhost"``).
        target_domain: The remote domain to replace with.
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        webroot: Path to WordPress installation on remote server.
        **kwargs: Additional keyword arguments (ignored).
    """
    wp_cmd = (
        f"cd {webroot} && wp search-replace "
        f"'http://{source_domain}' 'https://{target_domain}' "
        f"--all-tables --precise --skip-columns=guid --allow-root"
    )

    await run_ssh_command(ssh_host, ssh_user, wp_cmd, timeout=120)


async def replace_urls_remote_sql(
    source_domain: str,
    target_domain: str,
    db_name: str,
    ssh_host: str,
    ssh_user: str,
    **kwargs: Any,
) -> None:
    """Replace URLs using SQL UPDATE on the remote server via SSH.

    Executes SQL UPDATE statements against ``wp_options``,
    ``wp_posts``, and ``wp_postmeta`` tables via SSH.  Skips the
    ``guid`` column in ``wp_posts`` (consistent with wp-cli strategy).

    Args:
        source_domain: The local domain to replace.
        target_domain: The remote domain to replace with.
        db_name: Remote database name.
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        **kwargs: Additional keyword arguments (ignored).
    """
    # NOTE: wp_posts.guid is intentionally excluded (same as local variant).
    sql = (
        f"UPDATE wp_options SET option_value = REPLACE(option_value, "
        f"'http://{source_domain}', 'https://{target_domain}') "
        f"WHERE option_name IN ('siteurl', 'home'); "
        f"UPDATE wp_posts SET post_content = REPLACE(post_content, "
        f"'http://{source_domain}', 'https://{target_domain}'); "
        f"UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, "
        f"'http://{source_domain}', 'https://{target_domain}') "
        f"WHERE meta_value LIKE '%{source_domain}%';"
    )

    mysql_cmd = f'mysql {db_name} -e "{sql}"'
    await run_ssh_command(ssh_host, ssh_user, mysql_cmd, timeout=120)
