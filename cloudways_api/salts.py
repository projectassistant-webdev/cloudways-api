"""WordPress salt generation using Python's secrets module.

Generates cryptographically secure random salts for WordPress
authentication keys. Uses secrets.token_urlsafe() which provides
URL-safe base64-encoded random bytes.
"""

import secrets

SALT_KEYS: list[str] = [
    "AUTH_KEY",
    "SECURE_AUTH_KEY",
    "LOGGED_IN_KEY",
    "NONCE_KEY",
    "AUTH_SALT",
    "SECURE_AUTH_SALT",
    "LOGGED_IN_SALT",
    "NONCE_SALT",
]


def generate_salt() -> str:
    """Generate a single WordPress salt.

    Returns:
        A 64-character URL-safe random string.
    """
    return secrets.token_urlsafe(48)


def generate_wp_salts() -> dict[str, str]:
    """Generate all 8 WordPress salts.

    Returns:
        Dict mapping salt key names to random salt values.
    """
    return {key: generate_salt() for key in SALT_KEYS}


def generate_placeholder_salts() -> dict[str, str]:
    """Generate placeholder salts for --no-salts mode.

    Returns:
        Dict mapping salt key names to 'generateme' placeholder values.
    """
    return {key: "generateme" for key in SALT_KEYS}
