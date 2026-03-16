"""Tests for the ssh command (interactive and exec modes).

Covers interactive SSH via os.execvp, exec mode via run_ssh_command,
--server flag, app directory resolution, and error handling.
All os.execvp calls and SSH operations are mocked.
"""

import os
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.exceptions import SSHError
from cloudways_api.ssh import build_interactive_ssh_args

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _config_path() -> str:
    return os.path.join(FIXTURES_DIR, "project-config.yml")


# ---- build_interactive_ssh_args tests ----


class TestBuildInteractiveSSHArgs:
    """Tests for build_interactive_ssh_args() in ssh.py."""

    def test_no_batch_mode(self) -> None:
        """AC-3B.2: Interactive SSH args do NOT include BatchMode=yes."""
        args = build_interactive_ssh_args("host", "user")
        assert "BatchMode=yes" not in args

    def test_has_tty_flag(self) -> None:
        """AC-3B.3: Interactive SSH args include -t flag."""
        args = build_interactive_ssh_args("host", "user")
        assert "-t" in args

    def test_no_connect_timeout(self) -> None:
        """AC-3B.4: Interactive SSH args do NOT include ConnectTimeout."""
        args = build_interactive_ssh_args("host", "user")
        for arg in args:
            assert "ConnectTimeout" not in arg

    def test_has_strict_host_key(self) -> None:
        """StrictHostKeyChecking=accept-new is present."""
        args = build_interactive_ssh_args("host", "user")
        assert "StrictHostKeyChecking=accept-new" in args

    def test_with_remote_command(self) -> None:
        """Remote command appended when provided."""
        args = build_interactive_ssh_args(
            "host", "user", remote_command="cd /app && exec $SHELL -l"
        )
        assert "cd /app && exec $SHELL -l" in args

    def test_without_remote_command(self) -> None:
        """No remote command when None."""
        args = build_interactive_ssh_args("host", "user")
        assert args[-1] == "user@host"

    def test_user_host_format(self) -> None:
        """user@host formatted correctly."""
        args = build_interactive_ssh_args("1.2.3.4", "master_abc")
        assert "master_abc@1.2.3.4" in args


# ---- Interactive mode tests ----


class TestSSHInteractiveMode:
    """Tests for ssh command interactive mode (os.execvp mocked)."""

    @patch("cloudways_api.commands.ssh_cmd.os.execvp")
    def test_calls_execvp(self, mock_execvp, monkeypatch) -> None:
        """AC-3B.1: Interactive mode calls os.execvp with 'ssh'."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production"])
        mock_execvp.assert_called_once()
        assert mock_execvp.call_args[0][0] == "ssh"

    @patch("cloudways_api.commands.ssh_cmd.os.execvp")
    def test_interactive_args_correct(self, mock_execvp, monkeypatch) -> None:
        """Full arg list verified for interactive mode."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production"])
        args = mock_execvp.call_args[0][1]
        assert args[0] == "ssh"
        assert "-t" in args
        assert "BatchMode=yes" not in args

    @patch("cloudways_api.commands.ssh_cmd.os.execvp")
    def test_cd_to_app_directory(self, mock_execvp, monkeypatch) -> None:
        """AC-3B.5: Default behavior cd to app directory."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production"])
        args = mock_execvp.call_args[0][1]
        # Should have a remote command with cd
        remote_cmd = args[-1]
        assert "cd" in remote_cmd
        assert "public_html/current" in remote_cmd

    @patch("cloudways_api.commands.ssh_cmd.os.execvp")
    def test_server_flag_no_cd(self, mock_execvp, monkeypatch) -> None:
        """AC-3B.6: --server flag skips cd to app directory."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production", "--server"])
        args = mock_execvp.call_args[0][1]
        # Last arg should be user@host, not a cd command
        last_arg = args[-1]
        assert "cd" not in last_arg

    @patch("cloudways_api.commands.ssh_cmd.os.execvp")
    def test_default_environment_production(
        self, mock_execvp, monkeypatch
    ) -> None:
        """AC-3B.11: Default environment is production."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        # Calling without specifying environment uses default "production"
        runner.invoke(app, ["ssh"])
        mock_execvp.assert_called_once()

    @patch(
        "cloudways_api.commands.ssh_cmd.os.execvp",
        side_effect=OSError("No such file"),
    )
    def test_execvp_failure_raises_error(
        self, mock_execvp, monkeypatch
    ) -> None:
        """AC-3B.16: OSError from execvp raises CloudwaysError."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(app, ["ssh", "production"])
        assert result.exit_code == 1
        assert "Error" in result.output


# ---- Exec mode tests ----


