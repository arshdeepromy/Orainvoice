"""Unit tests for ``CarjamClient.lookup_owner_check`` and its response parser.

Covers:

1. **Happy path** — a CarJam JSON ``owner_check`` response with
   ``match=1`` parses into ``CarjamOwnerCheckResponse(match=True)`` and the
   per-type fields flow into the outgoing query string.
2. **Pre-flight validation** — missing per-type fields raise ``ValueError``
   before any HTTP call is made.
3. **Upstream validation error** — ``err-owner-check-validation`` raises
   ``CarjamOwnerCheckValidationError`` carrying the upstream message.
4. **API-product error** — ``err-api-product-not-allowed`` raises
   ``CarjamOwnerCheckNotAllowedError``.
5. **Charges + redaction** — charges parse into cents; the api_key is
   redacted from ``requested_options``.

The HTTP layer is mocked end-to-end; no real CarJam calls are made.

**Validates: Requirements R2 — PPSR owner_check (CarJam client extension).**
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.carjam import (
    CarjamClient,
    CarjamError,
    CarjamOwnerCheckNotAllowedError,
    CarjamOwnerCheckResponse,
    CarjamOwnerCheckValidationError,
    _parse_owner_check_response,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirror tests/unit/test_carjam_lookup_ppsr.py)
# ---------------------------------------------------------------------------


def _make_redis_under_limit() -> MagicMock:
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


def _make_http_response(
    *,
    status_code: int = 200,
    text: str = "",
    url: str = "https://www.carjam.co.nz/api/car/",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = {}
    response.url = url
    response.history = []
    return response


def _patch_httpx_with(response: MagicMock):
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


def _owner_check_body(
    *,
    match: int = 1,
    check_type: str = "person_names",
    ref: str = "OC1A2B3C4D",
    plate: str = "NSN5OO",
    cents: int | None = 155,
) -> str:
    body: dict = {
        "owner_check": {
            "ref": ref,
            "type": check_type,
            "plate": plate,
            "match": match,
        }
    }
    if cents is not None:
        body["charges"] = {"cents": cents}
    return json.dumps(body)


# ===========================================================================
# 1. Happy path
# ===========================================================================


class TestOwnerCheckHappyPath:
    @pytest.mark.asyncio
    async def test_match_one_parses_to_true(self):
        client = _make_client()
        response = _make_http_response(text=_owner_check_body(match=1))

        patch_ctx, mock_http = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_owner_check(
                "nsn5oo",
                check_type="person_names",
                last_name="Smith",
                first_name="Jane",
            )

        assert isinstance(result, CarjamOwnerCheckResponse)
        assert result.rego == "NSN5OO"
        assert result.match is True
        assert result.check_type == "person_names"
        assert result.ref == "OC1A2B3C4D"
        assert result.charges_cents == 155

        # Outgoing query string carries the per-type fields + redacted key.
        params = mock_http.get.await_args.kwargs["params"]
        assert params["type"] == "person_names"
        assert params["plate"] == "NSN5OO"
        assert params["last_name"] == "Smith"
        assert params["first_name"] == "Jane"
        assert params["f"] == "json"
        # api key must never end up in the recorded options.
        assert result.requested_options.get("key") == "<redacted>"

    @pytest.mark.asyncio
    async def test_match_zero_parses_to_false(self):
        client = _make_client()
        response = _make_http_response(text=_owner_check_body(match=0))

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            result = await client.lookup_owner_check(
                "NSN5OO",
                check_type="company",
                company_name="Acme Ltd",
            )

        assert result.match is False

    @pytest.mark.asyncio
    async def test_person_dl_sends_driver_licence(self):
        client = _make_client()
        response = _make_http_response(text=_owner_check_body(check_type="person_dl"))

        patch_ctx, mock_http = _patch_httpx_with(response)
        with patch_ctx:
            await client.lookup_owner_check(
                "NSN5OO",
                check_type="person_dl",
                driver_licence="DL123456",
            )

        params = mock_http.get.await_args.kwargs["params"]
        assert params["type"] == "person_dl"
        assert params["driver_licence"] == "DL123456"


# ===========================================================================
# 2. Pre-flight validation (no HTTP call)
# ===========================================================================


class TestOwnerCheckPreflightValidation:
    @pytest.mark.asyncio
    async def test_unknown_type_raises_value_error(self):
        client = _make_client()
        with pytest.raises(ValueError, match="check_type must be one of"):
            await client.lookup_owner_check("NSN5OO", check_type="bogus")

    @pytest.mark.asyncio
    async def test_person_names_without_last_name_raises(self):
        client = _make_client()
        with pytest.raises(ValueError, match="last_name is required"):
            await client.lookup_owner_check(
                "NSN5OO", check_type="person_names", first_name="Jane",
            )

    @pytest.mark.asyncio
    async def test_person_names_without_first_or_dob_raises(self):
        client = _make_client()
        with pytest.raises(ValueError, match="first_name or dob is required"):
            await client.lookup_owner_check(
                "NSN5OO", check_type="person_names", last_name="Smith",
            )

    @pytest.mark.asyncio
    async def test_person_dl_without_licence_raises(self):
        client = _make_client()
        with pytest.raises(ValueError, match="driver_licence is required"):
            await client.lookup_owner_check("NSN5OO", check_type="person_dl")

    @pytest.mark.asyncio
    async def test_company_without_name_raises(self):
        client = _make_client()
        with pytest.raises(ValueError, match="company_name is required"):
            await client.lookup_owner_check("NSN5OO", check_type="company")

    @pytest.mark.asyncio
    async def test_person_names_dob_only_is_valid(self):
        client = _make_client()
        response = _make_http_response(text=_owner_check_body())

        patch_ctx, mock_http = _patch_httpx_with(response)
        with patch_ctx:
            await client.lookup_owner_check(
                "NSN5OO",
                check_type="person_names",
                last_name="Smith",
                dob="1990-01-01",
            )

        params = mock_http.get.await_args.kwargs["params"]
        assert params["dob"] == "1990-01-01"
        assert "first_name" not in params


# ===========================================================================
# 3 + 4. Upstream errors
# ===========================================================================


class TestOwnerCheckUpstreamErrors:
    @pytest.mark.asyncio
    async def test_validation_error_scode_raises_validation_error(self):
        client = _make_client()
        body = json.dumps(
            {
                "code": -1,
                "scode": "err-owner-check-validation",
                "message": "Please select the check type",
                "class": "apperror",
            }
        )
        response = _make_http_response(text=body)

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            with pytest.raises(
                CarjamOwnerCheckValidationError, match="Please select the check type",
            ):
                await client.lookup_owner_check(
                    "NSN5OO", check_type="company", company_name="Acme Ltd",
                )

    @pytest.mark.asyncio
    async def test_product_not_allowed_raises_not_allowed_error(self):
        client = _make_client()
        body = json.dumps(
            {
                "code": -1,
                "scode": "err-api-product-not-allowed",
                "message": "Missing API product(s) - 'owner_check'.",
                "class": "apperror",
            }
        )
        response = _make_http_response(text=body)

        patch_ctx, _ = _patch_httpx_with(response)
        with patch_ctx:
            with pytest.raises(CarjamOwnerCheckNotAllowedError, match="owner_check"):
                await client.lookup_owner_check(
                    "NSN5OO", check_type="company", company_name="Acme Ltd",
                )

    def test_parser_xml_validation_error(self):
        body = (
            "<error>"
            "<code>-1</code>"
            "<scode>err-owner-check-validation</scode>"
            "<message>missing plate</message>"
            "<class>apperror</class>"
            "</error>"
        )
        with pytest.raises(CarjamOwnerCheckValidationError, match="missing plate"):
            _parse_owner_check_response("NSN5OO", body, requested_options={})

    def test_parser_missing_owner_check_block_raises(self):
        body = json.dumps({"message": {"something_else": {}}})
        with pytest.raises(CarjamError, match="missing owner_check block"):
            _parse_owner_check_response("NSN5OO", body, requested_options={})
