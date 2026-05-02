"""Property-based tests for portal pagination logic.

Tests the pure pagination logic: given a list of items with random limit
and offset, the paginated result contains at most `limit` items starting
from `offset`, and `total` equals the full list length.

Properties covered:
  P23 — Pagination returns correct subset and total

**Validates: Requirements 26.2, 26.3**
"""

from __future__ import annotations

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Pure pagination function (mirrors the service-layer logic)
# ---------------------------------------------------------------------------

def paginate(items: list, limit: int, offset: int) -> dict:
    """Pure pagination function matching the portal service pattern.

    All portal list endpoints apply:
        query.offset(offset).limit(limit)
        total = count(*)

    This function replicates that logic on a plain list.
    """
    total = len(items)
    subset = items[offset : offset + limit]
    return {"items": subset, "total": total}


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Items can be anything — we use simple integers for clarity
_item = st.integers(min_value=1, max_value=10000)

_items_list = st.lists(_item, min_size=0, max_size=200)

_limit = st.integers(min_value=1, max_value=100)

# offset can be 0 up to beyond the list length (edge case)
_offset = st.integers(min_value=0, max_value=250)


# ===========================================================================
# Property 23: Pagination returns correct subset and total
# ===========================================================================


class TestP23PaginationReturnsCorrectSubsetAndTotal:
    """For any dataset of N items and random limit (1-100) and offset (0-N)
    values, the portal list endpoint SHALL return at most `limit` items,
    the items SHALL start from position `offset` in the full ordered set,
    and `total` SHALL equal N regardless of `limit` and `offset`.

    **Validates: Requirements 26.2, 26.3**
    """

    @given(items=_items_list, limit=_limit, offset=_offset)
    @settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_result_contains_at_most_limit_items(
        self, items: list[int], limit: int, offset: int
    ) -> None:
        """P23: The paginated result contains at most `limit` items.

        **Validates: Requirements 26.2**
        """
        result = paginate(items, limit, offset)
        assert len(result["items"]) <= limit, (
            f"Expected at most {limit} items, got {len(result['items'])} "
            f"(total={len(items)}, offset={offset})"
        )

    @given(items=_items_list, limit=_limit, offset=_offset)
    @settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_total_equals_full_list_length(
        self, items: list[int], limit: int, offset: int
    ) -> None:
        """P23: `total` equals the full list length regardless of limit/offset.

        **Validates: Requirements 26.3**
        """
        result = paginate(items, limit, offset)
        assert result["total"] == len(items), (
            f"Expected total={len(items)}, got {result['total']} "
            f"(limit={limit}, offset={offset})"
        )

    @given(items=_items_list, limit=_limit, offset=_offset)
    @settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_items_start_from_offset_position(
        self, items: list[int], limit: int, offset: int
    ) -> None:
        """P23: The returned items start from position `offset` in the full set.

        **Validates: Requirements 26.2**
        """
        result = paginate(items, limit, offset)
        expected_slice = items[offset : offset + limit]
        assert result["items"] == expected_slice, (
            f"Items mismatch: got {result['items']}, "
            f"expected {expected_slice} (offset={offset}, limit={limit})"
        )

    @given(items=_items_list, limit=_limit)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_offset_zero_returns_first_items(
        self, items: list[int], limit: int
    ) -> None:
        """P23: With offset=0, the first `limit` items are returned.

        **Validates: Requirements 26.2**
        """
        result = paginate(items, limit, offset=0)
        expected = items[:limit]
        assert result["items"] == expected

    @given(items=st.lists(_item, min_size=1, max_size=200), limit=_limit)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_offset_beyond_list_returns_empty(
        self, items: list[int], limit: int
    ) -> None:
        """P23: When offset >= len(items), an empty list is returned but total
        still equals the full list length.

        **Validates: Requirements 26.2, 26.3**
        """
        offset = len(items) + 1
        result = paginate(items, limit, offset)
        assert result["items"] == [], (
            f"Expected empty list for offset={offset} > len={len(items)}, "
            f"got {result['items']}"
        )
        assert result["total"] == len(items)

    @given(
        items=st.lists(_item, min_size=1, max_size=200),
        limit=_limit,
        offset=_offset,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_consecutive_pages_cover_all_items(
        self, items: list[int], limit: int, offset: int
    ) -> None:
        """P23: Iterating through all pages with the given limit covers every item
        exactly once.

        **Validates: Requirements 26.2, 26.3**
        """
        all_items: list[int] = []
        current_offset = 0
        while True:
            result = paginate(items, limit, current_offset)
            if not result["items"]:
                break
            all_items.extend(result["items"])
            current_offset += limit

        assert all_items == items, (
            f"Consecutive pages did not reconstruct the full list "
            f"(limit={limit}, len={len(items)})"
        )

    def test_empty_list_returns_empty_with_zero_total(self) -> None:
        """P23: Empty input list returns empty items and total=0.

        **Validates: Requirements 26.2, 26.3**
        """
        result = paginate([], limit=20, offset=0)
        assert result["items"] == []
        assert result["total"] == 0
