"""Manage Cloudways server security, IP whitelisting, and SSL certificates.

Provides whitelist list/add/remove, blacklist-check, whitelist-siab,
whitelist-adminer, and SSL certificate management commands for the
configured project server via the Cloudways API v2.

Usage::

    cloudways security whitelist list [--type sftp|mysql]
    cloudways security whitelist add --ip <ip> [--type sftp|mysql]
    cloudways security whitelist remove --ip <ip> [--type sftp|mysql]
    cloudways security blacklist-check --ip <ip>
    cloudways security whitelist-siab --ip <ip>
    cloudways security whitelist-adminer --ip <ip>
    cloudways security ssl install <env> --email <email> --domains <domains> [--wildcard]
    cloudways security ssl renew <env> [--wildcard] [--email <email>] [--domain <domain>]
    cloudways security ssl auto <env> --enable | --disable
    cloudways security ssl revoke <env> --domain <domain> [--wildcard]
    cloudways security ssl install-custom <env> --cert-file <path> --key-file <path>
    cloudways security ssl remove-custom <env>
"""

import asyncio
from pathlib import Path

import typer

from cloudways_api.client import CloudwaysClient
from cloudways_api.commands._shared import (
    console,
    err_console,
    handle_cli_errors,
    load_creds,
    validate_environment,
)

security_group = typer.Typer(help="Manage server security and IP whitelisting.")
whitelist_group = typer.Typer(help="Manage IP whitelist for SSH/SFTP and MySQL access.")
security_group.add_typer(whitelist_group, name="whitelist")

ssl_group = typer.Typer(help="Manage SSL certificates.")
security_group.add_typer(ssl_group, name="ssl")


# ------------------------------------------------------------------
# Whitelist list / add / remove
# ------------------------------------------------------------------


@whitelist_group.command(name="list")
@handle_cli_errors
def whitelist_list(
    list_type: str = typer.Option(
        "sftp", "--type", help="Whitelist type: sftp or mysql", metavar="sftp|mysql"
    ),
) -> None:
    """List whitelisted IPs for SSH/SFTP or MySQL access."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_whitelist_list(creds=creds, server_id=server_id, list_type=list_type)
    )


async def _execute_whitelist_list(creds: dict, server_id: int, list_type: str) -> None:
    """Execute whitelist list workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        if list_type == "mysql":
            ip_list = await client.get_whitelisted_ips_mysql(server_id=server_id)
        else:
            ip_list = await client.get_whitelisted_ips(server_id=server_id)

        if ip_list:
            for ip in ip_list:
                console.print(ip)
        else:
            console.print("No IPs whitelisted.")


@whitelist_group.command(name="add")
@handle_cli_errors
def whitelist_add(
    ip: str = typer.Option(..., "--ip", help="IP address to whitelist"),
    list_type: str = typer.Option(
        "sftp", "--type", help="Whitelist type: sftp or mysql", metavar="sftp|mysql"
    ),
) -> None:
    """Add an IP to the whitelist (read-modify-write)."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_whitelist_add(
            creds=creds, server_id=server_id, ip=ip, list_type=list_type
        )
    )


async def _execute_whitelist_add(
    creds: dict, server_id: int, ip: str, list_type: str
) -> None:
    """Execute whitelist add workflow (read-modify-write)."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # READ
        if list_type == "mysql":
            current_list = await client.get_whitelisted_ips_mysql(server_id=server_id)
        else:
            current_list = await client.get_whitelisted_ips(server_id=server_id)
        # CHECK idempotency
        if ip in current_list:
            console.print(f"IP {ip} is already whitelisted.")
            return
        # MODIFY
        updated_list = current_list + [ip]
        # WRITE
        await client.update_whitelisted_ips(
            server_id=server_id, ip_list=updated_list, tab=list_type
        )
        console.print(f"Added {ip} to {list_type} whitelist.")


