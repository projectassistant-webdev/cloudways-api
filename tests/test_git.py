"""Tests for git deployment commands and client methods.

Covers git clone, pull, branches, and history commands with
mocked Cloudways API responses, plus client method tests.
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


# --- Mock API response constants ---

MOCK_CLONE_RESPONSE = {"operation_id": 88001}
MOCK_PULL_RESPONSE = {"operation_id": 88002}
# VERIFIED: response shape confirmed from LocalDocs (cloudways-v2-git.md)
MOCK_BRANCHES_RESPONSE = {"branches": ["main", "staging", "develop"]}
# VERIFIED: response shape confirmed from LocalDocs (cloudways-v2-git.md)
MOCK_HISTORY_RESPONSE = {
    "logs": [
        {
            "branch_name": "main",
            "datetime": "13, 03, 2026 - 10:00",
            "git_url": "git@bitbucket.org:org/repo.git",
            "result": "1",
            "description": "running",
        },
        {
            "branch_name": "staging",
            "datetime": "12, 03, 2026 - 15:30",
            "git_url": "git@bitbucket.org:org/repo.git",
            "result": "1",
            "description": "running",
        },
    ]
}


# --- Operation response helpers ---


def _make_operation_complete_response():
    """Return a completed operation response."""
    return {"operation": {"is_completed": True, "status": "completed"}}


def _make_operation_pending_response():
    """Return a pending (not completed) operation response."""
    return {"operation": {"is_completed": False, "status": "pending"}}


# --- Handler factory ---


def _make_git_handler(
    clone_response=None,
    clone_error=False,
    pull_response=None,
    pull_error=False,
    branches_response=None,
    branches_error=False,
    history_response=None,
    history_error=False,
    operation_response=None,
):
    """Build httpx mock handler for git deployment API calls.

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

        # CRITICAL: /git/branchNames must be checked first among all git routes.
        # There is no /git/branch handler -- this ordering ensures branchNames is
        # not inadvertently matched by a hypothetical shorter prefix. Routes are:
        # /git/branchNames (GET), /git/clone (POST), /git/pull (POST),
        # /git/history (GET)
        if "/git/branchNames" in url and method == "GET":
            if branches_error:
                return httpx.Response(422, text="Branch list failed")
            return httpx.Response(
                200, json=branches_response or MOCK_BRANCHES_RESPONSE
            )

        if "/git/clone" in url and method == "POST":
            if clone_error:
                return httpx.Response(422, text="Clone failed")
            return httpx.Response(
                200, json=clone_response or MOCK_CLONE_RESPONSE
            )

        if "/git/pull" in url and method == "POST":
            if pull_error:
                return httpx.Response(422, text="Pull failed")
            return httpx.Response(
                200, json=pull_response or MOCK_PULL_RESPONSE
            )

        if "/git/history" in url and method == "GET":
            if history_error:
                return httpx.Response(422, text="History failed")
            return httpx.Response(
                200, json=history_response or MOCK_HISTORY_RESPONSE
            )

        return httpx.Response(404)

    return handler, captured


# --- Env helper ---


# ===================================================================
# Client method tests
# ===================================================================


