"""Create shared directory structure and linked files on remote server.

Reads linked_files and linked_dirs from Capistrano config (or uses
defaults) and creates the necessary directory structure and files
in ``~/public_html/shared/`` on the remote server via SSH.

Usage::

    cloudways init-shared staging
    cloudways init-shared production --dry-run
    cloudways init-shared staging --with-cache-plugins
    cloudways init-shared staging --force
    cloudways init-shared staging --empty-htaccess
"""

import asyncio
from pathlib import Path

import typer

from cloudways_api.capistrano_parser import (
    get_linked_dirs_for_environment,
    get_linked_files_for_environment,
)
from cloudways_api.commands._shared import (
    console,
    handle_cli_errors,
    validate_environment,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.ssh import run_ssh_command

# Files that are handled by other commands (skip creating content)
_SKIP_CONTENT_FILES = {".env"}

# Cache plugin placeholder files
_CACHE_PLUGIN_FILES = [
    "web/app/object-cache.php",
    "web/app/advanced-cache.php",
]


def _load_template(name: str) -> str:
    """Load a template file from the templates/ directory.

    Args:
        name: Template filename (e.g., 'htaccess.template').

    Returns:
        Template content string.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    template_path = Path(__file__).parent.parent.parent / "templates" / name
    if not template_path.is_file():
        raise FileNotFoundError(
            f"Template not found: {template_path}. "
            "Ensure templates/ directory is intact."
        )
    return template_path.read_text()


def _get_file_content(
    file_path: str,
    environment: str,
    domain: str,
    empty_htaccess: bool = False,
) -> str | None:
    """Determine the content for a linked file.

    Args:
        file_path: Relative file path (e.g., 'web/.htaccess').
        environment: Environment name for template selection.
        domain: Domain for template placeholder replacement.
        empty_htaccess: If True, create empty .htaccess.

    Returns:
        File content string, or None if the file should be skipped.
    """
    basename = Path(file_path).name

    if file_path in _SKIP_CONTENT_FILES:
        return None

    if basename == ".htaccess":
        if empty_htaccess:
            return ""
        return _load_template("htaccess.template")

    if basename == "robots.txt":
        # Try environment-specific template first
        template_name = f"robots-{environment}.template"
        try:
            content = _load_template(template_name)
        except FileNotFoundError:
            # Fall back to staging template (blocks all crawlers)
            content = _load_template("robots-staging.template")

        # Replace {{WP_HOME}} placeholder with domain
        content = content.replace("{{WP_HOME}}", domain)
        return content

    # Unknown file type -- create empty
    return ""


@handle_cli_errors
def init_shared(
    environment: str = typer.Argument(
        help="Environment name from project config (e.g., staging, production)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be created without executing"
    ),
    with_cache_plugins: bool = typer.Option(
        False, "--with-cache-plugins", help="Include cache plugin placeholder files"
    ),
    empty_htaccess: bool = typer.Option(
        False,
        "--empty-htaccess",
        help="Create empty .htaccess instead of Bedrock template",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing linked files"
    ),
) -> None:
    """Create shared directory structure and linked files on remote server."""
    config = load_config()
    validate_ssh_config(config)
    env_config = validate_environment(config, environment)

    asyncio.run(
        _execute_init_shared(
            config=config,
            env_config=env_config,
            environment=environment,
            dry_run=dry_run,
            with_cache_plugins=with_cache_plugins,
            empty_htaccess=empty_htaccess,
            force=force,
        )
    )


async def _execute_init_shared(
    config: dict,
    env_config: dict,
    environment: str,
    dry_run: bool,
    with_cache_plugins: bool,
    empty_htaccess: bool,
    force: bool,
) -> None:
    """Execute the init-shared workflow."""
    server_config = config["server"]
    ssh_host = server_config["ssh_host"]
    ssh_user = env_config.get("ssh_user", server_config["ssh_user"])
    domain = env_config.get("domain", "")

    # Get linked files and dirs from Capistrano config or defaults
    linked_files = get_linked_files_for_environment(environment)
    linked_dirs = get_linked_dirs_for_environment()

    # Filter out .env from linked files (handled by env-generate)
    actionable_files = [f for f in linked_files if f not in _SKIP_CONTENT_FILES]

    # Collect all directories to create
    all_dirs = set()
    for d in linked_dirs:
        all_dirs.add(f"~/public_html/shared/{d}")
    for f in linked_files:
        parent = str(Path(f).parent)
        if parent != ".":
            all_dirs.add(f"~/public_html/shared/{parent}")

    # Summary tracking
    created = []
    skipped = []
    failed = []

    if dry_run:
        console.print(
            "\n[bold yellow]Dry Run[/bold yellow] - No changes will be made\n"
        )
        console.print("[bold]Directories to create:[/bold]")
        for d in sorted(all_dirs):
            console.print(f"  mkdir -p {d}")
        console.print("\n[bold]Linked files to create:[/bold]")
        for f in actionable_files:
            console.print(f"  {f}")
        if with_cache_plugins:
            console.print("\n[bold]Cache plugin files:[/bold]")
            for f in _CACHE_PLUGIN_FILES:
                console.print(f"  {f}")
        console.print()
        return

    # Step 1: Create all directories
    mkdir_cmd = " ".join(f"'{d}'" for d in sorted(all_dirs))
    if mkdir_cmd:
        await run_ssh_command(
            ssh_host,
            ssh_user,
            f"mkdir -p {mkdir_cmd}",
        )

    # Step 2: Create linked files
    for file_path in actionable_files:
        remote_path = f"~/public_html/shared/{file_path}"

        # Check if file already exists (unless --force)
        if not force:
            _, _, rc = await run_ssh_command(
                ssh_host,
                ssh_user,
                f"test -f {remote_path}",
                raise_on_error=False,
            )
            if rc == 0:
                skipped.append(file_path)
                console.print(f"  [yellow]SKIP[/yellow]  {file_path} (already exists)")
                continue

        # Get content for the file
        content = _get_file_content(file_path, environment, domain, empty_htaccess)
        if content is None:
            continue

        # Create file with content via SSH using heredoc
        await run_ssh_command(
            ssh_host,
            ssh_user,
            f"cat > {remote_path} << 'CLOUDWAYS_EOF'\n{content}\nCLOUDWAYS_EOF",
        )
        created.append(file_path)
        console.print(f"  [green]CREATED[/green]  {file_path}")

    # Step 3: Cache plugin placeholder files
    if with_cache_plugins:
        # Ensure parent directory exists
        await run_ssh_command(
            ssh_host,
            ssh_user,
            "mkdir -p ~/public_html/shared/web/app",
            raise_on_error=False,
        )

        for cache_file in _CACHE_PLUGIN_FILES:
            remote_path = f"~/public_html/shared/{cache_file}"

            if not force:
                _, _, rc = await run_ssh_command(
                    ssh_host,
                    ssh_user,
                    f"test -f {remote_path}",
                    raise_on_error=False,
                )
                if rc == 0:
                    skipped.append(cache_file)
                    console.print(
                        f"  [yellow]SKIP[/yellow]  {cache_file} (already exists)"
                    )
                    continue

            await run_ssh_command(
                ssh_host,
                ssh_user,
                f"touch {remote_path}",
            )
            created.append(cache_file)
            console.print(f"  [green]CREATED[/green]  {cache_file}")

    # Step 4: Summary
    console.print()
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Created: {len(created)} files")
    if skipped:
        console.print(f"  Skipped: {len(skipped)} files (already exist)")
    if failed:
        console.print(f"  Failed: {len(failed)} files")
    console.print()
