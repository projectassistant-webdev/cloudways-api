"""Capistrano and Bitbucket pipeline template strings.

All template strings are defined as module-level constants. Templates
with variable substitution use ``str.format()`` for consistency.
Static templates (Capfile, Gemfile) are returned as-is by their
rendering functions.
"""

# ---- Bedrock WordPress defaults ----

DEFAULT_LINKED_FILES: list[str] = [".env", "web/.htaccess"]
DEFAULT_LINKED_DIRS: list[str] = ["web/app/uploads"]


# ---- Template strings ----

CAPFILE_TEMPLATE = """\
# frozen_string_literal: true

require "capistrano/setup"
require "capistrano/deploy"
require "capistrano/scm/git"

install_plugin Capistrano::SCM::Git

Dir.glob("lib/capistrano/tasks/*.rake").each { |r| import r }
"""

DEPLOY_RB_TEMPLATE = """\
set :application, "{application}"
set :repo_url, "{repo_url}"

set :deploy_to, "{deploy_to}"
set :keep_releases, {keep_releases}

set :linked_files, %w[{linked_files_str}]
set :linked_dirs, %w[{linked_dirs_str}]

set :tmp_dir, "/home/{user}/tmp"
"""

STAGE_DEPLOY_TEMPLATE = """\
server "{server}", user: "{user}", roles: %w[app db web]

set :branch, "{branch}"
set :deploy_to, "{deploy_to}"
"""

GEMFILE_TEMPLATE = """\
source "https://rubygems.org"

gem "capistrano", "~> 3.17"
gem "capistrano-composer"
"""

PIPELINES_TEMPLATE = """\
image:
  name: {docker_image}
  username: $DOCKER_USERNAME
  password: $DOCKER_PASSWORD

pipelines:
  branches:
    main:
      - step:
          name: Deploy to Production
          deployment: production
          script:
            - bundle install
            - bundle exec cap production deploy
    staging:
      - step:
          name: Deploy to Staging
          deployment: staging
          script:
            - bundle install
            - bundle exec cap staging deploy
  custom:
    rollback-production:
      - step:
          name: Rollback Production
          script:
            - bundle install
            - bundle exec cap production deploy:rollback
    rollback-staging:
      - step:
          name: Rollback Staging
          script:
            - bundle install
            - bundle exec cap staging deploy:rollback
"""


# ---- Rendering functions ----


def render_capfile() -> str:
    """Return Capfile content (static template).

    Returns:
        Capfile content string.
    """
    return CAPFILE_TEMPLATE


def render_deploy_rb(
    application: str,
    repo_url: str,
    deploy_to: str,
    user: str,
    keep_releases: int = 5,
    linked_files: list[str] | None = None,
    linked_dirs: list[str] | None = None,
) -> str:
    """Render main deploy.rb with variables substituted.

    Args:
        application: Application name.
        repo_url: Git repository URL.
        deploy_to: Remote deployment path.
        user: SSH username.
        keep_releases: Number of releases to keep.
        linked_files: Files to symlink into each release.
            Defaults to Bedrock conventions.
        linked_dirs: Directories to symlink into each release.
            Defaults to Bedrock conventions.

    Returns:
        Rendered deploy.rb content string.
    """
    if linked_files is None:
        linked_files = DEFAULT_LINKED_FILES
    if linked_dirs is None:
        linked_dirs = DEFAULT_LINKED_DIRS

    linked_files_str = " ".join(linked_files)
    linked_dirs_str = " ".join(linked_dirs)

    return DEPLOY_RB_TEMPLATE.format(
        application=application,
        repo_url=repo_url,
        deploy_to=deploy_to,
        user=user,
        keep_releases=keep_releases,
        linked_files_str=linked_files_str,
        linked_dirs_str=linked_dirs_str,
    )


def render_stage_deploy(
    server: str,
    user: str,
    branch: str,
    deploy_to: str,
) -> str:
    """Render stage-specific deploy file (production.rb / staging.rb).

    Args:
        server: Remote server hostname or IP.
        user: SSH username.
        branch: Git branch for this stage.
        deploy_to: Remote deployment path.

    Returns:
        Rendered stage deploy content string.
    """
    return STAGE_DEPLOY_TEMPLATE.format(
        server=server,
        user=user,
        branch=branch,
        deploy_to=deploy_to,
    )


def render_gemfile() -> str:
    """Return Gemfile content (static template).

    Returns:
        Gemfile content string.
    """
    return GEMFILE_TEMPLATE


def render_pipelines(
    docker_image: str = "projectassistant/pipelines:3.0",
) -> str:
    """Render bitbucket-pipelines.yml with Docker image.

    Args:
        docker_image: Docker image name for pipeline steps.

    Returns:
        Rendered bitbucket-pipelines.yml content string.
    """
    return PIPELINES_TEMPLATE.format(docker_image=docker_image)