@whitelist_group.command(name="remove")
@handle_cli_errors
def whitelist_remove(
    ip: str = typer.Option(..., "--ip", help="IP address to remove from whitelist"),
    list_type: str = typer.Option(
        "sftp", "--type", help="Whitelist type: sftp or mysql", metavar="sftp|mysql"
    ),
) -> None:
    """Remove an IP from the whitelist (read-modify-write)."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(
        _execute_whitelist_remove(
            creds=creds, server_id=server_id, ip=ip, list_type=list_type
        )
    )


async def _execute_whitelist_remove(
    creds: dict, server_id: int, ip: str, list_type: str
) -> None:
    """Execute whitelist remove workflow (read-modify-write)."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        # READ
        if list_type == "mysql":
            current_list = await client.get_whitelisted_ips_mysql(server_id=server_id)
        else:
            current_list = await client.get_whitelisted_ips(server_id=server_id)
        # CHECK
        if ip not in current_list:
            console.print(f"IP {ip} is not in the whitelist.")
            return
        # MODIFY
        updated_list = [x for x in current_list if x != ip]
        # WRITE (may be empty list - that is allowed)
        await client.update_whitelisted_ips(
            server_id=server_id, ip_list=updated_list, tab=list_type
        )
        console.print(f"Removed {ip} from {list_type} whitelist.")


# ------------------------------------------------------------------
# Standalone security commands
# ------------------------------------------------------------------


@security_group.command(name="blacklist-check")
@handle_cli_errors
def blacklist_check(
    ip: str = typer.Option(..., "--ip", help="IP address to check"),
) -> None:
    """Check if an IP is blacklisted on the server."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_blacklist_check(creds=creds, server_id=server_id, ip=ip))


async def _execute_blacklist_check(creds: dict, server_id: int, ip: str) -> None:
    """Execute blacklist check workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        is_blacklisted = await client.check_ip_blacklisted(server_id=server_id, ip=ip)
        if is_blacklisted:
            console.print(f"IP {ip} is blacklisted.")
        else:
            console.print(f"IP {ip} is not blacklisted.")


@security_group.command(name="whitelist-siab")
@handle_cli_errors
def whitelist_siab_cmd(
    ip: str = typer.Option(..., "--ip", help="IP address to whitelist for Web SSH"),
) -> None:
    """Whitelist an IP for Web SSH (Shell-in-a-Box) access."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_whitelist_siab(creds=creds, server_id=server_id, ip=ip))


async def _execute_whitelist_siab(creds: dict, server_id: int, ip: str) -> None:
    """Execute whitelist SIAB workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.whitelist_siab(server_id=server_id, ip=ip)
        console.print(f"Whitelisted {ip} for Web SSH (Shell-in-a-Box).")


@security_group.command(name="whitelist-adminer")
@handle_cli_errors
def whitelist_adminer_cmd(
    ip: str = typer.Option(..., "--ip", help="IP address to whitelist for Adminer"),
) -> None:
    """Whitelist an IP for Adminer (database manager) access."""
    creds, config = load_creds()
    server_id = int(config["server"]["id"])
    asyncio.run(_execute_whitelist_adminer(creds=creds, server_id=server_id, ip=ip))


