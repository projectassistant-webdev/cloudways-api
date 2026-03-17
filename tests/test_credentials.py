"""Tests for credential loading and env var resolution."""

from pathlib import Path

import pytest

from cloudways_api.credentials import load_credentials
from cloudways_api.exceptions import CredentialsError
from conftest import FIXTURES_DIR


class TestCredentialLoading:
    """Tests for the load_credentials function."""

    def test_credentials_loads_account_by_name(self) -> None:
        """Happy path: load account credentials by name with plain text key."""
        creds = load_credentials(
            "primary", path=str(FIXTURES_DIR / "accounts.yml")
        )
        assert creds["email"] == "anthonys@projectassistant.org"
        assert creds["api_key"] == "plain_text_api_key_12345"

    def test_credentials_loads_different_account(self) -> None:
        """Load a different account by name."""
        creds = load_credentials(
            "agency", path=str(FIXTURES_DIR / "accounts.yml")
        )
        assert creds["email"] == "webdev@projectassistant.org"
        assert creds["api_key"] == "agency_api_key_67890"

    def test_credentials_resolves_env_var_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${ENV_VAR} references in api_key are resolved from environment."""
        monkeypatch.setenv("CLOUDWAYS_API_KEY_PRIMARY", "resolved_key_value")
        creds = load_credentials(
            "primary", path=str(FIXTURES_DIR / "accounts-envvar.yml")
        )
        assert creds["api_key"] == "resolved_key_value"

    def test_credentials_missing_file_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Missing accounts.yml raises CredentialsError."""
        with pytest.raises(CredentialsError, match="Could not find"):
            load_credentials(
                "primary", path=str(tmp_path / "nonexistent.yml")
            )

    def test_credentials_missing_account_raises_credentials_error(self) -> None:
        """Account not found in accounts.yml raises CredentialsError."""
        with pytest.raises(CredentialsError, match="not found"):
            load_credentials(
                "nonexistent", path=str(FIXTURES_DIR / "accounts.yml")
            )

    def test_credentials_unresolvable_env_var_raises_credentials_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing env var reference raises CredentialsError naming the variable."""
        monkeypatch.delenv("CLOUDWAYS_API_KEY_PRIMARY", raising=False)
        with pytest.raises(CredentialsError, match="CLOUDWAYS_API_KEY_PRIMARY"):
            load_credentials(
                "primary", path=str(FIXTURES_DIR / "accounts-envvar.yml")
            )

    def test_credentials_account_file_email_takes_priority_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Account file email takes priority over CLOUDWAYS_EMAIL env var."""
        monkeypatch.setenv("CLOUDWAYS_EMAIL", "override@example.com")
        creds = load_credentials(
            "primary", path=str(FIXTURES_DIR / "accounts.yml")
        )
        # Account file value should win over env var
        assert creds["email"] == "anthonys@projectassistant.org"

    def test_credentials_account_file_api_key_takes_priority_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Account file api_key takes priority over CLOUDWAYS_API_KEY env var."""
        monkeypatch.setenv("CLOUDWAYS_API_KEY", "direct_override_key")
        creds = load_credentials(
            "primary", path=str(FIXTURES_DIR / "accounts.yml")
        )
        # Account file value should win over env var
        assert creds["api_key"] == "plain_text_api_key_12345"

    def test_credentials_env_email_fallback_when_account_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLOUDWAYS_EMAIL env var used as fallback when account email is empty."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            '    email: ""\n'
            "    api_key: some_key\n"
        )
        monkeypatch.setenv("CLOUDWAYS_EMAIL", "fallback@example.com")
        creds = load_credentials("primary", path=str(acct))
        assert creds["email"] == "fallback@example.com"

    def test_credentials_env_api_key_fallback_when_account_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLOUDWAYS_API_KEY env var used as fallback when account api_key is empty."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            '    api_key: ""\n'
        )
        monkeypatch.setenv("CLOUDWAYS_API_KEY", "fallback_key_value")
        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "fallback_key_value"

    def test_credentials_env_email_fallback_when_account_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLOUDWAYS_EMAIL env var used as fallback when email field is missing."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    api_key: some_key\n"
        )
        monkeypatch.setenv("CLOUDWAYS_EMAIL", "fallback@example.com")
        creds = load_credentials("primary", path=str(acct))
        assert creds["email"] == "fallback@example.com"

    def test_credentials_env_api_key_fallback_when_account_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CLOUDWAYS_API_KEY env var used as fallback when api_key field is missing."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_API_KEY", "fallback_key_value")
        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "fallback_key_value"

    def test_credentials_accounts_file_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLOUDWAYS_ACCOUNTS_FILE env var overrides default path."""
        fixture_path = str(FIXTURES_DIR / "accounts.yml")
        monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", fixture_path)
        creds = load_credentials("primary")
        assert creds["email"] == "anthonys@projectassistant.org"

    def test_credentials_path_parameter_override(self) -> None:
        """load_credentials() accepts explicit path parameter."""
        creds = load_credentials(
            "primary", path=str(FIXTURES_DIR / "accounts.yml")
        )
        assert creds["email"] == "anthonys@projectassistant.org"


