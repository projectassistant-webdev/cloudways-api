"""Shared test fixtures for cloudways-api tests."""

import asyncio
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ACCOUNTS_PATH = FIXTURES_DIR / "accounts.yml"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_cloudways_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all CLOUDWAYS_* env vars for test isolation.

    This is autouse so it runs for every test automatically, ensuring no
    environment variables leak between tests or from the host.
    """
    for var in [
        "CLOUDWAYS_EMAIL",
        "CLOUDWAYS_API_KEY",
        "CLOUDWAYS_ACCOUNTS_FILE",
        "CLOUDWAYS_PROJECT_CONFIG",
        "CLOUDWAYS_API_KEY_PRIMARY",
        "CLOUDWAYS_API_KEY_AGENCY",
    ]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set common env vars for CLI tests.

    Sets CLOUDWAYS_ACCOUNTS_FILE and CLOUDWAYS_PROJECT_CONFIG to the
    shared test fixtures. Use this fixture in any test that invokes CLI
    commands requiring account/project configuration.
    """
    monkeypatch.setenv("CLOUDWAYS_ACCOUNTS_FILE", str(ACCOUNTS_PATH))
    monkeypatch.setenv(
        "CLOUDWAYS_PROJECT_CONFIG",
        str(FIXTURES_DIR / "project-config.yml"),
    )


# ---------------------------------------------------------------------------
# Shared helper functions
# ---------------------------------------------------------------------------


def make_auth_response() -> dict:
    """Return a standard OAuth token response dict for mocking."""
    return {
        "access_token": "test_token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }


def make_patched_client_class(transport):
    """Create a CloudwaysClient subclass that injects mock transport.

    Args:
        transport: An httpx transport (typically httpx.MockTransport) to inject.

    Returns:
        A CloudwaysClient subclass that forces the provided transport.
    """
    from cloudways_api.client import CloudwaysClient

    class PatchedClient(CloudwaysClient):
        def __init__(self, email: str, api_key: str, **kwargs):
            super().__init__(email=email, api_key=api_key, transport=transport)

    return PatchedClient


class MockProcess:
    """Simulates asyncio.subprocess.Process for SSH testing.

    Provides configurable stdout, stderr, and returncode for use
    with unittest.mock.patch on asyncio.create_subprocess_exec.
    """

    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self._stdout_data = stdout
        self._stderr_data = stderr
        self.returncode = returncode
        self.pid = 12345

        self.stdout = asyncio.StreamReader()
        if stdout:
            self.stdout.feed_data(stdout)
        self.stdout.feed_eof()

        self.stderr = asyncio.StreamReader()
        if stderr:
            self.stderr.feed_data(stderr)
        self.stderr.feed_eof()

    async def communicate(self) -> tuple[bytes, bytes]:
        """Return buffered stdout and stderr."""
        stdout_data = await self.stdout.read()
        stderr_data = await self.stderr.read()
        return stdout_data, stderr_data

    async def wait(self) -> int:
        """Return the configured return code."""
        return self.returncode
