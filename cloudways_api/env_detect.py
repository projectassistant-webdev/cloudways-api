"""Environment detection and wp-config.php parsing.

Detects whether a remote WordPress installation is Bedrock (.env)
or traditional (wp-config.php) and extracts environment variables
from either format.
"""

import re
import shlex
from datetime import datetime, timezone

from cloudways_api.exceptions import ConfigError
from cloudways_api.ssh import run_ssh_command

# Regex for define('KEY', 'value') with single or double quotes
# and optional whitespace.  Only matches string-literal values
# (skips getenv(), concatenation, heredoc).
DEFINE_PATTERN = re.compile(
    r"""define\s*\(\s*['"](\w+)['"]\s*,\s*['"](.*?)['"]\s*\)""",
    re.IGNORECASE,
)

# Regex for $table_prefix = 'wp_';
TABLE_PREFIX_PATTERN = re.compile(
    r"""\$table_prefix\s*=\s*['"](.+?)['"]\s*;"""
)

# Lines starting with these prefixes are comments and should be skipped.
_COMMENT_PREFIXES = ("//", "#")


async def detect_env_type(host: str, user: str, webroot: str) -> str:
    """Detect whether the remote WP installation is Bedrock or traditional.

    Args:
        host: Remote server hostname or IP.
        user: SSH username.
        webroot: Path to the WordPress installation root.

    Returns:
        ``"bedrock"`` if a ``.env`` file exists, ``"traditional"`` if
        ``wp-config.php`` exists.

    Raises:
        ConfigError: If neither ``.env`` nor ``wp-config.php`` is found
            in the webroot.
    """
    quoted = shlex.quote(webroot)
    cmd = f"test -f {quoted}/.env && echo bedrock || echo traditional"
    stdout, _, _ = await run_ssh_command(host, user, cmd)
    env_type = stdout.strip()

    if env_type == "traditional":
        # Verify wp-config.php actually exists; otherwise the webroot
        # is invalid (neither Bedrock nor traditional WordPress).
        verify_cmd = f"test -f {quoted}/wp-config.php && echo found || echo missing"
        verify_out, _, _ = await run_ssh_command(host, user, verify_cmd)
        if verify_out.strip() == "missing":
            raise ConfigError(
                f"Neither .env nor wp-config.php found in {webroot}. "
                f"Verify the webroot path is correct."
            )

    return env_type


async def capture_bedrock_env(host: str, user: str, webroot: str) -> str:
    """Read the ``.env`` file from a Bedrock installation via SSH.

    Args:
        host: Remote server hostname or IP.
        user: SSH username.
        webroot: Path to the Bedrock project root.

    Returns:
        The raw ``.env`` file content.
    """
    cmd = f"cat {shlex.quote(webroot)}/.env"
    stdout, _, _ = await run_ssh_command(host, user, cmd)
    return stdout


async def capture_traditional_env(
    host: str, user: str, webroot: str
) -> dict[str, str]:
    """Parse ``wp-config.php`` on the remote server for env variables.

    Args:
        host: Remote server hostname or IP.
        user: SSH username.
        webroot: Path to the WordPress installation root.

    Returns:
        Dictionary of extracted key-value pairs.
    """
    cmd = f"cat {shlex.quote(webroot)}/wp-config.php"
    stdout, _, _ = await run_ssh_command(host, user, cmd)
    env_vars = parse_wp_config_defines(stdout)
    prefix = parse_wp_config_table_prefix(stdout)
    if prefix is not None:
        env_vars["TABLE_PREFIX"] = prefix
    return env_vars


def parse_wp_config_defines(content: str) -> dict[str, str]:
    """Extract ``define('KEY', 'VALUE')`` pairs from wp-config.php content.

    Skips commented-out lines (``//`` or ``#`` prefixes) and lines where
    the value is not a string literal (e.g. ``getenv()`` calls or
    string concatenation).

    Args:
        content: Raw wp-config.php file content.

    Returns:
        Dictionary of extracted constants.
    """
    result: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        # Skip comment lines
        if any(stripped.startswith(p) for p in _COMMENT_PREFIXES):
            continue
        # Skip lines with function calls in the value position
        if "getenv(" in stripped:
            continue
        # Skip string concatenation (. operator between quotes and $var)
        if re.search(
            r"""define\s*\(\s*['"](\w+)['"]\s*,\s*['"].*['"]\s*\.""",
            stripped,
        ):
            continue
        match = DEFINE_PATTERN.search(stripped)
        if match:
            result[match.group(1)] = match.group(2)
    return result


def parse_wp_config_table_prefix(content: str) -> str | None:
    """Extract ``$table_prefix`` from wp-config.php content.

    Args:
        content: Raw wp-config.php file content.

    Returns:
        The table prefix string, or ``None`` if not found.
    """
    match = TABLE_PREFIX_PATTERN.search(content)
    if match:
        return match.group(1)
    return None


def parse_dotenv_content(content: str) -> dict[str, str]:
    """Parse ``.env`` file content into a dictionary of key-value pairs.

    Handles ``KEY=VALUE``, ``KEY="VALUE"`` (double-quoted), and
    ``KEY='VALUE'`` (single-quoted) formats.  Comment lines (starting
    with ``#``) and blank lines are skipped.

    Args:
        content: Raw ``.env`` file content.

    Returns:
        Dictionary of extracted key-value pairs.
    """
    result: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # Remove surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def _quote_env_value(value: str) -> str:
    """Wrap a value in double quotes if it contains special characters.

    Characters that trigger quoting: space, ``#``, ``"``, ``$``, ``'``.
    Inside double quotes, ``"`` and ``$`` are escaped with a backslash.

    Args:
        value: Raw environment variable value.

    Returns:
        The value, optionally wrapped and escaped.
    """
    if any(ch in value for ch in (' ', '#', '"', '$', "'")):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$')
        return f'"{escaped}"'
    return value


def format_env_output(
    env_vars: dict[str, str],
    env_type: str,
    timestamp: str | None = None,
) -> str:
    """Format environment variables as ``.env`` file content.

    Keys are output in alphabetical order.  A header comment
    records the source type and capture date.  Values containing
    special characters (spaces, ``#``, ``"``, ``$``, ``'``) are
    wrapped in double quotes with proper escaping.

    Args:
        env_vars: Key-value pairs to format.
        env_type: ``"bedrock"`` or ``"traditional"``.
        timestamp: Optional ISO-8601 timestamp for testability.
            Defaults to the current UTC time.

    Returns:
        Formatted ``.env`` file content string.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    lines: list[str] = [
        f"# Captured from {'wp-config.php' if env_type == 'traditional' else '.env'}"
        f" ({env_type} WordPress)",
        f"# Date: {timestamp}",
        "",
    ]
    for key in sorted(env_vars.keys()):
        lines.append(f"{key}={_quote_env_value(env_vars[key])}")
    # Ensure trailing newline
    lines.append("")
    return "\n".join(lines)
