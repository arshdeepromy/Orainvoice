"""Tests for portal CSRF protection (double-submit cookie pattern).

Tests the pure logic of CSRF validation without requiring a database:
- validate_portal_csrf rejects missing cookie or header
- validate_portal_csrf rejects mismatched cookie and header
- validate_portal_csrf accepts matching cookie and header
- CSRFValidationError is raised (not ValueError) for CSRF failures

**Validates: Requirements 41.1, 41.2, 41.3**
"""

from __future__ import annotations

import secrets
from unittest.mock import MagicMock

import pytest

from app.modules.portal.service import (
    CSRFValidationError,
    validate_portal_csrf,
)


def _make_request(cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock request with the given cookies and headers."""
    request = MagicMock()
    request.cookies = cookies or {}
    # Headers should be case-insensitive like real Starlette headers
    raw_headers = headers or {}
    request.headers = {k.lower(): v for k, v in raw_headers.items()}
    return request


class TestValidatePortalCsrf:
    """Unit tests for the validate_portal_csrf helper.

    **Validates: Requirements 41.1, 41.2, 41.3**
    """

    def test_missing_cookie_raises_csrf_error(self) -> None:
        """When portal_csrf cookie is missing, CSRFValidationError is raised.

        **Validates: Requirements 41.3**
        """
        token = secrets.token_urlsafe(32)
        request = _make_request(
            cookies={},
            headers={"X-CSRF-Token": token},
        )
        with pytest.raises(CSRFValidationError, match="Missing CSRF token"):
            validate_portal_csrf(request)

    def test_missing_header_raises_csrf_error(self) -> None:
        """When X-CSRF-Token header is missing, CSRFValidationError is raised.

        **Validates: Requirements 41.3**
        """
        token = secrets.token_urlsafe(32)
        request = _make_request(
            cookies={"portal_csrf": token},
            headers={},
        )
        with pytest.raises(CSRFValidationError, match="Missing CSRF token"):
            validate_portal_csrf(request)

    def test_both_missing_raises_csrf_error(self) -> None:
        """When both cookie and header are missing, CSRFValidationError is raised.

        **Validates: Requirements 41.3**
        """
        request = _make_request(cookies={}, headers={})
        with pytest.raises(CSRFValidationError, match="Missing CSRF token"):
            validate_portal_csrf(request)

    def test_mismatched_tokens_raises_csrf_error(self) -> None:
        """When cookie and header have different values, CSRFValidationError is raised.

        **Validates: Requirements 41.3**
        """
        cookie_token = secrets.token_urlsafe(32)
        header_token = secrets.token_urlsafe(32)
        request = _make_request(
            cookies={"portal_csrf": cookie_token},
            headers={"X-CSRF-Token": header_token},
        )
        with pytest.raises(CSRFValidationError, match="CSRF token mismatch"):
            validate_portal_csrf(request)

    def test_matching_tokens_passes(self) -> None:
        """When cookie and header match, validation passes without error.

        **Validates: Requirements 41.1, 41.2**
        """
        token = secrets.token_urlsafe(32)
        request = _make_request(
            cookies={"portal_csrf": token},
            headers={"X-CSRF-Token": token},
        )
        # Should not raise
        validate_portal_csrf(request)

    def test_csrf_error_is_not_value_error(self) -> None:
        """CSRFValidationError is a distinct exception from ValueError,
        allowing endpoints to return 403 for CSRF failures and 400 for
        business logic errors.

        **Validates: Requirements 41.3**
        """
        assert not issubclass(CSRFValidationError, ValueError)

    def test_empty_string_cookie_raises_csrf_error(self) -> None:
        """An empty string cookie value is treated as missing.

        **Validates: Requirements 41.3**
        """
        request = _make_request(
            cookies={"portal_csrf": ""},
            headers={"X-CSRF-Token": "some-token"},
        )
        with pytest.raises(CSRFValidationError, match="Missing CSRF token"):
            validate_portal_csrf(request)

    def test_empty_string_header_raises_csrf_error(self) -> None:
        """An empty string header value is treated as missing.

        **Validates: Requirements 41.3**
        """
        request = _make_request(
            cookies={"portal_csrf": "some-token"},
            headers={"X-CSRF-Token": ""},
        )
        with pytest.raises(CSRFValidationError, match="Missing CSRF token"):
            validate_portal_csrf(request)

    def test_header_lookup_is_case_insensitive(self) -> None:
        """The X-CSRF-Token header lookup works regardless of case.

        **Validates: Requirements 41.2**
        """
        token = secrets.token_urlsafe(32)
        request = _make_request(
            cookies={"portal_csrf": token},
            headers={"x-csrf-token": token},
        )
        # Should not raise
        validate_portal_csrf(request)
