"""Tests for WordPress salt generation module.

Covers salt length, uniqueness, character set, and placeholder mode.
"""

import re

from cloudways_api.salts import (
    SALT_KEYS,
    generate_placeholder_salts,
    generate_salt,
    generate_wp_salts,
)

# URL-safe base64 character set: A-Z, a-z, 0-9, -, _
URL_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class TestGenerateSalt:
    """Tests for generate_salt()."""

    def test_generate_salt_length(self) -> None:
        """AC-7.1: Each salt is exactly 64 characters."""
        salt = generate_salt()
        assert len(salt) == 64

    def test_generate_salt_uniqueness(self) -> None:
        """AC-7.2: Two generated salts are never identical."""
        salt1 = generate_salt()
        salt2 = generate_salt()
        assert salt1 != salt2

    def test_generate_salt_characters(self) -> None:
        """AC-7.3: Salts contain only URL-safe characters [A-Za-z0-9_-]."""
        salt = generate_salt()
        assert URL_SAFE_PATTERN.match(salt), f"Invalid characters in salt: {salt}"


class TestGenerateWpSalts:
    """Tests for generate_wp_salts()."""

    def test_generate_wp_salts_returns_all_eight(self) -> None:
        """AC-7.4: Returns dict with all 8 salt keys."""
        salts = generate_wp_salts()
        assert len(salts) == 8
        for key in SALT_KEYS:
            assert key in salts

    def test_generate_wp_salts_unique_values(self) -> None:
        """AC-7.5: All 8 salt values are unique."""
        salts = generate_wp_salts()
        values = list(salts.values())
        assert len(set(values)) == 8


class TestGeneratePlaceholderSalts:
    """Tests for generate_placeholder_salts()."""

    def test_generate_placeholder_salts_values(self) -> None:
        """AC-7.6: All 8 values are 'generateme'."""
        salts = generate_placeholder_salts()
        for value in salts.values():
            assert value == "generateme"

    def test_generate_placeholder_salts_keys(self) -> None:
        """AC-7.7: Returns all 8 salt key names."""
        salts = generate_placeholder_salts()
        assert len(salts) == 8
        for key in SALT_KEYS:
            assert key in salts


class TestSaltKeysConstant:
    """Tests for the SALT_KEYS constant."""

    def test_salt_keys_constant(self) -> None:
        """AC-7.8: SALT_KEYS contains exactly the 8 expected key names."""
        expected = [
            "AUTH_KEY",
            "SECURE_AUTH_KEY",
            "LOGGED_IN_KEY",
            "NONCE_KEY",
            "AUTH_SALT",
            "SECURE_AUTH_SALT",
            "LOGGED_IN_SALT",
            "NONCE_SALT",
        ]
        assert SALT_KEYS == expected
