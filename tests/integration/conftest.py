"""Integration test fixtures - require real Cloudways API credentials.

These fixtures provide access to real Cloudways API credentials for
integration tests. Tests using these fixtures will self-skip when
credentials are not available in the environment.

Required environment variables:
    CLOUDWAYS_TEST_EMAIL: Cloudways account email for API access
    CLOUDWAYS_TEST_API_KEY: Cloudways API key for authentication
"""

import os

import pytest


def has_cloudways_credentials() -> bool:
    """Check if real Cloudways API credentials are available."""
    return bool(
        os.environ.get("CLOUDWAYS_TEST_EMAIL")
        and os.environ.get("CLOUDWAYS_TEST_API_KEY")
    )


@pytest.fixture
def cloudways_email():
    """Provide Cloudways test email from environment."""
    return os.environ["CLOUDWAYS_TEST_EMAIL"]


@pytest.fixture
def cloudways_api_key():
    """Provide Cloudways test API key from environment."""
    return os.environ["CLOUDWAYS_TEST_API_KEY"]