class TestGitCloneClient:
    """Tests for CloudwaysClient.git_clone()."""

    @pytest.mark.asyncio
    async def test_git_clone_success(self) -> None:
        """POST /git/clone with all four fields in form body."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.git_clone(
                server_id=999999,
                app_id=1234567,
                git_url="https://bitbucket.org/org/repo.git",
                branch_name="main",
            )

        assert result["operation_id"] == 88001
        request = [
            r
            for r in captured
            if r.method == "POST" and "/git/clone" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "git_url=https%3A%2F%2Fbitbucket.org%2Forg%2Frepo.git" in body
        assert "branch_name=main" in body

    @pytest.mark.asyncio
    async def test_git_clone_api_error(self) -> None:
        """Raises APIError on 422."""
        handler, captured = _make_git_handler(clone_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.git_clone(
                    server_id=999999,
                    app_id=1234567,
                    git_url="https://bitbucket.org/org/repo.git",
                    branch_name="main",
                )


class TestGitPullClient:
    """Tests for CloudwaysClient.git_pull()."""

    @pytest.mark.asyncio
    async def test_git_pull_success(self) -> None:
        """POST /git/pull with server_id, app_id, branch_name in body."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.git_pull(
                server_id=999999,
                app_id=1234567,
                branch_name="main",
            )

        assert result["operation_id"] == 88002
        request = [
            r
            for r in captured
            if r.method == "POST" and "/git/pull" in str(r.url)
        ][0]
        body = request.content.decode()
        assert "server_id=999999" in body
        assert "app_id=1234567" in body
        assert "branch_name=main" in body

    @pytest.mark.asyncio
    async def test_git_pull_api_error(self) -> None:
        """Raises APIError on 422."""
        handler, captured = _make_git_handler(pull_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.git_pull(
                    server_id=999999,
                    app_id=1234567,
                    branch_name="main",
                )


class TestGitBranchNamesClient:
    """Tests for CloudwaysClient.git_branch_names()."""

    @pytest.mark.asyncio
    async def test_git_branch_names_success(self) -> None:
        """GET /git/branchNames with query params."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.git_branch_names(
                server_id=999999,
                app_id=1234567,
                git_url="https://bitbucket.org/org/repo.git",
            )

        assert result == MOCK_BRANCHES_RESPONSE
        request = [
            r
            for r in captured
            if r.method == "GET" and "/git/branchNames" in str(r.url)
        ][0]
        url_str = str(request.url)
        assert "server_id=999999" in url_str
        assert "app_id=1234567" in url_str
        assert "git_url=https%3A%2F%2Fbitbucket.org%2Forg%2Frepo.git" in url_str

    @pytest.mark.asyncio
    async def test_git_branch_names_api_error(self) -> None:
        """Raises APIError on 422."""
        handler, captured = _make_git_handler(branches_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.git_branch_names(
                    server_id=999999,
                    app_id=1234567,
                    git_url="https://bitbucket.org/org/repo.git",
                )


class TestGitHistoryClient:
    """Tests for CloudwaysClient.git_history()."""

    @pytest.mark.asyncio
    async def test_git_history_success(self) -> None:
        """GET /git/history with query params."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            result = await client.git_history(
                server_id=999999,
                app_id=1234567,
            )

        assert result == MOCK_HISTORY_RESPONSE
        request = [
            r
            for r in captured
            if r.method == "GET" and "/git/history" in str(r.url)
        ][0]
        url_str = str(request.url)
        assert "server_id=999999" in url_str
        assert "app_id=1234567" in url_str

    @pytest.mark.asyncio
    async def test_git_history_api_error(self) -> None:
        """Raises APIError on 422."""
        handler, captured = _make_git_handler(history_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        async with PatchedClient("test@example.com", "key") as client:
            with pytest.raises(APIError):
                await client.git_history(
                    server_id=999999,
                    app_id=1234567,
                )


# ===================================================================
# CLI command tests
# ===================================================================


class TestGitCloneCommand:
    """Tests for `cloudways git clone` command."""

    def test_git_clone_success(self, set_env) -> None:
        """Invokes git clone with --repo and --branch, exits 0."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "git",
                    "clone",
                    "production",
                    "--repo",
                    "https://bitbucket.org/org/repo.git",
                    "--branch",
                    "main",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Git clone initiated. Operation ID: 88001" in result.output

    def test_git_clone_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_git_handler(clone_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "git",
                    "clone",
                    "production",
                    "--repo",
                    "https://bitbucket.org/org/repo.git",
                    "--branch",
                    "main",
                ],
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_git_clone_invalid_env(self, set_env) -> None:
        """Invalid environment exits 1 with 'not found' message."""
        result = runner.invoke(
            app,
            [
                "git",
                "clone",
                "nonexistent",
                "--repo",
                "https://bitbucket.org/org/repo.git",
                "--branch",
                "main",
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output


class TestGitPullCommand:
    """Tests for `cloudways git pull` command."""

    def test_git_pull_no_wait(self, set_env) -> None:
        """Without --wait, prints operation ID and exits immediately."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["git", "pull", "production", "--branch", "main"]
            )

        assert result.exit_code == 0, result.output
        assert result.output == "Git pull initiated. Operation ID: 88002\n"

    def test_git_pull_with_wait(self, set_env) -> None:
        """With --wait, polls operation and prints completion."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.client.asyncio.sleep", return_value=None):
            with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
                result = runner.invoke(
                    app,
                    ["git", "pull", "production", "--branch", "main", "--wait"],
                )

        assert result.exit_code == 0, result.output
        assert "Git pull complete." in result.output

    def test_git_pull_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_git_handler(pull_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app, ["git", "pull", "production", "--branch", "main"]
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_git_pull_invalid_env(self, set_env) -> None:
        """Invalid environment exits 1 with 'not found' message."""
        result = runner.invoke(
            app, ["git", "pull", "nonexistent", "--branch", "main"]
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_git_pull_wait_timeout(self, set_env) -> None:
        """Operation timeout exits 1."""
        handler, captured = _make_git_handler(
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
                    "cloudways_api.commands.git.CloudwaysClient", PatchedClient
                ):
                    result = runner.invoke(
                        app,
                        [
                            "git",
                            "pull",
                            "production",
                            "--branch",
                            "main",
                            "--wait",
                            "--timeout",
                            "1",
                        ],
                    )

        assert result.exit_code == 1


class TestGitBranchesCommand:
    """Tests for `cloudways git branches` command."""

    def test_git_branches_success(self, set_env) -> None:
        """Lists branch names, one per line."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "git",
                    "branches",
                    "production",
                    "--repo",
                    "https://bitbucket.org/org/repo.git",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "main" in result.output
        assert "staging" in result.output
        assert "develop" in result.output

    def test_git_branches_empty(self, set_env) -> None:
        """Empty branch list prints informative message."""
        handler, captured = _make_git_handler(
            branches_response={"branches": []}
        )
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "git",
                    "branches",
                    "production",
                    "--repo",
                    "https://bitbucket.org/org/repo.git",
                ],
            )

        assert result.exit_code == 0
        assert "No branches found." in result.output

    def test_git_branches_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_git_handler(branches_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(
                app,
                [
                    "git",
                    "branches",
                    "production",
                    "--repo",
                    "https://bitbucket.org/org/repo.git",
                ],
            )

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_git_branches_invalid_env(self, set_env) -> None:
        """Invalid environment exits 1 with 'not found' message."""
        result = runner.invoke(
            app,
            [
                "git",
                "branches",
                "nonexistent",
                "--repo",
                "https://bitbucket.org/org/repo.git",
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output


class TestGitHistoryCommand:
    """Tests for `cloudways git history` command."""

    def test_git_history_success(self, set_env) -> None:
        """Prints deployment history with branch and datetime."""
        handler, captured = _make_git_handler()
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["git", "history", "production"])

        assert result.exit_code == 0, result.output
        assert "main" in result.output
        assert "13, 03, 2026" in result.output

    def test_git_history_empty(self, set_env) -> None:
        """Empty history prints informative message."""
        handler, captured = _make_git_handler(history_response={"logs": []})
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["git", "history", "production"])

        assert result.exit_code == 0
        assert "No deployment history found." in result.output

    def test_git_history_api_error(self, set_env) -> None:
        """API 422 exits with code 1."""
        handler, captured = _make_git_handler(history_error=True)
        transport = httpx.MockTransport(handler)
        PatchedClient = make_patched_client_class(transport)

        with patch("cloudways_api.commands.git.CloudwaysClient", PatchedClient):
            result = runner.invoke(app, ["git", "history", "production"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_git_history_invalid_env(self, set_env) -> None:
        """Invalid environment exits 1 with 'not found' message."""
        result = runner.invoke(app, ["git", "history", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output


# ===================================================================
# CLI registration tests
# ===================================================================


class TestGitRegistration:
    """Tests for git command registration in CLI."""

    def test_git_in_help(self) -> None:
        """git appears in cloudways --help."""
        result = runner.invoke(app, ["--help"])
        assert "git" in result.output

    def test_git_help(self) -> None:
        """git --help shows all four subcommands."""
        result = runner.invoke(app, ["git", "--help"])
        assert result.exit_code == 0
        assert "clone" in result.output
        assert "pull" in result.output
        assert "branches" in result.output
        assert "history" in result.output

    def test_git_group_help_text(self) -> None:
        """git --help shows correct help text."""
        result = runner.invoke(app, ["git", "--help"])
        assert "Git deployment operations" in result.output