class TestCredentialValidation:
    """M-5: Tests for non-empty credential validation after resolution."""

    def test_credentials_empty_email_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Empty email field raises CredentialsError with guidance."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            '    email: ""\n'
            "    api_key: some_key\n"
        )
        with pytest.raises(CredentialsError, match="email"):
            load_credentials("primary", path=str(acct))

    def test_credentials_empty_api_key_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Empty api_key field raises CredentialsError with guidance."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            '    api_key: ""\n'
        )
        with pytest.raises(CredentialsError, match="api_key"):
            load_credentials("primary", path=str(acct))

    def test_credentials_missing_email_field_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Missing email field entirely raises CredentialsError."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    api_key: some_key\n"
        )
        with pytest.raises(CredentialsError, match="email"):
            load_credentials("primary", path=str(acct))

    def test_credentials_missing_api_key_field_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Missing api_key field entirely raises CredentialsError."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
        )
        with pytest.raises(CredentialsError, match="api_key"):
            load_credentials("primary", path=str(acct))


class TestDotenvFallback:
    """Tests for _load_dotenv() fallback when env vars are not set."""

    def test_dotenv_resolves_var_from_dotenv_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """${VAR} in api_key resolves from ~/.cloudways/.env when not in os.environ."""
        # Create the accounts file referencing an env var
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: ${MY_DOTENV_KEY}\n"
        )

        # Create a fake ~/.cloudways/.env
        fake_home = tmp_path / "fakehome"
        cw_dir = fake_home / ".cloudways"
        cw_dir.mkdir(parents=True)
        dotenv = cw_dir / ".env"
        dotenv.write_text("MY_DOTENV_KEY=resolved_from_dotenv\n")

        monkeypatch.delenv("MY_DOTENV_KEY", raising=False)
        monkeypatch.setattr("cloudways_api.credentials.Path.home", lambda: fake_home)

        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "resolved_from_dotenv"

    def test_dotenv_skips_comments_and_blank_lines(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """.env parser ignores comments and blank lines."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: ${DOTENV_COMMENT_KEY}\n"
        )

        fake_home = tmp_path / "fakehome"
        cw_dir = fake_home / ".cloudways"
        cw_dir.mkdir(parents=True)
        dotenv = cw_dir / ".env"
        dotenv.write_text(
            "# This is a comment\n"
            "\n"
            "DOTENV_COMMENT_KEY=works_fine\n"
            "# Another comment\n"
        )

        monkeypatch.delenv("DOTENV_COMMENT_KEY", raising=False)
        monkeypatch.setattr("cloudways_api.credentials.Path.home", lambda: fake_home)

        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "works_fine"

    def test_dotenv_file_missing_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing .env file means dotenv returns empty dict, triggering error."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: ${NO_SUCH_VAR}\n"
        )

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir(parents=True)
        # No .cloudways/.env exists

        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        monkeypatch.setattr("cloudways_api.credentials.Path.home", lambda: fake_home)

        with pytest.raises(CredentialsError, match="NO_SUCH_VAR"):
            load_credentials("primary", path=str(acct))

    def test_dotenv_os_environ_takes_priority(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """os.environ value takes priority over .env file value."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: ${PRIORITY_KEY}\n"
        )

        fake_home = tmp_path / "fakehome"
        cw_dir = fake_home / ".cloudways"
        cw_dir.mkdir(parents=True)
        dotenv = cw_dir / ".env"
        dotenv.write_text("PRIORITY_KEY=from_dotenv\n")

        monkeypatch.setenv("PRIORITY_KEY", "from_environ")
        monkeypatch.setattr("cloudways_api.credentials.Path.home", lambda: fake_home)

        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "from_environ"


class TestCredentialEdgeCases:
    """Tests for edge cases in credential loading."""

    def test_non_string_api_key_coerced_to_string(
        self, tmp_path: Path
    ) -> None:
        """Numeric api_key in YAML is coerced to string via _resolve_env_vars."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: 12345\n"
        )
        creds = load_credentials("primary", path=str(acct))
        assert creds["api_key"] == "12345"

    def test_none_api_key_resolves_to_empty_and_raises(
        self, tmp_path: Path
    ) -> None:
        """None api_key (via YAML null) resolves to empty string and raises."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary:\n"
            "    email: test@example.com\n"
            "    api_key: null\n"
        )
        with pytest.raises(CredentialsError, match="api_key"):
            load_credentials("primary", path=str(acct))

    def test_invalid_yaml_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Malformed YAML raises CredentialsError with 'Invalid YAML'."""
        acct = tmp_path / "accounts.yml"
        acct.write_text("accounts:\n  primary:\n    - this: is\n  bad yaml: [")
        with pytest.raises(CredentialsError, match="Invalid YAML"):
            load_credentials("primary", path=str(acct))

    def test_yaml_list_instead_of_dict_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """YAML file containing a list instead of dict raises CredentialsError."""
        acct = tmp_path / "accounts.yml"
        acct.write_text("- item1\n- item2\n")
        with pytest.raises(CredentialsError, match="YAML mapping"):
            load_credentials("primary", path=str(acct))

    def test_missing_accounts_section_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """YAML dict without 'accounts' key raises CredentialsError."""
        acct = tmp_path / "accounts.yml"
        acct.write_text("settings:\n  key: value\n")
        with pytest.raises(CredentialsError, match="accounts"):
            load_credentials("primary", path=str(acct))

    def test_account_value_not_dict_raises_credentials_error(
        self, tmp_path: Path
    ) -> None:
        """Account entry that is a string instead of dict raises CredentialsError."""
        acct = tmp_path / "accounts.yml"
        acct.write_text(
            "accounts:\n"
            "  primary: just_a_string\n"
        )
        with pytest.raises(CredentialsError, match="not found"):
            load_credentials("primary", path=str(acct))
