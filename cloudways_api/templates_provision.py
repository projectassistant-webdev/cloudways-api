"""Provisioning template loader, validator, and variable interpolator.

Supports YAML-based templates for automating server and app provisioning.
Templates define provision type, parameters, and optional variable
placeholders that are resolved from CLI flags or environment variables.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from cloudways_api.exceptions import ConfigError

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "provision"
_VAR_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Required top-level keys in a provisioning template
_REQUIRED_KEYS = {"provision"}

# Required keys within the provision section
_REQUIRED_PROVISION_KEYS = {"type"}

# Valid provision types
_VALID_TYPES = {"server", "app"}

# Valid cloud providers
_VALID_PROVIDERS = {"do"}

# Required fields per provision type
_TYPE_REQUIRED_FIELDS: dict[str, set[str]] = {
    "server": {"provider"},
    "app": {"server_id"},
}

# Known keys per provision type (for unknown-key warnings)
_KNOWN_PROVISION_KEYS: dict[str, set[str]] = {
    "server": {
        "type", "provider", "region", "size", "server_label",
        "app_label", "project_name",
    },
    "app": {
        "type", "server_id", "app_label", "application",
        "project_name", "configure",
    },
}

# Known keys in the configure sub-block
_KNOWN_CONFIGURE_KEYS = {"php_version", "domain"}


def load_template(name_or_path: str) -> dict:
    """Load a provisioning template from a file path or built-in name.

    Resolution order:
    1. If ``name_or_path`` is an existing file, load it directly.
    2. If ``name_or_path`` ends with ``.yml`` or ``.yaml``, treat as a
       path and raise if not found.
    3. Otherwise, look up the name in the built-in templates directory
       (``templates/provision/<name>.yml``).

    Args:
        name_or_path: File path or built-in template name.

    Returns:
        Parsed YAML dict.

    Raises:
        ConfigError: If the file is not found or YAML is invalid.
    """
    path = _resolve_template_path(name_or_path)

    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in template {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"Template {path} must be a YAML mapping, got {type(data).__name__}"
        )

    return data


def validate_template(template: dict) -> list[str]:
    """Validate a provisioning template structure.

    Checks for required top-level keys, valid provision type,
    and type-specific required fields. Unresolved variable
    placeholders (``{var_name}``) are NOT considered errors
    since they may be resolved later via ``interpolate_variables``.

    Args:
        template: Parsed template dict from :func:`load_template`.

    Returns:
        A list of error message strings (empty if valid).
    """
    errors: list[str] = []

    # Check top-level keys
    for key in _REQUIRED_KEYS:
        if key not in template:
            errors.append(f"Missing required key: '{key}'")

    provision = template.get("provision")
    if not isinstance(provision, dict):
        errors.append("'provision' must be a mapping")
        return errors

    # Check provision type
    ptype = provision.get("type")
    if ptype is None:
        errors.append("Missing required key: 'provision.type'")
        return errors

    if ptype not in _VALID_TYPES:
        errors.append(
            f"Invalid provision type '{ptype}'. "
            f"Must be one of: {', '.join(sorted(_VALID_TYPES))}"
        )
        return errors

    # Check type-specific required fields
    required = _TYPE_REQUIRED_FIELDS.get(ptype, set())
    for field in sorted(required):
        if field not in provision:
            errors.append(
                f"Missing required field 'provision.{field}' "
                f"for type '{ptype}'"
            )

    # Validate provider value for server templates
    provider = provision.get("provider")
    if ptype == "server" and provider is not None and provider not in _VALID_PROVIDERS:
        errors.append(
            f"Invalid provider '{provider}'. "
            f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}"
        )

    # Flag unknown keys in provision block
    known = _KNOWN_PROVISION_KEYS.get(ptype, set())
    if known:
        for key in sorted(provision.keys()):
            if key not in known:
                errors.append(
                    f"Unknown key 'provision.{key}' for type '{ptype}'"
                )

    # Flag unknown keys in configure sub-block
    configure = provision.get("configure")
    if isinstance(configure, dict):
        for key in sorted(configure.keys()):
            if key not in _KNOWN_CONFIGURE_KEYS:
                errors.append(
                    f"Unknown key 'provision.configure.{key}'"
                )

    return errors


def interpolate_variables(
    template: dict,
    cli_vars: dict[str, str] | None = None,
) -> dict:
    """Resolve ``{variable}`` placeholders in template string values.

    Resolution order for each placeholder:
    1. ``cli_vars`` dict (CLI flags passed by the user).
    2. Environment variables (``os.environ``).

    Non-string values and unresolvable placeholders are left unchanged.

    Args:
        template: Parsed template dict.
        cli_vars: Variable overrides from CLI flags.

    Returns:
        A new dict with resolved string values.
    """
    vars_dict = dict(os.environ)
    if cli_vars:
        vars_dict.update(cli_vars)

    return _interpolate_dict(template, vars_dict)


def _resolve_template_path(name_or_path: str) -> Path:
    """Determine the template file path."""
    # Direct file path
    p = Path(name_or_path)
    if p.is_file():
        return p

    # Explicit path that doesn't exist
    if name_or_path.endswith((".yml", ".yaml")):
        raise ConfigError(f"Template file not found: {name_or_path}")

    # Built-in template name
    builtin = _TEMPLATES_DIR / f"{name_or_path}.yml"
    if builtin.is_file():
        return builtin

    raise ConfigError(
        f"Template '{name_or_path}' not found. "
        f"Checked: {name_or_path}, {builtin}"
    )


def _interpolate_dict(d: dict, vars_dict: dict[str, str]) -> dict:
    """Recursively interpolate string values in a dict."""
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = _interpolate_string(value, vars_dict)
        elif isinstance(value, dict):
            result[key] = _interpolate_dict(value, vars_dict)
        elif isinstance(value, list):
            result[key] = _interpolate_list(value, vars_dict)
        else:
            result[key] = value
    return result


def _interpolate_list(lst: list, vars_dict: dict[str, str]) -> list:
    """Recursively interpolate string values in a list."""
    result = []
    for item in lst:
        if isinstance(item, str):
            result.append(_interpolate_string(item, vars_dict))
        elif isinstance(item, dict):
            result.append(_interpolate_dict(item, vars_dict))
        elif isinstance(item, list):
            result.append(_interpolate_list(item, vars_dict))
        else:
            result.append(item)
    return result


def _interpolate_string(value: str, vars_dict: dict[str, str]) -> str:
    """Replace {variable} placeholders in a string.

    Uses a regex-based approach rather than str.format_map to avoid
    KeyError on unresolvable variables, leaving them as-is.
    """

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return vars_dict.get(var_name, match.group(0))

    return _VAR_PATTERN.sub(replacer, value)
