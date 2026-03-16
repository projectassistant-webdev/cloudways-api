"""Async Cloudways API v2 client with OAuth token caching and retry logic.

Uses httpx.AsyncClient for HTTP communication with connection pooling.
Handles authentication, token refresh, and transient error retries.
"""

import asyncio
import time
from typing import Any

import httpx

from cloudways_api.exceptions import (
    APIError,
    AuthenticationError,
    OperationTimeoutError,
    ProvisioningError,
    RateLimitError,
    ServerError,
)

_TOKEN_VALIDITY_SECONDS = 3000  # Refresh at 50 minutes (of 60-minute expiry)
_MAX_RETRIES = 3
_BASE_BACKOFF_DELAY = 1.0  # seconds
_DEFAULT_RATE_LIMIT_DELAY = 30  # seconds
_REQUEST_TIMEOUT = 30.0  # seconds


class CloudwaysClient:
    """Async client for the Cloudways API v2.

    Usage as an async context manager for proper resource cleanup::

        async with CloudwaysClient(email, api_key) as client:
            servers = await client.get_servers()
    """

    BASE_URL = "https://api.cloudways.com/api/v2"

    def __init__(
        self,
        email: str,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.email = email
        self.api_key = api_key
        self._token: str | None = None
        self._token_obtained_at: float | None = None

        client_kwargs: dict[str, Any] = {
            "timeout": _REQUEST_TIMEOUT,
            "headers": {"User-Agent": "cloudways-api-cli/0.1.0"},
            "base_url": self.BASE_URL,
        }
        if transport is not None:
            client_kwargs["transport"] = transport

        self._http_client = httpx.AsyncClient(**client_kwargs)

    async def __aenter__(self) -> "CloudwaysClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._http_client.aclose()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> str:
        """Obtain or return a cached OAuth bearer token.

        Returns the cached token if it was obtained less than
        3000 seconds ago. Otherwise requests a fresh token.

        Returns:
            The bearer token string.

        Raises:
            AuthenticationError: On invalid credentials (HTTP 401).
            APIError: On network or unexpected errors.
        """
        if self._token and self._token_obtained_at:
            elapsed = time.monotonic() - self._token_obtained_at
            if elapsed < _TOKEN_VALIDITY_SECONDS:
                return self._token

        return await self._request_token()

    async def _request_token(self) -> str:
        """POST to /oauth/access_token to obtain a new bearer token."""
        try:
            response = await self._http_client.post(
                "/oauth/access_token",
                data={
                    "email": self.email,
                    "api_key": self.api_key,
                    "grant_type": "password",
                },
            )
        except httpx.ConnectError as exc:
            raise APIError(
                "Could not connect to Cloudways API. Check your internet connection."
            ) from exc
        except httpx.HTTPError as exc:
            raise APIError(f"HTTP error during authentication: {exc}") from exc

        if response.status_code == 401:
            raise AuthenticationError(
                "Authentication failed. "
                "Check your email and API key in ~/.cloudways/accounts.yml."
            )

        if response.status_code != 200:
            raise APIError(
                f"Unexpected status {response.status_code} during authentication."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise APIError("Unexpected response format from Cloudways API.") from exc

        try:
            self._token = data["access_token"]
        except KeyError as exc:
            raise APIError("Unexpected response format from Cloudways API.") from exc

        self._token_obtained_at = time.monotonic()
        return self._token

    # ------------------------------------------------------------------
    # API Methods
    # ------------------------------------------------------------------

    async def get_servers(self) -> list[dict]:
        """Retrieve the list of all servers on the account.

        Returns:
            A list of server dicts (each containing nested ``apps``).
        """
        data = await self._api_request("GET", "/server")
        return data.get("servers", [])

    async def get_server_settings(self, server_id: int) -> dict:
        """Retrieve server settings including package versions.

        Args:
            server_id: Numeric server ID.

        Returns:
            The full settings response dict.
        """
        return await self._api_request(
            "GET", "/server/manage/settings", params={"server_id": server_id}
        )

    async def get_cloudflare_cdn(self, server_id: int, app_id: int) -> dict:
        """Get Cloudflare CDN configuration for an app.

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.

        Returns:
            The API response dict with CF CDN status and DNS records.
        """
        return await self._api_request(
            "GET",
            "/app/cloudflareCdn",
            params={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # Cloudflare Analytics
    # ------------------------------------------------------------------

    async def get_cloudflare_analytics(
        self, app_id: int, server_id: int, mins: int
    ) -> list[dict]:
        """Retrieve Cloudflare cache analytics for an application.

        Args:
            app_id: Numeric application ID (embedded in URL path).
            server_id: Numeric server ID (query parameter).
            mins: Time window in minutes (query parameter).

        Returns:
            List of analytics data dicts from data["data"].
        """
        data = await self._api_request(
            "GET",
            f"/app/cloudflare/{app_id}/analytics",
            params={"server_id": server_id, "mins": mins},
        )
        return data.get("data", [])

    async def get_cloudflare_security(
        self, app_id: int, server_id: int, mins: int
    ) -> list[dict]:
        """Retrieve Cloudflare security analytics for an application.

        Args:
            app_id: Numeric application ID (embedded in URL path).
            server_id: Numeric server ID (query parameter).
            mins: Time window in minutes (query parameter).

        Returns:
            List of security analytics data dicts from data["data"].
        """
        data = await self._api_request(
            "GET",
            f"/app/cloudflare/{app_id}/security",
            params={"server_id": server_id, "mins": mins},
        )
        return data.get("data", [])

    async def get_cloudflare_logpush_analytics(self, app_id: int) -> dict:
        """Retrieve Cloudflare Logpush analytics data for an application.

        Args:
            app_id: Numeric application ID (embedded in URL path).

        Returns:
            Full response dict with fields: app_id, cloudflare_zone_id,
            analytics, period, generated_at, message.
        """
        return await self._api_request(
            "GET",
            f"/app/cloudflare/{app_id}/logpush_analytics",
        )

    async def get_cloudflare_logpush_security(self, app_id: int) -> dict:
        """Retrieve Cloudflare Logpush security event data for an application.

        Args:
            app_id: Numeric application ID (embedded in URL path).

        Returns:
            Full response dict with fields: app_id, cloudflare_zone_id,
            security_events, summary, period, pagination, generated_at, message.
        """
        return await self._api_request(
            "GET",
            f"/app/cloudflare/{app_id}/logpush_security",
        )

    # ------------------------------------------------------------------
    # Metadata Methods (GET, no side effects)
    # ------------------------------------------------------------------

    async def get_provider_list(self) -> list[dict]:
        """Retrieve the list of available cloud providers.

        Returns:
            A list of provider dicts.
        """
        data = await self._api_request("GET", "/provider")
        return data.get("providers", [])

    async def get_region_list(self, provider: str) -> list[dict]:
        """Retrieve the list of available regions for a cloud provider.

        Args:
            provider: Cloud provider code (e.g., "do" for DigitalOcean).

        Returns:
            A list of region dicts.
        """
        data = await self._api_request("GET", "/region", params={"provider": provider})
        return data.get("regions", [])

    async def get_server_sizes(self, provider: str) -> list[dict]:
        """Retrieve the list of available server sizes for a cloud provider.

        Args:
            provider: Cloud provider code (e.g., "do" for DigitalOcean).

        Returns:
            A list of server size dicts.
        """
        data = await self._api_request(
            "GET", "/server_size", params={"provider": provider}
        )
        return data.get("sizes", [])

    async def get_app_types(self) -> list[dict]:
        """Retrieve the list of available application types.

        Returns:
            A list of application type dicts.
        """
        data = await self._api_request("GET", "/app_list")
        return data.get("app_list", [])

    # ------------------------------------------------------------------
    # Mutation Methods (POST/PUT, side effects)
    # ------------------------------------------------------------------

    async def create_server(
        self,
        *,
        cloud: str,
        region: str,
        instance_type: str,
        application: str,
        app_version: str,
        server_label: str,
        app_label: str,
        project_name: str,
    ) -> dict:
        """Create a new server on the specified cloud provider.

        Args:
            cloud: Cloud provider code (e.g., "do").
            region: Region code (e.g., "nyc3").
            instance_type: Server size (e.g., "2GB").
            application: Initial application type (e.g., "wordpress").
            app_version: Application version (e.g., "6.5").
            server_label: Human-readable server label.
            app_label: Human-readable application label.
            project_name: Project name for organization.

        Returns:
            API response dict containing server and operation details.

        Raises:
            ProvisioningError: On creation failure (4xx response).
        """
        try:
            response = await self._api_request(
                "POST",
                "/server",
                data={
                    "cloud": cloud,
                    "region": region,
                    "instance_type": instance_type,
                    "application": application,
                    "app_version": app_version,
                    "server_label": server_label,
                    "app_label": app_label,
                    "project_name": project_name,
                },
            )
        except APIError as exc:
            raise ProvisioningError(f"Server creation failed: {exc}") from exc
        return response

    async def create_app(
        self,
        *,
        server_id: int,
        application: str,
        app_version: str,
        app_label: str,
        project_name: str,
    ) -> dict:
        """Create a new application on an existing server.

        Args:
            server_id: Target server ID.
            application: Application type (e.g., "wordpress").
            app_version: Application version (e.g., "6.5").
            app_label: Human-readable application label.
            project_name: Project name for organization.

        Returns:
            API response dict containing app and operation details.

        Raises:
            ProvisioningError: On creation failure (4xx response).
        """
        try:
            response = await self._api_request(
                "POST",
                "/app",
                data={
                    "server_id": server_id,
                    "application": application,
                    "app_version": app_version,
                    "app_label": app_label,
                    "project_name": project_name,
                },
            )
        except APIError as exc:
            raise ProvisioningError(f"App creation failed: {exc}") from exc
        return response

    async def update_php_version(
        self,
        *,
        server_id: int,
        app_id: int | str,
        php_version: str,
    ) -> dict:
        """Update the PHP version for an application.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            php_version: Target PHP version (e.g., "8.2").

        Returns:
            API response dict.
        """
        return await self._api_request(
            "PUT",
            "/app/manage/fpm_setting",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "php_version": php_version,
            },
        )

    async def add_domain(
        self,
        *,
        server_id: int,
        app_id: int | str,
        domain: str,
    ) -> dict:
        """Add a domain/CNAME to an application.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            domain: Domain name to add.

        Returns:
            API response dict.
        """
        return await self._api_request(
            "POST",
            "/app/manage/cname",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "cname": domain,
            },
        )

    # ------------------------------------------------------------------
    # App Credentials (SSH/SFTP Users)
    # ------------------------------------------------------------------

    async def create_app_credential(
        self,
        server_id: int,
        app_id: int | str,
        username: str,
        password: str,
    ) -> dict:
        """Create an SSH/SFTP user on an application.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            username: Username for the new credential.
            password: Password for the new credential.

        Returns:
            API response dict containing the new credential details.
        """
        return await self._api_request(
            "POST",
            "/app/creds",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "username": username,
                "password": password,
            },
        )

    async def get_app_credentials(
        self,
        server_id: int,
        app_id: int | str,
    ) -> list[dict]:
        """List SSH/SFTP users for an application.

        Args:
            server_id: Server ID.
            app_id: Application ID.

        Returns:
            A list of credential dicts.
        """
        data = await self._api_request(
            "GET",
            "/app/creds",
            params={"server_id": server_id, "app_id": app_id},
        )
        return data.get("app_creds", [])

    async def delete_app_credential(
        self,
        server_id: int,
        app_id: int | str,
        app_cred_id: int,
    ) -> dict:
        """Delete an SSH/SFTP user.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            app_cred_id: Credential ID to delete.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "DELETE",
            f"/app/creds/{app_cred_id}",
            data={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    async def create_staging_app(
        self,
        *,
        server_id: int,
        app_id: int | str,
        app_label: str,
        project_name: str = "Default",
    ) -> dict:
        """Clone a staging app from an existing production application.

        Posts to POST /app/clone to create a staging clone.
        Response mirrors POST /app: {"app": {"id": ...}, "operation_id": ...}

        Args:
            server_id: Target server ID.
            app_id: Source (production) app ID to clone from.
            app_label: Human-readable label for the staging app.
            project_name: Project name for organization (optional,
                defaults to "Default").

        Returns:
            API response dict containing app and operation details.

        Raises:
            ProvisioningError: On creation failure (4xx response).
        """
        try:
            response = await self._api_request(
                "POST",
                "/app/clone",
                data={
                    "server_id": server_id,
                    "app_id": app_id,
                    "app_label": app_label,
                    "project_name": project_name,
                },
            )
        except APIError as exc:
            raise ProvisioningError(f"Staging app creation failed: {exc}") from exc
        return response

    # ------------------------------------------------------------------
    # Application Management
    # ------------------------------------------------------------------

    async def update_webroot(
        self,
        server_id: int,
        app_id: int | str,
        webroot: str,
    ) -> dict:
        """Update application webroot via POST /app/manage/webroot.

        Args:
            server_id: Numeric ID of the server.
            app_id: Numeric ID of the application.
            webroot: New webroot path (e.g., 'public_html/current/web').

        Returns:
            API response dict (typically empty on success, 200 status).
        """
        return await self._api_request(
            "POST",
            "/app/manage/webroot",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "webroot": webroot,
            },
        )

    async def reset_permissions(
        self,
        server_id: int,
        app_id: int | str,
    ) -> dict:
        """Reset file ownership to application user.

        Posts to POST /app/manage/reset_permissions?ownership=sys_user.
        The ownership query param goes in params=; body data has server_id
        and app_id.

        Args:
            server_id: Numeric ID of the server.
            app_id: Numeric ID of the application.

        Returns:
            API response dict (typically empty on success).
        """
        return await self._api_request(
            "POST",
            "/app/manage/reset_permissions",
            params={"ownership": "sys_user"},
            data={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # SSH Keys
    # ------------------------------------------------------------------

    async def add_ssh_key(
        self,
        server_id: int,
        app_creds_id: int,
        key_name: str,
        public_key: str,
    ) -> dict:
        """Add an SSH public key to a credential user.

        Args:
            server_id: Server ID.
            app_creds_id: Credential ID to attach the key to.
            key_name: Label for the SSH key.
            public_key: The SSH public key string.

        Returns:
            API response dict with SSH key details.
        """
        return await self._api_request(
            "POST",
            "/ssh_key",
            data={
                "server_id": server_id,
                "ssh_key_name": key_name,
                "ssh_key": public_key,
                "app_creds_id": app_creds_id,
            },
        )

    async def delete_ssh_key(
        self,
        server_id: int,
        ssh_key_id: int,
    ) -> dict:
        """Delete an SSH key.

        Args:
            server_id: Server ID.
            ssh_key_id: SSH key ID to delete.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "DELETE",
            f"/ssh_key/{ssh_key_id}",
            data={"server_id": server_id},
        )

    async def update_ssh_key(
        self,
        server_id: int,
        ssh_key_id: int,
        key_name: str,
    ) -> dict:
        """Rename an SSH key label.

        Args:
            server_id: Server ID.
            ssh_key_id: SSH key ID to rename.
            key_name: New label for the SSH key.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "PUT",
            f"/ssh_key/{ssh_key_id}",
            data={"server_id": server_id, "ssh_key_name": key_name},
        )

    # ------------------------------------------------------------------
    # Server Lifecycle
    # ------------------------------------------------------------------

    async def stop_server(self, server_id: int) -> dict:
        """Stop a running server.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with operation_id.
        """
        return await self._api_request(
            "POST",
            "/server/stop",
            data={"server_id": server_id},
        )

    async def start_server(self, server_id: int) -> dict:
        """Start a stopped server.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with operation_id.
        """
        return await self._api_request(
            "POST",
            "/server/start",
            data={"server_id": server_id},
        )

    async def restart_server(self, server_id: int) -> dict:
        """Restart a running server.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with operation_id.
        """
        return await self._api_request(
            "POST",
            "/server/restart",
            data={"server_id": server_id},
        )

    async def delete_server(self, server_id: int) -> dict:
        """Delete a server.

        NOTE: Server ID is passed as a path parameter only. No request body.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with operation_id.
        """
        return await self._api_request(
            "DELETE",
            f"/server/{server_id}",
        )

    async def update_server(self, server_id: int, label: str) -> dict:
        """Rename a server (update its label).

        Args:
            server_id: Server ID.
            label: New label for the server.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "PUT",
            f"/server/{server_id}",
            data={"label": label},
        )

    # ------------------------------------------------------------------
    # Security / IP Whitelist
    # ------------------------------------------------------------------

    async def get_whitelisted_ips(self, server_id: int) -> list[str]:
        """Retrieve whitelisted IPs for SSH/SFTP access.

        Args:
            server_id: Server ID.

        Returns:
            List of whitelisted IP strings.
        """
        data = await self._api_request(
            "GET",
            "/security/whitelisted",
            params={"server_id": server_id},
        )
        return data.get("ip_list", [])

    async def get_whitelisted_ips_mysql(self, server_id: int) -> list[str]:
        """Retrieve whitelisted IPs for MySQL access.

        Args:
            server_id: Server ID.

        Returns:
            List of whitelisted IP strings.
        """
        data = await self._api_request(
            "GET",
            "/security/whitelistedIpsMysql",
            params={"server_id": server_id},
        )
        return data.get("ip_list", [])

    async def update_whitelisted_ips(
        self,
        server_id: int,
        ip_list: list[str],
        tab: str = "sftp",
        ip_policy: str = "allow_all",
    ) -> dict:
        """Replace the entire IP whitelist for SSH/SFTP or MySQL access.

        NOTE: This endpoint REPLACES the entire whitelist. Pass the complete
        desired list including all IPs that should remain whitelisted.

        Args:
            server_id: Server ID.
            ip_list: Complete new whitelist (all IPs after the update).
            tab: Whitelist type — "sftp" or "mysql".
            ip_policy: Policy — "allow_all" or "block_all". Default "allow_all".

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "POST",
            "/security/whitelisted",
            data={
                "server_id": server_id,
                "tab": tab,
                "ip": ip_list,
                "type": tab,
                "ipPolicy": ip_policy,
            },
        )

    async def check_ip_blacklisted(self, server_id: int, ip: str) -> bool:
        """Check if an IP is blacklisted on the server.

        Args:
            server_id: Server ID.
            ip: IP address to check.

        Returns:
            True if the IP is blacklisted, False otherwise.
        """
        data = await self._api_request(
            "GET",
            "/security/isBlacklisted",
            params={"server_id": server_id, "ip": ip},
        )
        return bool(data.get("ip_list", False))

    async def whitelist_siab(self, server_id: int, ip: str) -> dict:
        """Whitelist an IP for Web SSH (Shell-in-a-Box) access.

        Args:
            server_id: Server ID.
            ip: IP address to whitelist.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "POST",
            "/security/siab",
            data={"server_id": server_id, "ip": ip},
        )

    async def whitelist_adminer(self, server_id: int, ip: str) -> dict:
        """Whitelist an IP for Adminer (database manager) access.

        Args:
            server_id: Server ID.
            ip: IP address to whitelist.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "POST",
            "/security/adminer",
            data={"server_id": server_id, "ip": ip},
        )

    # ------------------------------------------------------------------
    # SSL Certificate Management
    # ------------------------------------------------------------------

    async def install_lets_encrypt(
        self,
        server_id: int,
        app_id: int,
        ssl_email: str,
        ssl_domains: list[str],
        wild_card: bool = False,
    ) -> dict:
        """Install a Let's Encrypt SSL certificate.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            ssl_email: Email address for the SSL certificate.
            ssl_domains: List of domains for the certificate.
            wild_card: Whether to install a wildcard certificate.

        Returns:
            Dict with ``operation_id``.
        """
        return await self._api_request(
            "POST",
            "/security/lets_encrypt_install",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ssl_email": ssl_email,
                "ssl_domains": ssl_domains,
                "wild_card": wild_card,
            },
        )

    async def create_wildcard_dns(
        self,
        server_id: int,
        app_id: int,
        ssl_email: str,
        ssl_domains: list[str],
    ) -> dict:
        """Create DNS records for wildcard SSL verification (step 1).

        Args:
            server_id: Server ID.
            app_id: Application ID.
            ssl_email: Email address for the SSL certificate.
            ssl_domains: List of domains for the certificate.

        Returns:
            Dict with ``wildcard_ssl`` containing DNS record info.
        """
        return await self._api_request(
            "POST",
            "/security/createDNS",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ssl_email": ssl_email,
                "wild_card": True,
                "ssl_domains": ssl_domains,
            },
        )

    async def verify_wildcard_dns(
        self,
        server_id: int,
        app_id: int,
        ssl_email: str,
        ssl_domains: list[str],
    ) -> dict:
        """Verify DNS records for wildcard SSL (step 2).

        Args:
            server_id: Server ID.
            app_id: Application ID.
            ssl_email: Email address for the SSL certificate.
            ssl_domains: List of domains for the certificate.

        Returns:
            Dict with ``wildcard_ssl`` containing verification status.
        """
        return await self._api_request(
            "POST",
            "/security/verifyDNS",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ssl_email": ssl_email,
                "wild_card": True,
                "ssl_domains": ssl_domains,
            },
        )

    async def renew_lets_encrypt(
        self,
        server_id: int,
        app_id: int,
        wild_card: bool = False,
        ssl_email: str | None = None,
        domain: str | None = None,
    ) -> dict:
        """Manually renew a Let's Encrypt SSL certificate.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            wild_card: Whether this is a wildcard certificate.
            ssl_email: Email address (required for wildcard renewal).
            domain: Domain name (optional for wildcard renewal).

        Returns:
            Dict with ``operation_id``.
        """
        payload: dict = {
            "server_id": server_id,
            "app_id": app_id,
            "wild_card": wild_card,
        }
        if ssl_email is not None:
            payload["ssl_email"] = ssl_email
        if domain is not None:
            payload["domain"] = domain
        return await self._api_request(
            "POST",
            "/security/lets_encrypt_manual_renew",
            data=payload,
        )

    async def set_lets_encrypt_auto(
        self,
        server_id: int,
        app_id: int,
        auto: bool,
    ) -> dict:
        """Enable or disable Let's Encrypt auto-renewal.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            auto: True to enable, False to disable auto-renewal.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "POST",
            "/security/lets_encrypt_auto",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "auto": auto,
            },
        )

    async def revoke_lets_encrypt(
        self,
        server_id: int,
        app_id: int,
        ssl_domain: str,
        wild_card: bool = False,
    ) -> dict:
        """Revoke a Let's Encrypt SSL certificate.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            ssl_domain: Domain of the certificate to revoke.
            wild_card: Whether this is a wildcard certificate.

        Returns:
            Dict with ``operation_id``.
        """
        return await self._api_request(
            "POST",
            "/security/lets_encrypt_revoke",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ssl_domain": ssl_domain,
                "wild_card": wild_card,
            },
        )

    async def install_custom_ssl(
        self,
        server_id: int,
        app_id: int,
        ssl_crt: str,
        ssl_key: str,
        password: str | None = None,
    ) -> dict:
        """Install a custom SSL certificate.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            ssl_crt: PEM-encoded certificate content.
            ssl_key: PEM-encoded private key content.
            password: Optional certificate password.

        Returns:
            Empty dict on success.
        """
        payload: dict = {
            "server_id": server_id,
            "app_id": app_id,
            "ssl_crt": ssl_crt,
            "ssl_key": ssl_key,
        }
        if password is not None:
            payload["password"] = password
        return await self._api_request(
            "POST",
            "/security/ownSSL",
            data=payload,
        )

    async def remove_custom_ssl(
        self,
        server_id: int,
        app_id: int,
    ) -> dict:
        """Remove a custom SSL certificate.

        Args:
            server_id: Server ID.
            app_id: Application ID.

        Returns:
            Dict with ``operation_id``.
        """
        return await self._api_request(
            "DELETE",
            "/security/removeCustomSSL",
            data={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # Deploy Keys (Server Keypair)
    # ------------------------------------------------------------------

    async def generate_deploy_key(
        self,
        server_id: int,
        app_id: int | str,
    ) -> dict:
        """Generate an SSH keypair on the server for git operations.

        Args:
            server_id: Server ID.
            app_id: Application ID.

        Returns:
            API response dict.
        """
        return await self._api_request(
            "POST",
            "/git/generateKey",
            data={"server_id": server_id, "app_id": app_id},
        )

    async def get_deploy_key(
        self,
        server_id: int,
        app_id: int | str,
    ) -> dict:
        """Get the server's public deploy key.

        Args:
            server_id: Server ID.
            app_id: Application ID.

        Returns:
            API response dict with the public key.
        """
        return await self._api_request(
            "GET",
            "/git/key",
            params={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # Git Deployment Operations
    # ------------------------------------------------------------------

    async def git_clone(
        self,
        server_id: int,
        app_id: int | str,
        git_url: str,
        branch_name: str,
    ) -> dict:
        """Clone a git repository to a Cloudways application.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            git_url: URL of the git repository to clone.
            branch_name: Branch name to clone.

        Returns:
            API response dict containing operation_id.
        """
        return await self._api_request(
            "POST",
            "/git/clone",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "git_url": git_url,
                "branch_name": branch_name,
            },
        )

    async def git_pull(
        self,
        server_id: int,
        app_id: int | str,
        branch_name: str,
    ) -> dict:
        """Pull latest changes from a git repository.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            branch_name: Branch name to pull.

        Returns:
            API response dict containing operation_id.
        """
        return await self._api_request(
            "POST",
            "/git/pull",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "branch_name": branch_name,
            },
        )

    async def git_branch_names(
        self,
        server_id: int,
        app_id: int | str,
        git_url: str,
    ) -> dict:
        """List available branches for a git repository.

        Args:
            server_id: Server ID.
            app_id: Application ID.
            git_url: URL of the git repository.

        Returns:
            API response dict with "branches" key containing list of
            branch name strings.
        """
        return await self._api_request(
            "GET",
            "/git/branchNames",
            params={
                "server_id": server_id,
                "app_id": app_id,
                "git_url": git_url,
            },
        )

    async def git_history(
        self,
        server_id: int,
        app_id: int | str,
    ) -> dict:
        """Retrieve git deployment history for an application.

        Args:
            server_id: Server ID.
            app_id: Application ID.

        Returns:
            API response dict with "logs" key containing list of
            deployment records (each with "branch_name", "datetime"
            fields).
        """
        return await self._api_request(
            "GET",
            "/git/history",
            params={
                "server_id": server_id,
                "app_id": app_id,
            },
        )

    # ------------------------------------------------------------------
    # Backup and Disk
    # ------------------------------------------------------------------

    async def trigger_backup(self, server_id: int) -> dict:
        """Trigger an on-demand server backup.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with ``operation_id``.
        """
        return await self._api_request(
            "POST",
            "/server/manage/backup",
            data={"server_id": server_id},
        )

    async def update_backup_settings(
        self,
        server_id: int,
        *,
        local_backups: bool,
        backup_frequency: str | None = None,
        backup_retention: int | None = None,
        backup_time: str | None = None,
    ) -> dict:
        """Update automated backup settings for a server.

        Only ``server_id`` and ``local_backups`` are always sent; the
        remaining fields are included only when not ``None``.

        Args:
            server_id: Server ID.
            local_backups: Enable or disable local backups.
            backup_frequency: Backup frequency in hours (e.g. ``"24"``).
            backup_retention: Number of backups to retain.
            backup_time: Time of day for backup (e.g. ``"00:10"``).

        Returns:
            Empty dict on success.
        """
        payload: dict = {
            "server_id": server_id,
            "local_backups": "true" if local_backups else "false",
        }
        if backup_frequency is not None:
            payload["backup_frequency"] = backup_frequency
        if backup_retention is not None:
            payload["backup_retention"] = backup_retention
        if backup_time is not None:
            payload["backup_time"] = backup_time
        return await self._api_request(
            "POST",
            "/server/manage/backupSettings",
            data=payload,
        )

    async def get_disk_settings(self, server_id: int) -> dict:
        """Get disk cleanup settings for a server.

        Args:
            server_id: Server ID.

        Returns:
            API response dict with ``settings`` key.
        """
        return await self._api_request(
            "GET",
            "/server/disk",
            params={"server_id": server_id},
        )

    async def update_disk_settings(
        self,
        server_id: int,
        *,
        automate_cleanup: str,
        remove_app_tmp: str,
        remove_app_private_html: str,
        rotate_system_log: str,
        rotate_app_log: str,
        remove_app_local_backup: str,
    ) -> dict:
        """Update disk cleanup settings for a server.

        The server ID is sent in the URL path; all six setting fields
        are required in the request body.

        Args:
            server_id: Server ID.
            automate_cleanup: ``"enable"`` or ``"disable"``.
            remove_app_tmp: ``"yes"`` or ``"no"``.
            remove_app_private_html: ``"yes"`` or ``"no"``.
            rotate_system_log: ``"yes"`` or ``"no"``.
            rotate_app_log: ``"yes"`` or ``"no"``.
            remove_app_local_backup: ``"yes"`` or ``"no"``.

        Returns:
            Empty dict on success.
        """
        return await self._api_request(
            "PUT",
            f"/server/disk/{server_id}",
            data={
                "automate_cleanup": automate_cleanup,
                "remove_app_tmp": remove_app_tmp,
                "remove_app_private_html": remove_app_private_html,
                "rotate_system_log": rotate_system_log,
                "rotate_app_log": rotate_app_log,
                "remove_app_local_backup": remove_app_local_backup,
            },
        )

    async def trigger_disk_cleanup(
        self,
        server_id: int,
        *,
        remove_app_tmp: str,
        remove_app_private_html: str,
        rotate_system_log: str,
        rotate_app_log: str,
        remove_app_local_backup: str,
    ) -> dict:
        """Trigger a one-time disk cleanup operation.

        Args:
            server_id: Server ID.
            remove_app_tmp: ``"yes"`` or ``"no"``.
            remove_app_private_html: ``"yes"`` or ``"no"``.
            rotate_system_log: ``"yes"`` or ``"no"``.
            rotate_app_log: ``"yes"`` or ``"no"``.
            remove_app_local_backup: ``"yes"`` or ``"no"``.

        Returns:
            API response dict with ``operation_id``.
        """
        return await self._api_request(
            "POST",
            "/server/disk/cleanup",
            data={
                "server_id": server_id,
                "remove_app_tmp": remove_app_tmp,
                "remove_app_private_html": remove_app_private_html,
                "rotate_system_log": rotate_system_log,
                "rotate_app_log": rotate_app_log,
                "remove_app_local_backup": remove_app_local_backup,
            },
        )

    # ------------------------------------------------------------------
    # CloudwaysBot Alerts
    # ------------------------------------------------------------------

    async def get_alerts(self) -> list[dict]:
        """Retrieve all CloudwaysBot alerts for the account.

        Returns:
            List of alert dicts from the account.
        """
        data = await self._api_request("GET", "/alerts/")
        return data.get("alerts", [])

    async def get_alerts_page(self, last_id: int) -> list[dict]:
        """Retrieve a page of alerts older than the given alert ID.

        The Cloudways API uses reverse-chronological cursor pagination.
        The last_id parameter is the ID of the last (oldest) alert seen
        in the previous page -- it is a cursor, not a page number.

        Args:
            last_id: Cursor -- the alert ID of the last alert in the
                previous page.

        Returns:
            List of up to 20 alert dicts older than last_id.
        """
        data = await self._api_request("GET", f"/alerts/{last_id}")
        return data.get("alerts", [])

    async def mark_alert_read(self, alert_id: int) -> dict:
        """Mark a single alert as read.

        Args:
            alert_id: ID of the alert to mark as read.

        Returns:
            Empty dict on success (API returns 200 with empty body).
        """
        return await self._api_request("POST", f"/alert/markAsRead/{alert_id}")

    async def mark_all_alerts_read(self) -> dict:
        """Mark all account alerts as read.

        Returns:
            Empty dict on success (API returns 200 with empty body).
        """
        return await self._api_request("POST", "/alert/markAllRead/")

    # ------------------------------------------------------------------
    # Integration (Channel) Management
    # ------------------------------------------------------------------

    async def get_integrations(self) -> list[dict]:
        """Retrieve all configured alert notification channels.

        Returns:
            List of integration (channel) dicts.
        """
        data = await self._api_request("GET", "/integrations")
        return data.get("integrations", [])

    async def get_integration_channels(self) -> dict:
        """Retrieve available alert channel types and event types.

        Returns:
            Full response dict containing both 'channels' and 'events' keys.
        """
        return await self._api_request("GET", "/integrations/create")

    async def create_integration(
        self,
        *,
        name: str,
        channel: int,
        events: list[int],
        to: str | None = None,
        url: str | None = None,
        is_active: bool = True,
    ) -> dict:
        """Create a new alert notification channel.

        Args:
            name: Human-readable label for the channel.
            channel: Channel type ID (e.g., 2 for email, 3 for Slack).
            events: List of event type IDs to subscribe to.
            to: Email address (for email channels); None for other types.
            url: Webhook URL (for webhook channels); None for other types.
            is_active: Whether the channel is active. Defaults to True.

        Returns:
            The created integration dict from data["integration"].
        """
        payload: dict = {
            "name": name,
            "channel": channel,
            "events": events,
            "is_active": is_active,
        }
        if to is not None:
            payload["to"] = to
        if url is not None:
            payload["url"] = url
        data = await self._api_request("POST", "/integrations", data=payload)
        return data.get("integration", data)

    async def update_integration(
        self,
        channel_id: int,
        *,
        name: str,
        channel: int,
        events: list[int],
        to: str | None = None,
        url: str | None = None,
        is_active: bool = True,
    ) -> dict:
        """Update an existing alert notification channel.

        Args:
            channel_id: ID of the integration to update.
            name: New label for the channel.
            channel: Channel type ID.
            events: New list of event type IDs.
            to: Email address; None for non-email channels.
            url: Webhook URL; None for non-webhook channels.
            is_active: Whether the channel is active.

        Returns:
            The updated integration dict from data["integration"].
        """
        payload: dict = {
            "name": name,
            "channel": channel,
            "events": events,
            "is_active": is_active,
        }
        if to is not None:
            payload["to"] = to
        if url is not None:
            payload["url"] = url
        data = await self._api_request(
            "PUT", f"/integrations/{channel_id}", data=payload
        )
        return data.get("integration", data)

    async def delete_integration(self, channel_id: int) -> dict:
        """Delete an alert notification channel.

        Args:
            channel_id: ID of the integration to delete.

        Returns:
            Empty dict on success.
        """
        return await self._api_request("DELETE", f"/integrations/{channel_id}")

    # ------------------------------------------------------------------
    # Copilot Plans & Billing
    # ------------------------------------------------------------------

    async def get_copilot_plans(self) -> dict:
        """Retrieve available Copilot subscription plans.

        Returns:
            Full response dict containing plan data, previous plans,
            and pending downgrade requests.
        """
        return await self._api_request("GET", "/copilot/plans")

    async def get_copilot_status(self) -> dict:
        """Retrieve current Copilot subscription status.

        Returns:
            Full response dict containing plan name, status, and expiry.
        """
        return await self._api_request("GET", "/copilot/plans/status")

    async def subscribe_copilot_plan(self, plan_id: int) -> dict:
        """Subscribe to a Copilot plan.

        Args:
            plan_id: ID of the plan to subscribe to.

        Returns:
            Full response dict from the subscription operation.
        """
        return await self._api_request(
            "POST",
            "/copilot/plans/subscribe",
            data={"plan_id": plan_id},
        )

    async def cancel_copilot_plan(self) -> dict:
        """Cancel the current Copilot subscription.

        Returns:
            Full response dict from the cancellation operation.
        """
        return await self._api_request("DELETE", "/copilot/plans/subscribe")

    async def change_copilot_plan(
        self,
        *,
        plan_id: int,
        touchpoint: str | None = None,
    ) -> dict:
        """Change the current Copilot subscription plan.

        Args:
            plan_id: ID of the new plan.
            touchpoint: Optional touchpoint string for analytics tracking.

        Returns:
            Full response dict from the plan change operation.
        """
        payload: dict = {"plan_id": plan_id}
        if touchpoint is not None:
            payload["touchpoint"] = touchpoint
        return await self._api_request("POST", "/copilot/plans/change", data=payload)

    async def get_copilot_billing(self, billing_cycle: str | None = None) -> dict:
        """Retrieve real-time Copilot billing data.

        Args:
            billing_cycle: Optional billing cycle in YYYY-MM format
                (e.g., "2026-01"). When None, current cycle is used.

        Returns:
            Full response dict containing billing data.
        """
        params: dict | None = None
        if billing_cycle is not None:
            params = {"billing_cycle": billing_cycle}
        return await self._api_request(
            "GET",
            "/copilot/billing/real-time",
            params=params,
        )

    # ------------------------------------------------------------------
    # Copilot Server Settings & Insights
    # ------------------------------------------------------------------

    async def get_copilot_server_settings(self) -> dict:
        """Retrieve Copilot server settings.

        Returns:
            Full response dict containing per-server insights settings.
        """
        return await self._api_request("GET", "/copilot/server-settings")

    async def update_copilot_server_settings(
        self,
        *,
        server_id: int,
        insights_enabled: bool,
    ) -> dict:
        """Update Copilot server settings (enable/disable insights).

        Args:
            server_id: ID of the server to update.
            insights_enabled: Whether to enable insights for the server.

        Returns:
            Full response dict from the update operation.
        """
        return await self._api_request(
            "POST",
            "/copilot/server-settings",
            data={"server_id": server_id, "insights_enabled": insights_enabled},
        )

    async def get_insights_summary(self) -> dict:
        """Retrieve Copilot Insights summary.

        Returns:
            Full response dict containing aggregated insight counts.
        """
        return await self._api_request("GET", "/insights/summary")

    async def get_insights(self) -> dict:
        """Retrieve all Copilot Insights.

        Returns:
            Full response dict containing insights list and pagination.
        """
        return await self._api_request("GET", "/insights")

    async def get_insight(self, alert_id: int) -> dict:
        """Retrieve detail for a specific Copilot Insight.

        Args:
            alert_id: Numeric ID of the insight alert.

        Returns:
            Full response dict containing insight detail fields.
        """
        return await self._api_request("GET", f"/insights/{alert_id}")

    # ------------------------------------------------------------------
    # SafeUpdate Management
    # ------------------------------------------------------------------

    async def get_safeupdates_available(
        self, *, server_id: int, app_id: int
    ) -> dict:
        """Check available SafeUpdates for a server/app combination.

        Args:
            server_id: ID of the server.
            app_id: ID of the application.

        Returns:
            Full response dict containing available update info.
        """
        return await self._api_request(
            "GET",
            "/app/safeupdates",
            params={"server_id": server_id, "app_id": app_id},
        )

    async def list_safeupdates_apps(self, *, server_id: int) -> dict:
        """List all apps with SafeUpdate information for a server.

        Args:
            server_id: ID of the server.

        Returns:
            Full response dict containing app SafeUpdate info list.
        """
        return await self._api_request(
            "GET",
            "/app/safeupdates/list",
            params={"server_id": server_id},
        )

    async def get_safeupdate_status(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get SafeUpdate enabled status for a specific app.

        Args:
            app_id: ID of the application (path parameter).
            server_id: ID of the server (query parameter).

        Returns:
            Full response dict containing SafeUpdate status.
        """
        return await self._api_request(
            "GET",
            f"/app/safeupdates/{app_id}/status",
            params={"server_id": server_id},
        )

    async def set_safeupdate_status(
        self, *, server_id: int, app_id: int, status: int
    ) -> dict:
        """Enable or disable SafeUpdate for an app.

        Args:
            server_id: ID of the server.
            app_id: ID of the application.
            status: 1 to enable SafeUpdate, 0 to disable.

        Returns:
            Full response dict from the status update operation.
        """
        return await self._api_request(
            "POST",
            "/app/safeupdates/status",
            data={"server_id": server_id, "app_id": app_id, "status": status},
        )

    async def get_safeupdate_settings(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get SafeUpdate schedule settings for an app.

        Args:
            app_id: ID of the application (path parameter).
            server_id: ID of the server (query parameter).

        Returns:
            Full response dict containing day_of_week and time_slot settings.
        """
        return await self._api_request(
            "GET",
            f"/app/safeupdates/{app_id}/settings",
            params={"server_id": server_id},
        )

    async def update_safeupdate_settings(
        self,
        *,
        server_id: int,
        app_id: int,
        day_of_week: str,
        time_slot: str,
    ) -> dict:
        """Configure SafeUpdate schedule settings for an app.

        Args:
            server_id: ID of the server.
            app_id: ID of the application.
            day_of_week: Day of the week for updates (e.g., "monday").
            time_slot: Time slot for updates (e.g., "02:00").

        Returns:
            Full response dict from the settings update operation.
        """
        return await self._api_request(
            "POST",
            "/app/safeupdates/settings",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "day_of_week": day_of_week,
                "time_slot": time_slot,
            },
        )

    async def get_safeupdate_schedule(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get queued/scheduled SafeUpdates for an app.

        Args:
            app_id: ID of the application (path parameter).
            server_id: ID of the server (query parameter).

        Returns:
            Full response dict containing scheduled update info.
        """
        return await self._api_request(
            "GET",
            f"/app/safeupdates/{app_id}/schedule",
            params={"server_id": server_id},
        )

    async def get_safeupdate_history(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get SafeUpdate history for an app.

        Args:
            app_id: ID of the application (path parameter).
            server_id: ID of the server (query parameter).

        Returns:
            Full response dict containing update history records.
        """
        return await self._api_request(
            "GET",
            f"/app/safeupdates/{app_id}/history",
            params={"server_id": server_id},
        )

    async def trigger_safeupdate(
        self,
        app_id: int,
        *,
        server_id: int,
        core: bool = False,
        plugins: list[str] | None = None,
        themes: list[str] | None = None,
    ) -> dict:
        """Trigger an on-demand SafeUpdate for an app.

        Args:
            app_id: ID of the application (path parameter).
            server_id: ID of the server.
            core: Whether to update WordPress core.
            plugins: List of plugin slugs to update (or None/empty to skip plugins).
            themes: List of theme slugs to update (or None/empty to skip themes).

        Returns:
            Full response dict from the trigger operation.
        """
        payload: dict = {"server_id": server_id}
        if core:
            payload["core"] = 1
        if plugins:
            payload["plugins"] = plugins
        if themes:
            payload["themes"] = themes
        return await self._api_request(
            "PUT", f"/app/safeupdates/{app_id}", data=payload
        )

    # ------------------------------------------------------------------
    # Team Members
    # ------------------------------------------------------------------

    async def get_members(self) -> dict:
        """List all team members for the account.

        Returns:
            Full response dict. Access via result["contents"]["members"].values()
            to iterate team member objects.
        """
        return await self._api_request("GET", "/member")

    async def add_member(self, *, name: str, email: str, role: str = "") -> dict:
        """Add a new team member to the account.

        Args:
            name: Display name for the new member.
            email: Email address for the new member (required by the API).
            role: Optional role string (e.g., "Project Manager").

        Returns:
            Full response dict from the add operation.

        Note:
            The Cloudways API docs describe the request body as "string" without
            field-level documentation. Fields are inferred from the GET response schema.
            If the API rejects these field names, update the data= dict accordingly.
        """
        body: dict = {"name": name, "email": email}
        if role:
            body["role"] = role
        return await self._api_request("POST", "/member", data=body)

    async def update_member(
        self, member_id: int, *, name: str = "", role: str = ""
    ) -> dict:
        """Update an existing team member.

        Args:
            member_id: Integer ID of the member (path parameter).
            name: Optional new display name.
            role: Optional new role string.

        Returns:
            Full response dict from the update operation.
        """
        body: dict = {}
        if name:
            body["name"] = name
        if role:
            body["role"] = role
        return await self._api_request("PUT", f"/member/{member_id}", data=body)

    async def delete_member(self, member_id: int) -> dict:
        """Remove a team member from the account.

        Args:
            member_id: Integer ID of the member to remove (path parameter).

        Returns:
            Full response dict from the delete operation (typically {"contents": []}).

        Note:
            The Cloudways API requires ``id`` (the member_id integer) in the request body
            as form-encoded data, in addition to the path parameter. Both are sent.
        """
        return await self._api_request(
            "DELETE", f"/member/{member_id}", data={"id": member_id}
        )

    # ------------------------------------------------------------------
    # Monitoring and Analytics
    # ------------------------------------------------------------------

    async def get_server_monitor_summary(
        self, server_id: int, summary_type: str
    ) -> dict:
        """Get bandwidth or disk summary for a server.

        Args:
            server_id: Numeric server ID.
            summary_type: Summary type — "bandwidth" or "disk".

        Returns:
            Full response dict containing the summary data.
        """
        return await self._api_request(
            "GET",
            "/server/monitor/summary",
            params={"server_id": server_id, "type": summary_type},
        )

    async def get_server_usage(self, server_id: int) -> dict:
        """Get server usage analytics (task-based).

        Args:
            server_id: Numeric server ID.

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        return await self._api_request(
            "GET",
            "/server/analytics/serverUsage",
            params={"server_id": server_id},
        )

    async def get_server_monitor_detail(
        self,
        server_id: int,
        target: str,
        duration: str,
        storage: bool,
        timezone: str,
        output_format: str | None = None,
    ) -> dict:
        """Get server monitor detail graph (task-based).

        Args:
            server_id: Numeric server ID.
            target: Monitor target string (e.g., "cpu", "mem").
            duration: Time window — "15m", "30m", "1h", or "1d".
            storage: Whether to include storage data.
            timezone: Timezone string (e.g., "UTC").
            output_format: Optional output format — "json" or "svg".

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        params: dict = {
            "server_id": server_id,
            "target": target,
            "duration": duration,
            "storage": storage,
            "timezone": timezone,
        }
        if output_format is not None:
            params["output_format"] = output_format
        return await self._api_request(
            "GET", "/server/monitor/detail", params=params
        )

    async def get_app_monitor_summary(
        self, server_id: int, app_id: int, summary_type: str
    ) -> dict:
        """Get bandwidth or database summary for an app.

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.
            summary_type: Summary type — "bw" (bandwidth) or "db" (database).

        Returns:
            Full response dict containing the summary data.
        """
        return await self._api_request(
            "GET",
            "/app/monitor/summary",
            params={"server_id": server_id, "app_id": app_id, "type": summary_type},
        )

    async def get_app_traffic_analytics(
        self, server_id: int, app_id: int, duration: str, resource: str
    ) -> dict:
        """Get app traffic analytics (task-based).

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.
            duration: Time window — "15m", "30m", "1h", or "1d".
            resource: Resource type — "top_ips", "top_bots",
                "top_urls", or "top_statuses".

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        return await self._api_request(
            "GET",
            "/app/analytics/traffic",
            params={
                "server_id": server_id,
                "app_id": app_id,
                "duration": duration,
                "resource": resource,
            },
        )

    async def get_app_traffic_details(
        self,
        server_id: int,
        app_id: int,
        from_dt: str,
        until_dt: str,
        resource: str,
        resource_list: list[str] | None = None,
    ) -> dict:
        """Get detailed traffic analytics for a date range (task-based).

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.
            from_dt: Start datetime string in "DD/MM/YYYY HH:MM" format.
                NOTE: Python param is ``from_dt`` but sent as ``"from"``
                in body.
            until_dt: End datetime string in "DD/MM/YYYY HH:MM" format.
                NOTE: Python param is ``until_dt`` but sent as ``"until"``
                in body.
            resource: Resource type for traffic details.
            resource_list: Optional list of specific resources to filter.

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        data: dict = {
            "server_id": server_id,
            "app_id": app_id,
            "from": from_dt,
            "until": until_dt,
            "resource": resource,
        }
        if resource_list:
            data["resource_list"] = resource_list
        return await self._api_request(
            "POST", "/app/analytics/trafficDetails", data=data
        )

    async def get_app_php_analytics(
        self, server_id: int, app_id: int, duration: str, resource: str
    ) -> dict:
        """Get PHP-FPM analytics for an app (task-based).

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.
            duration: Time window -- "15m", "30m", "1h", or "1d".
            resource: PHP resource type -- "url_durations", "processes",
                or "slow_pages".

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        return await self._api_request(
            "GET",
            "/app/analytics/php",
            params={
                "server_id": server_id,
                "app_id": app_id,
                "duration": duration,
                "resource": resource,
            },
        )

    async def get_app_mysql_analytics(
        self, server_id: int, app_id: int, duration: str, resource: str
    ) -> dict:
        """Get MySQL analytics for an app (task-based).

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.
            duration: Time window -- "15m", "30m", "1h", or "1d".
            resource: MySQL resource type -- "running_queries" or
                "slow_queries".

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        return await self._api_request(
            "GET",
            "/app/analytics/mysql",
            params={
                "server_id": server_id,
                "app_id": app_id,
                "duration": duration,
                "resource": resource,
            },
        )

    async def get_app_cron_analytics(self, server_id: int, app_id: int) -> dict:
        """Get cron analytics for an app (task-based).

        Args:
            server_id: Numeric server ID.
            app_id: Numeric application ID.

        Returns:
            Task envelope dict containing {"status": True, "task_id": "<uuid>"}.
        """
        return await self._api_request(
            "GET",
            "/app/analytics/cron",
            params={"server_id": server_id, "app_id": app_id},
        )

    # ------------------------------------------------------------------
    # App Security Suite
    # ------------------------------------------------------------------

    async def get_app_security_status(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get the Imunify360 security status for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Security status dict with activation state and plan info.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/status",
            params={"server_id": server_id},
        )

    async def list_security_scans(
        self,
        app_id: int,
        *,
        server_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """List security scans for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            offset: Pagination offset (default ``0``).
            limit: Page size (default ``20``).

        Returns:
            Dict with scan list and pagination info.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/scans",
            params={
                "server_id": server_id,
                "offset": offset,
                "limit": limit,
            },
        )

    async def initiate_security_scan(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Initiate an Imunify360 security scan for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Response dict which may contain a ``task_id`` for polling.
        """
        return await self._api_request(
            "POST",
            f"/app/security/{app_id}/scans",
            data={"server_id": server_id, "app_id": app_id},
        )

    async def get_security_scan_status(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get the current scan status for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Scan status dict with progress information.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/scans/status",
            params={"server_id": server_id},
        )

    async def get_security_scan_detail(
        self, app_id: int, scan_id: int, *, server_id: int
    ) -> dict:
        """Get detailed results for a specific scan.

        Args:
            app_id: Numeric application ID.
            scan_id: Numeric scan ID.
            server_id: Numeric server ID.

        Returns:
            Scan detail dict with findings and status.

        Raises:
            APIError: If the scan is not found (404).
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/scans/{scan_id}",
            params={"server_id": server_id},
        )

    async def get_security_events(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get security events for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Events dict with security event list.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/events",
            params={"server_id": server_id},
        )

    async def get_security_incidents(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get security incidents for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Incidents dict with security incident list.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/incidents",
            params={"server_id": server_id},
        )

    async def list_security_files(
        self,
        app_id: int,
        *,
        server_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """List quarantined files for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            offset: Pagination offset (default ``0``).
            limit: Page size (default ``20``).

        Returns:
            Dict with quarantined file list and pagination info.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/files",
            params={
                "server_id": server_id,
                "offset": offset,
                "limit": limit,
            },
        )

    async def restore_security_files(
        self, app_id: int, *, server_id: int, db: str, files: str
    ) -> dict:
        """Restore quarantined files for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            db: Database identifier.
            files: Comma-separated list of files to restore.

        Returns:
            Response dict with restore status.
        """
        return await self._api_request(
            "POST",
            f"/app/security/{app_id}/files/restore",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "db": db,
                "files": files,
            },
        )

    async def get_cleaned_diff(
        self, app_id: int, *, server_id: int
    ) -> dict:
        """Get the cleaned diff for quarantined files.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.

        Returns:
            Dict with cleaned file diff information.
        """
        return await self._api_request(
            "GET",
            f"/app/security/{app_id}/files/cleaned-diff",
            params={"server_id": server_id},
        )

    async def activate_security_suite(
        self,
        app_id: int,
        *,
        server_id: int,
        mp_offer_availed: bool = False,
    ) -> dict:
        """Activate the Imunify360 security suite for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            mp_offer_availed: Whether marketplace offer was availed.

        Returns:
            Dict with activation status.
        """
        return await self._api_request(
            "POST",
            f"/app/security/{app_id}/activate",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "mp_offer_availed": int(mp_offer_availed),
            },
        )

    async def deactivate_security_suite(
        self,
        app_id: int,
        *,
        server_id: int,
        app_name: str,
        feedback_text: str | None = None,
    ) -> dict:
        """Deactivate the Imunify360 security suite for an application.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            app_name: Application name (required by API).
            feedback_text: Optional deactivation feedback.

        Returns:
            Dict with deactivation status.
        """
        body: dict = {
            "server_id": server_id,
            "app_id": app_id,
            "app_name": app_name,
        }
        if feedback_text is not None:
            body["feedback_text"] = feedback_text
        return await self._api_request(
            "PATCH",
            f"/app/security/{app_id}/deactivate",
            data=body,
        )

    async def add_security_ip(
        self,
        app_id: int,
        *,
        server_id: int,
        ip: str,
        mode: str,
        ttl: int = 0,
        reason: str,
    ) -> dict:
        """Add an IP to the security allow/blocklist.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            ip: IP address to add.
            mode: List mode — ``"allow"`` or ``"block"``.
            ttl: Time-to-live in seconds (0 = permanent).
            reason: Reason for adding the IP.

        Returns:
            Dict with operation result.
        """
        return await self._api_request(
            "PUT",
            f"/app/security/{app_id}/ips",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ttl": ttl,
                "reason": reason,
                "mode": mode,
                "ips": ip,
            },
        )

    async def remove_security_ip(
        self,
        app_id: int,
        *,
        server_id: int,
        ip: str,
        mode: str,
        ttl: int = 0,
        reason: str,
    ) -> dict:
        """Remove an IP from the security allow/blocklist.

        Uses HTTP DELETE with a body payload.

        Args:
            app_id: Numeric application ID.
            server_id: Numeric server ID.
            ip: IP address to remove.
            mode: List mode — ``"allow"`` or ``"block"``.
            ttl: Time-to-live in seconds (0 = permanent).
            reason: Reason for removing the IP.

        Returns:
            Dict with operation result.
        """
        return await self._api_request(
            "DELETE",
            f"/app/security/{app_id}/ips",
            data={
                "server_id": server_id,
                "app_id": app_id,
                "ttl": ttl,
                "reason": reason,
                "mode": mode,
                "ips": ip,
            },
        )

    # ------------------------------------------------------------------
    # Server Security Suite
    # ------------------------------------------------------------------

    async def get_server_security_incidents(
        self, *, server_id: int
    ) -> dict:
        """Get server-level security incidents.

        Args:
            server_id: Numeric server ID.

        Returns:
            Dict with security incident list.
        """
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/incidents",
            params={"server_id": server_id},
        )

    async def get_server_security_ips(
        self, *, server_id: int
    ) -> dict:
        """Get server security IP allow/blocklist.

        Args:
            server_id: Numeric server ID.

        Returns:
            Dict with allowlist and blocklist IPs.
        """
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/ips",
            params={"server_id": server_id},
        )

    async def update_server_security_ips(
        self,
        *,
        server_id: int,
        ip: str,
        mode: str,
        ttl: int = 0,
        ttl_type: str = "minutes",
    ) -> dict:
        """Add an IP to the server security allow/blocklist.

        Args:
            server_id: Numeric server ID.
            ip: IP address to add.
            mode: List mode -- ``"allow"`` or ``"block"``.
            ttl: Time-to-live (0 = permanent).
            ttl_type: TTL unit -- ``"minutes"`` or ``"hours"``.

        Returns:
            Dict with operation result.
        """
        api_mode = "white" if mode == "allow" else "black"
        return await self._api_request(
            "PUT",
            f"/server/security/{server_id}/ips",
            data={
                "server_id": server_id,
                "iplist[]": ip,
                "mode": api_mode,
                "ttl": ttl,
                "ttl_type": ttl_type,
            },
        )

    async def delete_server_security_ips(
        self,
        *,
        server_id: int,
        ip: str,
        mode: str,
    ) -> dict:
        """Remove an IP from the server security allow/blocklist.

        Uses HTTP DELETE with a request body.

        Args:
            server_id: Numeric server ID.
            ip: IP address to remove.
            mode: List mode -- ``"allow"`` or ``"block"``.

        Returns:
            Dict with operation result.
        """
        api_mode = "white" if mode == "allow" else "black"
        return await self._api_request(
            "DELETE",
            f"/server/security/{server_id}/ips",
            data={
                "server_id": server_id,
                "iplist[]": ip,
                "mode": api_mode,
            },
        )

    async def add_server_blacklist_countries(
        self,
        *,
        server_id: int,
        country: str,
        reason: str | None = None,
    ) -> dict:
        """Add a country to the server security geoblocking list.

        Args:
            server_id: Numeric server ID.
            country: Two-letter country code (uppercased automatically).
            reason: Optional reason for blocking the country.

        Returns:
            Dict with operation result.
        """
        body: dict = {
            "server_id": server_id,
            "countrylist[]": country.upper(),
        }
        if reason is not None:
            body["reason"] = reason
        return await self._api_request(
            "PUT",
            f"/server/security/{server_id}/blacklist-countries",
            data=body,
        )

    async def remove_server_blacklist_countries(
        self,
        *,
        server_id: int,
        country: str,
    ) -> dict:
        """Remove a country from the server security geoblocking list.

        Uses HTTP DELETE with a request body.

        Args:
            server_id: Numeric server ID.
            country: Two-letter country code (uppercased automatically).

        Returns:
            Dict with operation result.
        """
        return await self._api_request(
            "DELETE",
            f"/server/security/{server_id}/blacklist-countries",
            data={
                "server_id": server_id,
                "countrylist[]": country.upper(),
            },
        )

    async def get_server_security_stats(
        self,
        *,
        server_id: int,
        data_types: list[str],
        group_by: str,
        start: int,
        end: int,
    ) -> dict:
        """Get server security statistics.

        Args:
            server_id: Numeric server ID.
            data_types: List of data type names (e.g. ``["bandwidth", "requests"]``).
            group_by: Grouping interval (e.g. ``"day"``).
            start: Start timestamp (epoch seconds).
            end: End timestamp (epoch seconds).

        Returns:
            Dict with security statistics.
        """
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/stats",
            params={
                "server_id": server_id,
                "data_types[]": data_types,
                "group_by": group_by,
                "start": str(start),
                "end": str(end),
            },
        )

    async def list_server_infected_domains(
        self,
        *,
        server_id: int,
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """List infected domains on a server.

        Args:
            server_id: Numeric server ID.
            offset: Pagination offset (default 0).
            limit: Page size (default 20).

        Returns:
            Dict with infected domains list and total count.
        """
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/infected-domains",
            params={
                "server_id": server_id,
                "offset": str(offset),
                "limit": str(limit),
            },
        )

    async def sync_server_infected_domains(
        self, *, server_id: int
    ) -> dict:
        """Trigger a sync of infected domains on a server.

        Args:
            server_id: Numeric server ID.

        Returns:
            Dict with sync operation result.
        """
        return await self._api_request(
            "POST",
            f"/server/security/{server_id}/infected-domains/sync",
            data={"server_id": server_id},
        )

    async def get_server_firewall_settings(
        self, *, server_id: int
    ) -> dict:
        """Get server firewall settings.

        Args:
            server_id: Numeric server ID.

        Returns:
            Dict with firewall settings.
        """
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/firewall-settings",
            params={"server_id": server_id},
        )

    async def update_server_firewall_settings(
        self,
        *,
        server_id: int,
        request_limit: int | None = None,
        weak_password: bool | None = None,
    ) -> dict:
        """Update server firewall settings.

        Args:
            server_id: Numeric server ID.
            request_limit: Maximum request limit (optional).
            weak_password: Enable/disable weak password detection (optional).

        Returns:
            Dict with operation result.
        """
        body: dict = {"server_id": server_id}
        if request_limit is not None:
            body["request_limit"] = request_limit
        if weak_password is not None:
            body["weak_password"] = int(weak_password)
        return await self._api_request(
            "PUT",
            f"/server/security/{server_id}/firewall-settings",
            data=body,
        )

    async def get_server_security_apps(
        self,
        *,
        server_id: int,
        page: int = 1,
        page_limit: int = 20,
        app_name: str | None = None,
        filter_by: str | None = None,
    ) -> dict:
        """Get server security app inventory.

        Args:
            server_id: Numeric server ID.
            page: Page number (default 1).
            page_limit: Page size (default 20).
            app_name: Filter by application name (optional).
            filter_by: Filter by status, e.g. ``"infected"`` (optional).

        Returns:
            Dict with apps list.
        """
        params: dict = {
            "server_id": server_id,
            "page": str(page),
            "page_limit": str(page_limit),
        }
        if app_name is not None:
            params["app_name"] = app_name
        if filter_by is not None:
            params["filter_by"] = filter_by
        return await self._api_request(
            "GET",
            f"/server/security/{server_id}/apps",
            params=params,
        )

    # ------------------------------------------------------------------
    # Operation Polling
    # ------------------------------------------------------------------

    async def get_operation_status(self, operation_id: int) -> dict:
        """Get the status of a long-running operation.

        Args:
            operation_id: Operation ID from a creation response.

        Returns:
            API response dict with operation status.
        """
        return await self._api_request("GET", f"/operation/{operation_id}")

    async def wait_for_operation(
        self,
        operation_id: int,
        *,
        max_wait: int = 600,
        poll_interval: int = 10,
    ) -> dict:
        """Poll an operation until completion or timeout.

        Waits an initial 5 seconds before the first poll, then polls
        at ``poll_interval`` intervals until the operation completes
        or ``max_wait`` is exceeded.

        Args:
            operation_id: Operation ID to poll.
            max_wait: Maximum seconds to wait (default 600).
            poll_interval: Seconds between polls (default 10).

        Returns:
            The final operation response dict when completed.

        Raises:
            OperationTimeoutError: If the operation does not complete
                within ``max_wait`` seconds.
        """
        start = time.monotonic()

        # Initial delay before first poll
        await asyncio.sleep(5)

        while True:
            result = await self.get_operation_status(operation_id)
            operation = result.get("operation", {})

            if operation.get("is_completed"):
                return result

            elapsed = time.monotonic() - start
            if elapsed >= max_wait:
                raise OperationTimeoutError(
                    operation_id=operation_id,
                    elapsed=elapsed,
                    max_wait=max_wait,
                )

            await asyncio.sleep(poll_interval)

    async def get_task_status(self, task_id: str) -> dict:
        """Get the status of a task-based analytics/monitoring operation.

        Args:
            task_id: Task UUID string from a task-based API response.

        Returns:
            API response dict with task status.
        """
        return await self._api_request("GET", f"/operation/task/{task_id}")

    async def wait_for_task(
        self,
        task_id: str,
        *,
        max_wait: int = 300,
        poll_interval: int = 5,
    ) -> dict:
        """Poll a task until completion or timeout.

        Waits an initial 2 seconds before the first poll, then polls
        at ``poll_interval`` intervals until the task completes
        or ``max_wait`` is exceeded.

        Args:
            task_id: Task UUID string to poll.
            max_wait: Maximum seconds to wait (default 300).
            poll_interval: Seconds between polls (default 5).

        Returns:
            The final task response dict when completed.

        Raises:
            ValueError: If ``max_wait`` <= 0 or ``poll_interval`` <= 0.
            OperationTimeoutError: If the task does not complete
                within ``max_wait`` seconds.
        """
        if max_wait <= 0:
            raise ValueError(f"max_wait must be positive, got {max_wait}")
        if poll_interval <= 0:
            raise ValueError(
                f"poll_interval must be positive, got {poll_interval}"
            )

        start = time.monotonic()

        # Initial delay before first poll (shorter than wait_for_operation's 5s)
        await asyncio.sleep(2)

        while True:
            result = await self.get_task_status(task_id)

            if result.get("is_completed"):
                return result

            elapsed = time.monotonic() - start
            if elapsed >= max_wait:
                raise OperationTimeoutError(
                    operation_id=task_id,
                    elapsed=elapsed,
                    max_wait=max_wait,
                )

            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Internal request handling with retry logic
    # ------------------------------------------------------------------

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        _reauth_attempted: bool = False,
    ) -> dict:
        """Execute an authenticated API request with retry logic.

        Handles:
        - 429 (rate limit): retries after Retry-After header value
        - 500/502/503: retries with exponential backoff
        - 401: invalidates token, re-authenticates once, then retries

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API path (relative to BASE_URL).
            params: Query parameters (for GET requests).
            data: Form-encoded body data (for POST/PUT requests).
            _reauth_attempted: Internal flag to prevent infinite re-auth loops.
        """
        token = await self.authenticate()

        headers = {"Authorization": f"Bearer {token}"}

        request_kwargs: dict[str, Any] = {"headers": headers}
        if params is not None:
            request_kwargs["params"] = params
        if data is not None:
            request_kwargs["data"] = data

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._http_client.request(
                    method, path, **request_kwargs
                )
            except httpx.ConnectError as exc:
                raise APIError(
                    "Could not connect to Cloudways API. "
                    "Check your internet connection."
                ) from exc
            except httpx.HTTPError as exc:
                raise APIError(f"HTTP error: {exc}") from exc

            status = response.status_code

            # Success
            if 200 <= status < 300:
                # Handle empty response bodies (e.g., 204 No Content
                # or 200 with empty body from DELETE endpoints)
                body = response.content
                if not body or status == 204:
                    return {}
                try:
                    return response.json()
                except ValueError as exc:
                    raise APIError(
                        "Unexpected response format from Cloudways API."
                    ) from exc

            # 401 - token expired/invalid: re-auth once
            if status == 401 and not _reauth_attempted:
                self._token = None
                self._token_obtained_at = None
                return await self._api_request(
                    method, path, params=params, data=data, _reauth_attempted=True
                )

            if status == 401 and _reauth_attempted:
                raise AuthenticationError(
                    "Authentication failed after re-authentication attempt. "
                    "Check your email and API key."
                )

            # 429 - rate limit
            if status == 429:
                if attempt >= _MAX_RETRIES:
                    raise RateLimitError(
                        "Rate limit exceeded after maximum retries. Try again later."
                    )
                try:
                    retry_after = int(
                        response.headers.get("Retry-After", _DEFAULT_RATE_LIMIT_DELAY)
                    )
                except ValueError:
                    retry_after = _DEFAULT_RATE_LIMIT_DELAY
                await asyncio.sleep(retry_after)
                continue

            # 5xx - server error
            if status in (500, 502, 503):
                if attempt >= _MAX_RETRIES:
                    raise ServerError(
                        f"Server error ({status}) after {_MAX_RETRIES} retries."
                    )
                delay = _BASE_BACKOFF_DELAY * (2**attempt)
                await asyncio.sleep(delay)
                continue

            # Other 4xx - no retry
            raise APIError(f"API request failed with status {status}: {response.text}")

        # Should not reach here, but just in case
        raise APIError("Request failed after all retry attempts.")
