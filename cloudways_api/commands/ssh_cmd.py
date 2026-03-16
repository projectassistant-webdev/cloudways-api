"""Open an SSH session or execute remote commands.

Supports two modes:
- Interactive (default): Replaces the current process with an SSH
  session via ``os.execvp``, landing in the application directory.
- Exec (command after ``--``): Runs the command remotely and prints
  stdout/stderr, exiting with the remote command's exit code.

Usage::

    cloudways ssh production              # interactive, app directory
    cloudways ssh production --server     # interactive, server root
    cloudways ssh production -- wp plugin list   # exec mode
"""

import asyncio
import os
import shlex
import sys
from typing import Optional

import typer

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.exceptions import (
    CloudwaysError,
)
from cloudways_api.ssh import build_interactive_ssh_args, run_ssh_command


@handle_cli_errors
def ssh(
    environment: str = typer.Argument(
        "production", help="Environment to connect to (production, staging)"
    ),
    server: bool = typer.Option(
        False, "--server", help="SSH to server root instead of app directory"
    ),
    command: Optional[list[str]] = typer.Argument(
        None, help="Command to execute (exec mode). Pass after --"
    ),
) -> None:
    """Open SSH session or execute remote commands."""
    config = load_config()
    validate_ssh_config(config)
    env_config = validate_environment(config, environment)

    ssh_user = config["server"]["ssh_user"]
    ssh_host = config["server"]["ssh_host"]
    webroot = env_config.get("webroot", DEFAULT_WEBROOT)

    if command:
        # Exec mode: run command remotely and return output
        asyncio.run(
            _execute_ssh_command(
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                webroot=webroot,
                remote_command=command,
                server_flag=server,
            )
        )
    else:
        # Interactive mode: replace process with SSH
        _interactive_ssh(
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            webroot=webroot,
            server_flag=server,
        )


def _resolve_app_path(webroot: str) -> str:
    """Build the remote command to cd into the app directory.

    Args:
        webroot: Webroot path from config.

    Returns:
        A shell command string that changes to the app directory
        and starts a login shell.
    """
    return f"cd {shlex.quote(webroot)} && exec $SHELL -l"


def _interactive_ssh(
    ssh_host: str,
    ssh_user: str,
    webroot: str,
    server_flag: bool,
) -> None:
    """Launch an interactive SSH session via os.execvp.

    This replaces the current Python process with the SSH client.
    """
    remote_command: str | None = None
    if not server_flag:
        remote_command = _resolve_app_path(webroot)

    args = build_interactive_ssh_args(
        host=ssh_host,
        user=ssh_user,
        remote_command=remote_command,
    )

    try:
        os.execvp("ssh", args)
    except OSError as exc:
        raise CloudwaysError(f"Could not launch SSH session: {exc}") from exc


async def _execute_ssh_command(
    ssh_host: str,
    ssh_user: str,
    webroot: str,
    remote_command: list[str],
    server_flag: bool,
) -> None:
    """Execute a remote command via SSH and print output.

    Args:
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        webroot: Webroot path from config.
        remote_command: List of command tokens to execute.
        server_flag: Whether to run from server root.

    Raises:
        typer.Exit: With the remote command's actual exit code.
    """
    cmd_str = shlex.join(remote_command)

    # If not in server mode, prefix with cd to webroot
    if not server_flag:
        cmd_str = f"cd {shlex.quote(webroot)} && {cmd_str}"

    stdout, stderr, returncode = await run_ssh_command(
        ssh_host, ssh_user, cmd_str, raise_on_error=False
    )

    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)

    if returncode != 0:
        raise typer.Exit(code=returncode)
