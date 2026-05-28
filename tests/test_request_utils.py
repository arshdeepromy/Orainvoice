"""Unit tests for ``app.core.request_utils.extract_request_base_url``.

Covers Requirements 3.12 and 3.16 of the
``email-delivery-visibility-fixes`` bugfix spec:

- Origin header is preferred and trailing slash is stripped.
- Host header is used as fallback when Origin is missing/empty.
- Whitespace-only header values are treated as empty.
- Returns ``None`` when neither Origin nor Host carry a value so
  callers can fall back to ``settings.frontend_base_url``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.request_utils import extract_request_base_url


def _make_request(headers: dict[str, str], scheme: str = "https") -> MagicMock:
    """Build a fake ``fastapi.Request`` with header + scheme behaviour.

    ``Request.headers.get`` is case-insensitive in Starlette; the
    helper only ever asks for lowercase keys (``origin`` / ``host``)
    so a plain dict ``.get`` is sufficient for these tests.
    """
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.get = lambda key, default=None: headers.get(key.lower(), default)
    request.url = MagicMock()
    request.url.scheme = scheme
    return request


def test_origin_set_returns_origin() -> None:
    request = _make_request({"origin": "https://devin.oraflows.co.nz"})
    assert extract_request_base_url(request) == "https://devin.oraflows.co.nz"


def test_origin_with_trailing_slash_is_stripped() -> None:
    request = _make_request({"origin": "https://devin.oraflows.co.nz/"})
    assert extract_request_base_url(request) == "https://devin.oraflows.co.nz"


def test_origin_missing_falls_back_to_scheme_plus_host() -> None:
    request = _make_request(
        {"host": "devin.oraflows.co.nz"},
        scheme="https",
    )
    assert extract_request_base_url(request) == "https://devin.oraflows.co.nz"


def test_origin_empty_falls_back_to_scheme_plus_host() -> None:
    request = _make_request(
        {"origin": "", "host": "devin.oraflows.co.nz"},
        scheme="http",
    )
    assert extract_request_base_url(request) == "http://devin.oraflows.co.nz"


def test_origin_whitespace_only_falls_back_to_host() -> None:
    request = _make_request(
        {"origin": "   ", "host": "example.com"},
        scheme="https",
    )
    assert extract_request_base_url(request) == "https://example.com"


def test_host_only_with_port_is_preserved() -> None:
    request = _make_request(
        {"host": "localhost:5173"},
        scheme="http",
    )
    assert extract_request_base_url(request) == "http://localhost:5173"


def test_no_origin_no_host_returns_none() -> None:
    request = _make_request({})
    assert extract_request_base_url(request) is None


def test_origin_and_host_both_empty_returns_none() -> None:
    request = _make_request({"origin": "", "host": ""})
    assert extract_request_base_url(request) is None


def test_host_whitespace_only_with_no_origin_returns_none() -> None:
    request = _make_request({"host": "   "})
    assert extract_request_base_url(request) is None


def test_origin_takes_precedence_over_host() -> None:
    request = _make_request(
        {
            "origin": "https://devin.oraflows.co.nz",
            "host": "internal.example.com",
        },
    )
    assert extract_request_base_url(request) == "https://devin.oraflows.co.nz"
