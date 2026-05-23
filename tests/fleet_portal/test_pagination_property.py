"""Property test for pagination shape (Property 32, Req 13.1, 13.3, 18.1, 18.2)."""
from __future__ import annotations

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.modules.fleet_portal import schemas as S


@given(
    offset=st.integers(min_value=0, max_value=1_000_000),
    limit=st.integers(min_value=1, max_value=100),
)
@hyp_settings(max_examples=200)
def test_pagination_params_accept_valid_inputs(offset: int, limit: int) -> None:
    p = S.PaginationParams(offset=offset, limit=limit)
    assert p.offset == offset
    assert p.limit == limit


def test_pagination_rejects_negative_offset() -> None:
    with pytest.raises(ValidationError):
        S.PaginationParams(offset=-1, limit=10)


def test_pagination_rejects_zero_limit() -> None:
    with pytest.raises(ValidationError):
        S.PaginationParams(offset=0, limit=0)


def test_pagination_rejects_huge_limit() -> None:
    with pytest.raises(ValidationError):
        S.PaginationParams(offset=0, limit=101)


def test_pagination_rejects_skip_field() -> None:
    """`skip` must be rejected so callers don't paginate by accident."""
    with pytest.raises(ValidationError):
        S.PaginationParams(skip=10, limit=10)  # type: ignore[call-arg]


def test_paginated_response_carries_four_fields() -> None:
    """The wrapper schema always exposes items, total, limit, offset."""
    r = S.VehicleListResponse(items=[], total=0, limit=50, offset=0)
    dumped = r.model_dump()
    assert {"items", "total", "limit", "offset"} <= set(dumped)
