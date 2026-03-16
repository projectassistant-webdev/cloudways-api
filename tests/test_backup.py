"""Tests for backup/disk commands and client methods.

Covers backup trigger, backup settings, disk settings, and disk cleanup
commands with mocked Cloudways API responses, plus client method tests
for all five backup/disk operations.
"""

import time as _time
from unittest.mock import patch

import httpx
import pytest
from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import APIError
from conftest import make_auth_response, make_patched_client_class

runner = CliRunner()


# --- Mock API response helpers ---


def _make_operation_complete_response():
    """Return a completed operation response."""
    return {"operation": {"is_completed": True, "status": "completed"}}


def _make_operation_pending_response():
    """Return a pending (not completed) operation response."""
    return {"operation": {"is_completed": False, "status": "pending"}}


# --- Handler factory ---


def _make_backup_handler(
    backup_trigger_response=None,
    backup_trigger_error=False,
    backup_settings_response=None,
    backup_settings_error=False,
    servers_response=None,
    servers_error=False,
    disk_get_response=None,
    disk_get_error=False,
    disk_put_response=None,
    disk_put_error=False,
    disk_cleanup_response=None,
    disk_cleanup_error=False,
    operation_response=None,
):
    """Build httpx mock handler for backup and disk API calls.

    Returns a (handler, captured) tuple where captured is a mutable list
    that accumulates every httpx.Request seen by the handler.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        url = str(request.url)
        method = request.method

        if "/oauth/access_token" in url:
            return httpx.Response(200, json=make_auth_response())

        if "/operation/" in url:
            return httpx.Response(
                200, json=operation_response or _make_operation_complete_response()
            )

        # CRITICAL: /server/manage/backupSettings BEFORE /server/manage/backup
        # to avoid backupSettings being matched by the shorter prefix
        if "/server/manage/backupSettings" in url and method == "POST":
            if backup_settings_error:
                return httpx.Response(422, text="Settings update failed")
            return httpx.Response(200, json=backup_settings_response or {})

        if "/server/manage/backup" in url and method == "POST":
            if backup_trigger_error:
                return httpx.Response(422, text="Backup failed")
            return httpx.Response(
                200, json=backup_trigger_response or {"operation_id": 99002}
            )

        # CRITICAL: /server/disk/cleanup BEFORE /server/disk/ to avoid cleanup
        # being treated as a server_id path param
        if "/server/disk/cleanup" in url and method == "POST":
            if disk_cleanup_error:
                return httpx.Response(422, text="Cleanup failed")
            return httpx.Response(
                200, json=disk_cleanup_response or {"operation_id": 99003}
            )

        if "/server/disk" in url and method == "GET":
            if disk_get_error:
                return httpx.Response(422, text="Disk settings unavailable")
            return httpx.Response(
                200,
                json=disk_get_response
                or {
                    "settings": {
                        "automate_cleanup": "disabled",
                        "remove_app_local_backup": "no",
                        "remove_app_private_html": "no",
                        "remove_app_tmp": "no",
                        "rotate_app_log": "no",
                        "rotate_system_log": "no",
                    }
                },
            )

        if "/server/disk/" in url and method == "PUT":
            if disk_put_error:
                return httpx.Response(422, text="Disk settings update failed")
            return httpx.Response(200, json=disk_put_response or {})

        if "/server" in url and method == "GET":
            if servers_error:
                return httpx.Response(422, text="Server list unavailable")
            return httpx.Response(
                200, json=servers_response or {"servers": []}
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests
# ===================================================================


class TestTriggerBackup:
    """Tests for CloudwaysClient.trigger_backup()."""

    @pytest.mark.asyncio
    async def test_trigger_backup_success(self) -> None:
        """POST /server/manage/backup with server_id in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/backup" in str(request.url) and request.method == "POST":
                return httpx.Response(200, json={"operation_id": 99002})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_backup(server_id=999999)

        assert result["operation_id"] == 99002
        request = [
            r
            for r in captured
            if r.method == "POST" and "/server/manage/backup" in str(r.url)
        ][0]
        assert request.method == "POST"
        assert "/server/manage/backup" in str(request.url)
        assert request.content.decode() == "server_id=999999"

    @pytest.mark.asyncio
    async def test_trigger_backup_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/backup" in str(request.url):
                return httpx.Response(422, text="Backup failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.trigger_backup(server_id=999999)


class TestUpdateBackupSettings:
    """Tests for CloudwaysClient.update_backup_settings()."""

    @pytest.mark.asyncio
    async def test_update_backup_settings_with_all_fields(self) -> None:
        """POST /server/manage/backupSettings with all fields."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/server/manage/backupSettings" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_backup_settings(
                server_id=999999,
                backup_frequency="24",
                backup_retention=7,
                local_backups=True,
                backup_time="00:10",
            )

        assert result == {}
        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/server/manage/backupSettings" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "backup_frequency=24" in body
        assert "backup_retention=7" in body
        assert "backup_time=00%3A10" in body
        assert "local_backups=true" in body

    @pytest.mark.asyncio
    async def test_update_backup_settings_omits_none_fields(self) -> None:
        """Only sends server_id and local_backups when others are None."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/server/manage/backupSettings" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            await client.update_backup_settings(
                server_id=999999, local_backups=False
            )

        request = [
            r
            for r in captured
            if r.method == "POST"
            and "/server/manage/backupSettings" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "local_backups=false" in body
        assert "backup_frequency" not in body
        assert "backup_retention" not in body
        assert "backup_time" not in body

    @pytest.mark.asyncio
    async def test_update_backup_settings_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/manage/backupSettings" in str(request.url):
                return httpx.Response(422, text="Settings update failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_backup_settings(
                    server_id=999999, local_backups=True
                )


class TestGetDiskSettings:
    """Tests for CloudwaysClient.get_disk_settings()."""

    @pytest.mark.asyncio
    async def test_get_disk_settings_success(self) -> None:
        """GET /server/disk with server_id as query parameter."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/disk" in str(request.url) and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "settings": {
                            "automate_cleanup": "disabled",
                            "remove_app_local_backup": "no",
                            "remove_app_private_html": "no",
                            "remove_app_tmp": "no",
                            "rotate_app_log": "no",
                            "rotate_system_log": "no",
                        }
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.get_disk_settings(server_id=999999)

        assert result["settings"]["automate_cleanup"] == "disabled"
        assert result["settings"]["remove_app_tmp"] == "no"
        request = [
            r
            for r in captured
            if r.method == "GET" and "/server/disk" in str(r.url)
        ][0]
        assert request.method == "GET"
        assert "server_id=999999" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_disk_settings_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/disk" in str(request.url):
                return httpx.Response(422, text="Disk settings unavailable")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.get_disk_settings(server_id=999999)


class TestUpdateDiskSettings:
    """Tests for CloudwaysClient.update_disk_settings()."""

    @pytest.mark.asyncio
    async def test_update_disk_settings_success(self) -> None:
        """PUT /server/disk/{server_id} with settings in form body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/disk/999999" in str(request.url) and request.method == "PUT":
                return httpx.Response(200, content=b"")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.update_disk_settings(
                server_id=999999,
                automate_cleanup="enable",
                remove_app_tmp="yes",
                remove_app_private_html="no",
                rotate_system_log="yes",
                rotate_app_log="no",
                remove_app_local_backup="no",
            )

        assert result == {}
        request = [r for r in captured if r.method == "PUT"][0]
        assert "/server/disk/999999" in str(request.url)
        body = request.content.decode()
        assert "automate_cleanup=enable" in body
        assert "remove_app_tmp=yes" in body
        assert "remove_app_private_html=no" in body
        assert "rotate_system_log=yes" in body
        assert "rotate_app_log=no" in body
        assert "remove_app_local_backup=no" in body

    @pytest.mark.asyncio
    async def test_update_disk_settings_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/disk/" in str(request.url) and request.method == "PUT":
                return httpx.Response(422, text="Disk settings update failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.update_disk_settings(
                    server_id=999999,
                    automate_cleanup="enable",
                    remove_app_tmp="yes",
                    remove_app_private_html="no",
                    rotate_system_log="yes",
                    rotate_app_log="no",
                    remove_app_local_backup="no",
                )


class TestTriggerDiskCleanup:
    """Tests for CloudwaysClient.trigger_disk_cleanup()."""

    @pytest.mark.asyncio
    async def test_trigger_disk_cleanup_success(self) -> None:
        """POST /server/disk/cleanup with server_id and scope in body."""
        captured = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if (
                "/server/disk/cleanup" in str(request.url)
                and request.method == "POST"
            ):
                return httpx.Response(200, json={"operation_id": 99003})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.trigger_disk_cleanup(
                server_id=999999,
                remove_app_tmp="yes",
                remove_app_private_html="no",
                rotate_system_log="yes",
                rotate_app_log="no",
                remove_app_local_backup="no",
            )

        assert result["operation_id"] == 99003
        request = [
            r
            for r in captured
            if r.method == "POST" and "/server/disk/cleanup" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "remove_app_tmp=yes" in body
        assert "remove_app_private_html=no" in body
        assert "rotate_system_log=yes" in body
        assert "rotate_app_log=no" in body
        assert "remove_app_local_backup=no" in body

    @pytest.mark.asyncio
    async def test_trigger_disk_cleanup_api_error(self) -> None:
        """Raises APIError on 422."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "/oauth/access_token" in str(request.url):
                return httpx.Response(200, json=make_auth_response())
            if "/server/disk/cleanup" in str(request.url):
                return httpx.Response(422, text="Cleanup failed")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.trigger_disk_cleanup(
                    server_id=999999,
                    remove_app_tmp="yes",
                    remove_app_private_html="no",
                    rotate_system_log="yes",
                    rotate_app_log="no",
                    remove_app_local_backup="no",
                )


# ===================================================================
# CLI command tests
# ===================================================================


class TestBackupRunCli:
    """Tests for `cloudways backup run` command."""

    def test_backup_run_no_wait(self, set_env) -> None:
        """Without --wait, prints operation ID and exits immediately."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["backup", "run"])

        assert result.exit_code == 0, result.output
        assert "Backup triggered. Operation ID: 99002" in result.output
        assert "Backup complete." not in result.output

    def test_backup_run_with_wait(self, set_env) -> None:
        """With --wait, polls operation and prints completion."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
                result = runner.invoke(app, ["backup", "run", "--wait"])

        assert result.exit_code == 0, result.output
        assert "Backup complete." in result.output

    def test_backup_run_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_backup_handler(backup_trigger_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["backup", "run"])

        assert result.exit_code == 1

    def test_backup_run_wait_timeout(self, set_env) -> None:
        """Operation timeout exits 1."""
        handler, captured = _make_backup_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.backup.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(
                        app, ["backup", "run", "--wait", "--timeout", "1"]
                    )

        assert result.exit_code == 1


class TestBackupSettingsGetCli:
    """Tests for `cloudways backup settings get` command."""

    def test_backup_settings_get_server_found(self, set_env) -> None:
        """Displays backup fields from server object."""
        handler, captured = _make_backup_handler(
            servers_response={
                "servers": [
                    {
                        "id": "999999",
                        "backup_frequency": "24",
                        "local_backups": "yes",
                        "snapshot_frequency": "0",
                    }
                ]
            }
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["backup", "settings", "get"])

        assert result.exit_code == 0, result.output
        assert "backup_frequency: 24" in result.output
        assert "local_backups: yes" in result.output
        assert "snapshot_frequency: 0" in result.output

    def test_backup_settings_get_server_not_found(self, set_env) -> None:
        """Server not found exits 1 with error message."""
        handler, captured = _make_backup_handler(
            servers_response={
                "servers": [{"id": "9999999", "backup_frequency": "24"}]
            }
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["backup", "settings", "get"], catch_exceptions=False
            )

        assert result.exit_code == 1
        assert "Error: Server 999999 not found in account." in result.output


class TestBackupSettingsSetCli:
    """Tests for `cloudways backup settings set` command."""

    def test_backup_settings_set_success(self, set_env) -> None:
        """Sets backup settings with all options."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "backup",
                    "settings",
                    "set",
                    "--frequency",
                    "24",
                    "--retention",
                    "7",
                    "--time",
                    "00:10",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Backup settings updated." in result.output
        post_req = next(
            r
            for r in captured
            if r.method == "POST"
            and "/server/manage/backupSettings" in str(r.url)
        )
        body = post_req.content.decode()
        assert "backup_frequency=24" in body
        assert "backup_retention=7" in body
        assert "backup_time=00%3A10" in body
        assert "local_backups=true" in body
        assert "server_id=999999" in body

    def test_backup_settings_set_no_local_backups(self, set_env) -> None:
        """--no-local-backups sends local_backups=false."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["backup", "settings", "set", "--no-local-backups"]
            )

        assert result.exit_code == 0, result.output
        post_req = next(
            r
            for r in captured
            if r.method == "POST"
            and "/server/manage/backupSettings" in str(r.url)
        )
        body = post_req.content.decode()
        assert "local_backups=false" in body

    def test_backup_settings_set_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_backup_handler(backup_settings_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.backup.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["backup", "settings", "set"])

        assert result.exit_code == 1


class TestDiskSettingsGetCli:
    """Tests for `cloudways disk settings get` command."""

    def test_disk_settings_get_success(self, set_env) -> None:
        """Displays all six disk settings."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["disk", "settings", "get"])

        assert result.exit_code == 0, result.output
        assert "automate_cleanup: disabled" in result.output
        assert "rotate_system_log: no" in result.output

    def test_disk_settings_get_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_backup_handler(disk_get_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["disk", "settings", "get"])

        assert result.exit_code == 1


class TestDiskSettingsSetCli:
    """Tests for `cloudways disk settings set` command."""

    def test_disk_settings_set_success(self, set_env) -> None:
        """Sets all six disk settings."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "disk",
                    "settings",
                    "set",
                    "--automate-cleanup",
                    "enable",
                    "--remove-tmp",
                    "yes",
                    "--remove-private-html",
                    "no",
                    "--rotate-system-log",
                    "yes",
                    "--rotate-app-log",
                    "no",
                    "--remove-local-backup",
                    "no",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Disk settings updated." in result.output
        put_req = next(r for r in captured if r.method == "PUT")
        assert "/server/disk/999999" in str(put_req.url)
        body = put_req.content.decode()
        assert "automate_cleanup=enable" in body
        assert "remove_app_tmp=yes" in body
        assert "remove_app_private_html=no" in body
        assert "rotate_system_log=yes" in body
        assert "rotate_app_log=no" in body
        assert "remove_app_local_backup=no" in body
        assert "server_id" not in body

    def test_disk_settings_set_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_backup_handler(disk_put_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "disk",
                    "settings",
                    "set",
                    "--automate-cleanup",
                    "enable",
                    "--remove-tmp",
                    "yes",
                    "--remove-private-html",
                    "no",
                    "--rotate-system-log",
                    "yes",
                    "--rotate-app-log",
                    "no",
                    "--remove-local-backup",
                    "no",
                ],
            )

        assert result.exit_code == 1


class TestDiskCleanupCli:
    """Tests for `cloudways disk cleanup` command."""

    def test_disk_cleanup_no_wait(self, set_env) -> None:
        """Without --wait, prints operation ID and exits."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "disk",
                    "cleanup",
                    "--remove-tmp",
                    "yes",
                    "--remove-private-html",
                    "no",
                    "--rotate-system-log",
                    "yes",
                    "--rotate-app-log",
                    "no",
                    "--remove-local-backup",
                    "no",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Disk cleanup triggered. Operation ID: 99003" in result.output
        assert "Disk cleanup complete." not in result.output
        post_req = next(
            r
            for r in captured
            if r.method == "POST" and "/server/disk/cleanup" in str(r.url)
        )
        body = post_req.content.decode()
        assert "server_id=999999" in body
        assert "remove_app_tmp=yes" in body
        assert "remove_app_private_html=no" in body
        assert "rotate_system_log=yes" in body
        assert "rotate_app_log=no" in body
        assert "remove_app_local_backup=no" in body

    def test_disk_cleanup_with_wait(self, set_env) -> None:
        """With --wait, polls operation and prints completion."""
        handler, captured = _make_backup_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
                result = runner.invoke(
                    app,
                    [
                        "disk",
                        "cleanup",
                        "--wait",
                        "--remove-tmp",
                        "yes",
                        "--remove-private-html",
                        "no",
                        "--rotate-system-log",
                        "yes",
                        "--rotate-app-log",
                        "no",
                        "--remove-local-backup",
                        "no",
                    ],
                )

        assert result.exit_code == 0, result.output
        assert "Disk cleanup complete." in result.output

    def test_disk_cleanup_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_backup_handler(disk_cleanup_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.disk.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "disk",
                    "cleanup",
                    "--remove-tmp",
                    "yes",
                    "--remove-private-html",
                    "no",
                    "--rotate-system-log",
                    "yes",
                    "--rotate-app-log",
                    "no",
                    "--remove-local-backup",
                    "no",
                ],
            )

        assert result.exit_code == 1

    def test_disk_cleanup_wait_timeout(self, set_env) -> None:
        """Operation timeout exits 1."""
        handler, captured = _make_backup_handler(
            operation_response=_make_operation_pending_response()
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        start_time = _time.monotonic()
        call_count = {"value": 0}

        def mock_monotonic():
            call_count["value"] += 1
            return start_time + (call_count["value"] * 200)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch(
                "cloudways_api.client.time.monotonic",
                side_effect=mock_monotonic,
            ):
                with patch(
                    "cloudways_api.commands.disk.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(
                        app,
                        [
                            "disk",
                            "cleanup",
                            "--wait",
                            "--timeout",
                            "1",
                            "--remove-tmp",
                            "yes",
                            "--remove-private-html",
                            "no",
                            "--rotate-system-log",
                            "yes",
                            "--rotate-app-log",
                            "no",
                            "--remove-local-backup",
                            "no",
                        ],
                    )

        assert result.exit_code == 1


# ===================================================================
# CLI registration tests
# ===================================================================


class TestBackupDiskRegistration:
    """Tests for backup and disk command registration in CLI."""

    def test_backup_group_in_help(self) -> None:
        """backup appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "backup" in result.output

    def test_disk_group_in_help(self) -> None:
        """disk appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "disk" in result.output

    def test_backup_subcommands_visible(self) -> None:
        """backup --help shows run and settings subcommands."""
        result = runner.invoke(app, ["backup", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "settings" in result.output

    def test_disk_subcommands_visible(self) -> None:
        """disk --help shows settings and cleanup subcommands."""
        result = runner.invoke(app, ["disk", "--help"])
        assert result.exit_code == 0
        assert "settings" in result.output
        assert "cleanup" in result.output
