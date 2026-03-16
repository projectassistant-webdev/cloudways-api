"""Parse linked_files and linked_dirs from Capistrano Ruby config files.

Extracts the file and directory lists that Capistrano uses for
symlinking into each deployment release. When no Capistrano config
exists, provides sensible Bedrock defaults.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Default linked files/dirs for standard Bedrock deployments
DEFAULT_LINKED_FILES: list[str] = [".env", "web/.htaccess", "web/robots.txt"]
DEFAULT_LINKED_DIRS: list[str] = ["web/app/uploads", "web/app/cache"]

# Regex to match: set :linked_files, ... .push(...)
_LINKED_FILES_RE = re.compile(
    r"^\s*set\s+:linked_files\b.*?\.push\(([^)]*)\)",
    re.MULTILINE,
)

# Regex to match: set :linked_dirs, ... .push(...)
_LINKED_DIRS_RE = re.compile(
    r"^\s*set\s+:linked_dirs\b.*?\.push\(([^)]*)\)",
    re.MULTILINE,
)

# Regex to extract quoted strings (single or double) from .push() args
_QUOTED_STRING_RE = re.compile(r"""['"]([^'"]+)['"]""")


def _extract_push_args(content: str, pattern: re.Pattern, label: str) -> list[str]:
    """Extract quoted string arguments from a .push() call.

    Args:
        content: Full file content to search.
        pattern: Compiled regex with one capture group for push args.
        label: Human-readable label for error messages (e.g., "linked_files").

    Returns:
        List of extracted string values.

    Raises:
        ValueError: If the pattern is not found in the content.
    """
    match = pattern.search(content)
    if match is None:
        raise ValueError(
            f"Could not find 'set :{label}' with .push() in config file."
        )
    push_args = match.group(1).strip()
    if not push_args:
        return []
    return _QUOTED_STRING_RE.findall(push_args)


def parse_linked_files(stage_file: str | Path) -> list[str]:
    """Parse linked_files from a Capistrano stage config file.

    Reads the Ruby file, finds the ``set :linked_files, ...`` line,
    and extracts the string arguments from the ``.push(...)`` call.

    Args:
        stage_file: Path to config/deploy/{environment}.rb

    Returns:
        List of linked file paths (e.g., ['.env', 'web/.htaccess']).

    Raises:
        FileNotFoundError: If the stage file does not exist.
        ValueError: If the linked_files line cannot be parsed.
    """
    path = Path(stage_file)
    if not path.is_file():
        raise FileNotFoundError(f"Stage config not found: {stage_file}")
    content = path.read_text()
    return _extract_push_args(content, _LINKED_FILES_RE, "linked_files")


def parse_linked_dirs(deploy_file: str | Path) -> list[str]:
    """Parse linked_dirs from the Capistrano base deploy config.

    Reads the Ruby file, finds the ``set :linked_dirs, ...`` line,
    and extracts the string arguments from the ``.push(...)`` call.

    Args:
        deploy_file: Path to config/deploy.rb

    Returns:
        List of linked directory paths (e.g., ['web/app/uploads']).

    Raises:
        FileNotFoundError: If the deploy file does not exist.
        ValueError: If the linked_dirs line cannot be parsed.
    """
    path = Path(deploy_file)
    if not path.is_file():
        raise FileNotFoundError(f"Deploy config not found: {deploy_file}")
    content = path.read_text()
    return _extract_push_args(content, _LINKED_DIRS_RE, "linked_dirs")


def get_linked_files_for_environment(
    environment: str,
    project_root: str | Path | None = None,
) -> list[str]:
    """Get linked files for an environment, with fallback to defaults.

    Tries to parse from Capistrano config. If no config exists,
    returns sensible defaults for a standard Bedrock deployment.

    Args:
        environment: Environment name (e.g., 'staging', 'production').
        project_root: Root directory to search for config/deploy/.
            Defaults to cwd.

    Returns:
        List of linked file paths.
    """
    root = Path(project_root) if project_root else Path.cwd()
    stage_file = root / "config" / "deploy" / f"{environment}.rb"

    if not stage_file.is_file():
        logger.warning(
            "No config/deploy/%s.rb found, using default linked files.",
            environment,
        )
        return list(DEFAULT_LINKED_FILES)

    try:
        return parse_linked_files(stage_file)
    except ValueError:
        logger.warning(
            "Could not parse linked_files from %s, using default linked files.",
            stage_file,
        )
        return list(DEFAULT_LINKED_FILES)


def get_linked_dirs_for_environment(
    project_root: str | Path | None = None,
) -> list[str]:
    """Get linked directories, with fallback to defaults.

    Args:
        project_root: Root directory to search for config/deploy.rb.
            Defaults to cwd.

    Returns:
        List of linked directory paths.
    """
    root = Path(project_root) if project_root else Path.cwd()
    deploy_file = root / "config" / "deploy.rb"

    if not deploy_file.is_file():
        logger.warning(
            "No config/deploy.rb found, using default linked dirs.",
        )
        return list(DEFAULT_LINKED_DIRS)

    try:
        return parse_linked_dirs(deploy_file)
    except ValueError:
        logger.warning(
            "Could not parse linked_dirs from %s, using default linked dirs.",
            deploy_file,
        )
        return list(DEFAULT_LINKED_DIRS)