async def _execute_whitelist_adminer(creds: dict, server_id: int, ip: str) -> None:
    """Execute whitelist Adminer workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.whitelist_adminer(server_id=server_id, ip=ip)
        console.print(f"Whitelisted {ip} for Adminer (database manager).")


# ------------------------------------------------------------------
# SSL Certificate Management
# ------------------------------------------------------------------


@ssl_group.command(name="install")
@handle_cli_errors
def ssl_install(
    environment: str = typer.Argument(help="Environment name from project config"),
    email: str = typer.Option(..., "--email", help="Email for SSL certificate"),
    domains: str = typer.Option(..., "--domains", help="Comma-separated domain list"),
    wildcard: bool = typer.Option(
        False, "--wildcard", help="Install wildcard SSL (two-step DNS flow)"
    ),
) -> None:
    """Install a Let's Encrypt SSL certificate."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    ssl_domains = [d.strip() for d in domains.split(",") if d.strip()]
    if not ssl_domains:
        err_console.print("[bold red]Error:[/bold red] No valid domains provided.")
        raise typer.Exit(code=1)

    if wildcard:
        # Step 1: createDNS
        dns_result = asyncio.run(
            _execute_create_dns(
                creds=creds,
                server_id=server_id,
                app_id=app_id,
                email=email,
                ssl_domains=ssl_domains,
            )
        )
        # Display DNS record info
        wildcard_info = dns_result.get("wildcard_ssl", {}).get("wildcard", {})
        app_prefix = wildcard_info.get("app_prefix", "")
        console.print(f"Add the TXT record to your DNS provider for: {app_prefix}")

        # Step 2: prompt user
        typer.confirm("Have you added the DNS TXT record?", abort=True)

        # Step 3: verifyDNS
        verify_result = asyncio.run(
            _execute_verify_dns(
                creds=creds,
                server_id=server_id,
                app_id=app_id,
                email=email,
                ssl_domains=ssl_domains,
            )
        )
        if not verify_result.get("wildcard_ssl", {}).get("status", False):
            err_console.print(
                "[bold red]Error:[/bold red] DNS verification failed. "
                "Ensure the TXT record is live and retry."
            )
            raise typer.Exit(code=1)

        # Step 4: install with wildcard
        result = asyncio.run(
            _execute_ssl_install(
                creds=creds,
                server_id=server_id,
                app_id=app_id,
                email=email,
                ssl_domains=ssl_domains,
                wild_card=True,
            )
        )
        console.print(
            f"Wildcard SSL installation started. Operation ID: {result['operation_id']}"
        )
    else:
        result = asyncio.run(
            _execute_ssl_install(
                creds=creds,
                server_id=server_id,
                app_id=app_id,
                email=email,
                ssl_domains=ssl_domains,
                wild_card=False,
            )
        )
        console.print(
            f"SSL installation started. Operation ID: {result['operation_id']}"
        )


async def _execute_create_dns(
    creds: dict,
    server_id: int,
    app_id: int,
    email: str,
    ssl_domains: list[str],
) -> dict:
    """Execute createDNS API call."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        return await client.create_wildcard_dns(
            server_id=server_id,
            app_id=app_id,
            ssl_email=email,
            ssl_domains=ssl_domains,
        )


async def _execute_verify_dns(
    creds: dict,
    server_id: int,
    app_id: int,
    email: str,
    ssl_domains: list[str],
) -> dict:
    """Execute verifyDNS API call."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        return await client.verify_wildcard_dns(
            server_id=server_id,
            app_id=app_id,
            ssl_email=email,
            ssl_domains=ssl_domains,
        )


async def _execute_ssl_install(
    creds: dict,
    server_id: int,
    app_id: int,
    email: str,
    ssl_domains: list[str],
    wild_card: bool,
) -> dict:
    """Execute Let's Encrypt install API call."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        return await client.install_lets_encrypt(
            server_id=server_id,
            app_id=app_id,
            ssl_email=email,
            ssl_domains=ssl_domains,
            wild_card=wild_card,
        )


@ssl_group.command(name="renew")
@handle_cli_errors
def ssl_renew(
    environment: str = typer.Argument(help="Environment name from project config"),
    wildcard: bool = typer.Option(
        False, "--wildcard", help="Renew wildcard SSL certificate"
    ),
    email: str | None = typer.Option(
        None, "--email", help="Email (required for wildcard)"
    ),
    domain: str | None = typer.Option(
        None, "--domain", help="Domain (optional for wildcard)"
    ),
) -> None:
    """Manually renew a Let's Encrypt SSL certificate."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    if wildcard and email is None:
        err_console.print(
            "[bold red]Error:[/bold red] --email is required for wildcard renewal."
        )
        raise typer.Exit(code=1)

    asyncio.run(
        _execute_ssl_renew(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            wildcard=wildcard,
            email=email,
            domain=domain,
        )
    )


