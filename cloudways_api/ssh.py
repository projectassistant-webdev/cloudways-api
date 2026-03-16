"""SSH operations using asyncio subprocess.

Provides functions for executing commands on remote servers,
piping data through SSH tunnels, and downloading files via SCP.
All operations use the system ``ssh`` client (openssh-client).
"""

import asyncio
import os
from collections.abc import Callable

from cloudways_api.exceptions import SSHError

_SSH_OPTIONS: list[str] = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "BatchMode=yes",
]

_SCP_OPTIONS: list[str] = [
    "-O",  # Legacy SCP protocol (required on macOS with newer openssh)
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "BatchMode=yes",
]

_SSH_NOT_INSTALLED_MSG = (
    "openssh-client not installed. "
    "Rebuild with: docker compose build app"
)


async def _drain_stream(stream: asyncio.StreamReader) -> bytes:
    """Read all data from an async stream reader until EOF.

    Used to drain stderr pipes in background tasks to prevent
    OS buffer deadlocks during streaming operations.

    Args:
        stream: An asyncio.StreamReader to drain.

    Returns:
        All bytes read from the stream.
    """
    data = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        data += chunk
    return data


def _ssh_base_args(
    host: str, user: str, timeout: int = 10
) -> list[str]:
    """Build the base SSH argument list."""
    return [
        "ssh",
        *_SSH_OPTIONS,
        "-o", f"ConnectTimeout={timeout}",
        f"{user}@{host}",
    ]


def _classify_ssh_error(
    stderr: str, returncode: int, host: str, user: str, timeout: int
) -> SSHError:
    """Map SSH stderr patterns to user-friendly SSHError messages."""
    stderr_lower = stderr.lower()

    if "permission denied" in stderr_lower:
        return SSHError(
            f"SSH authentication failed. "
            f"Verify your SSH key is configured for {user}@{host}."
        )
    if "could not resolve hostname" in stderr_lower:
        return SSHError(
            f"Cannot resolve hostname '{host}'. "
            f"Check server.ssh_host in project-config.yml."
        )
    if "connection refused" in stderr_lower:
        return SSHError(
            f"SSH connection refused by {host}. "
            f"Verify the server is running and SSH port is open."
        )
    if "connection timed out" in stderr_lower:
        return SSHError(
            f"SSH connection to {host} timed out after {timeout}s. "
            f"Check network connectivity."
        )

    return SSHError(
        f"SSH command failed (exit {returncode}): {stderr.strip()}"
    )


def build_interactive_ssh_args(
    host: str,
    user: str,
    remote_command: str | None = None,
) -> list[str]:
    """Build SSH argument list for interactive sessions.

    Unlike :func:`_ssh_base_args`, this:
    - Omits ``BatchMode=yes`` (allows interactive input)
    - Omits ``ConnectTimeout`` (no timeout for interactive sessions)
    - Adds ``-t`` flag for TTY allocation

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        remote_command: Optional command to execute on connection
            (e.g. ``cd /path && exec $SHELL -l``).

    Returns:
        List of SSH argument strings suitable for ``os.execvp``.
    """
    args = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",  # No BatchMode for interactive
        "-t",
        f"{user}@{host}",
    ]
    if remote_command is not None:
        args.append(remote_command)
    return args


async def run_ssh_command(
    host: str,
    user: str,
    command: str,
    timeout: int = 60,
    raise_on_error: bool = True,
) -> tuple[str, str, int]:
    """Execute a command on the remote server via SSH.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        command: Shell command to execute remotely.
        timeout: Maximum seconds to wait for completion.
        raise_on_error: If ``True`` (default), raise :class:`SSHError`
            on non-zero exit codes. If ``False``, return the result
            tuple and let the caller handle the exit code.

    Returns:
        Tuple of (stdout, stderr, returncode).

    Raises:
        SSHError: On connection failure, timeout, or (when
            *raise_on_error* is ``True``) non-zero exit code.
    """
    args = _ssh_base_args(host, user, timeout=min(timeout, 10))
    args.append(command)

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise SSHError(_SSH_NOT_INSTALLED_MSG) from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        raise SSHError(
            f"SSH command timed out after {timeout}s."
        )

    stdout_str = stdout_bytes.decode("utf-8", errors="replace")
    stderr_str = stderr_bytes.decode("utf-8", errors="replace")

    if raise_on_error and process.returncode != 0:
        raise _classify_ssh_error(
            stderr_str, process.returncode, host, user, timeout
        )

    return stdout_str, stderr_str, process.returncode


async def validate_ssh_connection(
    host: str,
    user: str,
    timeout: int = 10,
) -> None:
    """Test SSH connectivity to a remote host.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        timeout: Maximum seconds to wait.

    Raises:
        SSHError: If SSH connection cannot be established.
    """
    await run_ssh_command(host, user, "echo ok", timeout=timeout)


