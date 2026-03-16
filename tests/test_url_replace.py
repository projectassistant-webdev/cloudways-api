"""Tests for URL replacement strategies module."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cloudways_api.exceptions import ConfigError, SSHError


class TestGetURLReplacer:
    """Tests for strategy dispatch."""

    def test_get_url_replacer_wp_cli_returns_function(self) -> None:
        """get_url_replacer('wp-cli') returns a callable."""
        from cloudways_api.url_replace import get_url_replacer

        func = get_url_replacer("wp-cli")
        assert callable(func)

    def test_get_url_replacer_env_file_returns_function(self) -> None:
        """get_url_replacer('env-file') returns a callable."""
        from cloudways_api.url_replace import get_url_replacer

        func = get_url_replacer("env-file")
        assert callable(func)

    def test_get_url_replacer_sql_replace_returns_function(self) -> None:
        """get_url_replacer('sql-replace') returns a callable."""
        from cloudways_api.url_replace import get_url_replacer

        func = get_url_replacer("sql-replace")
        assert callable(func)

    def test_get_url_replacer_invalid_method_raises_config_error(self) -> None:
        """get_url_replacer with unknown method raises ConfigError."""
        from cloudways_api.url_replace import get_url_replacer

        with pytest.raises(ConfigError, match="Unknown url_replace_method"):
            get_url_replacer("invalid-method")


class TestWPCLIStrategy:
    """Tests for wp-cli URL replacement strategy."""

    @pytest.mark.asyncio
    async def test_wp_cli_generates_correct_docker_exec_command(self) -> None:
        """wp-cli strategy generates docker exec wp search-replace command."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_wp_cli

            await replace_urls_wp_cli(
                "example.com", "localhost", "wp-container"
            )

            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            assert "docker" in flat
            assert "exec" in flat
            assert "wp-container" in flat
            assert "wp" in flat

    @pytest.mark.asyncio
    async def test_wp_cli_includes_all_tables_precise_skip_guid(self) -> None:
        """wp-cli command includes --all-tables, --precise, --skip-columns=guid."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_wp_cli

            await replace_urls_wp_cli(
                "example.com", "localhost", "wp-container"
            )

            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            assert "--all-tables" in flat
            assert "--precise" in flat
            assert "--skip-columns=guid" in flat

    @pytest.mark.asyncio
    async def test_wp_cli_replaces_source_with_target_domain(self) -> None:
        """wp-cli command uses source_domain and target_domain correctly."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_wp_cli

            await replace_urls_wp_cli(
                "wp.example.com", "localhost", "container"
            )

            call_args = mock_exec.call_args[0]
            flat = list(call_args)
            # Should contain source URL
            assert any("wp.example.com" in str(a) for a in flat)
            # Should contain target
            assert any("localhost" in str(a) for a in flat)


class TestEnvFileStrategy:
    """Tests for env-file URL replacement strategy."""

    @pytest.mark.asyncio
    async def test_env_file_replaces_domain_in_file(self, tmp_path: Path) -> None:
        """env-file strategy replaces domain in .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "WP_HOME=https://example.com\n"
            "WP_SITEURL=https://example.com\n"
            "OTHER=unrelated\n"
        )

        from cloudways_api.url_replace import replace_urls_env_file

        await replace_urls_env_file(
            "example.com", "localhost", str(env_file)
        )

        content = env_file.read_text()
        assert "localhost" in content
        assert "example.com" not in content

    @pytest.mark.asyncio
    async def test_env_file_preserves_non_url_lines(self, tmp_path: Path) -> None:
        """env-file strategy preserves lines without the domain."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DB_HOST=127.0.0.1\n"
            "WP_HOME=https://example.com\n"
            "DB_NAME=wordpress\n"
        )

        from cloudways_api.url_replace import replace_urls_env_file

        await replace_urls_env_file(
            "example.com", "localhost", str(env_file)
        )

        content = env_file.read_text()
        assert "DB_HOST=127.0.0.1" in content
        assert "DB_NAME=wordpress" in content


