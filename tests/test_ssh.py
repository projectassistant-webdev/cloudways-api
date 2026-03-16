"""Tests for SSH operations module."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cloudways_api.exceptions import CloudwaysError, SSHError
from tests.conftest import MockProcess


class TestSSHExceptionHierarchy:
    """Tests for SSHError and DatabaseError exception classes."""

    def test_ssh_error_inherits_cloudways_error(self) -> None:
        """SSHError is a subclass of CloudwaysError."""
        assert issubclass(SSHError, CloudwaysError)

    def test_database_error_inherits_cloudways_error(self) -> None:
        """DatabaseError is a subclass of CloudwaysError."""
        from cloudways_api.exceptions import DatabaseError

        assert issubclass(DatabaseError, CloudwaysError)


class TestRunSSHCommand:
    """Tests for run_ssh_command function."""

    @pytest.mark.asyncio
    async def test_ssh_run_command_returns_stdout_stderr_returncode(self) -> None:
        """Happy path: returns (stdout, stderr, returncode) tuple."""
        mock_proc = MockProcess(
            stdout=b"hello world\n",
            stderr=b"",
            returncode=0,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            stdout, stderr, code = await run_ssh_command(
                "1.2.3.4", "master_user", "echo hello"
            )
            assert stdout == "hello world\n"
            assert stderr == ""
            assert code == 0

    @pytest.mark.asyncio
    async def test_ssh_run_command_uses_batch_mode(self) -> None:
        """SSH command includes BatchMode=yes option."""
        mock_proc = MockProcess(stdout=b"ok", returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import run_ssh_command

            await run_ssh_command("host", "user", "echo ok")

            call_args = mock_exec.call_args
            args = call_args[0] if call_args[0] else []
            flat = list(args)
            assert "BatchMode=yes" in flat

    @pytest.mark.asyncio
    async def test_ssh_run_command_uses_strict_host_key_accept_new(self) -> None:
        """SSH command includes StrictHostKeyChecking=accept-new option."""
        mock_proc = MockProcess(stdout=b"ok", returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import run_ssh_command

            await run_ssh_command("host", "user", "echo ok")

            call_args = mock_exec.call_args
            args = call_args[0] if call_args[0] else []
            flat = list(args)
            assert "StrictHostKeyChecking=accept-new" in flat

    @pytest.mark.asyncio
    async def test_ssh_run_command_connect_timeout_option(self) -> None:
        """SSH command includes ConnectTimeout option."""
        mock_proc = MockProcess(stdout=b"ok", returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import run_ssh_command

            await run_ssh_command("host", "user", "echo ok", timeout=15)

            call_args = mock_exec.call_args
            args = call_args[0] if call_args[0] else []
            flat = list(args)
            # ConnectTimeout should be present
            assert any("ConnectTimeout" in str(a) for a in flat)

    @pytest.mark.asyncio
    async def test_ssh_run_command_timeout_raises_ssh_error(self) -> None:
        """asyncio.TimeoutError is caught and re-raised as SSHError."""
        mock_proc = MockProcess()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())  # type: ignore[method-assign]
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="timed out"):
                await run_ssh_command("host", "user", "slow-cmd", timeout=5)

    @pytest.mark.asyncio
    async def test_ssh_run_command_permission_denied_raises_ssh_error(self) -> None:
        """'Permission denied' in stderr raises SSHError with descriptive message."""
        mock_proc = MockProcess(
            stderr=b"Permission denied (publickey).\n",
            returncode=255,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="SSH authentication failed"):
                await run_ssh_command("host", "user", "whoami")

    @pytest.mark.asyncio
    async def test_ssh_run_command_connection_refused_raises_ssh_error(self) -> None:
        """'Connection refused' in stderr raises SSHError with descriptive message."""
        mock_proc = MockProcess(
            stderr=b"ssh: connect to host 1.2.3.4 port 22: Connection refused\n",
            returncode=255,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="connection refused"):
                await run_ssh_command("1.2.3.4", "user", "whoami")

    @pytest.mark.asyncio
    async def test_ssh_run_command_hostname_not_found_raises_ssh_error(self) -> None:
        """'Could not resolve hostname' in stderr raises SSHError."""
        mock_proc = MockProcess(
            stderr=b"ssh: Could not resolve hostname badhost: Name or service not known\n",
            returncode=255,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="resolve hostname"):
                await run_ssh_command("badhost", "user", "whoami")

    @pytest.mark.asyncio
    async def test_ssh_run_command_missing_binary_raises_ssh_error(self) -> None:
        """FileNotFoundError/OSError when ssh binary missing raises SSHError."""
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("No such file or directory: 'ssh'"),
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="openssh-client"):
                await run_ssh_command("host", "user", "whoami")

    @pytest.mark.asyncio
    async def test_ssh_run_command_nonzero_exit_raises_ssh_error(self) -> None:
        """Generic non-zero exit code raises SSHError."""
        mock_proc = MockProcess(
            stderr=b"some error output\n",
            returncode=1,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import run_ssh_command

            with pytest.raises(SSHError, match="SSH command failed"):
                await run_ssh_command("host", "user", "bad-cmd")


class TestValidateSSHConnection:
    """Tests for validate_ssh_connection function."""

    @pytest.mark.asyncio
    async def test_ssh_validate_connection_success(self) -> None:
        """Successful SSH connection validation (exit 0)."""
        mock_proc = MockProcess(stdout=b"ok\n", returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import validate_ssh_connection

            # Should not raise
            await validate_ssh_connection("host", "user")

    @pytest.mark.asyncio
    async def test_ssh_validate_connection_failure_raises_ssh_error(self) -> None:
        """Failed SSH connection validation raises SSHError."""
        mock_proc = MockProcess(
            stderr=b"Connection refused\n",
            returncode=255,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import validate_ssh_connection

            with pytest.raises(SSHError):
                await validate_ssh_connection("host", "user")


class TestStreamSSHPipe:
    """Tests for stream_ssh_pipe function."""

    @pytest.mark.asyncio
    async def test_ssh_stream_pipe_returns_exit_code(self) -> None:
        """stream_ssh_pipe returns the local process exit code."""
        mock_ssh_proc = MockProcess(stdout=b"piped data\n", returncode=0)
        mock_local_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            # First call = ssh, second call = local
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_ssh_proc
            return mock_local_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_ssh_pipe

            code = await stream_ssh_pipe(
                "host", "user", "mysqldump db | gzip", "gunzip | mysql local"
            )
            assert code == 0


    @pytest.mark.asyncio
    async def test_ssh_stream_pipe_raises_on_remote_failure(self) -> None:
        """stream_ssh_pipe raises SSHError when SSH process exits non-zero (HIGH-2).

        If remote mysqldump fails but local process succeeds, the error
        must not be silently ignored as it leads to empty DB imports.
        """
        mock_ssh_proc = MockProcess(
            stdout=b"",
            stderr=b"mysqldump: Got error: Access denied\n",
            returncode=1,
        )
        mock_local_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_ssh_proc
            return mock_local_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_ssh_pipe

            with pytest.raises(SSHError, match="Remote command failed"):
                await stream_ssh_pipe(
                    "host", "user", "mysqldump db", "mysql local"
                )

    @pytest.mark.asyncio
    async def test_ssh_stream_pipe_includes_stderr_in_error(self) -> None:
        """stream_ssh_pipe includes remote stderr text in the SSHError message."""
        mock_ssh_proc = MockProcess(
            stdout=b"",
            stderr=b"mysqldump: Got error: 1045 Access denied for user\n",
            returncode=2,
        )
        mock_local_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_ssh_proc
            return mock_local_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_ssh_pipe

            with pytest.raises(SSHError, match="Access denied"):
                await stream_ssh_pipe(
                    "host", "user", "mysqldump db", "mysql local"
                )

    @pytest.mark.asyncio
    async def test_ssh_stream_pipe_large_stderr_does_not_deadlock(self) -> None:
        """stream_ssh_pipe handles large stderr without deadlocking (MEDIUM-2).

        When stderr is set to PIPE but never consumed, large stderr
        output can fill the OS buffer and deadlock. This test verifies
        that the function completes even with substantial stderr output.
        """
        # Generate large stderr data (~100KB)
        large_stderr = b"W: warning line\n" * 6000
        mock_ssh_proc = MockProcess(
            stdout=b"some data\n",
            stderr=large_stderr,
            returncode=0,
        )
        mock_local_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_ssh_proc
            return mock_local_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_ssh_pipe

            # Should complete without hanging
            code = await stream_ssh_pipe(
                "host", "user", "mysqldump db", "mysql local"
            )
            assert code == 0


class TestSFTPDownload:
    """Tests for sftp_download function."""

    @pytest.mark.asyncio
    async def test_ssh_sftp_download_success(self) -> None:
        """SFTP download completes successfully with exit code 0."""
        mock_proc = MockProcess(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import sftp_download

            # Should not raise
            await sftp_download(
                "host", "user", "/tmp/dump.sql.gz", "/local/dump.sql.gz"
            )

    @pytest.mark.asyncio
    async def test_ssh_sftp_download_failure_raises_ssh_error(self) -> None:
        """SFTP download failure raises SSHError."""
        mock_proc = MockProcess(
            stderr=b"scp: /remote/file: No such file or directory\n",
            returncode=1,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import sftp_download

            with pytest.raises(SSHError, match="download"):
                await sftp_download(
                    "host", "user", "/remote/file", "/local/file"
                )


class TestSFTPUpload:
    """Tests for sftp_upload function."""

    @pytest.mark.asyncio
    async def test_sftp_upload_success_calls_scp_with_correct_args(self) -> None:
        """sftp_upload completes successfully with exit code 0."""
        mock_proc = MockProcess(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import sftp_upload

            await sftp_upload(
                "host", "user", "/local/dump.sql.gz", "/tmp/dump.sql.gz"
            )

            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            assert flat[0] == "scp"
            assert "user@host:/tmp/dump.sql.gz" in flat

    @pytest.mark.asyncio
    async def test_sftp_upload_failure_raises_ssh_error(self) -> None:
        """sftp_upload raises SSHError when SCP fails (non-zero exit)."""
        mock_proc = MockProcess(
            stderr=b"scp: /tmp/dump.sql.gz: Permission denied\n",
            returncode=1,
        )
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.ssh import sftp_upload

            with pytest.raises(SSHError, match="upload"):
                await sftp_upload(
                    "host", "user", "/local/file", "/remote/file"
                )

    @pytest.mark.asyncio
    async def test_sftp_upload_missing_binary_raises_ssh_error(self) -> None:
        """sftp_upload raises SSHError when SCP binary is missing."""
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("No such file or directory: 'scp'"),
        ):
            from cloudways_api.ssh import sftp_upload

            with pytest.raises(SSHError, match="openssh-client"):
                await sftp_upload(
                    "host", "user", "/local/file", "/remote/file"
                )

    @pytest.mark.asyncio
    async def test_sftp_upload_uses_batch_mode_and_strict_host_key(self) -> None:
        """sftp_upload uses BatchMode=yes and StrictHostKeyChecking=accept-new."""
        mock_proc = MockProcess(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import sftp_upload

            await sftp_upload(
                "host", "user", "/local/file", "/remote/file"
            )

            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            assert "BatchMode=yes" in flat
            assert "StrictHostKeyChecking=accept-new" in flat

    @pytest.mark.asyncio
    async def test_sftp_upload_scp_arg_order_local_then_remote(self) -> None:
        """sftp_upload constructs SCP with local path before remote path."""
        mock_proc = MockProcess(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.ssh import sftp_upload

            await sftp_upload(
                "myhost", "myuser", "/local/path.gz", "/remote/path.gz"
            )

            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            local_idx = flat.index("/local/path.gz")
            remote_idx = flat.index("myuser@myhost:/remote/path.gz")
            assert local_idx < remote_idx


class TestStreamLocalToRemote:
    """Tests for stream_local_to_remote function."""

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_success_returns_zero(self) -> None:
        """stream_local_to_remote returns 0 on success."""
        mock_local_proc = MockProcess(stdout=b"piped data\n", returncode=0)
        mock_ssh_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_local_proc
            return mock_ssh_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_local_to_remote

            code = await stream_local_to_remote(
                "host", "user", "mysqldump db | gzip", "gunzip | mysql remote"
            )
            assert code == 0

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_remote_failure_raises_ssh_error(
        self,
    ) -> None:
        """stream_local_to_remote raises SSHError when remote command fails."""
        mock_local_proc = MockProcess(stdout=b"data\n", returncode=0)
        mock_ssh_proc = MockProcess(
            stderr=b"mysql: Access denied\n",
            returncode=1,
        )

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_local_proc
            return mock_ssh_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_local_to_remote

            with pytest.raises(SSHError, match="Remote command failed"):
                await stream_local_to_remote(
                    "host", "user", "mysqldump db", "mysql remote"
                )

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_local_failure_raises_ssh_error(
        self,
    ) -> None:
        """stream_local_to_remote raises SSHError when local command fails."""
        mock_local_proc = MockProcess(
            stderr=b"docker: container not found\n",
            returncode=1,
        )
        mock_ssh_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_local_proc
            return mock_ssh_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_local_to_remote

            with pytest.raises(SSHError, match="Local command failed"):
                await stream_local_to_remote(
                    "host", "user", "mysqldump db", "mysql remote"
                )

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_drains_local_stderr(self) -> None:
        """stream_local_to_remote drains local stderr to prevent deadlock."""
        large_stderr = b"W: warning\n" * 5000
        mock_local_proc = MockProcess(
            stdout=b"data\n", stderr=large_stderr, returncode=0
        )
        mock_ssh_proc = MockProcess(returncode=0)

        async def mock_exec(*args, **kwargs):
            if not hasattr(mock_exec, "_call_count"):
                mock_exec._call_count = 0  # type: ignore[attr-defined]
            mock_exec._call_count += 1  # type: ignore[attr-defined]
            if mock_exec._call_count == 1:  # type: ignore[attr-defined]
                return mock_local_proc
            return mock_ssh_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_local_to_remote

            code = await stream_local_to_remote(
                "host", "user", "cmd", "remote_cmd"
            )
            assert code == 0

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_missing_ssh_binary_raises_ssh_error(
        self,
    ) -> None:
        """stream_local_to_remote raises SSHError when SSH binary missing."""
        mock_local_proc = MockProcess(stdout=b"data\n", returncode=0)

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_local_proc
            raise FileNotFoundError("No such file or directory: 'ssh'")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ):
            from cloudways_api.ssh import stream_local_to_remote

            with pytest.raises(SSHError, match="openssh-client"):
                await stream_local_to_remote(
                    "host", "user", "cmd", "remote_cmd"
                )

    @pytest.mark.asyncio
    async def test_stream_local_to_remote_pipes_local_stdout_to_ssh_stdin(
        self,
    ) -> None:
        """stream_local_to_remote connects local stdout to SSH stdin via os.pipe fd."""
        mock_local_proc = MockProcess(stdout=b"data\n", returncode=0)
        mock_ssh_proc = MockProcess(returncode=0)

        # Sentinel file descriptors returned by the patched os.pipe()
        FAKE_R_FD = 100
        FAKE_W_FD = 101

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Local process: stdout should be the write-end fd
                assert kwargs.get("stdout") == FAKE_W_FD
                return mock_local_proc
            # SSH process: stdin should be the read-end fd
            assert kwargs.get("stdin") == FAKE_R_FD
            return mock_ssh_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=mock_exec,
        ), patch(
            "cloudways_api.ssh.os.pipe",
            return_value=(FAKE_R_FD, FAKE_W_FD),
        ), patch(
            "cloudways_api.ssh.os.close",
        ):
            from cloudways_api.ssh import stream_local_to_remote

            code = await stream_local_to_remote(
                "host", "user", "cmd", "remote_cmd"
            )
            assert code == 0
