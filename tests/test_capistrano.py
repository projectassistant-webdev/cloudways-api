"""Tests for the capistrano command and templates module.

Covers template rendering, file generation, preview mode,
force overwrite, bitbucket pipelines, repo URL detection,
application name derivation, Bedrock defaults, and error handling.
"""

import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cloudways_api.cli import app
from cloudways_api.commands.capistrano import (
    derive_app_name,
    detect_repo_url,
)
from cloudways_api.templates import (
    DEFAULT_LINKED_DIRS,
    DEFAULT_LINKED_FILES,
    render_capfile,
    render_deploy_rb,
    render_gemfile,
    render_pipelines,
    render_stage_deploy,
)

runner = CliRunner()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

SAMPLE_GIT_CONFIG = """\
[core]
\trepositoryformatversion = 0
\tfilemode = true
[remote "origin"]
\turl = git@bitbucket.org:myworkspace/mysite-wp.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
[branch "main"]
\tremote = origin
\tmerge = refs/heads/main
"""

SAMPLE_GIT_CONFIG_HTTPS = """\
[core]
\trepositoryformatversion = 0
[remote "origin"]
\turl = https://bitbucket.org/myworkspace/mysite-wp.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
"""

SAMPLE_GIT_CONFIG_NO_ORIGIN = """\
[core]
\trepositoryformatversion = 0
\tfilemode = true
[branch "main"]
\tremote = origin
\tmerge = refs/heads/main
"""


def _config_path() -> str:
    return os.path.join(FIXTURES_DIR, "project-config.yml")


# ---- Template rendering unit tests ----


class TestRenderCapfile:
    """Tests for render_capfile()."""

    def test_contains_require_deploy(self) -> None:
        """AC-3C.1: Capfile contains require deploy."""
        content = render_capfile()
        assert 'require "capistrano/deploy"' in content

    def test_contains_scm_git(self) -> None:
        """AC-3C.1: Capfile contains Git SCM plugin."""
        content = render_capfile()
        assert 'require "capistrano/scm/git"' in content
        assert "install_plugin Capistrano::SCM::Git" in content

    def test_contains_setup(self) -> None:
        """Capfile contains capistrano/setup."""
        content = render_capfile()
        assert 'require "capistrano/setup"' in content

    def test_contains_tasks_glob(self) -> None:
        """Capfile contains task file globbing."""
        content = render_capfile()
        assert "Dir.glob" in content
        assert "lib/capistrano/tasks/*.rake" in content

    def test_valid_ruby_brace_syntax(self) -> None:
        """C-1: Capfile uses single braces (valid Ruby), not double braces."""
        content = render_capfile()
        assert "{ |r|" in content
        assert "{{ |r|" not in content


class TestRenderDeployRb:
    """Tests for render_deploy_rb()."""

    def test_contains_application_name(self) -> None:
        """AC-3C.2: deploy.rb contains application name."""
        content = render_deploy_rb(
            "mysite", "git@host:user/repo.git", "/path", "master"
        )
        assert ':application, "mysite"' in content

    def test_contains_repo_url(self) -> None:
        """AC-3C.2: deploy.rb contains repo URL."""
        url = "git@bitbucket.org:user/repo.git"
        content = render_deploy_rb("app", url, "/path", "master")
        assert f':repo_url, "{url}"' in content

    def test_contains_deploy_to(self) -> None:
        """AC-3C.2: deploy.rb contains deploy_to path."""
        content = render_deploy_rb(
            "app", "url", "public_html/current", "master"
        )
        assert ':deploy_to, "public_html/current"' in content

    def test_contains_keep_releases(self) -> None:
        """AC-3C.2: deploy.rb contains keep_releases default 5."""
        content = render_deploy_rb("app", "url", "/path", "master")
        assert ":keep_releases, 5" in content

    def test_custom_keep_releases(self) -> None:
        """keep_releases can be overridden."""
        content = render_deploy_rb(
            "app", "url", "/path", "master", keep_releases=3
        )
        assert ":keep_releases, 3" in content

    def test_contains_linked_files(self) -> None:
        """AC-3C.2: deploy.rb contains linked_files."""
        content = render_deploy_rb("app", "url", "/path", "master")
        assert ":linked_files" in content

    def test_contains_linked_dirs(self) -> None:
        """AC-3C.2: deploy.rb contains linked_dirs."""
        content = render_deploy_rb("app", "url", "/path", "master")
        assert ":linked_dirs" in content

    def test_default_linked_files_bedrock(self) -> None:
        """AC-3C.6: Default linked_files includes Bedrock defaults."""
        content = render_deploy_rb("app", "url", "/path", "master")
        assert ".env" in content
        assert "web/.htaccess" in content

    def test_default_linked_dirs_bedrock(self) -> None:
        """AC-3C.7: Default linked_dirs includes Bedrock default."""
        content = render_deploy_rb("app", "url", "/path", "master")
        assert "web/app/uploads" in content

    def test_custom_linked_files(self) -> None:
        """AC-3C.2: Custom linked_files override defaults."""
        content = render_deploy_rb(
            "app", "url", "/path", "master",
            linked_files=["custom.conf", "data.json"],
        )
        assert "custom.conf" in content
        assert "data.json" in content
        # Default .env should not be present
        assert ".env" not in content

    def test_contains_tmp_dir(self) -> None:
        """deploy.rb contains tmp_dir set."""
        content = render_deploy_rb("app", "url", "/path", "master_abc")
        assert ':tmp_dir, "/home/master_abc/tmp"' in content


