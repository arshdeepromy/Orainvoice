"""Unit tests for ``CarjamClient.lookup_ppsr`` and the PPSR response parser.

Covers:

1. **Happy path** — a CarJam JSON response with ``ppsr=1`` parses into
   ``CarjamPpsrResponse`` with ``money_owing.match='N'``.
2. **Validation** — requesting owner / ownership-history without an
   ``s241_purpose`` raises ``ValueError``.
3. **Upstream error** — a top-level ``error.message`` in the response body
   raises ``CarjamError`` carrying the upstream message.
4. **not_found** — a ``message.idh.header.not_found=true`` payload (or the
   XML ``<not_found>true</not_found>`` form) sets ``not_found=True``.
5. **Financing-statement parsing** — a 3-statement fixture flows through to
   ``ppsr_details`` as a 3-element list with the right field names.

The HTTP layer is mocked end-to-end; no real CarJam calls are made.
The Redis client is also stubbed to keep the rate-limit check clean.

**Validates: Requirements R2 — PPSR module (CarJam client extension).**
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.carjam import (
    CarjamClient,
    CarjamError,
    CarjamPpsrResponse,
    _parse_ppsr_response,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_redis_under_limit() -> MagicMock:
    """Build a Redis stub whose pipeline returns ``count=0`` (under limit)."""

    pipe_check = MagicMock()
    pipe_check.zremrangebyscore = MagicMock()
    pipe_check.zcard = MagicMock()
    pipe_check.execute = AsyncMock(return_value=[None, 0])

    pipe_record = MagicMock()
    pipe_record.zadd = MagicMock()
    pipe_record.expire = MagicMock()
    pipe_record.execute = AsyncMock(return_value=[None, None])

    redis = MagicMock()
    redis.pipeline.side_effect = [pipe_check, pipe_record]
    return redis


def _make_http_response(*, status_code: int = 200, text: str = "", url: str = "https://www.carjam.co.nz/api/car/") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = {}
    response.url = url
    response.history = []
    return response


def _patch_httpx_with(response: MagicMock):
    """Return a context manager that patches ``httpx.AsyncClient`` to return ``response``."""

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=response)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    mock_cls = MagicMock(return_value=mock_http_client)
    return patch("app.integrations.carjam.httpx.AsyncClient", mock_cls), mock_http_client


def _make_client() -> CarjamClient:
    return CarjamClient(
        redis=_make_redis_under_limit(),
        api_key="test-key",
        base_url="https://www.carjam.co.nz",
        rate_limit=100,
    )


# A canonical happy-path JSON shape, mirroring CarJam's wire format when
# ``f=json`` is set. The structure mirrors the XML response — keys match
# what the design doc lists for ``message.*``.
def _happy_response_body(*, statement_count: int = 0, statements: list[dict] | None = None) -> str:
    body = {
        "message": {
            "idh": {
                "header": {"not_found": False},
                "vehicle": {
                    "make": "Toyota",
                    "model": "Hilux",
                    "year_of_manufacture": "2018",
                    "main_colour": "Silver",
                },
            },
            "ppsr": {"count": statement_count},
            "ppsr_details": (
                {"financing_statement": statements}
                if statements is not None
                else {}
            ),
            "money_owing": {
                "match": "N",
                "match_description": "No money owing",
                "search_id": "ppsr-12345",
            },
            "warnings": {},
            "charges": {"cents": 50},
        }
    }
    return json.dumps(body)


# ===========================================================================
# 1. Happy path — ppsr=1 only
# ===========================================================================


class TestPpsrHappyPath:
    """The simplest possible PPSR call returns a populated dataclass."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_money_owing_match_n(self):
        client = _make_client()
        response = _make_http_response(text=_happy_response_body())

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_ppsr("ABC123")

        assert isinstance(result, CarjamPpsrResponse)
        assert result.rego == "ABC123"
        assert result.not_found is False
        assert result.money_owing["match"] == "N"
        assert result.money_owing["match_description"] == "No money owing"
        assert result.money_owing["search_id"] == "ppsr-12345"
        assert result.ppsr_details == []
        assert result.charges_cents == 50
        # raw_xml is the legacy field — stores the response body verbatim.
        assert json.loads(result.raw_xml)["message"]["money_owing"]["match"] == "N"
        # requested_options should mention the flags actually sent.
        assert result.requested_options.get("ppsr") == "1"
        assert result.requested_options.get("basic") == "1"
        assert result.requested_options.get("f") == "json"
        # api key must never end up in the recorded options.
        assert result.requested_options.get("key") == "<redacted>"

    @pytest.mark.asyncio
    async def test_happy_path_normalises_rego_to_upper(self):
        client = _make_client()
        response = _make_http_response(text=_happy_response_body())

        patch_ctx, mock_http_client = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_ppsr("  abc123  ")

        assert result.rego == "ABC123"
        # Confirm the outgoing query string carried the normalised plate.
        called_kwargs = mock_http_client.get.await_args.kwargs
        assert called_kwargs["params"]["plate"] == "ABC123"

    @pytest.mark.asyncio
    async def test_happy_path_basic_block_extracts_make_model(self):
        """The ``basic`` field surfaces the parsed idh.vehicle data."""
        client = _make_client()
        response = _make_http_response(text=_happy_response_body())

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_ppsr("ABC123")

        assert result.basic is not None
        assert result.basic["make"] == "Toyota"
        assert result.basic["model"] == "Hilux"
        assert result.basic["year"] == 2018
        assert result.basic["colour"] == "Silver"


