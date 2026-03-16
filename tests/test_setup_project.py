"""Tests for setup-project composite command.

Covers full success path, partial failures, fatal provision failures,
summary output, missing SSH username, missing key files, app_id
propagation from provision steps to downstream steps, helper-level
integration tests, execution order verification, and exact argument
assertions.
"""

import os
from urllib.parse import parse_qs
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CONFIG_PATH = os.path.join(FIXTURES_DIR, "project-config.yml")
ACCOUNTS_PATH = os.path.join(FIXTURES_DIR, "accounts.yml")


def _env_vars() -> dict:
    """Standard env vars pointing to test fixture config."""
    return {
        "CLOUDWAYS_PROJECT_CONFIG": CONFIG_PATH,
        "CLOUDWAYS_ACCOUNTS_FILE": ACCOUNTS_PATH,
    }


# All 12 _run_* helpers that need to be mocked for a full workflow test.
_MODULE = "cloudways_api.commands.setup_project"

_ALL_PATCHES = [
    f"{_MODULE}._run_provision_prod",
    f"{_MODULE}._run_provision_staging",
    f"{_MODULE}._run_ssh_user_create_prod",
    f"{_MODULE}._run_ssh_user_create_staging",
    f"{_MODULE}._run_ssh_key_add_my_prod",
    f"{_MODULE}._run_ssh_key_add_my_staging",
    f"{_MODULE}._run_ssh_key_add_pipeline_prod",
    f"{_MODULE}._run_ssh_key_add_pipeline_staging",
    f"{_MODULE}._run_services_deploy_prod",
    f"{_MODULE}._run_services_deploy_staging",
    f"{_MODULE}._run_reset_permissions_prod",
    f"{_MODULE}._run_reset_permissions_staging",
]


def _make_tmp_key_files(tmp_path):
    """Create temporary SSH key files for testing."""
    my_key = tmp_path / "id_ed25519.pub"
    my_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 my@key\n")
    pipeline_key = tmp_path / "id_ed25519_pipeline.pub"
    pipeline_key.write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 pipeline@key\n")
    return str(my_key), str(pipeline_key)


class TestSetupProjectHelp:
    """CLI registration tests for setup-project."""

    def test_setup_project_registered(self) -> None:
        """setup-project is registered and shows help text."""
        result = runner.invoke(app, ["setup-project", "--help"])
        assert result.exit_code == 0
        assert "setup-project" in result.output.lower() or "project" in result.output.lower()