class TestRenderStageDeploy:
    """Tests for render_stage_deploy()."""

    def test_contains_server(self) -> None:
        """AC-3C.3: Stage deploy contains server IP."""
        content = render_stage_deploy(
            "1.2.3.4", "user", "main", "/path"
        )
        assert '"1.2.3.4"' in content

    def test_contains_user(self) -> None:
        """AC-3C.3: Stage deploy contains SSH user."""
        content = render_stage_deploy(
            "host", "master_abc", "main", "/path"
        )
        assert 'user: "master_abc"' in content

    def test_contains_branch(self) -> None:
        """AC-3C.3: Stage deploy contains deploy branch."""
        content = render_stage_deploy("host", "user", "staging", "/path")
        assert ':branch, "staging"' in content

    def test_contains_deploy_to(self) -> None:
        """AC-3C.3: Stage deploy contains deploy_to path."""
        content = render_stage_deploy(
            "host", "user", "main", "public_html/current"
        )
        assert ':deploy_to, "public_html/current"' in content

    def test_contains_roles(self) -> None:
        """Stage deploy includes app db web roles."""
        content = render_stage_deploy("host", "user", "main", "/path")
        assert "roles: %w[app db web]" in content


class TestRenderGemfile:
    """Tests for render_gemfile()."""

    def test_contains_capistrano(self) -> None:
        """AC-3C.4: Gemfile contains capistrano gem."""
        content = render_gemfile()
        assert 'gem "capistrano"' in content

    def test_contains_capistrano_composer(self) -> None:
        """AC-3C.4: Gemfile contains capistrano-composer gem."""
        content = render_gemfile()
        assert 'gem "capistrano-composer"' in content

    def test_contains_rubygems_source(self) -> None:
        """Gemfile has rubygems source."""
        content = render_gemfile()
        assert 'source "https://rubygems.org"' in content


class TestRenderPipelines:
    """Tests for render_pipelines()."""

    def test_contains_docker_image(self) -> None:
        """AC-3C.5: Pipelines has default Docker image."""
        content = render_pipelines()
        assert "myworkspace/pipelines:3.0" in content

    def test_custom_docker_image(self) -> None:
        """Custom Docker image substituted."""
        content = render_pipelines(docker_image="custom/image:1.0")
        assert "custom/image:1.0" in content

    def test_contains_production_step(self) -> None:
        """Pipelines contains production deploy step."""
        content = render_pipelines()
        assert "Deploy to Production" in content
        assert "cap production deploy" in content

    def test_contains_staging_step(self) -> None:
        """Pipelines contains staging deploy step."""
        content = render_pipelines()
        assert "Deploy to Staging" in content
        assert "cap staging deploy" in content

    def test_contains_rollback_custom(self) -> None:
        """Pipelines contains rollback custom pipelines."""
        content = render_pipelines()
        assert "rollback-production" in content
        assert "rollback-staging" in content
        assert "deploy:rollback" in content


class TestDefaultLinkedValues:
    """Tests for Bedrock default constants."""

    def test_default_linked_files(self) -> None:
        """AC-3C.6: Default linked files."""
        assert ".env" in DEFAULT_LINKED_FILES
        assert "web/.htaccess" in DEFAULT_LINKED_FILES

    def test_default_linked_dirs(self) -> None:
        """AC-3C.7: Default linked dirs."""
        assert "web/app/uploads" in DEFAULT_LINKED_DIRS