async def _execute_ssl_renew(
    creds: dict,
    server_id: int,
    app_id: int,
    wildcard: bool,
    email: str | None,
    domain: str | None,
) -> None:
    """Execute SSL renewal workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.renew_lets_encrypt(
            server_id=server_id,
            app_id=app_id,
            wild_card=wildcard,
            ssl_email=email,
            domain=domain,
        )
        console.print(f"SSL renewal started. Operation ID: {result['operation_id']}")


@ssl_group.command(name="auto")
@handle_cli_errors
def ssl_auto(
    environment: str = typer.Argument(help="Environment name from project config"),
    enable: bool = typer.Option(False, "--enable", help="Enable auto-renewal"),
    disable: bool = typer.Option(False, "--disable", help="Disable auto-renewal"),
) -> None:
    """Enable or disable Let's Encrypt auto-renewal."""
    if enable == disable:
        err_console.print(
            "[bold red]Error:[/bold red] Specify exactly one of --enable or --disable."
        )
        raise typer.Exit(code=1)

    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssl_auto(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            auto=enable,
        )
    )

    if enable:
        console.print("Auto-renewal enabled.")
    else:
        console.print("Auto-renewal disabled.")


async def _execute_ssl_auto(
    creds: dict,
    server_id: int,
    app_id: int,
    auto: bool,
) -> None:
    """Execute SSL auto-renewal toggle."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.set_lets_encrypt_auto(
            server_id=server_id,
            app_id=app_id,
            auto=auto,
        )


@ssl_group.command(name="revoke")
@handle_cli_errors
def ssl_revoke(
    environment: str = typer.Argument(help="Environment name from project config"),
    domain: str = typer.Option(..., "--domain", help="SSL domain to revoke"),
    wildcard: bool = typer.Option(
        False, "--wildcard", help="Revoke wildcard SSL certificate"
    ),
) -> None:
    """Revoke a Let's Encrypt SSL certificate."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssl_revoke(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            domain=domain,
            wildcard=wildcard,
        )
    )


async def _execute_ssl_revoke(
    creds: dict,
    server_id: int,
    app_id: int,
    domain: str,
    wildcard: bool,
) -> None:
    """Execute SSL revocation workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.revoke_lets_encrypt(
            server_id=server_id,
            app_id=app_id,
            ssl_domain=domain,
            wild_card=wildcard,
        )
        console.print(f"SSL revocation started. Operation ID: {result['operation_id']}")


@ssl_group.command(name="install-custom")
@handle_cli_errors
def ssl_install_custom(
    environment: str = typer.Argument(help="Environment name from project config"),
    cert_file: str = typer.Option(
        ..., "--cert-file", help="Path to SSL certificate PEM file"
    ),
    key_file: str = typer.Option(
        ..., "--key-file", help="Path to SSL private key PEM file"
    ),
    password: str | None = typer.Option(
        None, "--password", help="Optional certificate password"
    ),
) -> None:
    """Install a custom SSL certificate from PEM files."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    ssl_crt = Path(cert_file).read_text()
    ssl_key = Path(key_file).read_text()

    asyncio.run(
        _execute_ssl_install_custom(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
            ssl_crt=ssl_crt,
            ssl_key=ssl_key,
            password=password,
        )
    )


async def _execute_ssl_install_custom(
    creds: dict,
    server_id: int,
    app_id: int,
    ssl_crt: str,
    ssl_key: str,
    password: str | None,
) -> None:
    """Execute custom SSL installation workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        await client.install_custom_ssl(
            server_id=server_id,
            app_id=app_id,
            ssl_crt=ssl_crt,
            ssl_key=ssl_key,
            password=password,
        )
        console.print("Custom SSL certificate installed successfully.")


@ssl_group.command(name="remove-custom")
@handle_cli_errors
def ssl_remove_custom(
    environment: str = typer.Argument(help="Environment name from project config"),
) -> None:
    """Remove a custom SSL certificate."""
    creds, config = load_creds()
    env_config = validate_environment(config, environment)
    server_id = int(config["server"]["id"])
    app_id = int(env_config["app_id"])

    asyncio.run(
        _execute_ssl_remove_custom(
            creds=creds,
            server_id=server_id,
            app_id=app_id,
        )
    )


async def _execute_ssl_remove_custom(
    creds: dict,
    server_id: int,
    app_id: int,
) -> None:
    """Execute custom SSL removal workflow."""
    async with CloudwaysClient(creds["email"], creds["api_key"]) as client:
        result = await client.remove_custom_ssl(
            server_id=server_id,
            app_id=app_id,
        )
        console.print(
            f"Custom SSL removal started. Operation ID: {result['operation_id']}"
        )
