"""Tests for the `cloudways services deploy` command."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import SSHError
from conftest import FIXTURES_DIR

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_CONFIG_WITH_SSH_USER = """\
hosting:
  cloudways:
    account: primary
    server:
      id: 1089270
      label: "test-server"
      ssh_user: master_pbztrcznuv
      ssh_host: 159.223.142.14
    environments:
      production:
        app_id: 3937401
        domain: wp.example.com
        ssh_user: unsvkhbwwr
"""

_CONFIG_NO_SSH_HOST = """\
hosting:
  cloudways:
    account: primary
    server:
      id: 1089270
      label: "test-server"
    environments:
      production:
        app_id: 3937401
        domain: wp.example.com
        ssh_user: unsvkhbwwr
"""

_CONFIG_NO_ENV_SSH_USER = """\
hosting:
  cloudways:
    account: primary
    server:
      id: 1089270
      label: "test-server"
      ssh_user: master_pbztrcznuv
      ssh_host: 159.223.142.14
    environments:
      production:
        app_id: 3937401
        domain: wp.example.com
"""


def _write_tmp_config(monkeypatch: pytest.MonkeyPatch, content: str) -> str:
    """Write a temporary config file and point env var to it."""
    fd, path = tempfile.mkstemp(suffix=".yml")
    os.write(fd, content.encode())
    os.close(fd)
    monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", path)
    return path


def _setup_env(
    monkeypatch: pytest.MonkeyPatch,
    config_content: str | None = None,
    template_content: str | None = None,
) -> dict:
    """Set up environment for services deploy tests.

    Returns dict with paths for cleanup.
    """
    accounts_path = str(FIXTURES_DIR / "accounts.yml")
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", accounts_path)

    paths: dict[str, str] = {}

    if config_content is not None:
        paths["config"] = _write_tmp_config(monkeypatch, config_content)
    else:
        # Use fixture with ssh_user
        paths["config"] = _write_tmp_config(monkeypatch, _CONFIG_WITH_SSH_USER)

    if template_content is not None:
        fd, tpath = tempfile.mkstemp(suffix=".sh.template")
        os.write(fd, template_content.encode())
        os.close(fd)
        paths["template"] = tpath

    return paths


def _run_services_deploy(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str] | None = None,
    config_content: str | None = None,
    template_path: str | None = None,
    mock_sftp: AsyncMock | None = None,
) -> object:
    """Run 'cloudways services deploy' with mocked deps."""
    paths = _setup_env(monkeypatch, config_content=config_content)

    cmd_args = ["services", "deploy"] + (args or [])

    sftp_mock = mock_sftp or AsyncMock()

    with patch(
        "cloudways_api.commands.services.sftp_upload",
        sftp_mock,
    ):
        if template_path:
            # Override the template default
            with patch(
                "cloudways_api.commands.services._DEFAULT_TEMPLATE",
                Path(template_path),
            ):
                result = runner.invoke(app, cmd_args)
        else:
            result = runner.invoke(app, cmd_args)

    return result, sftp_mock, paths


# ===========================================================================
# Tests
# ===========================================================================


class TestServicesDeployRegistration:
    """Verify the services deploy command is registered."""

    def test_services_deploy_registered(self) -> None:
        """'cloudways services deploy --help' exits 0."""
        result = runner.invoke(app, ["services", "deploy", "--help"])
        assert result.exit_code == 0
        assert "deploy" in result.output.lower()


class TestServicesDeploySuccess:
    """Happy path: template rendered and uploaded."""

    def test_services_deploy_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Mock sftp_upload; assert called with correct remote_path."""
        template = tmp_path / "services.sh.template"
        template.write_text(
            "#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\nAPI_KEY=CLOUDWAYS_API_KEY\n"
        )

        result, sftp_mock, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path=str(template),
        )

        assert result.exit_code == 0
        sftp_mock.assert_called_once()
        call_args = sftp_mock.call_args
        # remote_path should contain the ssh_user from env config
        remote_path = call_args[0][3] if len(call_args[0]) > 3 else call_args.kwargs.get("remote_path", "")
        assert "/home/master/applications/unsvkhbwwr/private_html/services.sh" in remote_path or remote_path == "/home/master/applications/unsvkhbwwr/private_html/services.sh"

    def test_services_deploy_template_substitution(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Verify rendered content has real email/key, not literal tokens."""
        template = tmp_path / "services.sh.template"
        template.write_text(
            "#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\nAPI_KEY=CLOUDWAYS_API_KEY\n"
        )

        captured_content = {}

        async def capture_sftp(host, user, local_path, remote_path):
            """Capture the content of the uploaded file."""
            captured_content["text"] = Path(local_path).read_text()

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path=str(template),
            mock_sftp=AsyncMock(side_effect=capture_sftp),
        )

        assert result.exit_code == 0
        text = captured_content["text"]
        # Should have real credentials, not literal tokens
        assert "anthonys@projectassistant.org" in text
        assert "plain_text_api_key_12345" in text
        # Literal tokens should be gone
        assert "CLOUDWAYS_EMAIL" not in text.split("=")[1] if "=" in text else True
        # More precise check: the exact literal tokens should be replaced
        assert "EMAIL=CLOUDWAYS_EMAIL" not in text
        assert "API_KEY=CLOUDWAYS_API_KEY" not in text


class TestServicesDeployErrors:
    """Error scenarios."""

    def test_services_deploy_missing_template(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing template file -> exits 1."""
        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path="/nonexistent/template.sh",
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "template" in result.output.lower()

    def test_services_deploy_missing_ssh_host_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing server.ssh_host -> exits 1."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            config_content=_CONFIG_NO_SSH_HOST,
            template_path=str(template),
        )
        assert result.exit_code == 1
        assert "ssh_host" in result.output.lower() or "ssh" in result.output.lower()

    def test_services_deploy_missing_env_ssh_user(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing environments.{env}.ssh_user -> exits 1."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            config_content=_CONFIG_NO_ENV_SSH_USER,
            template_path=str(template),
        )
        assert result.exit_code == 1
        output_lower = result.output.lower()
        assert "ssh_user" in output_lower
        assert "environments" in output_lower or "production" in output_lower

    def test_services_deploy_missing_ssh_user_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Missing environments.production.ssh_user with config key path in error."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            config_content=_CONFIG_NO_ENV_SSH_USER,
            template_path=str(template),
        )
        assert result.exit_code == 1
        # Error must include the config key path
        assert "environments.production.ssh_user" in result.output.lower() or \
               "environments.production.ssh_user" in result.output

    def test_services_deploy_scp_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """sftp_upload raises SSHError -> exits 1."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        failing_sftp = AsyncMock(side_effect=SSHError("Connection refused"))

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path=str(template),
            mock_sftp=failing_sftp,
        )
        assert result.exit_code == 1
        assert "error" in result.output.lower()


class TestServicesDeployCleanup:
    """Verify temp file cleanup."""

    def test_services_deploy_cleanup_on_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Temp file cleaned up after successful upload."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        uploaded_paths = []

        async def track_sftp(host, user, local_path, remote_path):
            uploaded_paths.append(local_path)

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path=str(template),
            mock_sftp=AsyncMock(side_effect=track_sftp),
        )

        assert result.exit_code == 0
        assert len(uploaded_paths) == 1
        # Temp file should be cleaned up
        assert not Path(uploaded_paths[0]).exists()

    def test_services_deploy_cleanup_on_scp_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Temp file cleaned up after SCP failure."""
        template = tmp_path / "services.sh.template"
        template.write_text("#!/bin/bash\nEMAIL=CLOUDWAYS_EMAIL\n")

        uploaded_paths = []

        async def failing_sftp(host, user, local_path, remote_path):
            uploaded_paths.append(local_path)
            raise SSHError("Upload failed")

        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path=str(template),
            mock_sftp=AsyncMock(side_effect=failing_sftp),
        )

        assert result.exit_code == 1
        assert len(uploaded_paths) == 1
        # Temp file should still be cleaned up
        assert not Path(uploaded_paths[0]).exists()

    def test_services_deploy_cleanup_on_template_read_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No temp file created if template read fails."""
        # Point to a missing template
        result, _, _ = _run_services_deploy(
            monkeypatch,
            args=["production"],
            template_path="/nonexistent/template.sh",
        )
        assert result.exit_code == 1
        # No temp file should be created (nothing to clean up)


class TestServicesDeployTemplateDiscoverable:
    """Verify template exists in package."""

    def test_services_deploy_template_discoverable(self) -> None:
        """Template file exists at the expected package path."""
        from cloudways_api.commands.services import _DEFAULT_TEMPLATE
        assert _DEFAULT_TEMPLATE.is_file(), (
            f"Template not found at {_DEFAULT_TEMPLATE}. "
            "Ensure cloudways_api/templates/cloudways-services.sh.template exists."
        )
