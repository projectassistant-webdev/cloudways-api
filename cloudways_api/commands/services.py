"""Services deploy command - render and upload services.sh to server."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import typer

from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)
from cloudways_api.config import ConfigError, validate_ssh_config
from cloudways_api.ssh import sftp_upload

_DEFAULT_TEMPLATE = (
    Path(__file__).parent.parent / "templates" / "cloudways-services.sh.template"
)

services_group = typer.Typer(help="Manage services.sh deployment.")


@services_group.command(name="deploy")
@handle_cli_errors
def services_deploy(
    environment: str = typer.Argument(..., help="Environment name"),
    template: Path | None = typer.Option(
        None, "--template", help="Template path override"
    ),
) -> None:
    """Render and deploy services.sh to the server."""
    asyncio.run(
        _services_deploy_async(environment=environment, template_override=template)
    )


async def _services_deploy_async(
    *, environment: str, template_override: Path | None
) -> None:
    """Async implementation of the services deploy workflow."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    validate_ssh_config(config)

    ssh_host = config["server"]["ssh_host"]
    master_user = config["server"]["ssh_user"]

    ssh_user = env_config.get("ssh_user")
    if not ssh_user:
        raise ConfigError(
            f"Missing 'environments.{environment}.ssh_user' in project-config.yml. "
            "Required for services deploy. Set to the app-level SSH user "
            "(e.g., unsvkhbwwr)."
        )

    template_path = template_override or _DEFAULT_TEMPLATE
    if not template_path.is_file():
        raise ConfigError(f"Template not found: {template_path}")

    template_text = template_path.read_text()
    rendered = template_text.replace("CLOUDWAYS_EMAIL", creds["email"])
    rendered = rendered.replace("CLOUDWAYS_API_KEY", creds["api_key"])

    remote_path = f"/home/master/applications/{ssh_user}/private_html/services.sh"

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as tmp:
            tmp.write(rendered)
            tmp_path = tmp.name

        with console.status("[bold green]Uploading services.sh...[/bold green]"):
            await sftp_upload(ssh_host, master_user, tmp_path, remote_path)
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)

    console.print(
        f"[bold green]services.sh deployed to {environment} "
        f"({remote_path}).[/bold green]"
    )
