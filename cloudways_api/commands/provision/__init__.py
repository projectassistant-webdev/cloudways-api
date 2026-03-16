"""Provision sub-commands for creating servers and applications on Cloudways."""

import typer

from cloudways_api.commands.provision.app import provision_app
from cloudways_api.commands.provision.server import provision_server
from cloudways_api.commands.provision.staging import provision_staging

provision_app_group = typer.Typer(
    help="Provision servers and applications on Cloudways."
)

provision_app_group.command(name="server")(provision_server)
provision_app_group.command(name="app")(provision_app)
provision_app_group.command(name="staging")(provision_staging)
