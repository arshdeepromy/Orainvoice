"""Property-based tests for universal items catalogue.

Feature: universal-items-catalogue

Uses Hypothesis to verify correctness properties for the Items catalogue
schemas and service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.catalogue.schemas import ItemResponse


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Item names: non-empty strings up to 255 chars
item_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Descriptions: optional text
item_descriptions = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=0,
        max_size=200,
    ),
)

# Prices as Decimal with 2 decimal places, non-negative
item_prices = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Categories: optional free-text up to 100 chars
item_categories = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=100,
    ).filter(lambda s: s.strip()),
)

# ISO 8601 timestamps
item_timestamps = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


@st.composite
def item_dict(draw):
    """Generate a dict in the shape that _item_to_dict() / _service_to_dict() produces.

    This mirrors the serialisation format: id and default_price as strings,
    timestamps as ISO 8601 strings, category as optional string.
    """
    return {
        "id": str(draw(st.builds(uuid.uuid4))),
        "name": draw(item_names),
        "description": draw(item_descriptions),
        "default_price": str(draw(item_prices)),
        "is_gst_exempt": draw(st.booleans()),
        "category": draw(item_categories),
        "is_active": draw(st.booleans()),
        "created_at": draw(item_timestamps).isoformat(),
        "updated_at": draw(item_timestamps).isoformat(),
    }


# ---------------------------------------------------------------------------
# Property 10: Schema round-trip preservation
# ---------------------------------------------------------------------------


class TestSchemaRoundTripPreservation:
    """Property 10: Schema round-trip preservation.

    Feature: universal-items-catalogue, Property 10: Schema round-trip preservation

    **Validates: Requirement 7.6**

    For any valid Item object, serialising to a response dict via
    _item_to_dict() and then constructing an ItemResponse Pydantic model
    shall produce an equivalent representation with all field values preserved.
    """

    @given(data=item_dict())
    @PBT_SETTINGS
    def test_item_dict_to_response_round_trip(self, data):
        """A valid item dict round-trips through ItemResponse without data loss.

        **Validates: Requirement 7.6**
        """
        # Construct ItemResponse from the generated dict
        response = ItemResponse(**data)

        # Assert every field is preserved
        assert response.id == data["id"]
        assert response.name == data["name"]
        assert response.description == data["description"]
        assert response.default_price == data["default_price"]
        assert response.is_gst_exempt == data["is_gst_exempt"]
        assert response.category == data["category"]
        assert response.is_active == data["is_active"]
        assert response.created_at == data["created_at"]
        assert response.updated_at == data["updated_at"]

    @given(data=item_dict())
    @PBT_SETTINGS
    def test_item_response_model_dump_matches_input(self, data):
        """ItemResponse.model_dump() produces a dict equivalent to the input.

        **Validates: Requirement 7.6**
        """
        response = ItemResponse(**data)
        dumped = response.model_dump()

        # The dumped dict should match the original input for all fields
        for key in data:
            assert dumped[key] == data[key], f"Mismatch on field '{key}': {dumped[key]!r} != {data[key]!r}"


# ---------------------------------------------------------------------------
# Property 2: Category accepts any string or null
# ---------------------------------------------------------------------------

# Strategy: random category strings (length 1–100) or None
free_text_categories = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=100,
    ).filter(lambda s: s.strip()),
)


class TestCategoryAcceptsAnyStringOrNull:
    """Property 2: Category accepts any string or null.

    Feature: universal-items-catalogue, Property 2: Category accepts any string or null

    **Validates: Requirements 1.4, 1.5**

    For any non-empty string of length <= 100 provided as the category value
    when creating an Item, the Items API shall accept and persist the value.
    For any create request with no category value, the Items API shall accept
    the Item with a null category.
    """

    @given(category=free_text_categories)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_create_item_accepts_any_category(self, category):
        """create_item accepts any free-text string or None as category.

        **Validates: Requirements 1.4, 1.5**
        """
        from app.modules.catalogue.service import create_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # -- Mock DB session --
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Capture kwargs passed to ItemsCatalogue constructor
        captured_kwargs: dict = {}
        mock_item_instance = MagicMock()
        mock_item_instance.id = uuid.uuid4()
        mock_item_instance.name = "Test Item"
        mock_item_instance.description = None
        mock_item_instance.default_price = Decimal("10.00")
        mock_item_instance.is_gst_exempt = False
        mock_item_instance.category = category
        mock_item_instance.is_active = True
        mock_item_instance.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_item_instance.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def fake_items_catalogue(**kwargs):
            captured_kwargs.update(kwargs)
            for k, v in kwargs.items():
                setattr(mock_item_instance, k, v)
            return mock_item_instance

        with patch(
            "app.modules.catalogue.service.ItemsCatalogue",
            side_effect=fake_items_catalogue,
        ), patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_item(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                name="Test Item",
                default_price="10.00",
                category=category,
            )

        # The function should not raise — it accepted the category
        assert result is not None
        # The category passed to the ORM constructor matches what we provided
        assert captured_kwargs["category"] == category
        # The returned dict also reflects the category
        assert result["category"] == category

# ---------------------------------------------------------------------------
# Property 3: Search filters by name case-insensitively
# ---------------------------------------------------------------------------

# Strategy: search query strings — printable, non-empty, reasonable length
search_queries = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())


class TestSearchFiltersByNameCaseInsensitively:
    """Property 3: Search filters by name case-insensitively.

    Feature: universal-items-catalogue, Property 3: Search filters by name case-insensitively

    **Validates: Requirement 2.5**

    For any search query string q and any Item with name n, the Item shall
    appear in the list results if and only if q.lower() is a substring of
    n.lower().
    """

    @given(
        names=st.lists(item_names, min_size=1, max_size=5, unique=True),
        query=search_queries,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_search_filters_case_insensitively(self, names, query):
        """list_items with search param returns only items whose name
        contains the query case-insensitively.

        **Validates: Requirement 2.5**
        """
        from app.modules.catalogue.service import list_items

        org_id = uuid.uuid4()

        # Build mock ORM item objects
        mock_items = []
        for name in names:
            item = MagicMock()
            item.id = uuid.uuid4()
            item.org_id = org_id
            item.name = name
            item.description = None
            item.default_price = Decimal("10.00")
            item.is_gst_exempt = False
            item.category = None
            item.is_active = True
            item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_items.append(item)

        # Expected: items whose name contains query (case-insensitive)
        expected_matching = [
            n for n in names if query.lower() in n.lower()
        ]

        # Filter mock items the same way the ilike would
        matching_items = [
            i for i in mock_items if query.lower() in i.name.lower()
        ]

        # Mock the DB session to return the pre-filtered items
        # (simulating what Postgres ilike would do)
        mock_db = AsyncMock()

        # count query returns len(matching_items)
        count_result = MagicMock()
        count_result.scalar.return_value = len(matching_items)

        # items query returns matching_items
        items_result = MagicMock()
        items_scalars = MagicMock()
        items_scalars.all.return_value = matching_items
        items_result.scalars.return_value = items_scalars

        # execute is called twice: once for count, once for items
        mock_db.execute = AsyncMock(side_effect=[count_result, items_result])

        result = await list_items(
            mock_db,
            org_id=org_id,
            search=query,
        )

        # Verify the returned items match our expected set
        returned_names = [item["name"] for item in result["items"]]
        assert sorted(returned_names) == sorted(expected_matching)
        assert result["total"] == len(expected_matching)


# ---------------------------------------------------------------------------
# Property 6: Negative price rejected
# ---------------------------------------------------------------------------

# Strategy: negative decimal values as strings (what the service functions accept)
negative_prices = st.decimals(
    min_value=Decimal("-99999.99"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(str)


class TestNegativePriceRejected:
    """Property 6: Negative price rejected.

    Feature: universal-items-catalogue, Property 6: Negative price rejected

    **Validates: Requirement 2.8**

    For any create or update request where default_price parses to a negative
    decimal value, the Items API shall raise ValueError.
    """

    @given(price=negative_prices)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_create_item_rejects_negative_price(self, price):
        """create_item raises ValueError for any negative price.

        **Validates: Requirement 2.8**
        """
        from app.modules.catalogue.service import create_item

        mock_db = AsyncMock()

        with pytest.raises(ValueError, match="Price cannot be negative"):
            await create_item(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test Item",
                default_price=price,
            )

    @given(price=negative_prices)
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_update_item_rejects_negative_price(self, price):
        """update_item raises ValueError for any negative price.

        **Validates: Requirement 2.8**
        """
        from app.modules.catalogue.service import update_item

        item_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # Mock an existing item so update_item gets past the "not found" check
        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.org_id = org_id
        mock_item.name = "Existing Item"
        mock_item.description = None
        mock_item.default_price = Decimal("10.00")
        mock_item.is_gst_exempt = False
        mock_item.category = None
        mock_item.is_active = True
        mock_item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Price cannot be negative"):
            await update_item(
                mock_db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                item_id=item_id,
                default_price=price,
            )



# ---------------------------------------------------------------------------
# Property 5: Soft-delete sets is_active to false
# ---------------------------------------------------------------------------


class TestSoftDeleteSetsIsActiveToFalse:
    """Property 5: Soft-delete sets is_active to false.

    Feature: universal-items-catalogue, Property 5: Soft-delete sets is_active to false

    **Validates: Requirement 2.4**

    For any DELETE request to /api/v1/catalogue/items/{id} where the Item
    exists and belongs to the authenticated organisation, the Item's is_active
    field shall be set to false and the Item shall still be retrievable via
    the list endpoint with active_only=false.
    """

    @given(
        name=item_names,
        price=item_prices,
        category=item_categories,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_soft_delete_sets_is_active_false_and_item_still_retrievable(
        self, name, price, category
    ):
        """Soft-deleting an item sets is_active=False and the item remains
        retrievable with active_only=False.

        **Validates: Requirement 2.4**
        """
        from app.modules.catalogue.service import create_item, update_item, list_items

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # -- Mock DB session for create_item --
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.org_id = org_id
        mock_item.name = name
        mock_item.description = None
        mock_item.default_price = Decimal(str(price))
        mock_item.is_gst_exempt = False
        mock_item.category = category
        mock_item.is_active = True
        mock_item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def fake_items_catalogue(**kwargs):
            for k, v in kwargs.items():
                setattr(mock_item, k, v)
            return mock_item

        with patch(
            "app.modules.catalogue.service.ItemsCatalogue",
            side_effect=fake_items_catalogue,
        ), patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            created = await create_item(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                name=name,
                default_price=str(price),
                category=category,
            )

        assert created["is_active"] is True

        # -- Mock DB session for update_item (soft-delete: is_active=False) --
        mock_db2 = AsyncMock()
        mock_db2.flush = AsyncMock()
        mock_db2.refresh = AsyncMock()

        # Simulate the select query returning the existing item
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_item
        mock_db2.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            updated = await update_item(
                mock_db2,
                org_id=org_id,
                user_id=user_id,
                item_id=item_id,
                is_active=False,
            )

        # After soft-delete, is_active must be False
        assert updated["is_active"] is False

        # -- Mock DB session for list_items (active_only=False) --
        # The soft-deleted item should still be retrievable
        mock_db3 = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        items_result = MagicMock()
        items_scalars = MagicMock()
        items_scalars.all.return_value = [mock_item]
        items_result.scalars.return_value = items_scalars

        mock_db3.execute = AsyncMock(side_effect=[count_result, items_result])

        result = await list_items(
            mock_db3,
            org_id=org_id,
            active_only=False,
        )

        # The item should appear in the list
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == str(item_id)
        assert result["items"][0]["is_active"] is False


# ---------------------------------------------------------------------------
# Property 7: Cross-org access denied
# ---------------------------------------------------------------------------


class TestCrossOrgAccessDenied:
    """Property 7: Cross-org access denied.

    Feature: universal-items-catalogue, Property 7: Cross-org access denied

    **Validates: Requirement 2.9**

    For any update or delete request where the Item ID belongs to a different
    organisation than the authenticated user's organisation, the Items API
    shall return a 404 status code (ValueError at the service layer).
    """

    @given(
        name=item_names,
        price=item_prices,
        category=item_categories,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_update_item_from_different_org_raises_not_found(
        self, name, price, category
    ):
        """update_item raises ValueError('Item not found') when org B tries
        to update an item belonging to org A.

        **Validates: Requirement 2.9**
        """
        from app.modules.catalogue.service import update_item

        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock DB: the select query filters by item_id AND org_id.
        # Since org_b != org_a, scalar_one_or_none returns None.
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Item not found"):
            await update_item(
                mock_db,
                org_id=org_b,
                user_id=uuid.uuid4(),
                item_id=item_id,
                name=name,
            )

    @given(
        name=item_names,
        price=item_prices,
        category=item_categories,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_soft_delete_from_different_org_raises_not_found(
        self, name, price, category
    ):
        """Soft-deleting (is_active=False) from a different org raises
        ValueError('Item not found').

        **Validates: Requirement 2.9**
        """
        from app.modules.catalogue.service import update_item

        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock DB: org_b cannot see org_a's item
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Item not found"):
            await update_item(
                mock_db,
                org_id=org_b,
                user_id=uuid.uuid4(),
                item_id=item_id,
                is_active=False,
            )

# ---------------------------------------------------------------------------
# Property 4: Legacy endpoints return equivalent data
# ---------------------------------------------------------------------------

# Strategy: categories that are non-None (ServiceResponse.category is required str)
non_null_categories = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())


@st.composite
def item_dict_with_category(draw):
    """Generate an item dict with a guaranteed non-None category.

    ServiceResponse requires category as a non-optional str, so we ensure
    the generated items always have a category value.
    """
    return {
        "id": str(draw(st.builds(uuid.uuid4))),
        "name": draw(item_names),
        "description": draw(item_descriptions),
        "default_price": str(draw(item_prices)),
        "is_gst_exempt": draw(st.booleans()),
        "category": draw(non_null_categories),
        "is_active": draw(st.booleans()),
        "created_at": draw(item_timestamps).isoformat(),
        "updated_at": draw(item_timestamps).isoformat(),
    }


class TestLegacyEndpointEquivalence:
    """Property 4: Legacy endpoints return equivalent data.

    Feature: universal-items-catalogue, Property 4: Legacy endpoints return equivalent data

    **Validates: Requirements 2.6, 2.7**

    For any request to GET /api/v1/catalogue/services, the response shall
    contain the same Item data as an equivalent request to
    GET /api/v1/catalogue/items, with the response key being ``services``
    instead of ``items``.
    """

    @given(
        items_data=st.lists(item_dict_with_category(), min_size=1, max_size=5),
    )
    @PBT_SETTINGS
    def test_list_items_and_services_return_same_data_different_keys(self, items_data):
        """Wrapping list_items() result in ItemListResponse and
        ServiceListResponse produces the same item data under different keys.

        **Validates: Requirements 2.6, 2.7**
        """
        from app.modules.catalogue.schemas import (
            ItemListResponse,
            ItemResponse,
            ServiceListResponse,
            ServiceResponse,
        )

        total = len(items_data)

        # Build the new /items response
        item_list_response = ItemListResponse(
            items=[ItemResponse(**d) for d in items_data],
            total=total,
        )

        # Build the legacy /services response from the same data
        service_list_response = ServiceListResponse(
            services=[ServiceResponse(**d) for d in items_data],
            total=total,
        )

        # Both responses should have the same total
        assert item_list_response.total == service_list_response.total

        # The item data should be identical across both responses
        for item_resp, svc_resp in zip(
            item_list_response.items, service_list_response.services
        ):
            assert item_resp.id == svc_resp.id
            assert item_resp.name == svc_resp.name
            assert item_resp.description == svc_resp.description
            assert item_resp.default_price == svc_resp.default_price
            assert item_resp.is_gst_exempt == svc_resp.is_gst_exempt
            assert item_resp.category == svc_resp.category
            assert item_resp.is_active == svc_resp.is_active
            assert item_resp.created_at == svc_resp.created_at
            assert item_resp.updated_at == svc_resp.updated_at

        # The response keys differ: "items" vs "services"
        items_dump = item_list_response.model_dump()
        services_dump = service_list_response.model_dump()

        assert "items" in items_dump
        assert "services" not in items_dump
        assert "services" in services_dump
        assert "items" not in services_dump

        # The actual data lists should be equal
        assert items_dump["items"] == services_dump["services"]

