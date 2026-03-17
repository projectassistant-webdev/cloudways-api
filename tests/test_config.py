"""Tests for project config loading."""

from pathlib import Path

import pytest

from cloudways_api.config import load_config
from cloudways_api.exceptions import ConfigError
from conftest import FIXTURES_DIR


class TestConfigLoading:
    """Tests for the load_config function."""

    def test_config_loads_hosting_cloudways_section(self) -> None:
        """Happy path: load a valid project-config.yml and get hosting.cloudways."""
        config = load_config(path=str(FIXTURES_DIR / "project-config.yml"))
        assert config["account"] == "primary"
        assert config["server"]["id"] == 1089270
        assert "production" in config["environments"]
        assert "staging" in config["environments"]

    def test_config_loads_minimal_config(self) -> None:
        """Minimal config with only required fields loads successfully."""
        config = load_config(path=str(FIXTURES_DIR / "project-config-minimal.yml"))
        assert config["account"] == "primary"
        assert config["server"]["id"] == 1089270
        assert config["environments"]["production"]["app_id"] == 3937401

    def test_config_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        """Missing config file raises ConfigError with helpful message."""
        with pytest.raises(ConfigError, match="Could not find"):
            load_config(path=str(tmp_path / "nonexistent.yml"))

    def test_config_missing_hosting_section_raises_config_error(self) -> None:
        """Config without hosting.cloudways section raises ConfigError."""
        with pytest.raises(ConfigError, match="hosting"):
            load_config(
                path=str(FIXTURES_DIR / "project-config-missing-hosting.yml")
            )

    def test_config_invalid_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """Malformed YAML raises ConfigError."""
        bad_yaml = tmp_path / "bad.yml"
        bad_yaml.write_text("invalid: yaml: [unclosed")
        with pytest.raises(ConfigError):
            load_config(path=str(bad_yaml))

    def test_config_env_var_override_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLOUDWAYS_PROJECT_CONFIG env var overrides path discovery."""
        config_path = str(FIXTURES_DIR / "project-config.yml")
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", config_path)
        config = load_config()
        assert config["account"] == "primary"

    def test_config_path_discovery_walks_up_directories(
        self, tmp_path: Path
    ) -> None:
        """Config discovery walks up from cwd to find .prism/project-config.yml."""
        # Create a .prism/project-config.yml in tmp_path
        prism_dir = tmp_path / ".prism"
        prism_dir.mkdir()
        config_file = prism_dir / "project-config.yml"
        config_file.write_text(
            (FIXTURES_DIR / "project-config.yml").read_text()
        )
        # Create a nested subdirectory
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        # Discovery from nested dir should find config in tmp_path
        config = load_config(search_from=str(nested))
        assert config["account"] == "primary"

    def test_config_path_discovery_fails_after_max_depth(
        self, tmp_path: Path
    ) -> None:
        """Path discovery raises ConfigError after exceeding max depth."""
        # Create a deeply nested directory with no config
        deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f" / "g"
        deep.mkdir(parents=True)

        with pytest.raises(ConfigError, match="Could not find"):
            load_config(search_from=str(deep))

    def test_config_returns_full_cloudways_section(self) -> None:
        """Config returns the full hosting.cloudways section with all fields."""
        config = load_config(path=str(FIXTURES_DIR / "project-config.yml"))
        assert config["server"]["label"] == "projectassistant-prod"
        assert config["server"]["provider"] == "do"
        assert config["server"]["region"] == "nyc3"
        assert config["environments"]["production"]["domain"] == "wp.projectassistant.org"
        assert config["environments"]["staging"]["app_id"] == 5021818


class TestConfigPhase1Validation:
    """H-3: Tests for Phase 1 required field validation at load time."""

    def test_config_missing_account_raises_config_error(self, tmp_path: Path) -> None:
        """Missing account field raises ConfigError with hint."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    server:\n"
            "      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        with pytest.raises(ConfigError, match="account"):
            load_config(path=str(cfg))

    def test_config_missing_server_id_raises_config_error(self, tmp_path: Path) -> None:
        """Missing server.id raises ConfigError with hint."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      label: test\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        with pytest.raises(ConfigError, match="server.id"):
            load_config(path=str(cfg))

    def test_config_server_id_not_int_raises_config_error(self, tmp_path: Path) -> None:
        """Non-integer server.id raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: not-a-number\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        with pytest.raises(ConfigError, match="server.id"):
            load_config(path=str(cfg))

    def test_config_missing_environments_raises_config_error(self, tmp_path: Path) -> None:
        """Missing environments section raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 123\n"
        )
        with pytest.raises(ConfigError, match="environment"):
            load_config(path=str(cfg))

    def test_config_empty_environments_raises_config_error(self, tmp_path: Path) -> None:
        """Empty environments dict raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 123\n"
            "    environments: {}\n"
        )
        with pytest.raises(ConfigError, match="environment"):
            load_config(path=str(cfg))

    def test_config_env_missing_app_id_raises_config_error(self, tmp_path: Path) -> None:
        """Environment without app_id raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        domain: example.com\n"
        )
        with pytest.raises(ConfigError, match="app_id"):
            load_config(path=str(cfg))

    def test_config_env_missing_domain_raises_config_error(self, tmp_path: Path) -> None:
        """Environment without domain raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: primary\n"
            "    server:\n"
            "      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
        )
        with pytest.raises(ConfigError, match="domain"):
            load_config(path=str(cfg))

    def test_config_account_not_string_raises_config_error(self, tmp_path: Path) -> None:
        """Non-string account raises ConfigError."""
        cfg = tmp_path / "cfg.yml"
        cfg.write_text(
            "hosting:\n"
            "  cloudways:\n"
            "    account: 123\n"
            "    server:\n"
            "      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        with pytest.raises(ConfigError, match="account"):
            load_config(path=str(cfg))

    def test_config_valid_minimal_passes_validation(self) -> None:
        """Minimal valid config passes Phase 1 validation."""
        config = load_config(path=str(FIXTURES_DIR / "project-config-minimal.yml"))
        assert config["account"] == "primary"
        assert config["server"]["id"] == 1089270
