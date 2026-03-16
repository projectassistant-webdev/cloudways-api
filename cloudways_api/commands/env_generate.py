"""Generate and deploy Bedrock .env files to remote servers.

Pulls database credentials and app details from the Cloudways API v2,
generates WordPress salts locally, and renders a complete Bedrock .env
file from a template. Default mode uploads to ``public_html/shared/.env``
via SSH; ``--output`` and ``--stdout`` provide local-only alternatives.

Usage::

    cloudways env-generate production
    cloudways env-generate production --output .env.production
    cloudways env-generate production --stdout
    cloudways env-generate production --no-salts
    cloudways env-generate production --db-prefix custom_
"""

import asyncio
import re
import tempfile
from pathlib import Path

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.credentials import load_credentials
from cloudways_api.exceptions import APIError, ConfigError
from cloudways_api.salts import generate_placeholder_salts, generate_wp_salts
from cloudways_api.ssh import run_ssh_command, sftp_upload, validate_ssh_connection


@handle_cli_errors
def env_generate(
    environment: str = typer.Argument(
        help="Environment to generate .env for (production, staging)"
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (write locally instead of uploading)",
    ),
    stdout_flag: bool = typer.Option(
        False, "--stdout", help="Print to stdout instead of uploading"
    ),
    no_salts: bool = typer.Option(
        False, "--no-salts", help="Use placeholder values for salts"
    ),
    db_prefix: str = typer.Option("wp_", "--db-prefix", help="Database table prefix"),
) -> None:
    """Generate a Bedrock .env file and upload to remote server."""
    config = load_config()

    # Mutual exclusivity: --stdout and --output cannot be combined
    if stdout_flag and output is not None:
        err_console.print(
            "[bold red]Error:[/bold red] --stdout and --output are "
            "mutually exclusive. Use one or the other."
        )
        raise typer.Exit(code=1)

    # SSH validation only needed for default upload mode
    if not stdout_flag and output is None:
        validate_ssh_config(config)

    env_config = validate_environment(config, environment)

    asyncio.run(
        _execute_env_generate(
            config=config,
            env_config=env_config,
            environment=environment,
            output=output,
            stdout_flag=stdout_flag,
            no_salts=no_salts,
            db_prefix=db_prefix,
        )
    )


async def _execute_env_generate(
    config: dict,
    env_config: dict,
    environment: str,
    output: str | None,
    stdout_flag: bool,
    no_salts: bool,
    db_prefix: str,
) -> None:
    """Execute the env-generate workflow."""
    server_config = config["server"]
    server_id = str(server_config["id"])
    account_name = config["account"]
    app_id = str(env_config["app_id"])

    # Load credentials and create API client
    creds = load_credentials(account_name)

    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # 1. Get server/app data from API
        servers = await client.get_servers()
        server = _find_server(servers, server_id)
        app_data = _find_app_in_server(server, app_id)

        # 2. Extract database credentials
        db_name = app_data.get("mysql_db_name", "")
        db_user = app_data.get("mysql_user", "")
        db_password = app_data.get("mysql_password", "")

        # 3. Determine WP_HOME domain
        cname = app_data.get("cname", "").strip()
        app_fqdn = app_data.get("app_fqdn", "").strip()
        wp_home = cname if cname else app_fqdn

        # 4. Get Cloudflare CDN data (optional, non-fatal)
        cf_hostname_id = None
        try:
            cf_response = await client.get_cloudflare_cdn(int(server_id), int(app_id))
            cf_hostname_id = _extract_cf_hostname_id(cf_response, app_id)
        except (APIError, Exception):
            err_console.print(
                "[yellow]Warning:[/yellow] Cloudflare CDN data unavailable. "
                "Continuing without CF_HOSTNAME_ID."
            )

    # 5. Generate salts
    salts = generate_placeholder_salts() if no_salts else generate_wp_salts()

    # 6. Build template context
    context: dict[str, str] = {
        "DB_NAME": db_name,
        "DB_USER": db_user,
        "DB_PASSWORD": db_password,
        "DB_PREFIX": db_prefix,
        "WP_ENV": environment,
        "WP_HOME": wp_home,
        **salts,
    }
    if cf_hostname_id:
        context["CF_HOSTNAME_ID"] = cf_hostname_id

    # 7. Load template and render
    template = _load_template()
    rendered = render_bedrock_env(template, context)

    # 8. Output
    if stdout_flag:
        typer.echo(rendered, nl=False)
        return

    if output is not None:
        out_path = Path(output)
        out_path.write_text(rendered)
        console.print()
        console.print("[bold green]Environment Generated[/bold green]")
        console.print(f"  Environment: {environment}")
        console.print(f"  WP_ENV: {environment}")
        console.print(f"  Domain: {wp_home}")
        console.print(f"  Cloudflare: {'enabled' if cf_hostname_id else 'disabled'}")
        console.print(f"  Output: {out_path}")
        return

    # Default: upload to remote server
    ssh_user = server_config["ssh_user"]
    ssh_host = server_config["ssh_host"]

    # Validate SSH connectivity
    await validate_ssh_connection(ssh_host, ssh_user)

    # Check remote shared directory exists
    _, _, rc = await run_ssh_command(
        ssh_host, ssh_user, "test -d public_html/shared", raise_on_error=False
    )
    if rc != 0:
        raise ConfigError(
            "Remote directory public_html/shared/ not found. "
            "Run Capistrano setup first."
        )

    # Write to temp file and upload
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as tmp:
        tmp.write(rendered)
        tmp_path = tmp.name

    try:
        await sftp_upload(ssh_host, ssh_user, tmp_path, "public_html/shared/.env")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    console.print()
    console.print("[bold green]Environment Generated[/bold green]")
    console.print(f"  Environment: {environment}")
    console.print(f"  WP_ENV: {environment}")
    console.print(f"  Domain: {wp_home}")
    console.print(f"  Cloudflare: {'enabled' if cf_hostname_id else 'disabled'}")
    console.print("  Uploaded to: public_html/shared/.env")