class TestSQLReplaceStrategy:
    """Tests for sql-replace URL replacement strategy."""

    @pytest.mark.asyncio
    async def test_sql_replace_generates_update_wp_options(self) -> None:
        """sql-replace generates UPDATE for wp_options."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_sql_replace

            await replace_urls_sql_replace(
                "example.com", "localhost", "testdb"
            )

            # Check the SQL contains wp_options
            call_args = mock_exec.call_args[0]
            flat = " ".join(str(a) for a in call_args)
            assert "wp_options" in flat

    @pytest.mark.asyncio
    async def test_sql_replace_generates_update_wp_posts(self) -> None:
        """sql-replace generates UPDATE for wp_posts."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_sql_replace

            await replace_urls_sql_replace(
                "example.com", "localhost", "testdb"
            )

            call_args = mock_exec.call_args[0]
            flat = " ".join(str(a) for a in call_args)
            assert "wp_posts" in flat

    @pytest.mark.asyncio
    async def test_sql_replace_generates_update_wp_postmeta(self) -> None:
        """sql-replace generates UPDATE for wp_postmeta."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_sql_replace

            await replace_urls_sql_replace(
                "example.com", "localhost", "testdb"
            )

            call_args = mock_exec.call_args[0]
            flat = " ".join(str(a) for a in call_args)
            assert "wp_postmeta" in flat

    @pytest.mark.asyncio
    async def test_sql_replace_does_not_update_wp_posts_guid(self) -> None:
        """sql-replace must NOT update wp_posts.guid column (MEDIUM-1).

        WordPress GUIDs should never change after publish. The wp-cli
        strategy correctly skips guid via --skip-columns=guid, but
        sql-replace was incorrectly modifying it.
        """
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ) as mock_exec:
            from cloudways_api.url_replace import replace_urls_sql_replace

            await replace_urls_sql_replace(
                "example.com", "localhost", "testdb"
            )

            call_args = mock_exec.call_args[0]
            flat = " ".join(str(a) for a in call_args)
            # guid column should NOT be updated in wp_posts
            assert "SET guid" not in flat


class TestReplacerKwargsCompatibility:
    """Tests that all replacer strategies accept the kwargs from db_pull (HIGH-1).

    db_pull.py calls all replacers with source_domain, target_domain,
    container_name, and db_name. Each strategy must accept these kwargs
    without raising TypeError, even if it doesn't use all of them.
    """

    @pytest.mark.asyncio
    async def test_wp_cli_accepts_extra_db_name_kwarg(self) -> None:
        """wp-cli strategy accepts db_name kwarg without error."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.url_replace import replace_urls_wp_cli

            # Should NOT raise TypeError
            await replace_urls_wp_cli(
                source_domain="example.com",
                target_domain="localhost",
                container_name="wp-container",
                db_name="testdb",
            )

    @pytest.mark.asyncio
    async def test_env_file_accepts_extra_container_and_db_kwargs(
        self, tmp_path: Path
    ) -> None:
        """env-file strategy accepts container_name and db_name kwargs without error."""
        env_file = tmp_path / ".env"
        env_file.write_text("WP_HOME=https://example.com\n")

        from cloudways_api.url_replace import replace_urls_env_file

        # Should NOT raise TypeError
        await replace_urls_env_file(
            source_domain="example.com",
            target_domain="localhost",
            container_name="wp-container",
            db_name="testdb",
            env_file_path=str(env_file),
        )

    @pytest.mark.asyncio
    async def test_sql_replace_accepts_all_standard_kwargs(self) -> None:
        """sql-replace strategy accepts container_name and db_name kwargs."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_proc,
        ):
            from cloudways_api.url_replace import replace_urls_sql_replace

            # Should NOT raise TypeError
            await replace_urls_sql_replace(
                source_domain="example.com",
                target_domain="localhost",
                container_name="wp-container",
                db_name="testdb",
            )


class TestRemoteWPCLIStrategy:
    """Tests for remote wp-cli URL replacement via SSH."""

    @pytest.mark.asyncio
    async def test_remote_wp_cli_executes_via_ssh(self) -> None:
        """replace_urls_remote_wp_cli() calls run_ssh_command."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("Success", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_wp_cli

            await replace_urls_remote_wp_cli(
                source_domain="localhost",
                target_domain="wp.example.com",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
            )

            mock_ssh.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_wp_cli_includes_all_tables_precise_skip_guid(
        self,
    ) -> None:
        """Remote wp-cli includes --all-tables, --precise, --skip-columns=guid."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("Success", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_wp_cli

            await replace_urls_remote_wp_cli(
                source_domain="localhost",
                target_domain="wp.example.com",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
            )

            cmd = mock_ssh.call_args[1].get("command") or mock_ssh.call_args[0][2]
            assert "--all-tables" in cmd
            assert "--precise" in cmd
            assert "--skip-columns=guid" in cmd

    @pytest.mark.asyncio
    async def test_remote_wp_cli_uses_correct_webroot(self) -> None:
        """Remote wp-cli uses the webroot path for wp search-replace."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("Success", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_wp_cli

            await replace_urls_remote_wp_cli(
                source_domain="localhost",
                target_domain="wp.example.com",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
                webroot="public_html/current",
            )

            cmd = mock_ssh.call_args[1].get("command") or mock_ssh.call_args[0][2]
            assert "public_html/current" in cmd

    @pytest.mark.asyncio
    async def test_remote_wp_cli_raises_on_ssh_failure(self) -> None:
        """Remote wp-cli raises SSHError on SSH failure."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=SSHError("SSH connection refused"),
        ):
            from cloudways_api.url_replace import replace_urls_remote_wp_cli

            with pytest.raises(SSHError, match="SSH connection refused"):
                await replace_urls_remote_wp_cli(
                    source_domain="localhost",
                    target_domain="wp.example.com",
                    ssh_host="1.2.3.4",
                    ssh_user="master_user",
                )


class TestRemoteSQLStrategy:
    """Tests for remote sql-replace URL replacement via SSH."""

    @pytest.mark.asyncio
    async def test_remote_sql_executes_via_ssh(self) -> None:
        """replace_urls_remote_sql() calls run_ssh_command."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_sql

            await replace_urls_remote_sql(
                source_domain="localhost",
                target_domain="wp.example.com",
                db_name="wp_testdb",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
            )

            mock_ssh.assert_called_once()

    @pytest.mark.asyncio
    async def test_remote_sql_updates_wp_options_wp_posts_wp_postmeta(
        self,
    ) -> None:
        """Remote sql-replace generates UPDATE for wp_options, wp_posts, wp_postmeta."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_sql

            await replace_urls_remote_sql(
                source_domain="localhost",
                target_domain="wp.example.com",
                db_name="wp_testdb",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
            )

            cmd = mock_ssh.call_args[1].get("command") or mock_ssh.call_args[0][2]
            assert "wp_options" in cmd
            assert "wp_posts" in cmd
            assert "wp_postmeta" in cmd

    @pytest.mark.asyncio
    async def test_remote_sql_skips_guid_column(self) -> None:
        """Remote sql-replace skips guid column in wp_posts."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            return_value=("", "", 0),
        ) as mock_ssh:
            from cloudways_api.url_replace import replace_urls_remote_sql

            await replace_urls_remote_sql(
                source_domain="localhost",
                target_domain="wp.example.com",
                db_name="wp_testdb",
                ssh_host="1.2.3.4",
                ssh_user="master_user",
            )

            cmd = mock_ssh.call_args[1].get("command") or mock_ssh.call_args[0][2]
            assert "SET guid" not in cmd

    @pytest.mark.asyncio
    async def test_remote_sql_raises_on_ssh_failure(self) -> None:
        """Remote sql-replace raises SSHError on SSH failure."""
        with patch(
            "cloudways_api.url_replace.run_ssh_command",
            new_callable=AsyncMock,
            side_effect=SSHError("SSH timed out"),
        ):
            from cloudways_api.url_replace import replace_urls_remote_sql

            with pytest.raises(SSHError, match="SSH timed out"):
                await replace_urls_remote_sql(
                    source_domain="localhost",
                    target_domain="wp.example.com",
                    db_name="wp_testdb",
                    ssh_host="1.2.3.4",
                    ssh_user="master_user",
                )