# ---- Repo URL detection tests ----


class TestDetectRepoUrl:
    """Tests for detect_repo_url()."""

    def test_from_git_config(self, tmp_path, monkeypatch) -> None:
        """AC-3C.8: Parses remote origin URL from .git/config."""
        monkeypatch.chdir(tmp_path)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(SAMPLE_GIT_CONFIG)
        result = detect_repo_url()
        assert result == "git@bitbucket.org:myworkspace/mysite-wp.git"

    def test_no_git_config_returns_none(
        self, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.9: Returns None when .git/config not found."""
        monkeypatch.chdir(tmp_path)
        result = detect_repo_url()
        assert result is None

    def test_no_remote_origin_returns_none(
        self, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.10: Returns None when no remote origin section."""
        monkeypatch.chdir(tmp_path)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(SAMPLE_GIT_CONFIG_NO_ORIGIN)
        result = detect_repo_url()
        assert result is None

    def test_ssh_format(self, tmp_path, monkeypatch) -> None:
        """SSH format URL detected correctly."""
        monkeypatch.chdir(tmp_path)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(SAMPLE_GIT_CONFIG)
        result = detect_repo_url()
        assert result is not None
        assert result.startswith("git@")

    def test_https_format(self, tmp_path, monkeypatch) -> None:
        """HTTPS format URL detected correctly."""
        monkeypatch.chdir(tmp_path)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(SAMPLE_GIT_CONFIG_HTTPS)
        result = detect_repo_url()
        assert result is not None
        assert result.startswith("https://")


# ---- Application name derivation tests ----


class TestDeriveAppName:
    """Tests for derive_app_name()."""

    def test_from_ssh_repo_url(self) -> None:
        """AC-3C.22: Strip .git suffix from SSH URL."""
        name = derive_app_name(
            "git@bitbucket.org:myworkspace/mysite-wp.git"
        )
        assert name == "mysite-wp"

    def test_from_https_repo_url(self) -> None:
        """HTTPS URL also works."""
        name = derive_app_name(
            "https://bitbucket.org/myworkspace/mysite-wp.git"
        )
        assert name == "mysite-wp"

    def test_no_git_suffix(self) -> None:
        """URL without .git suffix works."""
        name = derive_app_name(
            "https://bitbucket.org/myworkspace/mysite-wp"
        )
        assert name == "mysite-wp"

    def test_trailing_slash(self) -> None:
        """Trailing slash handled."""
        name = derive_app_name(
            "https://bitbucket.org/myworkspace/mysite-wp.git/"
        )
        assert name == "mysite-wp"


# ---- Command integration tests ----


class TestCapistranoCommand:
    """Tests for the capistrano CLI command."""

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_generates_all_core_files(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.11: 5 core files created."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 0
        assert (tmp_path / "Capfile").is_file()
        assert (tmp_path / "config" / "deploy.rb").is_file()
        assert (tmp_path / "config" / "deploy" / "production.rb").is_file()
        assert (tmp_path / "config" / "deploy" / "staging.rb").is_file()
        assert (tmp_path / "Gemfile").is_file()

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_creates_config_deploy_directory(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.20: config/deploy/ directory created automatically."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        assert (tmp_path / "config" / "deploy").is_dir()

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_with_pipelines_generates_six_files(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.12: --with-pipelines generates additional pipeline file."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano", "--with-pipelines"])
        assert result.exit_code == 0
        assert (tmp_path / "bitbucket-pipelines.yml").is_file()
        # Plus the 5 core files
        assert (tmp_path / "Capfile").is_file()

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_preview_mode_no_files_written(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.13: --preview prints to stdout without writing."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano", "--preview"])
        assert result.exit_code == 0
        assert not (tmp_path / "Capfile").exists()
        assert not (tmp_path / "Gemfile").exists()

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_preview_mode_output_has_headers(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """Preview mode output has file headers."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano", "--preview"])
        assert "--- Capfile ---" in result.output
        assert "--- config/deploy.rb ---" in result.output
        assert "--- Gemfile ---" in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_existing_files_skipped_no_force(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.14: Existing files skipped with warning."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        # Pre-create a file
        (tmp_path / "Capfile").write_text("existing content")
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 0
        assert "Skipping Capfile" in result.output
        # File should not be overwritten
        assert (tmp_path / "Capfile").read_text() == "existing content"

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_force_overwrites_existing_files(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.15: --force overwrites existing files."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Capfile").write_text("old content")
        result = runner.invoke(app, ["capistrano", "--force"])
        assert result.exit_code == 0
        # File should be overwritten
        assert (tmp_path / "Capfile").read_text() != "old content"
        assert "capistrano/deploy" in (tmp_path / "Capfile").read_text()

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_production_rb_has_correct_values(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.18: Production.rb has correct per-environment values."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        content = (
            tmp_path / "config" / "deploy" / "production.rb"
        ).read_text()
        assert "1.2.3.4" in content
        assert "master_example" in content
        assert '"main"' in content

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_staging_rb_has_correct_values(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.18: Staging.rb has correct per-environment values."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        content = (
            tmp_path / "config" / "deploy" / "staging.rb"
        ).read_text()
        assert "1.2.3.4" in content
        assert "master_example" in content
        assert '"staging"' in content

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_deploy_rb_has_bedrock_defaults(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.19: deploy.rb has Bedrock linked_files and linked_dirs."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        content = (tmp_path / "config" / "deploy.rb").read_text()
        assert ".env" in content
        assert "web/.htaccess" in content
        assert "web/app/uploads" in content

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value=None,
    )
    def test_missing_repo_url_error(
        self, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.16: Missing repo URL shows error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 1
        assert "repository URL" in result.output

    def test_missing_ssh_config_error(
        self, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.17: Missing SSH config shows error."""
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
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 1

    def test_registered_in_cli_help(self) -> None:
        """AC-3C.24: capistrano command appears in CLI help."""
        result = runner.invoke(app, ["--help"])
        assert "capistrano" in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_exit_code_zero_on_success(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.25: Exit code 0 on success."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 0

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value=None,
    )
    def test_exit_code_one_on_error(
        self, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.26: Exit code 1 on error."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert result.exit_code == 1

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_success_output_lists_files(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.23: Success output lists created files."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert "Capistrano Configuration Generated" in result.output
        assert "Capfile" in result.output
        assert "config/deploy.rb" in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_branch_defaults_for_missing_branch(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.21: Missing branch defaults to env-appropriate value."""
        # Use a config without branch fields
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            "hosting:\n  cloudways:\n    account: primary\n"
            "    server:\n"
            "      id: 123\n"
            "      ssh_user: master_abc\n"
            "      ssh_host: 1.2.3.4\n"
            "    environments:\n"
            "      production:\n"
            "        app_id: 456\n"
            "        domain: example.com\n"
            "      staging:\n"
            "        app_id: 789\n"
            "        domain: staging.example.com\n"
        )
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", str(config_file))
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        prod_content = (
            tmp_path / "config" / "deploy" / "production.rb"
        ).read_text()
        staging_content = (
            tmp_path / "config" / "deploy" / "staging.rb"
        ).read_text()
        assert '"main"' in prod_content
        assert '"staging"' in staging_content

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_file_write_permission_error(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """File write permission error handled."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        # Make directory read-only to simulate permission error
        # We'll patch Path.write_text to raise OSError instead
        with patch.object(
            Path, "write_text", side_effect=OSError("Permission denied")
        ):
            result = runner.invoke(app, ["capistrano"])
            assert result.exit_code == 1
            assert "Error" in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=False,
    )
    def test_bedrock_warning_shown(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """AC-3C.28: Warning shown when Bedrock not detected."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert "Warning" in result.output
        assert "Bedrock" in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_no_bedrock_warning_when_detected(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """No Bedrock warning when indicators are found."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["capistrano"])
        assert "Warning" not in result.output

    @patch(
        "cloudways_api.commands.capistrano.detect_repo_url",
        return_value="git@bitbucket.org:user/mysite.git",
    )
    @patch(
        "cloudways_api.commands.capistrano._is_bedrock_project",
        return_value=True,
    )
    def test_deploy_rb_application_from_repo_url(
        self, mock_bedrock, mock_repo, tmp_path, monkeypatch
    ) -> None:
        """Application name in deploy.rb derived from repo URL."""
        monkeypatch.setenv("CLOUDWAYS_PROJECT_CONFIG", _config_path())
        monkeypatch.chdir(tmp_path)
        runner.invoke(app, ["capistrano"])
        content = (tmp_path / "config" / "deploy.rb").read_text()
        assert ':application, "mysite"' in content
