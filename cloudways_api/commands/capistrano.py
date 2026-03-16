"""Generate Capistrano deployment configuration files.

Creates Capistrano config files for Bedrock WordPress deployments.
Optionally generates a Bitbucket Pipelines configuration.

Usage::

    cloudways capistrano                   # generate all files
    cloudways capistrano --with-pipelines  # include bitbucket-pipelines.yml
    cloudways capistrano --preview         # print to stdout only
    cloudways capistrano --force           # overwrite existing files
"""

import re
from pathlib import Path

import typer

from cloudways_api.commands._shared import (
    DEFAULT_WEBROOT,
    console,
    err_console,
    handle_cli_errors,
)
from cloudways_api.config import load_config, validate_ssh_config
from cloudways_api.exceptions import (
    CloudwaysError,
)
from cloudways_api.templates import (
    render_capfile,
    render_deploy_rb,
    render_gemfile,
    render_pipelines,
    render_stage_deploy,
)


def detect_repo_url() -> str | None:
    """Detect git remote origin URL from .git/config.

    Parses the local ``.git/config`` file to find the
    ``[remote "origin"]`` section and extract the ``url`` value.

    Returns:
        The repository URL, or ``None`` if not detectable.
    """
    git_config_path = Path(".git/config")
    if not git_config_path.is_file():
        return None

    try:
        content = git_config_path.read_text()
    except OSError:
        return None

    # Find [remote "origin"] section and extract url
    in_origin = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == '[remote "origin"]':
            in_origin = True
            continue
        if in_origin:
            if stripped.startswith("["):
                # New section started, stop looking
                break
            match = re.match(r"url\s*=\s*(.+)", stripped)
            if match:
                return match.group(1).strip()

    return None


def derive_app_name(repo_url: str) -> str:
    """Derive application name from a repository URL.

    Strips the ``.git`` suffix and returns the basename.

    Args:
        repo_url: Git repository URL (SSH or HTTPS format).

    Returns:
        The application name (basename of URL without ``.git``).
    """
    # Handle both SSH (git@host:user/repo.git) and HTTPS formats
    basename = repo_url.rstrip("/").rsplit("/", 1)[-1]
    # Also handle SSH colon format: git@host:user/repo.git
    basename = basename.rsplit(":", 1)[-1]
    if "/" in basename:
        basename = basename.rsplit("/", 1)[-1]
    if basename.endswith(".git"):
        basename = basename[:-4]
    return basename


def _is_bedrock_project() -> bool:
    """Check if the current project appears to be a Bedrock WordPress project.

    Looks for common Bedrock indicators in the current directory.

    Returns:
        True if Bedrock indicators are found.
    """
    return Path(".env").is_file() or Path("web").is_dir()


@handle_cli_errors
def capistrano(
    with_pipelines: bool = typer.Option(
        False, "--with-pipelines", help="Also generate bitbucket-pipelines.yml"
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Print to stdout instead of writing files"
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files"),
) -> None:
    """Generate Capistrano deployment configuration."""
    config = load_config()
    validate_ssh_config(config)

    # Validate environments exist
    environments = config.get("environments", {})
    if not environments:
        err_console.print(
            "[bold red]Error:[/bold red] No environments configured. "
            "Add at least one environment to project-config.yml."
        )
        raise typer.Exit(code=1)

    # Detect repo URL
    repo_url = detect_repo_url()
    if repo_url is None:
        err_console.print(
            "[bold red]Error:[/bold red] Could not detect repository URL. "
            "Add a git remote origin or set repo_url in config."
        )
        raise typer.Exit(code=1)

    ssh_user = config["server"]["ssh_user"]
    ssh_host = config["server"]["ssh_host"]
    application = derive_app_name(repo_url)

    _generate_files(
        environments=environments,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        application=application,
        repo_url=repo_url,
        with_pipelines=with_pipelines,
        preview=preview,
        force=force,
    )


def _generate_files(
    environments: dict,
    ssh_host: str,
    ssh_user: str,
    application: str,
    repo_url: str,
    with_pipelines: bool,
    preview: bool,
    force: bool,
) -> None:
    """Build and write Capistrano configuration files.

    Args:
        environments: Environment configurations from project-config.yml.
        ssh_host: Remote server hostname or IP.
        ssh_user: SSH username.
        application: Application name for Capistrano.
        repo_url: Git repository URL.
        with_pipelines: Whether to generate bitbucket-pipelines.yml.
        preview: Print to stdout instead of writing files.
        force: Overwrite existing files.

    Raises:
        CloudwaysError: If a file cannot be written.
    """
    # Build file content mapping
    files: dict[str, str] = {}

    # Capfile
    files["Capfile"] = render_capfile()

    # deploy.rb
    # Use the first environment's webroot for deploy_to
    first_env = next(iter(environments.values()))
    deploy_to = first_env.get("webroot", DEFAULT_WEBROOT)

    files["config/deploy.rb"] = render_deploy_rb(
        application=application,
        repo_url=repo_url,
        deploy_to=deploy_to,
        user=ssh_user,
    )

    # Stage deploy files (production.rb, staging.rb, etc.)
    for env_name, env_config in environments.items():
        branch = env_config.get("branch", _default_branch(env_name))
        env_deploy_to = env_config.get("webroot", DEFAULT_WEBROOT)
        files[f"config/deploy/{env_name}.rb"] = render_stage_deploy(
            server=ssh_host,
            user=ssh_user,
            branch=branch,
            deploy_to=env_deploy_to,
        )

    # Gemfile
    files["Gemfile"] = render_gemfile()

    # Optional bitbucket-pipelines.yml
    if with_pipelines:
        files["bitbucket-pipelines.yml"] = render_pipelines()

    # Check Bedrock indicators and warn if not detected
    if not _is_bedrock_project():
        console.print(
            "[bold yellow]Warning:[/bold yellow] No Bedrock indicators "
            "(.env file, web/ directory) detected. Generated config uses "
            "Bedrock conventions and may need adjustment for traditional "
            "WordPress."
        )

    # Preview mode: print to stdout
    if preview:
        for filepath, content in files.items():
            typer.echo(f"--- {filepath} ---")
            typer.echo(content)
        return

    # Write files
    created: list[str] = []
    skipped: list[str] = []

    for filepath, content in files.items():
        path = Path(filepath)

        # Create parent directories if needed
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not force:
            skipped.append(filepath)
            console.print(
                f"  [yellow]Skipping {filepath}[/yellow] "
                "(already exists). Use --force to overwrite."
            )
            continue

        try:
            path.write_text(content)
        except OSError as exc:
            raise CloudwaysError(f"Could not write to {filepath}: {exc}") from exc

        created.append(filepath)

    # Success output
    console.print()
    console.print("[bold green]Capistrano Configuration Generated[/bold green]")
    if created:
        console.print("  Files created:")
        for f in created:
            console.print(f"    - {f}")
    if skipped:
        console.print(f"  Files skipped: {len(skipped)}")
    console.print("  Next steps:")
    console.print("    1. Run: bundle install")
    console.print("    2. Run: bundle exec cap production deploy:check")
    if with_pipelines:
        console.print("    3. Push to Bitbucket to trigger pipeline deployment")


def _default_branch(env_name: str) -> str:
    """Return the default branch for an environment name.

    Args:
        env_name: Environment name (e.g., ``"production"``, ``"staging"``).

    Returns:
        ``"main"`` for production, otherwise the environment name.
    """
    if env_name == "production":
        return "main"
    return env_name
