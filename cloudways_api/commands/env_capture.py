"""Capture environment variables from a remote WordPress server.

Automatically detects Bedrock (.env) vs traditional (wp-config.php)
installations and outputs captured variables to a file or stdout.

Usage::

    cloudways env-capture production
    cloudways env-capture production --output .env.local
    cloudways env-capture production --stdout
"""

import asyncio
from pathlib import Path

import typer

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    console,
    err_console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.env_detect import (
    capture_bedrock_env,
    capture_traditional_env,
    detect_env_type,
    format_env_output,
)
from cloudways_api.exceptions import (
    CloudwaysError,
    ConfigError,
)


@handle_cli_errors
def env_capture(
    environment: str = typer.Argument(
        help="Environment to capture from (production, staging)"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output file path (default: .env.{environment})"
    ),
    stdout_flag: bool = typer.Option(
        False, "--stdout", help="Print to stdout instead of writing file"
    ),
) -> None:
    """Capture environment variables from a remote server."""
    config = load_config()
    validate_ssh_config(config)
    env_config = validate_environment(config, environment)

    # Mutual exclusivity: --stdout and --output cannot be combined
    if stdout_flag and output is not None:
        err_console.print(
            "[bold red]Error:[/bold red] --stdout and --output are "
            "mutually exclusive. Use one or the other."
        )
        raise typer.Exit(code=1)

    asyncio.run(
        _execute_env_capture(
            config=config,
            env_config=env_config,
            environment=environment,
            output=output,
            stdout_flag=stdout_flag,
        )
    )


async def _execute_env_capture(
    config: dict,
    env_config: dict,
    environment: str,
    output: str | None,
    stdout_flag: bool,
) -> None:
    """Execute the env-capture workflow."""
    server = config["server"]
    ssh_user = server["ssh_user"]
    ssh_host = server["ssh_host"]
    webroot = env_config.get("webroot", DEFAULT_WEBROOT)

    # Detect environment type
    env_type = await detect_env_type(ssh_host, ssh_user, webroot)

    if env_type == "bedrock":
        content = await capture_bedrock_env(ssh_host, ssh_user, webroot)
        var_count = len(
            [
                line
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )
    else:
        env_vars = await capture_traditional_env(ssh_host, ssh_user, webroot)
        if not env_vars:
            raise ConfigError(
                "Could not parse any environment variables from wp-config.php. "
                "Verify the file format."
            )
        content = format_env_output(env_vars, env_type)
        var_count = len(env_vars)

    # Output
    if stdout_flag:
        typer.echo(content, nl=False)
        return

    out_path = Path(output) if output else Path(f".env.{environment}")
    try:
        out_path.write_text(content)
    except OSError as exc:
        raise CloudwaysError(f"Could not write to {out_path}: {exc}") from exc

    console.print()
    console.print("[bold green]Environment Captured[/bold green]")
    console.print(f"  Environment: {environment}")
    console.print(f"  Type: {env_type}")
    console.print(f"  Output: {out_path}")
    console.print(f"  Variables: {var_count}")