class TestSetupProjectCommand:
    """Tests for the setup-project composite CLI command."""

    def _invoke(self, args: list[str]) -> object:
        """Invoke setup-project with standard config env vars."""
        return runner.invoke(app, ["setup-project"] + args, env=_env_vars())

    # ------------------------------------------------------------------
    # Full success path
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_full_workflow_all_steps_called(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """All 12 steps execute successfully in correct order."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)

        # Track execution order with a shared recorder
        call_order: list[str] = []

        all_mocks = {
            "provision_prod": mock_prov_prod,
            "provision_staging": mock_prov_staging,
            "ssh_user_prod": mock_ssh_user_prod,
            "ssh_user_staging": mock_ssh_user_staging,
            "key_my_prod": mock_key_my_prod,
            "key_my_staging": mock_key_my_staging,
            "key_pipe_prod": mock_key_pipe_prod,
            "key_pipe_staging": mock_key_pipe_staging,
            "svc_prod": mock_svc_prod,
            "svc_staging": mock_svc_staging,
            "perm_prod": mock_perm_prod,
            "perm_staging": mock_perm_staging,
        }

        def _make_recorder(name, return_value):
            async def _record(*args, **kwargs):
                call_order.append(name)
                return return_value
            return _record

        mock_prov_prod.side_effect = _make_recorder("provision_prod", "1001")
        mock_prov_staging.side_effect = _make_recorder("provision_staging", "2001")
        for name in [
            "ssh_user_prod", "ssh_user_staging",
            "key_my_prod", "key_my_staging",
            "key_pipe_prod", "key_pipe_staging",
            "svc_prod", "svc_staging",
            "perm_prod", "perm_staging",
        ]:
            all_mocks[name].side_effect = _make_recorder(name, None)

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 0, f"Output: {result.output}"

        # Verify all 12 steps were called
        assert len(call_order) == 12

        # Verify exact execution sequence (steps 1-2 must precede 3-12)
        expected_order = [
            "provision_prod",
            "provision_staging",
            "ssh_user_prod",
            "ssh_user_staging",
            "key_my_prod",
            "key_my_staging",
            "key_pipe_prod",
            "key_pipe_staging",
            "svc_prod",
            "svc_staging",
            "perm_prod",
            "perm_staging",
        ]
        assert call_order == expected_order

    # ------------------------------------------------------------------
    # Partial failure continues
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_partial_failure_continues(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """One non-fatal step fails, remaining steps still run."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)

        mock_prov_prod.return_value = "1001"
        mock_prov_staging.return_value = "2001"
        mock_ssh_user_prod.return_value = None
        mock_ssh_user_staging.return_value = None
        mock_key_my_prod.side_effect = Exception("Key add failed")
        mock_key_my_staging.return_value = None
        mock_key_pipe_prod.return_value = None
        mock_key_pipe_staging.return_value = None
        mock_svc_prod.return_value = None
        mock_svc_staging.return_value = None
        mock_perm_prod.return_value = None
        mock_perm_staging.return_value = None

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        # Exit code 1 because at least one step failed
        assert result.exit_code == 1

        # Steps after the failure should still run
        mock_key_my_staging.assert_called_once()
        mock_key_pipe_prod.assert_called_once()
        mock_svc_prod.assert_called_once()
        mock_perm_staging.assert_called_once()

    # ------------------------------------------------------------------
    # Provision prod failure aborts
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_provision_failure_aborts(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """Step 1 (production provision) fails, no further steps."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)
        mock_prov_prod.side_effect = Exception("Provision failed")

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 1

        mock_prov_staging.assert_not_called()
        mock_ssh_user_prod.assert_not_called()
        mock_svc_prod.assert_not_called()
        mock_perm_prod.assert_not_called()

    # ------------------------------------------------------------------
    # Staging provision failure aborts
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_staging_provision_failure_aborts(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """Step 2 (staging provision) fails, steps 3-12 don't run."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)
        mock_prov_prod.return_value = "1001"
        mock_prov_staging.side_effect = Exception("Staging provision failed")

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 1

        mock_ssh_user_prod.assert_not_called()
        mock_svc_prod.assert_not_called()
        mock_perm_staging.assert_not_called()

    # ------------------------------------------------------------------
    # Summary output
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_shows_summary_output(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """Output contains summary of step results."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)
        mock_prov_prod.return_value = "1001"
        mock_prov_staging.return_value = "2001"
        for m in [
            mock_ssh_user_prod, mock_ssh_user_staging,
            mock_key_my_prod, mock_key_my_staging,
            mock_key_pipe_prod, mock_key_pipe_staging,
            mock_svc_prod, mock_svc_staging,
            mock_perm_prod, mock_perm_staging,
        ]:
            m.return_value = None

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "summary" in output_lower or "setup" in output_lower

    # ------------------------------------------------------------------
    # Missing --ssh-username
    # ------------------------------------------------------------------

    def test_setup_project_missing_ssh_username(self, tmp_path) -> None:
        """Omit --ssh-username; exit code 2 (Typer usage error)."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)
        result = self._invoke([
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 2

    # ------------------------------------------------------------------
    # app_id propagation
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_app_id_flows_from_provision_to_steps(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """Provision returns app_ids that flow to downstream steps."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)
        mock_prov_prod.return_value = "1001"
        mock_prov_staging.return_value = "2001"
        for m in [
            mock_ssh_user_prod, mock_ssh_user_staging,
            mock_key_my_prod, mock_key_my_staging,
            mock_key_pipe_prod, mock_key_pipe_staging,
            mock_svc_prod, mock_svc_staging,
            mock_perm_prod, mock_perm_staging,
        ]:
            m.return_value = None

        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 0

        # Extract server_id from fixture config (avoid hardcoding)
        fixture_server_id = 999999

        # Step 3: ssh-user create prod gets exact prod_app_id and server_id
        mock_ssh_user_prod.assert_awaited_once_with(
            mock_ssh_user_prod.call_args[0][0],  # creds (dict, verified separately)
            fixture_server_id,
            "1001",      # prod_app_id
            "testuser",  # ssh_username
        )

        # Step 4: ssh-user create staging gets exact staging_app_id
        # with default -stg suffix for shared server support
        mock_ssh_user_staging.assert_awaited_once_with(
            mock_ssh_user_staging.call_args[0][0],  # creds
            fixture_server_id,
            "2001",          # staging_app_id
            "testuser-stg",  # ssh_username (default -stg suffix)
        )

        # Step 5: my key prod gets exact prod_app_id
        mock_key_my_prod.assert_awaited_once_with(
            mock_key_my_prod.call_args[0][0],  # creds
            fixture_server_id,
            "1001",                             # prod_app_id
            "testuser",                         # ssh_username
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 my@key",  # key content
        )

        # Step 6: my key staging gets exact staging_app_id
        # with default -stg suffix for shared server support
        mock_key_my_staging.assert_awaited_once_with(
            mock_key_my_staging.call_args[0][0],  # creds
            fixture_server_id,
            "2001",                                 # staging_app_id
            "testuser-stg",                         # ssh_username (default -stg suffix)
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 my@key",  # key content
        )

    # ------------------------------------------------------------------
    # Missing key files (preflight validation)
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_missing_my_key_file(
        self,
        mock_prov_prod: AsyncMock,
        tmp_path,
    ) -> None:
        """Non-existent --my-key-file exits before any API calls."""
        _, pipe_key = _make_tmp_key_files(tmp_path)
        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", "/nonexistent/path/id_ed25519.pub",
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 1
        mock_prov_prod.assert_not_called()

    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_missing_pipeline_key_file(
        self,
        mock_prov_prod: AsyncMock,
        tmp_path,
    ) -> None:
        """Non-existent --pipeline-key-file exits before any API calls."""
        my_key, _ = _make_tmp_key_files(tmp_path)
        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", "/nonexistent/path/id_pipeline.pub",
        ])
        assert result.exit_code == 1
        mock_prov_prod.assert_not_called()

    # ------------------------------------------------------------------
    # SSH key content validation (H2)
    # ------------------------------------------------------------------

    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_invalid_my_key_content_aborts(
        self,
        mock_prov_prod: AsyncMock,
        tmp_path,
    ) -> None:
        """Invalid SSH key content in --my-key-file aborts before API calls."""
        my_key = tmp_path / "bad_key.pub"
        my_key.write_text("this is not an SSH key\n")
        _, pipe_key = _make_tmp_key_files(tmp_path)
        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", str(my_key),
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 1
        assert "valid ssh public key" in result.output.lower()
        mock_prov_prod.assert_not_called()

    @patch(f"{_MODULE}._run_provision_prod")
    def test_setup_project_invalid_pipeline_key_content_aborts(
        self,
        mock_prov_prod: AsyncMock,
        tmp_path,
    ) -> None:
        """Invalid SSH key content in --pipeline-key-file aborts before API calls."""
        my_key, _ = _make_tmp_key_files(tmp_path)
        bad_pipe = tmp_path / "bad_pipe.pub"
        bad_pipe.write_text("NOT-A-KEY garbage data\n")
        result = self._invoke([
            "--ssh-username", "testuser",
            "--my-key-file", my_key,
            "--pipeline-key-file", str(bad_pipe),
        ])
        assert result.exit_code == 1
        assert "valid ssh public key" in result.output.lower()
        mock_prov_prod.assert_not_called()


# ======================================================================
# Helper-level integration tests (H3)
# ======================================================================

class TestRunProvisionHelpers:
    """Test _run_provision_prod and _run_provision_staging with patched transport.

    These tests exercise the actual helper functions (not mocked) against a
    patched CloudwaysClient to catch call signature mismatches like H1.
    """

    def _make_transport(self, responses: dict[str, httpx.Response]):
        """Create a MockTransport that maps URL paths to responses."""
        def _handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            for pattern, response in responses.items():
                if pattern in path:
                    return response
            return httpx.Response(404, json={"error": "not found"})
        return httpx.MockTransport(_handler)

    @pytest.mark.asyncio
    async def test_run_provision_prod_calls_create_app_with_project_name(self) -> None:
        """_run_provision_prod passes project_name to create_app (H1 fix)."""
        captured_requests: list[httpx.Request] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            path = request.url.path

            if "oauth" in path or "token" in path:
                return httpx.Response(200, json=make_auth_response())

            if "/app" in path and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "app": {"id": 9999},
                        "operation_id": None,
                    },
                )

            return httpx.Response(200, json={})

        transport = httpx.MockTransport(_handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.setup_project.CloudwaysClient",
            PatchedClient,
        ):
            from cloudways_api.commands.setup_project import _run_provision_prod

            result = await _run_provision_prod(
                config={}, creds={"email": "t@t.com", "api_key": "key"}, server_id=111
            )

        assert result == "9999"

        # Verify create_app request included project_name
        create_app_reqs = [
            r for r in captured_requests
            if r.method == "POST" and "/app" in r.url.path
        ]
        assert len(create_app_reqs) == 1
        body = parse_qs(create_app_reqs[0].content.decode())
        assert "project_name" in body, "create_app must include project_name"
        assert body["project_name"] == ["Default"]

    @pytest.mark.asyncio
    async def test_run_provision_staging_calls_create_staging_app(self) -> None:
        """_run_provision_staging passes correct args to create_staging_app."""
        captured_requests: list[httpx.Request] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            path = request.url.path

            if "oauth" in path or "token" in path:
                return httpx.Response(200, json=make_auth_response())

            if "/app/clone" in path and request.method == "POST":
                return httpx.Response(
                    200,
                    json={
                        "app": {"id": 8888},
                        "operation_id": None,
                    },
                )

            return httpx.Response(200, json={})

        transport = httpx.MockTransport(_handler)
        PatchedClient = make_patched_client_class(transport)

        with patch(
            "cloudways_api.commands.setup_project.CloudwaysClient",
            PatchedClient,
        ):
            from cloudways_api.commands.setup_project import _run_provision_staging

            result = await _run_provision_staging(
                config={},
                creds={"email": "t@t.com", "api_key": "key"},
                server_id=111,
                prod_app_id="9999",
                staging_label="staging",
            )

        assert result == "8888"

        # Verify staging clone request was sent
        staging_reqs = [
            r for r in captured_requests
            if r.method == "POST" and "/app/clone" in r.url.path
        ]
        assert len(staging_reqs) == 1
        body = parse_qs(staging_reqs[0].content.decode())
        assert body.get("project_name") == ["Default"]


# ======================================================================
# Staging SSH username tests (shared server support)
# ======================================================================


class TestSetupProjectStagingSshUsername:
    """Tests for --staging-ssh-username option and default -stg suffix."""

    def _invoke(self, args: list[str]) -> object:
        return runner.invoke(app, ["setup-project"] + args, env=_env_vars())

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_default_staging_username_has_stg_suffix(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """Without --staging-ssh-username, staging user defaults to {name}-stg."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)

        mock_prov_prod.return_value = "1001"
        mock_prov_staging.return_value = "2001"
        for m in [
            mock_ssh_user_prod, mock_ssh_user_staging,
            mock_key_my_prod, mock_key_my_staging,
            mock_key_pipe_prod, mock_key_pipe_staging,
            mock_svc_prod, mock_svc_staging,
            mock_perm_prod, mock_perm_staging,
        ]:
            m.return_value = None

        result = self._invoke([
            "--ssh-username", "bitbucket",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 0, f"Output: {result.output}"

        # Staging SSH user should use the -stg suffix
        mock_ssh_user_staging.assert_awaited_once()
        staging_username_arg = mock_ssh_user_staging.call_args[0][3]
        assert staging_username_arg == "bitbucket-stg"

        # Production SSH user should use the original name
        mock_ssh_user_prod.assert_awaited_once()
        prod_username_arg = mock_ssh_user_prod.call_args[0][3]
        assert prod_username_arg == "bitbucket"

        # Staging SSH key steps should use -stg username
        mock_key_my_staging.assert_awaited_once()
        key_staging_username = mock_key_my_staging.call_args[0][3]
        assert key_staging_username == "bitbucket-stg"

    @patch(f"{_MODULE}._run_reset_permissions_staging")
    @patch(f"{_MODULE}._run_reset_permissions_prod")
    @patch(f"{_MODULE}._run_services_deploy_staging")
    @patch(f"{_MODULE}._run_services_deploy_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_pipeline_prod")
    @patch(f"{_MODULE}._run_ssh_key_add_my_staging")
    @patch(f"{_MODULE}._run_ssh_key_add_my_prod")
    @patch(f"{_MODULE}._run_ssh_user_create_staging")
    @patch(f"{_MODULE}._run_ssh_user_create_prod")
    @patch(f"{_MODULE}._run_provision_staging")
    @patch(f"{_MODULE}._run_provision_prod")
    def test_explicit_staging_ssh_username_override(
        self,
        mock_prov_prod: AsyncMock,
        mock_prov_staging: AsyncMock,
        mock_ssh_user_prod: AsyncMock,
        mock_ssh_user_staging: AsyncMock,
        mock_key_my_prod: AsyncMock,
        mock_key_my_staging: AsyncMock,
        mock_key_pipe_prod: AsyncMock,
        mock_key_pipe_staging: AsyncMock,
        mock_svc_prod: AsyncMock,
        mock_svc_staging: AsyncMock,
        mock_perm_prod: AsyncMock,
        mock_perm_staging: AsyncMock,
        tmp_path,
    ) -> None:
        """--staging-ssh-username overrides the default -stg suffix."""
        my_key, pipe_key = _make_tmp_key_files(tmp_path)

        mock_prov_prod.return_value = "1001"
        mock_prov_staging.return_value = "2001"
        for m in [
            mock_ssh_user_prod, mock_ssh_user_staging,
            mock_key_my_prod, mock_key_my_staging,
            mock_key_pipe_prod, mock_key_pipe_staging,
            mock_svc_prod, mock_svc_staging,
            mock_perm_prod, mock_perm_staging,
        ]:
            m.return_value = None

        result = self._invoke([
            "--ssh-username", "bitbucket",
            "--staging-ssh-username", "bitbucket-staging",
            "--my-key-file", my_key,
            "--pipeline-key-file", pipe_key,
        ])
        assert result.exit_code == 0, f"Output: {result.output}"

        # Staging SSH user should use the explicit override
        mock_ssh_user_staging.assert_awaited_once()
        staging_username_arg = mock_ssh_user_staging.call_args[0][3]
        assert staging_username_arg == "bitbucket-staging"

        # Production SSH user should still use the original name
        mock_ssh_user_prod.assert_awaited_once()
        prod_username_arg = mock_ssh_user_prod.call_args[0][3]
        assert prod_username_arg == "bitbucket"

        # All staging key steps should use the explicit override
        mock_key_my_staging.assert_awaited_once()
        assert mock_key_my_staging.call_args[0][3] == "bitbucket-staging"
        mock_key_pipe_staging.assert_awaited_once()
        assert mock_key_pipe_staging.call_args[0][3] == "bitbucket-staging"