async def stream_ssh_pipe(
    host: str,
    user: str,
    remote_cmd: str,
    local_cmd: str,
    on_progress: Callable | None = None,
) -> int:
    """Pipe remote command output through SSH into a local command.

    Connects the stdout of the remote SSH command to the stdin
    of a local command, enabling streaming data transfer.  Uses
    ``os.pipe()`` to create a real file-descriptor pipe between
    the two subprocesses so that asyncio StreamReaders (which lack
    ``.fileno()``) are never passed as ``stdin=``.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        remote_cmd: Command to execute on the remote server.
        local_cmd: Local command to receive piped data.
        on_progress: Optional callback for progress reporting.

    Returns:
        The local process return code.

    Raises:
        SSHError: If the SSH connection fails.
    """
    ssh_args = _ssh_base_args(host, user)
    ssh_args.append(remote_cmd)

    # Create an OS-level pipe: SSH writes to w_fd, local reads from r_fd.
    r_fd, w_fd = os.pipe()

    try:
        ssh_proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdout=w_fd,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        os.close(r_fd)
        os.close(w_fd)
        raise SSHError(_SSH_NOT_INSTALLED_MSG) from exc

    # Close the write end in the parent so the local process gets EOF
    # when SSH finishes writing.
    os.close(w_fd)

    try:
        local_proc = await asyncio.create_subprocess_exec(
            "sh", "-c", local_cmd,
            stdin=r_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    finally:
        # Close the read end in the parent; the local process owns it now.
        os.close(r_fd)

    # Consume SSH stderr in background to prevent OS buffer deadlock.
    assert ssh_proc.stderr is not None  # noqa: S101
    stderr_task = asyncio.create_task(_drain_stream(ssh_proc.stderr))

    # Wait for both processes.
    await local_proc.communicate()
    await ssh_proc.wait()

    ssh_stderr = await stderr_task

    # Check remote process exit code. A non-zero exit from the
    # SSH/mysqldump side means data may be corrupt or empty.
    if ssh_proc.returncode != 0:
        stderr_text = ssh_stderr.decode("utf-8", errors="replace").strip()
        raise SSHError(
            f"Remote command failed (exit {ssh_proc.returncode}): "
            f"{stderr_text}"
        )

    return local_proc.returncode


async def sftp_download(
    host: str,
    user: str,
    remote_path: str,
    local_path: str,
) -> None:
    """Download a file from the remote server via SCP.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        remote_path: Path to the file on the remote server.
        local_path: Local destination path.

    Raises:
        SSHError: If the download fails.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "scp",
            *_SCP_OPTIONS,
            f"{user}@{host}:{remote_path}",
            local_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise SSHError(_SSH_NOT_INSTALLED_MSG) from exc

    stdout_bytes, stderr_bytes = await process.communicate()
    stderr_str = stderr_bytes.decode("utf-8", errors="replace")

    if process.returncode != 0:
        raise SSHError(
            f"Failed to download {remote_path}: {stderr_str.strip()}"
        )


async def sftp_upload(
    host: str,
    user: str,
    local_path: str,
    remote_path: str,
) -> None:
    """Upload a file to the remote server via SCP.

    Inverse of :func:`sftp_download`. Uses the ``scp`` command to
    transfer a local file to the remote host.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        local_path: Local file path to upload.
        remote_path: Remote destination path.

    Raises:
        SSHError: If the upload fails.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "scp",
            *_SCP_OPTIONS,
            local_path,
            f"{user}@{host}:{remote_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise SSHError(_SSH_NOT_INSTALLED_MSG) from exc

    stdout_bytes, stderr_bytes = await process.communicate()
    stderr_str = stderr_bytes.decode("utf-8", errors="replace")

    if process.returncode != 0:
        raise SSHError(
            f"Failed to upload {local_path}: {stderr_str.strip()}"
        )


async def stream_local_to_remote(
    host: str,
    user: str,
    local_cmd: str,
    remote_cmd: str,
) -> int:
    """Pipe local command output through SSH into a remote command.

    Inverse of :func:`stream_ssh_pipe`. Connects the stdout of a
    local command to the stdin of a remote command via SSH.  Uses
    ``os.pipe()`` to create a real file-descriptor pipe between
    the two subprocesses.

    Args:
        host: Remote server hostname or IP address.
        user: SSH username.
        local_cmd: Local command whose stdout is piped.
        remote_cmd: Remote command to receive piped data via stdin.

    Returns:
        The SSH process return code (0 = success).

    Raises:
        SSHError: If the SSH connection fails, or the local/remote
            command errors.
    """
    # Create an OS-level pipe: local writes to w_fd, SSH reads from r_fd.
    r_fd, w_fd = os.pipe()

    # Step 1: Start local command, writing stdout to the pipe.
    local_proc = await asyncio.create_subprocess_exec(
        "sh", "-c", local_cmd,
        stdout=w_fd,
        stderr=asyncio.subprocess.PIPE,
    )

    # Close the write end in the parent so SSH gets EOF when local finishes.
    os.close(w_fd)

    # Step 2: Start SSH command, reading stdin from the pipe.
    ssh_args = _ssh_base_args(host, user)
    ssh_args.append(remote_cmd)

    try:
        ssh_proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdin=r_fd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        os.close(r_fd)
        raise SSHError(_SSH_NOT_INSTALLED_MSG) from exc
    finally:
        # Close the read end in the parent; SSH owns it now.
        # Use try/except in case it was already closed in the except above.
        try:
            os.close(r_fd)
        except OSError:
            pass

    # Step 3: Drain stderr pipes in background to prevent deadlock.
    assert local_proc.stderr is not None  # noqa: S101
    assert ssh_proc.stderr is not None  # noqa: S101
    local_stderr_task = asyncio.create_task(_drain_stream(local_proc.stderr))
    ssh_stderr_task = asyncio.create_task(_drain_stream(ssh_proc.stderr))

    # Step 4: Wait for both processes.
    await ssh_proc.communicate()
    await local_proc.wait()

    local_stderr = await local_stderr_task
    ssh_stderr = await ssh_stderr_task

    # Step 5: Check remote process exit code.
    if ssh_proc.returncode != 0:
        stderr_text = ssh_stderr.decode("utf-8", errors="replace").strip()
        raise SSHError(
            f"Remote command failed (exit {ssh_proc.returncode}): "
            f"{stderr_text}"
        )

    # Step 6: Check local process exit code.
    if local_proc.returncode != 0:
        stderr_text = local_stderr.decode("utf-8", errors="replace").strip()
        raise SSHError(
            f"Local command failed (exit {local_proc.returncode}): "
            f"{stderr_text}"
        )

    return ssh_proc.returncode
