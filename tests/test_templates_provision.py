"""Tests for the provisioning template loader, validator, and interpolator."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudways_api.exceptions import ConfigError
from cloudways_api.templates_provision import (
    interpolate_variables,
    load_template,
    validate_template,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_yaml(tmp_path: Path):
    """Factory to create temporary YAML files."""

    def _create(content: str, name: str = "template.yml") -> str:
        p = tmp_path / name
        p.write_text(content)
        return str(p)

    return _create


@pytest.fixture
def valid_server_template() -> dict:
    """Return a valid server provisioning template dict."""
    return {
        "provision": {
            "type": "server",
            "provider": "do",
            "region": "nyc3",
            "size": "2GB",
            "server_label": "my-server",
            "app_label": "my-app",
            "project_name": "Default",
        }
    }


@pytest.fixture
def valid_app_template() -> dict:
    """Return a valid app provisioning template dict."""
    return {
        "provision": {
            "type": "app",
            "server_id": "999999",
            "app_label": "my-app",
            "project_name": "Default",
        }
    }


# ===========================================================================
# Test Classes
# ===========================================================================


class TestLoadTemplate:
    """Tests for template loading from files and built-in names."""

    def test_load_from_file_path(self, tmp_yaml) -> None:
        """Load a template from an explicit file path."""
        path = tmp_yaml(
            "provision:\n  type: server\n  region: nyc3\n  size: 2GB\n  server_label: srv\n"
        )
        result = load_template(path)
        assert result["provision"]["type"] == "server"

    def test_load_from_builtin_name(self) -> None:
        """Load a built-in template by name (no .yml extension)."""
        result = load_template("do-2gb")
        assert result["provision"]["type"] == "server"
        assert result["provision"]["region"] == "nyc3"

    def test_load_nonexistent_file_raises_config_error(self) -> None:
        """Nonexistent file path raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_template("/tmp/nonexistent-template.yml")

    def test_load_nonexistent_name_raises_config_error(self) -> None:
        """Nonexistent built-in name raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_template("nonexistent-builtin-name")

    def test_load_invalid_yaml_raises_config_error(self, tmp_yaml) -> None:
        """Invalid YAML content raises ConfigError."""
        path = tmp_yaml("invalid: yaml: [content\n")
        with pytest.raises(ConfigError, match="Invalid YAML"):
            load_template(path)

    def test_load_non_dict_yaml_raises_config_error(self, tmp_yaml) -> None:
        """YAML that is not a dict raises ConfigError."""
        path = tmp_yaml("- just\n- a\n- list\n")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            load_template(path)

    def test_load_returns_full_template_dict(self, tmp_yaml) -> None:
        """Loaded template contains all expected keys."""
        path = tmp_yaml(
            "provision:\n  type: app\n  server_id: '123'\n  app_label: test\n"
        )
        result = load_template(path)
        assert "provision" in result
        assert result["provision"]["server_id"] == "123"


class TestValidateTemplate:
    """Tests for template validation."""

    def test_valid_server_template_returns_no_errors(
        self, valid_server_template
    ) -> None:
        """A complete server template has no validation errors."""
        errors = validate_template(valid_server_template)
        assert errors == []

    def test_valid_app_template_returns_no_errors(
        self, valid_app_template
    ) -> None:
        """A complete app template has no validation errors."""
        errors = validate_template(valid_app_template)
        assert errors == []

    def test_missing_provision_key(self) -> None:
        """Missing 'provision' key returns an error."""
        errors = validate_template({"other": "data"})
        assert any("provision" in e for e in errors)

    def test_provision_not_a_dict(self) -> None:
        """'provision' value is not a mapping returns an error."""
        errors = validate_template({"provision": "not-a-dict"})
        assert any("mapping" in e for e in errors)

    def test_missing_provision_type(self) -> None:
        """Missing 'provision.type' returns an error."""
        errors = validate_template({"provision": {"region": "nyc3"}})
        assert any("type" in e for e in errors)

    def test_invalid_provision_type(self) -> None:
        """Invalid provision type returns an error."""
        errors = validate_template(
            {"provision": {"type": "database"}}
        )
        assert any("database" in e for e in errors)

    def test_server_missing_provider(self) -> None:
        """Server template missing 'provider' returns an error."""
        template = {
            "provision": {
                "type": "server",
                "region": "nyc3",
                "size": "2GB",
                "server_label": "srv",
            }
        }
        errors = validate_template(template)
        assert any("provider" in e for e in errors)

    def test_server_invalid_provider(self) -> None:
        """Server template with invalid provider returns an error."""
        template = {
            "provision": {
                "type": "server",
                "provider": "aws",
                "region": "nyc3",
                "size": "2GB",
                "server_label": "srv",
            }
        }
        errors = validate_template(template)
        assert any("aws" in e for e in errors)

    def test_server_region_is_optional(self) -> None:
        """Server template without 'region' is valid (optional field)."""
        template = {
            "provision": {
                "type": "server",
                "provider": "do",
                "size": "2GB",
                "server_label": "srv",
            }
        }
        errors = validate_template(template)
        assert errors == []

    def test_server_size_is_optional(self) -> None:
        """Server template without 'size' is valid (optional field)."""
        template = {
            "provision": {
                "type": "server",
                "provider": "do",
                "region": "nyc3",
                "server_label": "srv",
            }
        }
        errors = validate_template(template)
        assert errors == []

    def test_server_label_is_optional(self) -> None:
        """Server template without 'server_label' is valid (optional field)."""
        template = {
            "provision": {
                "type": "server",
                "provider": "do",
                "region": "nyc3",
                "size": "2GB",
            }
        }
        errors = validate_template(template)
        assert errors == []

    def test_app_missing_server_id(self) -> None:
        """App template missing 'server_id' returns an error."""
        template = {
            "provision": {
                "type": "app",
                "app_label": "my-app",
            }
        }
        errors = validate_template(template)
        assert any("server_id" in e for e in errors)

    def test_app_label_is_optional(self) -> None:
        """App template without 'app_label' is valid (optional)."""
        template = {
            "provision": {
                "type": "app",
                "server_id": "123",
            }
        }
        errors = validate_template(template)
        assert errors == []

    def test_template_with_variables_is_valid(self) -> None:
        """Template with {variable} placeholders is still valid."""
        template = {
            "provision": {
                "type": "server",
                "provider": "do",
                "region": "nyc3",
                "size": "2GB",
                "server_label": "{label}",
            }
        }
        errors = validate_template(template)
        assert errors == []

    def test_unknown_provision_key_flagged(self) -> None:
        """Unknown key in provision block is reported as error."""
        template = {
            "provision": {
                "type": "server",
                "provider": "do",
                "unknown_field": "value",
            }
        }
        errors = validate_template(template)
        assert any("unknown_field" in e.lower() for e in errors)

    def test_unknown_configure_key_flagged(self) -> None:
        """Unknown key in configure sub-block is reported as error."""
        template = {
            "provision": {
                "type": "app",
                "server_id": "123",
                "configure": {
                    "php_version": "8.2",
                    "unknown_option": "value",
                },
            }
        }
        errors = validate_template(template)
        assert any("unknown_option" in e.lower() for e in errors)

    def test_valid_configure_block_no_errors(self) -> None:
        """Valid configure sub-block produces no errors."""
        template = {
            "provision": {
                "type": "app",
                "server_id": "123",
                "app_label": "my-app",
                "configure": {
                    "php_version": "8.2",
                    "domain": "example.com",
                },
            }
        }
        errors = validate_template(template)
        assert errors == []


class TestInterpolateVariables:
    """Tests for variable interpolation in templates."""

    def test_interpolate_from_cli_vars(self) -> None:
        """CLI variables are substituted into template strings."""
        template = {
            "provision": {
                "type": "server",
                "server_label": "{label}",
            }
        }
        result = interpolate_variables(template, {"label": "my-server"})
        assert result["provision"]["server_label"] == "my-server"

    def test_interpolate_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables are substituted when no CLI var matches."""
        monkeypatch.setenv("MY_LABEL", "env-server")
        template = {
            "provision": {
                "type": "server",
                "server_label": "{MY_LABEL}",
            }
        }
        result = interpolate_variables(template)
        assert result["provision"]["server_label"] == "env-server"

    def test_cli_vars_override_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI variables take precedence over environment variables."""
        monkeypatch.setenv("label", "from-env")
        template = {
            "provision": {
                "type": "server",
                "server_label": "{label}",
            }
        }
        result = interpolate_variables(template, {"label": "from-cli"})
        assert result["provision"]["server_label"] == "from-cli"

    def test_unresolvable_variables_left_unchanged(self) -> None:
        """Unresolvable placeholders are left as-is (no KeyError)."""
        template = {
            "provision": {
                "type": "server",
                "server_label": "{undefined_var}",
            }
        }
        result = interpolate_variables(template)
        assert result["provision"]["server_label"] == "{undefined_var}"

    def test_non_string_values_unchanged(self) -> None:
        """Integer and boolean values are not modified."""
        template = {
            "provision": {
                "type": "server",
                "timeout": 600,
                "enabled": True,
            }
        }
        result = interpolate_variables(template)
        assert result["provision"]["timeout"] == 600
        assert result["provision"]["enabled"] is True

    def test_interpolate_nested_dict(self) -> None:
        """Variables in nested dicts are resolved."""
        template = {
            "provision": {
                "type": "server",
                "config": {
                    "label": "{name}",
                },
            }
        }
        result = interpolate_variables(template, {"name": "nested-val"})
        assert result["provision"]["config"]["label"] == "nested-val"

    def test_interpolate_list_values(self) -> None:
        """Variables in list items are resolved."""
        template = {
            "provision": {
                "type": "server",
                "domains": ["{domain1}", "{domain2}"],
            }
        }
        result = interpolate_variables(
            template, {"domain1": "a.com", "domain2": "b.com"}
        )
        assert result["provision"]["domains"] == ["a.com", "b.com"]

    def test_multiple_variables_in_one_string(self) -> None:
        """Multiple placeholders in a single string are all resolved."""
        template = {
            "provision": {
                "type": "server",
                "label": "{prefix}-{suffix}",
            }
        }
        result = interpolate_variables(
            template, {"prefix": "staging", "suffix": "v1"}
        )
        assert result["provision"]["label"] == "staging-v1"

    def test_original_template_not_modified(self) -> None:
        """Interpolation returns a new dict without modifying the original."""
        template = {
            "provision": {
                "type": "server",
                "label": "{name}",
            }
        }
        interpolate_variables(template, {"name": "modified"})
        assert template["provision"]["label"] == "{name}"


class TestBuiltinTemplates:
    """Tests for the built-in sample templates."""

    def test_do_2gb_template_loads(self) -> None:
        """Built-in do-2gb template loads successfully."""
        result = load_template("do-2gb")
        assert result["provision"]["type"] == "server"

    def test_do_2gb_template_validates(self) -> None:
        """Built-in do-2gb template passes validation."""
        template = load_template("do-2gb")
        errors = validate_template(template)
        assert errors == []

    def test_do_2gb_has_provider(self) -> None:
        """Built-in do-2gb template has provider field."""
        template = load_template("do-2gb")
        assert template["provision"]["provider"] == "do"

    def test_staging_app_template_loads(self) -> None:
        """Built-in staging-app template loads successfully."""
        result = load_template("staging-app")
        assert result["provision"]["type"] == "app"

    def test_staging_app_template_validates(self) -> None:
        """Built-in staging-app template passes validation."""
        template = load_template("staging-app")
        errors = validate_template(template)
        assert errors == []

    def test_staging_app_uses_configure_block(self) -> None:
        """Built-in staging-app template uses configure sub-block."""
        template = load_template("staging-app")
        configure = template["provision"].get("configure", {})
        assert "php_version" in configure
        assert "domain" in configure

    def test_do_2gb_interpolation(self) -> None:
        """Built-in do-2gb template interpolates correctly."""
        template = load_template("do-2gb")
        result = interpolate_variables(
            template,
            {"label": "my-prod", "project_name": "MyProj"},
        )
        assert result["provision"]["server_label"] == "my-prod"
        assert result["provision"]["project_name"] == "MyProj"

    def test_staging_app_interpolation(self) -> None:
        """Built-in staging-app template interpolates correctly."""
        template = load_template("staging-app")
        result = interpolate_variables(
            template,
            {
                "server_id": "12345",
                "app_label": "staging-wp",
                "project_name": "MyProj",
                "domain": "example.com",
            },
        )
        assert result["provision"]["server_id"] == "12345"
        assert result["provision"]["app_label"] == "staging-wp"
        configure = result["provision"]["configure"]
        assert configure["domain"] == "staging.example.com"

    def test_wordpress_standard_template_loads(self) -> None:
        """Built-in wordpress-standard template loads successfully."""
        result = load_template("wordpress-standard")
        assert result["provision"]["type"] == "server"
        assert result["provision"]["provider"] == "do"

    def test_wordpress_standard_template_validates(self) -> None:
        """Built-in wordpress-standard template passes validation."""
        template = load_template("wordpress-standard")
        errors = validate_template(template)
        assert errors == []

    def test_app_wordpress_template_loads(self) -> None:
        """Built-in app-wordpress template loads successfully."""
        result = load_template("app-wordpress")
        assert result["provision"]["type"] == "app"

    def test_app_wordpress_template_validates(self) -> None:
        """Built-in app-wordpress template passes validation."""
        template = load_template("app-wordpress")
        errors = validate_template(template)
        assert errors == []

    def test_app_wordpress_uses_configure_block(self) -> None:
        """Built-in app-wordpress template uses configure sub-block."""
        template = load_template("app-wordpress")
        configure = template["provision"].get("configure", {})
        assert "php_version" in configure
        assert "domain" in configure