def _find_server(servers: list[dict], server_id: str) -> dict:
    """Find a server by ID in the servers response.

    Args:
        servers: List of server dicts from the API.
        server_id: Server ID to match (string coercion).

    Returns:
        The matching server dict.

    Raises:
        ConfigError: If server_id not found.
    """
    for server in servers:
        if str(server.get("id")) == str(server_id):
            return server
    raise ConfigError(
        f"Server ID {server_id} not found in Cloudways API response. "
        "Check server.id in project-config.yml."
    )


def _find_app_in_server(server: dict, app_id: str | int) -> dict:
    """Find an app by ID within a specific server's apps list.

    Args:
        server: Server dict containing an ``apps`` list.
        app_id: Application ID to match (string coercion).

    Returns:
        The matching app dict.

    Raises:
        ConfigError: If not found.
    """
    for app_entry in server.get("apps", []):
        if str(app_entry.get("id")) == str(app_id):
            return app_entry
    raise ConfigError(
        f"App ID {app_id} not found on server {server.get('id')}. "
        "Check environments.{env}.app_id in project-config.yml."
    )


def _extract_cf_hostname_id(cf_response: dict, app_id: str) -> str | None:
    """Extract hostname_id from Cloudflare CDN response.

    Args:
        cf_response: API response dict from get_cloudflare_cdn().
        app_id: Application ID to match in dns entries.

    Returns:
        The hostname_id string, or None if CF is not enabled.
    """
    if not cf_response.get("status"):
        return None

    dns = cf_response.get("dns")
    if not dns or not isinstance(dns, list):
        return None

    for entry in dns:
        if str(entry.get("app_id")) == str(app_id):
            return entry.get("hostname_id")

    return None


def render_bedrock_env(template: str, context: dict) -> str:
    """Render a Bedrock .env from template string and context dict.

    Replaces ``{{KEY}}`` placeholders with values from context.
    Appends conditional Cloudflare section if ``CF_HOSTNAME_ID``
    is present in context.

    Args:
        template: Raw template string with ``{{placeholders}}``.
        context: Dict of key-value pairs for substitution.

    Returns:
        Rendered .env content string.
    """

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        if key not in context:
            raise ConfigError(f"Missing template variable: {key}")
        return context[key]

    rendered = re.sub(r"\{\{(\w+)\}\}", replacer, template)

    # Append CF section conditionally
    cf_id = context.get("CF_HOSTNAME_ID")
    if cf_id:
        rendered += f"\n# Cloudflare Enterprise\nCF_HOSTNAME_ID='{cf_id}'\n"

    return rendered


def _load_template() -> str:
    """Load the bedrock-env.template file.

    Returns:
        The raw template string.

    Raises:
        ConfigError: If template file not found.
    """
    # Navigate from cloudways_api/commands/ up to project root / templates/
    template_path = (
        Path(__file__).parent.parent.parent / "templates" / "bedrock-env.template"
    )
    if not template_path.is_file():
        raise ConfigError(
            f"Template file not found: {template_path}\n"
            "Hint: Ensure templates/bedrock-env.template exists in the project."
        )
    return template_path.read_text()
