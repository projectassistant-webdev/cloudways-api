"""Cloudways API CLI entry point."""

import typer

from cloudways_api import __version__
from cloudways_api.commands.capistrano import capistrano as capistrano_command
from cloudways_api.commands.db_pull import db_pull as db_pull_command
from cloudways_api.commands.db_push import db_push as db_push_command
from cloudways_api.commands.db_restore import db_restore as db_restore_command
from cloudways_api.commands.db_sync import db_sync as db_sync_command
from cloudways_api.commands.env_capture import env_capture as env_capture_command
from cloudways_api.commands.env_generate import env_generate as env_generate_command
from cloudways_api.commands.info import info as info_command
from cloudways_api.commands.init_shared import init_shared as init_shared_command
from cloudways_api.commands.provision import provision_app_group
from cloudways_api.commands.ssh_cmd import ssh as ssh_command
from cloudways_api.commands.appsec import appsec_group
from cloudways_api.commands.alerts import alerts_group
from cloudways_api.commands.backup import backup_group
from cloudways_api.commands.cloudflare import cloudflare_group
from cloudways_api.commands.copilot import copilot_group
from cloudways_api.commands.safeupdates import safeupdates_group
from cloudways_api.commands.team import team_group
from cloudways_api.commands.monitor import monitor_group
from cloudways_api.commands.deploy_key import deploy_key_group
from cloudways_api.commands.disk import disk_group
from cloudways_api.commands.git import git_group
from cloudways_api.commands.security import security_group
from cloudways_api.commands.serversec import serversec_group
from cloudways_api.commands.server import server_group
from cloudways_api.commands.ssh_key import ssh_key_group
from cloudways_api.commands.ssh_setup import ssh_setup as ssh_setup_command
from cloudways_api.commands.ssh_user import ssh_user_group
from cloudways_api.commands.app_webroot import app_group
from cloudways_api.commands.reset_permissions import (
    reset_permissions as reset_permissions_command,
)
from cloudways_api.commands.services import services_group
from cloudways_api.commands.setup_bedrock import setup_bedrock as setup_bedrock_command
from cloudways_api.commands.setup_project import setup_project as setup_project_command
from cloudways_api.commands.verify_setup import verify_setup as verify_setup_command

app = typer.Typer(help="Cloudways API operations tool")


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"cloudways-api v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Cloudways API operations tool."""


app.command()(capistrano_command)
app.command()(info_command)
app.command(name="db-pull")(db_pull_command)
app.command(name="db-push")(db_push_command)
app.command(name="db-restore")(db_restore_command)
app.command(name="db-sync")(db_sync_command)
app.command(name="env-capture")(env_capture_command)
app.command(name="env-generate")(env_generate_command)
app.command()(ssh_command)
app.add_typer(provision_app_group, name="provision")
app.add_typer(ssh_user_group, name="ssh-user")
app.add_typer(ssh_key_group, name="ssh-key")
app.add_typer(deploy_key_group, name="deploy-key")
app.add_typer(git_group, name="git")
app.command(name="ssh-setup")(ssh_setup_command)
app.command(name="init-shared")(init_shared_command)
app.command(name="verify-setup")(verify_setup_command)
app.command(name="reset-permissions")(reset_permissions_command)
app.command(name="setup-bedrock")(setup_bedrock_command)
app.command(name="setup-project")(setup_project_command)
app.add_typer(alerts_group, name="alerts")
app.add_typer(appsec_group, name="appsec")
app.add_typer(app_group, name="app")
app.add_typer(backup_group, name="backup")
app.add_typer(cloudflare_group, name="cloudflare")
app.add_typer(copilot_group, name="copilot")
app.add_typer(safeupdates_group, name="safeupdates")
app.add_typer(monitor_group, name="monitor")
app.add_typer(disk_group, name="disk")
app.add_typer(security_group, name="security")
app.add_typer(serversec_group, name="serversec")
app.add_typer(server_group, name="server")
app.add_typer(services_group, name="services")
app.add_typer(team_group, name="team")


if __name__ == "__main__":
    app()