class TestGetURLReplacerRemote:
    """Tests for get_url_replacer with remote=True."""

    def test_get_url_replacer_remote_wp_cli_returns_remote_function(self) -> None:
        """get_url_replacer('wp-cli', remote=True) returns remote wp-cli function."""
        from cloudways_api.url_replace import (
            get_url_replacer,
            replace_urls_remote_wp_cli,
        )

        func = get_url_replacer("wp-cli", remote=True)
        assert func is replace_urls_remote_wp_cli

    def test_get_url_replacer_remote_sql_replace_returns_remote_function(
        self,
    ) -> None:
        """get_url_replacer('sql-replace', remote=True) returns remote sql function."""
        from cloudways_api.url_replace import (
            get_url_replacer,
            replace_urls_remote_sql,
        )

        func = get_url_replacer("sql-replace", remote=True)
        assert func is replace_urls_remote_sql

    def test_get_url_replacer_remote_env_file_raises_config_error(self) -> None:
        """get_url_replacer('env-file', remote=True) raises ConfigError."""
        from cloudways_api.url_replace import get_url_replacer

        with pytest.raises(ConfigError, match="not supported for remote"):
            get_url_replacer("env-file", remote=True)

    def test_get_url_replacer_local_still_returns_local_functions(self) -> None:
        """get_url_replacer with remote=False still returns local functions."""
        from cloudways_api.url_replace import (
            get_url_replacer,
            replace_urls_env_file,
            replace_urls_sql_replace,
            replace_urls_wp_cli,
        )

        assert get_url_replacer("wp-cli") is replace_urls_wp_cli
        assert get_url_replacer("env-file") is replace_urls_env_file
        assert get_url_replacer("sql-replace") is replace_urls_sql_replace