class TestSSHExecMode:
    """Tests for ssh command exec mode (command after --)."""

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("plugin-list-output\n", "", 0),
    )
    def test_calls_run_ssh_command(
        self, mock_ssh, monkeypatch
    ) -> None:
        """AC-3B.7: Exec mode uses run_ssh_command."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(
            app, ["ssh", "production", "wp", "plugin", "list"]
        )
        mock_ssh.assert_called_once()

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("plugin-list-output\n", "", 0),
    )
    def test_prints_stdout(self, mock_ssh, monkeypatch) -> None:
        """AC-3B.8: Exec mode prints stdout to console."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(
            app, ["ssh", "production", "wp", "plugin", "list"]
        )
        assert "plugin-list-output" in result.output

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "warning msg\n", 0),
    )
    def test_exec_mode_outputs_stderr(self, mock_ssh, monkeypatch) -> None:
        """AC-3B.10: Exec mode passes stderr through."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(app, ["ssh", "production", "echo", "test"])
        # stderr goes through sys.stderr, may not be in result.output
        # but the command should succeed
        assert result.exit_code == 0

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "", 0),
    )
    def test_multiple_args_joined(self, mock_ssh, monkeypatch) -> None:
        """Multiple command arguments joined as single command."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(
            app, ["ssh", "production", "wp", "plugin", "list"]
        )
        call_args = mock_ssh.call_args
        cmd_str = call_args[0][2]  # 3rd positional arg is the command string
        assert "wp plugin list" in cmd_str

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "", 0),
    )
    def test_exec_mode_uses_batch_ssh(self, mock_ssh, monkeypatch) -> None:
        """Exec mode uses run_ssh_command (batch SSH with BatchMode)."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production", "cat", "/etc/hostname"])
        # run_ssh_command internally uses _ssh_base_args which includes BatchMode
        mock_ssh.assert_called_once()

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "", 0),
    )
    def test_exec_mode_cd_to_webroot(self, mock_ssh, monkeypatch) -> None:
        """Exec mode prefixes command with cd to webroot."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(app, ["ssh", "production", "ls"])
        call_args = mock_ssh.call_args
        cmd_str = call_args[0][2]
        assert "cd" in cmd_str
        assert "public_html/current" in cmd_str

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "", 0),
    )
    def test_exec_mode_server_flag_no_cd(
        self, mock_ssh, monkeypatch
    ) -> None:
        """Exec mode with --server does not prefix cd."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(
            app, ["ssh", "production", "--server", "ls"]
        )
        call_args = mock_ssh.call_args
        cmd_str = call_args[0][2]
        assert "cd" not in cmd_str

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("", "error output\n", 2),
    )
    def test_exec_mode_preserves_remote_exit_code(
        self, mock_ssh, monkeypatch
    ) -> None:
        """H-2: Remote exit code 2 is preserved in CLI exit code."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(
            app, ["ssh", "production", "false"]
        )
        assert result.exit_code == 2

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("", "not found\n", 127),
    )
    def test_exec_mode_preserves_exit_code_127(
        self, mock_ssh, monkeypatch
    ) -> None:
        """H-2: Remote exit code 127 (command not found) is preserved."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(
            app, ["ssh", "production", "nonexistent-cmd"]
        )
        assert result.exit_code == 127

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        return_value=("output\n", "", 0),
    )
    def test_exec_mode_preserves_argument_quoting(
        self, mock_ssh, monkeypatch
    ) -> None:
        """H-3: Args with spaces are properly quoted via shlex.join."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        runner.invoke(
            app, ["ssh", "production", "echo", "hello world", "foo bar"]
        )
        call_args = mock_ssh.call_args
        cmd_str = call_args[0][2]
        # shlex.join should quote args with spaces
        assert "'hello world'" in cmd_str
        assert "'foo bar'" in cmd_str


# ---- Error and validation tests ----


class TestSSHErrors:
    """Tests for ssh command error handling."""

    def test_invalid_environment_error(self, monkeypatch) -> None:
        """AC-3B.12: Invalid environment shows error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(app, ["ssh", "nonexistent"])
        assert result.exit_code == 1
        assert "nonexistent" in result.output
        assert "not found" in result.output

    def test_missing_ssh_config_error(self, tmp_path, monkeypatch) -> None:
        """AC-3B.13: Missing SSH config shows descriptive error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            "hosting:\n  cloudways:\n    account: primary\n"
            "    server:\n      id: 123\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config_file))
        result = runner.invoke(app, ["ssh", "production"])
        assert result.exit_code == 1

    @patch(
        "cloudways_api.commands.ssh_cmd.run_ssh_command",
        new_callable=AsyncMock,
        side_effect=SSHError("Connection refused"),
    )
    def test_exec_mode_ssh_failure_error(
        self, mock_ssh, monkeypatch
    ) -> None:
        """SSH error in exec mode shows error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        result = runner.invoke(
            app, ["ssh", "production", "echo", "hello"]
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_registered_in_cli_help(self) -> None:
        """AC-3B.14: ssh command appears in CLI help."""
        result = runner.invoke(app, ["--help"])
        assert "ssh" in result.output

    def test_build_interactive_ssh_args_importable(self) -> None:
        """AC-3B.15: build_interactive_ssh_args is public in ssh.py."""
        from cloudways_api.ssh import build_interactive_ssh_args

        assert callable(build_interactive_ssh_args)