# ===========================================================================
# 2. Validation — owner lookups without s241_purpose
# ===========================================================================


class TestS241PurposeValidation:
    """Owner / ownership-history lookups require an ``s241_purpose``."""

    @pytest.mark.asyncio
    async def test_owners_flag_without_s241_raises_value_error(self):
        client = _make_client()
        with pytest.raises(ValueError, match="s241_purpose required"):
            await client.lookup_ppsr("ABC123", include_owners=True)

    @pytest.mark.asyncio
    async def test_owner_flag_without_s241_raises_value_error(self):
        client = _make_client()
        with pytest.raises(ValueError, match="s241_purpose required"):
            await client.lookup_ppsr("ABC123", include_owner=True)

    @pytest.mark.asyncio
    async def test_owners_with_s241_passes_through_to_query_string(self):
        client = _make_client()
        body = _happy_response_body()
        response = _make_http_response(text=body)

        patch_ctx, mock_http_client = _patch_httpx_with(response)
        with patch_ctx:
            await client.lookup_ppsr(
                "ABC123",
                include_owners=True,
                s241_purpose="Selling vehicle",
            )

        called_kwargs = mock_http_client.get.await_args.kwargs
        assert called_kwargs["params"]["owners"] == "1"
        assert called_kwargs["params"]["s241_purpose"] == "Selling vehicle"


# ===========================================================================
# 3. Upstream error — top-level error.message
# ===========================================================================


class TestUpstreamError:
    """A JSON body with a top-level ``error`` key should raise ``CarjamError``."""

    @pytest.mark.asyncio
    async def test_top_level_error_raises_carjam_error_with_message(self):
        client = _make_client()
        body = json.dumps({"error": {"code": "auth", "message": "Invalid key"}})
        response = _make_http_response(text=body)

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            with pytest.raises(CarjamError, match="Invalid key"):
                await client.lookup_ppsr("ABC123")

    def test_xml_error_tag_at_parser_level_raises_carjam_error(self):
        """The parser should also raise on XML-shaped errors (fallback path)."""
        body = (
            "<message>"
            "<error><code>auth</code><message>Invalid key</message></error>"
            "</message>"
        )
        with pytest.raises(CarjamError, match="Invalid key"):
            _parse_ppsr_response("ABC123", body, requested_options={})


# ===========================================================================
# 4. not_found indicator
# ===========================================================================


class TestNotFoundIndicator:
    """Both the JSON and XML ``not_found`` paths should set the dataclass flag."""

    def test_json_not_found_sets_flag(self):
        body = json.dumps(
            {
                "message": {
                    "idh": {"header": {"not_found": True}},
                    "money_owing": {},
                }
            }
        )
        result = _parse_ppsr_response("ABC123", body, requested_options={})
        assert result.not_found is True
        assert result.money_owing == {
            "match": None,
            "match_description": None,
            "search_id": None,
        }

    def test_xml_not_found_sets_flag(self):
        body = (
            "<message>"
            "<not_found>true</not_found>"
            "<money_owing><match>U</match></money_owing>"
            "</message>"
        )
        result = _parse_ppsr_response("ABC123", body, requested_options={})
        assert result.not_found is True
        assert result.money_owing["match"] == "U"


# ===========================================================================
# 5. Financing-statement parsing — pulls 3 statements correctly
# ===========================================================================


class TestFinancingStatementParsing:
    """``ppsr_details`` should resolve to a list[dict] regardless of the
    upstream's single-vs-list serialisation choice."""

    def _three_statement_fixture(self) -> str:
        statements = [
            {
                "secured_party": "ANZ Bank",
                "collateral_description": "All present and after-acquired property",
                "registration_date": "2020-01-15",
                "status": "Active",
            },
            {
                "secured_party": "Toyota Finance",
                "collateral_description": "2018 Toyota Hilux",
                "registration_date": "2021-06-30",
                "status": "Active",
            },
            {
                "secured_party": "UDC Finance",
                "collateral_description": "Motor vehicle finance",
                "registration_date": "2022-11-02",
                "status": "Discharged",
            },
        ]
        return _happy_response_body(statement_count=3, statements=statements)

    @pytest.mark.asyncio
    async def test_three_statement_fixture_parses_to_three_dicts(self):
        client = _make_client()
        response = _make_http_response(text=self._three_statement_fixture())

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_ppsr("ABC123")

        assert len(result.ppsr_details) == 3
        assert result.ppsr_details[0]["secured_party"] == "ANZ Bank"
        assert result.ppsr_details[1]["secured_party"] == "Toyota Finance"
        assert result.ppsr_details[2]["secured_party"] == "UDC Finance"
        assert result.ppsr_details[2]["status"] == "Discharged"
        # Summary count should agree.
        assert result.ppsr_summary == {"count": 3}

    def test_single_statement_dict_coerced_to_one_element_list(self):
        single = {
            "secured_party": "BNZ",
            "collateral_description": "Vehicle",
            "registration_date": "2023-04-01",
            "status": "Active",
        }
        body = _happy_response_body(statement_count=1, statements=[single])
        result = _parse_ppsr_response("ABC123", body, requested_options={})
        assert len(result.ppsr_details) == 1
        assert result.ppsr_details[0]["secured_party"] == "BNZ"
