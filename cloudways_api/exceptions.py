"""Custom exception hierarchy for cloudways-api."""


class CloudwaysError(Exception):
    """Base exception for all cloudways-api errors."""


class ConfigError(CloudwaysError):
    """Configuration file issues.

    Raised when:
    - project-config.yml is missing
    - hosting or hosting.cloudways section is absent
    - YAML syntax is invalid
    """


class CredentialsError(CloudwaysError):
    """Credential loading issues.

    Raised when:
    - accounts.yml is missing
    - Account name not found in accounts.yml
    - Environment variable reference cannot be resolved
    """


class AuthenticationError(CloudwaysError):
    """OAuth authentication failures.

    Raised when:
    - Invalid email/API key combination (HTTP 401)
    - Token refresh fails after re-authentication attempt
    """


class APIError(CloudwaysError):
    """API call failures.

    Raised when:
    - HTTP error responses (4xx, 5xx) after retries exhausted
    - Network connectivity errors
    - Unexpected response format
    """


class RateLimitError(APIError):
    """Rate limit exceeded (HTTP 429).

    Raised after the maximum number of retry attempts for
    rate-limited requests has been exhausted.
    """


class ServerError(APIError):
    """Server-side errors (HTTP 5xx).

    Raised after the maximum number of retry attempts for
    server errors (500, 502, 503) has been exhausted.
    """


class SSHError(CloudwaysError):
    """SSH connection and command execution failures.

    Raised when:
    - SSH connection cannot be established (auth, network, timeout)
    - Remote command execution fails
    - SFTP/SCP download fails
    """


class DatabaseError(CloudwaysError):
    """Database operation failures.

    Raised when:
    - mysqldump fails on remote server
    - Local mysql import fails
    - Database name detection fails
    - Database size estimation fails
    """


class ProvisioningError(CloudwaysError):
    """Provisioning operation failures.

    Raised when:
    - Server or app creation request is rejected by the API
    - Invalid provisioning parameters (bad region, size, etc.)
    - Account quota exceeded
    - Server ID not found for app creation
    """


class BitbucketError(CloudwaysError):
    """Bitbucket API operation failures.

    Raised when:
    - Bitbucket credentials are missing (~/.bitbucket-credentials not found)
    - Bitbucket credentials are incomplete (missing required fields)
    - Bitbucket API returns an error response
    - Git remote URL cannot be parsed for workspace/repo detection
    """


class OperationTimeoutError(ProvisioningError):
    """Operation polling timeout.

    Raised when:
    - wait_for_operation() exceeds max_wait without the operation completing
    - Includes the operation_id for manual status checking
    """

    def __init__(self, operation_id: int | str, elapsed: float, max_wait: int) -> None:
        self.operation_id: int | str = operation_id
        self.elapsed = elapsed
        self.max_wait = max_wait
        super().__init__(
            f"Operation {operation_id} did not complete within {max_wait}s "
            f"(elapsed: {elapsed:.0f}s). Check status manually."
        )
