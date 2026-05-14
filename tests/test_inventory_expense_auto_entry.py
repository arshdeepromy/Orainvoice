"""Property-based tests for inventory expense auto-entry feature.

Feature: inventory-expense-auto-entry
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.inventory.stock_items_service import _resolve_gst_mode


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=30, deadline=None)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeCatalogueItem:
    """Minimal catalogue item representation for testing GST mode resolution."""
    gst_mode: Optional[str] = None
    is_gst_exempt: bool = False
    gst_inclusive: bool = False


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

gst_mode_st = st.sampled_from([None, "inclusive", "exclusive", "exempt"])
bool_st = st.booleans()


# ---------------------------------------------------------------------------
# Property 3: GST Mode Resolution
# ---------------------------------------------------------------------------


class TestGSTModeResolution:
    """Property 3: GST Mode Resolution.

    # Feature: inventory-expense-auto-entry, Property 3: GST Mode Resolution

    **Validates: Requirements 5.4**

    For any catalogue item with fields gst_mode, is_gst_exempt, and gst_inclusive,
    the _resolve_gst_mode() function SHALL return:
    - gst_mode if it is not None
    - "exempt" if is_gst_exempt is True (and gst_mode is None)
    - "inclusive" if gst_inclusive is True (and gst_mode is None, is_gst_exempt is False)
    - "exclusive" otherwise
    """

    @PBT_SETTINGS
    @given(
        gst_mode=gst_mode_st,
        is_gst_exempt=bool_st,
        gst_inclusive=bool_st,
    )
    def test_gst_mode_resolution_priority(self, gst_mode, is_gst_exempt, gst_inclusive):
        """Verify correct priority resolution across all field combinations."""
        item = FakeCatalogueItem(
            gst_mode=gst_mode,
            is_gst_exempt=is_gst_exempt,
            gst_inclusive=gst_inclusive,
        )

        result = _resolve_gst_mode(item)

        # Priority 1: explicit gst_mode wins
        if gst_mode is not None:
            assert result == gst_mode
        # Priority 2: is_gst_exempt → "exempt"
        elif is_gst_exempt:
            assert result == "exempt"
        # Priority 3: gst_inclusive → "inclusive"
        elif gst_inclusive:
            assert result == "inclusive"
        # Priority 4: default → "exclusive"
        else:
            assert result == "exclusive"

    @PBT_SETTINGS
    @given(
        gst_mode=gst_mode_st,
        is_gst_exempt=bool_st,
        gst_inclusive=bool_st,
    )
    def test_result_always_valid_gst_mode(self, gst_mode, is_gst_exempt, gst_inclusive):
        """The result is always one of the three valid GST modes."""
        item = FakeCatalogueItem(
            gst_mode=gst_mode,
            is_gst_exempt=is_gst_exempt,
            gst_inclusive=gst_inclusive,
        )

        result = _resolve_gst_mode(item)

        assert result in {"inclusive", "exclusive", "exempt"}


# ---------------------------------------------------------------------------
# Property 2: GST Calculation Correctness
# ---------------------------------------------------------------------------

from decimal import Decimal, ROUND_HALF_UP

from app.modules.inventory.stock_items_service import _calculate_tax_amount

# Strategy: positive Decimal amounts between 0.01 and 999999.99
positive_amount_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

gst_mode_values_st = st.sampled_from(["inclusive", "exclusive", "exempt"])


class TestGSTCalculationCorrectness:
    """Property 2: GST Calculation Correctness.

    # Feature: inventory-expense-auto-entry, Property 2: GST Calculation Correctness

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**

    For any positive amount A and GST mode M in {"inclusive", "exclusive", "exempt"},
    the _calculate_tax_amount(A, M) function SHALL return:
    - M="inclusive": tax_amount == round(A × 3 / 23, 2) with ROUND_HALF_UP, tax_inclusive == True
    - M="exclusive": tax_amount == round(A × 0.15, 2) with ROUND_HALF_UP, tax_inclusive == False
    - M="exempt": tax_amount == 0, tax_inclusive == False
    """

    @PBT_SETTINGS
    @given(amount=positive_amount_st, gst_mode=gst_mode_values_st)
    def test_gst_calculation_formula_correctness(self, amount, gst_mode):
        """Verify formula correctness for each GST mode."""
        two_dp = Decimal("0.01")
        tax_amount, tax_inclusive = _calculate_tax_amount(amount, gst_mode)

        if gst_mode == "inclusive":
            expected_tax = (amount * Decimal("3") / Decimal("23")).quantize(
                two_dp, rounding=ROUND_HALF_UP
            )
            assert tax_amount == expected_tax
            assert tax_inclusive is True
        elif gst_mode == "exclusive":
            expected_tax = (amount * Decimal("0.15")).quantize(
                two_dp, rounding=ROUND_HALF_UP
            )
            assert tax_amount == expected_tax
            assert tax_inclusive is False
        else:  # exempt
            assert tax_amount == Decimal("0")
            assert tax_inclusive is False

    @PBT_SETTINGS
    @given(amount=positive_amount_st, gst_mode=gst_mode_values_st)
    def test_tax_amount_has_at_most_two_decimal_places(self, amount, gst_mode):
        """Verify tax_amount always has at most 2 decimal places."""
        tax_amount, _ = _calculate_tax_amount(amount, gst_mode)

        # Check that quantizing to 2dp doesn't change the value
        assert tax_amount == tax_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @PBT_SETTINGS
    @given(amount=positive_amount_st, gst_mode=gst_mode_values_st)
    def test_tax_amount_is_non_negative(self, amount, gst_mode):
        """Verify tax_amount is always non-negative for positive amounts."""
        tax_amount, _ = _calculate_tax_amount(amount, gst_mode)

        assert tax_amount >= Decimal("0")


# ---------------------------------------------------------------------------
# Property tests for _maybe_create_stock_expense
# ---------------------------------------------------------------------------

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.inventory.stock_items_service import _maybe_create_stock_expense


class _FakeExpenseCreate:
    """Lightweight stand-in for ExpenseCreate that stores kwargs as attributes."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# Strategies for _maybe_create_stock_expense tests
positive_price_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

positive_quantity_st = st.decimals(
    min_value=Decimal("1"),
    max_value=Decimal("9999"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

uuid_st = st.uuids()

optional_uuid_st = st.one_of(st.none(), st.uuids())


def _make_stock_item(purchase_price, branch_id=None):
    """Create a mock StockItem with the given purchase_price and branch_id."""
    item = MagicMock()
    item.id = uuid.uuid4()
    item.purchase_price = purchase_price
    item.branch_id = branch_id
    return item


def _make_movement(reference_id=None):
    """Create a mock StockMovement with the given reference_id."""
    movement = MagicMock()
    movement.id = uuid.uuid4()
    movement.reference_id = reference_id
    movement.reference_type = None
    return movement


def _make_catalogue_item():
    """Create a minimal mock catalogue item."""
    item = MagicMock()
    item.gst_mode = "exclusive"
    item.is_gst_exempt = False
    item.gst_inclusive = False
    item.name = "Test Part"
    return item


# ---------------------------------------------------------------------------
# Property 1: Expense Amount Correctness
# ---------------------------------------------------------------------------


class TestExpenseAmountCorrectness:
    """Property 1: Expense Amount Correctness.

    # Feature: inventory-expense-auto-entry, Property 1: Expense Amount Correctness

    **Validates: Requirements 1.1, 2.1**

    For any stock operation where the stock item has a purchase_price P > 0
    and the org setting is enabled, the auto-created expense SHALL have
    amount == P × Q.
    """

    @PBT_SETTINGS
    @given(
        purchase_price=positive_price_st,
        quantity=positive_quantity_st,
    )
    @pytest.mark.asyncio
    async def test_expense_amount_equals_price_times_quantity(
        self, purchase_price, quantity
    ):
        """Verify amount == purchase_price × quantity for all valid inputs."""
        stock_item = _make_stock_item(purchase_price=purchase_price)
        movement = _make_movement(reference_id=None)
        catalogue_item = _make_catalogue_item()

        mock_expense = MagicMock()
        mock_expense.id = uuid.uuid4()

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_instance

        with patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            mock_db = AsyncMock()

            await _maybe_create_stock_expense(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                stock_item=stock_item,
                movement=movement,
                catalogue_item=catalogue_item,
                quantity=quantity,
                description="Test purchase",
            )

            # Verify create_expense was called
            mock_instance.create_expense.assert_called_once()
            call_args = mock_instance.create_expense.call_args

            # The payload is the second positional arg (after org_id)
            payload = call_args[0][1]
            expected_amount = purchase_price * quantity
            assert payload.amount == expected_amount


# ---------------------------------------------------------------------------
# Property 4: Bidirectional Traceability
# ---------------------------------------------------------------------------


class TestBidirectionalTraceability:
    """Property 4: Bidirectional Traceability.

    # Feature: inventory-expense-auto-entry, Property 4: Bidirectional Traceability

    **Validates: Requirements 3.1, 3.2, 3.3, 9.1**

    For any auto-created expense, the expense's reference_number SHALL equal
    f"SM:{movement.id}", and the movement's reference_id SHALL equal the
    expense's id with reference_type == "expense".
    """

    @PBT_SETTINGS
    @given(
        movement_id=uuid_st,
        expense_id=uuid_st,
    )
    @pytest.mark.asyncio
    async def test_reference_number_format_and_movement_linkage(
        self, movement_id, expense_id
    ):
        """Verify reference_number == f'SM:{movement.id}' and movement linkage."""
        stock_item = _make_stock_item(purchase_price=Decimal("10.00"))
        movement = MagicMock()
        movement.id = movement_id
        movement.reference_id = None
        movement.reference_type = None
        catalogue_item = _make_catalogue_item()

        mock_expense = MagicMock()
        mock_expense.id = expense_id

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_instance

        with patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            mock_db = AsyncMock()

            await _maybe_create_stock_expense(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                stock_item=stock_item,
                movement=movement,
                catalogue_item=catalogue_item,
                quantity=Decimal("1"),
                description="Test purchase",
            )

            # Verify reference_number format
            call_args = mock_instance.create_expense.call_args
            payload = call_args[0][1]
            assert payload.reference_number == f"SM:{movement_id}"

            # Verify movement linkage
            assert movement.reference_id == expense_id
            assert movement.reference_type == "expense"


# ---------------------------------------------------------------------------
# Property 5: Branch Inheritance
# ---------------------------------------------------------------------------


class TestBranchInheritance:
    """Property 5: Branch Inheritance.

    # Feature: inventory-expense-auto-entry, Property 5: Branch Inheritance

    **Validates: Requirements 4.1, 4.2, 11.3, 11.4**

    For any stock item created with a branch_id value B (including None),
    the auto-created expense's branch_id SHALL equal B.
    """

    @PBT_SETTINGS
    @given(branch_id=optional_uuid_st)
    @pytest.mark.asyncio
    async def test_expense_branch_id_matches_stock_item_branch_id(self, branch_id):
        """Verify expense branch_id matches stock_item.branch_id."""
        stock_item = _make_stock_item(
            purchase_price=Decimal("25.00"), branch_id=branch_id
        )
        movement = _make_movement(reference_id=None)
        catalogue_item = _make_catalogue_item()

        mock_expense = MagicMock()
        mock_expense.id = uuid.uuid4()

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_instance

        with patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            mock_db = AsyncMock()

            await _maybe_create_stock_expense(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                stock_item=stock_item,
                movement=movement,
                catalogue_item=catalogue_item,
                quantity=Decimal("1"),
                description="Test purchase",
            )

            # Verify branch_id passed to create_expense matches stock_item.branch_id
            call_args = mock_instance.create_expense.call_args
            # branch_id is passed as keyword arg
            assert call_args[1]["branch_id"] == branch_id


# ---------------------------------------------------------------------------
# Property 6: Opt-Out Setting Disables Expense Creation
# ---------------------------------------------------------------------------


class TestOptOutSettingDisablesExpenseCreation:
    """Property 6: Opt-Out Setting Disables Expense Creation.

    # Feature: inventory-expense-auto-entry, Property 6: Opt-Out Setting Disables Expense Creation

    **Validates: Requirements 6.3, 6.4**

    For any stock operation where the org setting auto_expense_on_stock_purchase
    is explicitly False, no expense SHALL be created regardless of purchase_price
    or quantity values.
    """

    @PBT_SETTINGS
    @given(
        purchase_price=positive_price_st,
        quantity=positive_quantity_st,
    )
    @pytest.mark.asyncio
    async def test_no_expense_when_setting_is_false(self, purchase_price, quantity):
        """Verify no expense is created when setting is False."""
        stock_item = _make_stock_item(purchase_price=purchase_price)
        movement = _make_movement(reference_id=None)
        catalogue_item = _make_catalogue_item()

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": False}
        )
        mock_expense_svc_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_instance

        with patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            mock_db = AsyncMock()

            await _maybe_create_stock_expense(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                stock_item=stock_item,
                movement=movement,
                catalogue_item=catalogue_item,
                quantity=quantity,
                description="Test purchase",
            )

            # Verify create_expense was NOT called
            mock_instance.create_expense.assert_not_called()


# ---------------------------------------------------------------------------
# Property 9: Idempotency — No Duplicate Expense
# ---------------------------------------------------------------------------


class TestIdempotencyNoDuplicateExpense:
    """Property 9: Idempotency — No Duplicate Expense.

    # Feature: inventory-expense-auto-entry, Property 9: Idempotency — No Duplicate Expense

    **Validates: Requirements 10.2**

    For any stock movement where reference_id is already set (non-null),
    calling _maybe_create_stock_expense() SHALL not create a new expense
    and SHALL not modify the existing reference_id.
    """

    @PBT_SETTINGS
    @given(
        existing_ref_id=uuid_st,
        purchase_price=positive_price_st,
        quantity=positive_quantity_st,
    )
    @pytest.mark.asyncio
    async def test_no_expense_when_reference_id_already_set(
        self, existing_ref_id, purchase_price, quantity
    ):
        """Verify no new expense when movement.reference_id is already set."""
        stock_item = _make_stock_item(purchase_price=purchase_price)
        movement = _make_movement(reference_id=existing_ref_id)
        # Store original reference_id to verify it's not modified
        original_ref_id = movement.reference_id
        catalogue_item = _make_catalogue_item()

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_instance

        with patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            mock_db = AsyncMock()

            await _maybe_create_stock_expense(
                mock_db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                stock_item=stock_item,
                movement=movement,
                catalogue_item=catalogue_item,
                quantity=quantity,
                description="Test purchase",
            )

            # Verify create_expense was NOT called
            mock_instance.create_expense.assert_not_called()

            # Verify reference_id was not modified
            assert movement.reference_id == original_ref_id


# ---------------------------------------------------------------------------
# Property 8: Deletion Flags Linked Expenses
# ---------------------------------------------------------------------------

from app.modules.inventory.stock_items_service import delete_stock_item


class TestDeletionFlagsLinkedExpenses:
    """Property 8: Deletion Flags Linked Expenses.

    # Feature: inventory-expense-auto-entry, Property 8: Deletion Flags Linked Expenses

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**

    For any stock item with N linked expenses (via movements with
    reference_type='expense'), calling delete_stock_item() SHALL append
    " [Stock item deleted]" to each linked expense's notes field without
    deleting the expense records.
    """

    @PBT_SETTINGS
    @given(
        num_expenses=st.integers(min_value=0, max_value=5),
        existing_notes=st.lists(
            st.one_of(st.none(), st.text(min_size=0, max_size=50)),
            min_size=0,
            max_size=5,
        ),
    )
    @pytest.mark.asyncio
    async def test_deletion_appends_flag_to_all_linked_expenses(
        self, num_expenses, existing_notes
    ):
        """Verify ' [Stock item deleted]' is appended to notes of all linked expenses."""
        # Align existing_notes list length with num_expenses
        notes_list = existing_notes[:num_expenses]
        while len(notes_list) < num_expenses:
            notes_list.append(None)

        stock_item_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # Create mock stock item
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id

        # Create mock linked movements with expense references
        mock_movements = []
        for _ in range(num_expenses):
            mov = MagicMock()
            mov.reference_id = uuid.uuid4()
            mov.reference_type = "expense"
            mock_movements.append(mov)

        # Create mock expenses with existing notes (use simple object to track mutation)
        class SimpleExpense:
            def __init__(self, expense_id, notes):
                self.id = expense_id
                self.notes = notes

        mock_expenses = []
        for i in range(num_expenses):
            expense = SimpleExpense(
                expense_id=mock_movements[i].reference_id,
                notes=notes_list[i],
            )
            mock_expenses.append(expense)

        # Track whether db.delete was called (stock item deletion)
        deleted_objects = []

        # Build mock db session
        mock_db = AsyncMock()

        # We need to track call order to db.execute to return appropriate results
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Second call: linked movements query
                result.scalars.return_value.all.return_value = mock_movements
            else:
                # Subsequent calls: expense lookups (one per movement)
                expense_idx = call_idx - 2
                if expense_idx < len(mock_expenses):
                    result.scalar_one_or_none.return_value = mock_expenses[expense_idx]
                else:
                    result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.flush = AsyncMock()

        async def mock_delete(obj):
            deleted_objects.append(obj)

        mock_db.delete = AsyncMock(side_effect=mock_delete)

        await delete_stock_item(mock_db, org_id, stock_item_id)

        # PROPERTY: Each linked expense has " [Stock item deleted]" appended to notes
        for i in range(num_expenses):
            original_notes = notes_list[i] or ""
            expected_notes = original_notes + " [Stock item deleted]"
            assert mock_expenses[i].notes == expected_notes, (
                f"Expense {i}: expected notes={expected_notes!r}, "
                f"got {mock_expenses[i].notes!r}"
            )

        # PROPERTY: Expenses are NOT deleted (only the stock item is deleted)
        assert mock_stock_item in deleted_objects, "Stock item should be deleted"
        for expense in mock_expenses:
            assert expense not in deleted_objects, "Expenses should NOT be deleted"

    @PBT_SETTINGS
    @given(data=st.data())
    @pytest.mark.asyncio
    async def test_deletion_proceeds_normally_when_no_linked_expenses(self, data):
        """Verify deletion proceeds normally when no linked expenses exist."""
        stock_item_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # Create mock stock item
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id

        # No linked movements
        deleted_objects = []

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # Stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Linked movements query — empty
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.flush = AsyncMock()

        async def mock_delete(obj):
            deleted_objects.append(obj)

        mock_db.delete = AsyncMock(side_effect=mock_delete)

        await delete_stock_item(mock_db, org_id, stock_item_id)

        # PROPERTY: Stock item is still deleted even with no linked expenses
        assert mock_stock_item in deleted_objects, "Stock item should be deleted"
        # PROPERTY: flush is called for the deletion
        assert mock_db.flush.called


# ---------------------------------------------------------------------------
# Integration Tests: create_stock_item → verify expense created
# ---------------------------------------------------------------------------

from datetime import date

from app.modules.inventory.stock_items_schemas import CreateStockItemRequest


def _make_mock_stock_item_cls():
    """Create a mock StockItem class that avoids SQLAlchemy mapper initialization.

    Returns a class whose instances are simple namespace objects with the
    same attributes that create_stock_item() sets.
    """
    from datetime import datetime

    class MockStockItem:
        def __init__(self, **kwargs):
            self.id = None
            self.reserved_quantity = Decimal("0")
            self.created_at = datetime.now()
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockStockItem


def _make_mock_movement_cls():
    """Create a mock StockMovement class that avoids SQLAlchemy mapper initialization."""

    class MockStockMovement:
        def __init__(self, **kwargs):
            self.id = None
            self.reference_id = None
            self.reference_type = None
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockStockMovement


class TestIntegrationCreateStockItemExpense:
    """Integration test: create stock item → verify expense created with correct fields.

    # Feature: inventory-expense-auto-entry, Integration Tests

    **Validates: Requirements 1.1–1.8, 3.1–3.3, 4.1–4.2, 5.1–5.3, 9.1, 10.1–10.3**

    Tests the full create_stock_item() function with mocked DB and services,
    verifying that the auto-expense is created with all correct fields.
    """

    @pytest.mark.asyncio
    async def test_create_stock_item_creates_expense_with_correct_fields(self):
        """Verify full flow: create stock item → expense created with correct fields.

        Checks: amount, category, description, reference_number, notes,
        branch_id, created_by, tax_amount, tax_inclusive, movement linkage.
        """
        from app.modules.inventory.stock_items_service import create_stock_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()
        expense_id = uuid.uuid4()

        # Build a mock catalogue item (PartsCatalogue)
        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Brake Pad Set"
        mock_catalogue_item.part_number = "BP-001"
        mock_catalogue_item.brand = "Brembo"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.supplier_id = None
        mock_catalogue_item.min_stock_threshold = 5
        mock_catalogue_item.reorder_quantity = 10

        # Build the payload
        payload = CreateStockItemRequest(
            catalogue_item_id=catalogue_item_id,
            catalogue_type="part",
            quantity=10,
            reason="Initial stock purchase",
            purchase_price=25.50,
        )

        # Track objects added to the session
        added_objects = []
        stock_item_holder = [None]
        movement_holder = [None]

        # Mock expense returned by ExpenseService.create_expense
        mock_expense = MagicMock()
        mock_expense.id = expense_id

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_expense_instance

        # Build mock db session
        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: catalogue item lookup
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                # Supplier name lookup (returns None)
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockStockItem = _make_mock_stock_item_cls()
        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            added_objects.append(obj)
            if isinstance(obj, MockStockItem):
                stock_item_holder[0] = obj
            elif isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 1 and stock_item_holder[0] is not None:
                if stock_item_holder[0].id is None:
                    stock_item_holder[0].id = uuid.uuid4()
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        async def mock_refresh(obj):
            from datetime import datetime
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch(
            "app.modules.inventory.stock_items_service.StockItem", MockStockItem
        ), patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await create_stock_item(
                mock_db, org_id, user_id, payload, branch_id=branch_id
            )

        # Verify create_expense was called
        mock_expense_instance.create_expense.assert_called_once()
        call_args = mock_expense_instance.create_expense.call_args

        # The payload is the second positional arg (after org_id)
        expense_payload = call_args[0][1]
        called_org_id = call_args[0][0]

        # 1. expense.amount == purchase_price × quantity
        expected_amount = Decimal("25.50") * Decimal("10")
        assert expense_payload.amount == expected_amount, (
            f"Expected amount={expected_amount}, got {expense_payload.amount}"
        )

        # 2. expense.category == "materials"
        assert expense_payload.category == "materials"

        # 3. expense.description starts with "Inventory purchase:"
        assert expense_payload.description.startswith("Inventory purchase:")
        assert "Brake Pad Set" in expense_payload.description

        # 4. expense.reference_number == f"SM:{movement.id}"
        movement = movement_holder[0]
        assert expense_payload.reference_number == f"SM:{movement.id}"

        # 5. expense.notes contains stock item name and id
        stock_item = stock_item_holder[0]
        assert "Brake Pad Set" in expense_payload.notes
        assert str(stock_item.id) in expense_payload.notes

        # 6. expense.branch_id == stock_item.branch_id
        assert call_args[1]["branch_id"] == branch_id

        # 7. expense.created_by == user_id
        assert call_args[1]["created_by"] == user_id

        # 8. tax_amount and tax_inclusive match GST mode (exclusive)
        # For exclusive: tax_amount = amount * 0.15
        expected_tax = (expected_amount * Decimal("0.15")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert expense_payload.tax_amount == expected_tax
        assert expense_payload.tax_inclusive is False

        # 9. movement.reference_id == expense.id
        assert movement.reference_id == expense_id

        # 10. movement.reference_type == "expense"
        assert movement.reference_type == "expense"

        # Verify org_id passed correctly
        assert called_org_id == org_id

        # Verify expense_type and date
        assert expense_payload.expense_type == "expense"
        assert expense_payload.date == date.today()

    @pytest.mark.asyncio
    async def test_create_stock_item_gst_inclusive_tax_calculation(self):
        """Verify tax calculation for GST inclusive catalogue item."""
        from app.modules.inventory.stock_items_service import create_stock_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()
        expense_id = uuid.uuid4()

        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Oil Filter"
        mock_catalogue_item.part_number = "OF-100"
        mock_catalogue_item.brand = "Ryco"
        mock_catalogue_item.gst_mode = "inclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = True
        mock_catalogue_item.supplier_id = None
        mock_catalogue_item.min_stock_threshold = 0
        mock_catalogue_item.reorder_quantity = 0

        payload = CreateStockItemRequest(
            catalogue_item_id=catalogue_item_id,
            catalogue_type="part",
            quantity=5,
            reason="Restock",
            purchase_price=23.00,
        )

        stock_item_holder = [None]
        movement_holder = [None]

        mock_expense = MagicMock()
        mock_expense.id = expense_id

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_expense_instance

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1
            result = MagicMock()
            if call_idx == 0:
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockStockItem = _make_mock_stock_item_cls()
        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockStockItem):
                stock_item_holder[0] = obj
            elif isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 1 and stock_item_holder[0] is not None:
                if stock_item_holder[0].id is None:
                    stock_item_holder[0].id = uuid.uuid4()
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        async def mock_refresh(obj):
            from datetime import datetime
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch(
            "app.modules.inventory.stock_items_service.StockItem", MockStockItem
        ), patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await create_stock_item(
                mock_db, org_id, user_id, payload, branch_id=None
            )

        # Verify tax calculation for inclusive mode
        mock_expense_instance.create_expense.assert_called_once()
        call_args = mock_expense_instance.create_expense.call_args
        expense_payload = call_args[0][1]

        expected_amount = Decimal("23.00") * Decimal("5")  # 115.00
        expected_tax = (expected_amount * Decimal("3") / Decimal("23")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        assert expense_payload.amount == expected_amount
        assert expense_payload.tax_amount == expected_tax
        assert expense_payload.tax_inclusive is True

        # branch_id should be None
        assert call_args[1]["branch_id"] is None

    @pytest.mark.asyncio
    async def test_create_stock_item_no_expense_when_zero_purchase_price(self):
        """Verify no expense is created when purchase_price is zero or None."""
        from app.modules.inventory.stock_items_service import create_stock_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()

        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Free Sample"
        mock_catalogue_item.part_number = "FS-001"
        mock_catalogue_item.brand = "Generic"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.supplier_id = None
        mock_catalogue_item.min_stock_threshold = 0
        mock_catalogue_item.reorder_quantity = 0

        # purchase_price = None (no expense should be created)
        payload = CreateStockItemRequest(
            catalogue_item_id=catalogue_item_id,
            catalogue_type="part",
            quantity=3,
            reason="Free sample received",
            purchase_price=None,
        )

        stock_item_holder = [None]
        movement_holder = [None]

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_expense_instance

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1
            result = MagicMock()
            if call_idx == 0:
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockStockItem = _make_mock_stock_item_cls()
        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockStockItem):
                stock_item_holder[0] = obj
            elif isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 1 and stock_item_holder[0] is not None:
                if stock_item_holder[0].id is None:
                    stock_item_holder[0].id = uuid.uuid4()
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        async def mock_refresh(obj):
            from datetime import datetime
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch(
            "app.modules.inventory.stock_items_service.StockItem", MockStockItem
        ), patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await create_stock_item(
                mock_db, org_id, user_id, payload, branch_id=None
            )

        # Verify create_expense was NOT called (no purchase price)
        mock_expense_instance.create_expense.assert_not_called()

        # Verify stock item was still created successfully
        assert result is not None


# ---------------------------------------------------------------------------
# Property 7: Resilience — Expense Failure Does Not Fail Parent Operation
# ---------------------------------------------------------------------------


class TestResilienceExpenseFailureDoesNotFailParent:
    """Property 7: Resilience — Expense Failure Does Not Fail Parent Operation.

    # Feature: inventory-expense-auto-entry, Property 7: Resilience

    **Validates: Requirements 1.8, 2.5**

    For any stock operation where ExpenseService.create_expense() raises an
    exception, the parent operation (create_stock_item) SHALL still complete
    successfully — the stock item and movement are committed.
    """

    @PBT_SETTINGS
    @given(
        purchase_price=positive_price_st,
        quantity=st.decimals(
            min_value=Decimal("1"),
            max_value=Decimal("100"),
            places=0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @pytest.mark.asyncio
    async def test_stock_item_created_despite_expense_service_failure(
        self, purchase_price, quantity
    ):
        """Verify create_stock_item() succeeds even when ExpenseService raises."""
        from app.modules.inventory.stock_items_service import create_stock_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()

        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Test Part"
        mock_catalogue_item.part_number = "TP-001"
        mock_catalogue_item.brand = "TestBrand"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.supplier_id = None
        mock_catalogue_item.min_stock_threshold = 0
        mock_catalogue_item.reorder_quantity = 0

        payload = CreateStockItemRequest(
            catalogue_item_id=catalogue_item_id,
            catalogue_type="part",
            quantity=float(quantity),
            reason="Test purchase",
            purchase_price=float(purchase_price),
        )

        stock_item_holder = [None]
        movement_holder = [None]

        # Mock ExpenseService to RAISE an exception
        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock(
            side_effect=RuntimeError("Database connection lost")
        )
        mock_expense_svc_cls.return_value = mock_expense_instance

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1
            result = MagicMock()
            if call_idx == 0:
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockStockItem = _make_mock_stock_item_cls()
        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockStockItem):
                stock_item_holder[0] = obj
            elif isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 1 and stock_item_holder[0] is not None:
                if stock_item_holder[0].id is None:
                    stock_item_holder[0].id = uuid.uuid4()
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        async def mock_refresh(obj):
            from datetime import datetime
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch(
            "app.modules.inventory.stock_items_service.StockItem", MockStockItem
        ), patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            # This should NOT raise — resilience guarantee
            result = await create_stock_item(
                mock_db, org_id, user_id, payload, branch_id=branch_id
            )

        # PROPERTY: Stock item was created successfully despite expense failure
        assert result is not None
        assert stock_item_holder[0] is not None
        assert stock_item_holder[0].id is not None

        # PROPERTY: Movement was created
        assert movement_holder[0] is not None
        assert movement_holder[0].id is not None

        # PROPERTY: No exception propagated (we reached this point)
        # The expense service was called but failed — that's fine
        mock_expense_instance.create_expense.assert_called_once()

        # PROPERTY: Movement reference_id should NOT be set (expense failed)
        assert movement_holder[0].reference_id is None


# ---------------------------------------------------------------------------
# Integration Tests: adjust_stock_item → verify expense created
# ---------------------------------------------------------------------------

from app.modules.inventory.stock_items_service import adjust_stock_item
from app.modules.inventory.stock_items_schemas import AdjustStockItemRequest


class TestIntegrationAdjustStockItemExpense:
    """Integration test: adjust stock item → verify expense created.

    # Feature: inventory-expense-auto-entry, Integration Tests

    **Validates: Requirements 2.1–2.5**

    Tests the full adjust_stock_item() function with mocked DB and services,
    verifying that the auto-expense is created for positive adjustments and
    skipped for negative adjustments or zero purchase_price.
    """

    @pytest.mark.asyncio
    async def test_positive_adjustment_creates_expense(self):
        """Verify: positive adjustment with purchase_price → expense created.

        Checks: amount = purchase_price × quantity_change,
        description starts with "Stock adjustment: +5x".
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()
        expense_id = uuid.uuid4()

        # Build a mock stock item (returned by db.execute for the stock item query)
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id
        mock_stock_item.org_id = org_id
        mock_stock_item.current_quantity = Decimal("10")
        mock_stock_item.purchase_price = Decimal("15.00")
        mock_stock_item.catalogue_type = "part"
        mock_stock_item.catalogue_item_id = catalogue_item_id
        mock_stock_item.branch_id = branch_id

        # Build a mock catalogue item (returned for GST resolution)
        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Brake Pad Set"
        mock_catalogue_item.part_number = "BP-001"
        mock_catalogue_item.brand = "Brembo"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.is_active = True

        # Build the adjustment payload: +5
        payload = AdjustStockItemRequest(
            quantity_change=5,
            reason="Restocking from supplier",
        )

        # Track movement creation
        movement_holder = [None]

        # Mock expense returned by ExpenseService.create_expense
        mock_expense = MagicMock()
        mock_expense.id = expense_id

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock(return_value=mock_expense)
        mock_expense_svc_cls.return_value = mock_expense_instance

        # Build mock db session
        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Second call: catalogue item lookup (for positive adjustment)
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            # Second flush assigns movement.id
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        with patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await adjust_stock_item(
                mock_db, org_id, user_id, stock_item_id, payload
            )

        # Verify the adjustment result
        assert result["stock_item_id"] == str(stock_item_id)
        assert result["previous_quantity"] == 10.0
        assert result["new_quantity"] == 15.0
        assert result["quantity_change"] == 5

        # Verify create_expense was called
        mock_expense_instance.create_expense.assert_called_once()
        call_args = mock_expense_instance.create_expense.call_args

        # The payload is the second positional arg (after org_id)
        expense_payload = call_args[0][1]

        # 1. expense.amount == purchase_price × quantity_change = 15.00 × 5 = 75.00
        expected_amount = Decimal("15.00") * Decimal("5")
        assert expense_payload.amount == expected_amount

        # 2. expense.description starts with "Stock adjustment: +5x"
        assert expense_payload.description.startswith("Stock adjustment: +5")
        assert "Brake Pad Set" in expense_payload.description

        # 3. expense.category == "materials"
        assert expense_payload.category == "materials"

        # 4. expense.reference_number == f"SM:{movement.id}"
        movement = movement_holder[0]
        assert expense_payload.reference_number == f"SM:{movement.id}"

        # 5. expense.branch_id == stock_item.branch_id
        assert call_args[1]["branch_id"] == branch_id

        # 6. expense.created_by == user_id
        assert call_args[1]["created_by"] == user_id

        # 7. tax_amount for exclusive mode: amount * 0.15
        expected_tax = (expected_amount * Decimal("0.15")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert expense_payload.tax_amount == expected_tax
        assert expense_payload.tax_inclusive is False

        # 8. movement linkage
        assert movement.reference_id == expense_id
        assert movement.reference_type == "expense"

    @pytest.mark.asyncio
    async def test_negative_adjustment_no_expense(self):
        """Verify: negative adjustment → no expense created.

        A stock reduction (e.g., -3) should never trigger expense creation.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()

        # Build a mock stock item with sufficient quantity
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id
        mock_stock_item.org_id = org_id
        mock_stock_item.current_quantity = Decimal("10")
        mock_stock_item.purchase_price = Decimal("20.00")
        mock_stock_item.catalogue_type = "part"
        mock_stock_item.catalogue_item_id = catalogue_item_id
        mock_stock_item.branch_id = None

        # Build the adjustment payload: -3
        payload = AdjustStockItemRequest(
            quantity_change=-3,
            reason="Damaged stock removed",
        )

        movement_holder = [None]

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_expense_instance

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # Stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        with patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await adjust_stock_item(
                mock_db, org_id, user_id, stock_item_id, payload
            )

        # Verify the adjustment result
        assert result["stock_item_id"] == str(stock_item_id)
        assert result["previous_quantity"] == 10.0
        assert result["new_quantity"] == 7.0
        assert result["quantity_change"] == -3

        # Verify create_expense was NOT called (negative adjustment)
        mock_expense_instance.create_expense.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_purchase_price_no_expense(self):
        """Verify: positive adjustment with purchase_price=0 → no expense created.

        Even with a positive quantity_change, if purchase_price is 0 (or None),
        no expense should be created.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()

        # Build a mock stock item with purchase_price = 0
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id
        mock_stock_item.org_id = org_id
        mock_stock_item.current_quantity = Decimal("5")
        mock_stock_item.purchase_price = Decimal("0")
        mock_stock_item.catalogue_type = "part"
        mock_stock_item.catalogue_item_id = catalogue_item_id
        mock_stock_item.branch_id = None

        # Build a mock catalogue item
        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Free Widget"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.is_active = True

        # Build the adjustment payload: +5 (positive, but purchase_price is 0)
        payload = AdjustStockItemRequest(
            quantity_change=5,
            reason="Free stock received",
        )

        movement_holder = [None]

        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": True}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_expense_instance

        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # Stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Catalogue item lookup (positive adjustment triggers this)
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        with patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await adjust_stock_item(
                mock_db, org_id, user_id, stock_item_id, payload
            )

        # Verify the adjustment result (stock still adjusted)
        assert result["stock_item_id"] == str(stock_item_id)
        assert result["previous_quantity"] == 5.0
        assert result["new_quantity"] == 10.0
        assert result["quantity_change"] == 5

        # Verify create_expense was NOT called (purchase_price is 0)
        mock_expense_instance.create_expense.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Tests: delete_stock_item → verify expense notes flagged
# ---------------------------------------------------------------------------


class TestIntegrationDeleteStockItemFlagsExpenses:
    """Integration test: delete stock item → verify expense notes flagged.

    # Feature: inventory-expense-auto-entry, Integration Tests

    **Validates: Requirements 8.1–8.4**

    Tests the full delete_stock_item() function with mocked DB,
    verifying that linked expenses have " [Stock item deleted]" appended
    to their notes field and that the stock item is deleted.
    """

    @pytest.mark.asyncio
    async def test_delete_stock_item_flags_linked_expense_notes(self):
        """Verify: delete stock item with 1 linked expense → notes flagged.

        Creates a stock item with 1 linked expense (movement with
        reference_type="expense" and reference_id set), deletes it,
        verifies " [Stock item deleted]" is appended to the expense's notes.
        """
        stock_item_id = uuid.uuid4()
        org_id = uuid.uuid4()
        expense_id = uuid.uuid4()

        # Create mock stock item
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id

        # Create mock linked movement with expense reference
        mock_movement = MagicMock()
        mock_movement.reference_id = expense_id
        mock_movement.reference_type = "expense"

        # Create mock expense with existing notes (use simple object to track mutation)
        class SimpleExpense:
            def __init__(self, eid, notes):
                self.id = eid
                self.notes = notes

        mock_expense = SimpleExpense(expense_id, "Auto-created for stock item: Brake Pad Set")

        # Track deleted objects
        deleted_objects = []

        # Build mock db session
        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Second call: linked movements query
                result.scalars.return_value.all.return_value = [mock_movement]
            elif call_idx == 2:
                # Third call: expense lookup for the linked movement
                result.scalar_one_or_none.return_value = mock_expense
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.flush = AsyncMock()

        async def mock_delete(obj):
            deleted_objects.append(obj)

        mock_db.delete = AsyncMock(side_effect=mock_delete)

        await delete_stock_item(mock_db, org_id, stock_item_id)

        # Verify " [Stock item deleted]" was appended to expense notes
        expected_notes = "Auto-created for stock item: Brake Pad Set [Stock item deleted]"
        assert mock_expense.notes == expected_notes, (
            f"Expected notes={expected_notes!r}, got {mock_expense.notes!r}"
        )

        # Verify stock item was deleted
        assert mock_stock_item in deleted_objects, "Stock item should be deleted"

        # Verify expense was NOT deleted
        assert mock_expense not in deleted_objects, "Expense should NOT be deleted"

        # Verify flush was called (at least once for flagging, once for deletion)
        assert mock_db.flush.call_count >= 2

    @pytest.mark.asyncio
    async def test_delete_stock_item_no_linked_expenses_proceeds_normally(self):
        """Verify: delete stock item with no linked expenses → deletion proceeds.

        When the movements query returns empty (no linked expenses),
        the stock item is still deleted without error.
        """
        stock_item_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # Create mock stock item
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_item_id

        # Track deleted objects
        deleted_objects = []

        # Build mock db session
        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: stock item lookup
                result.scalar_one_or_none.return_value = mock_stock_item
            elif call_idx == 1:
                # Second call: linked movements query — empty
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.flush = AsyncMock()

        async def mock_delete(obj):
            deleted_objects.append(obj)

        mock_db.delete = AsyncMock(side_effect=mock_delete)

        await delete_stock_item(mock_db, org_id, stock_item_id)

        # Verify stock item was deleted
        assert mock_stock_item in deleted_objects, "Stock item should be deleted"

        # Verify flush was called (for the deletion)
        assert mock_db.flush.called

        # Verify db.delete was called exactly once (only the stock item)
        assert mock_db.delete.call_count == 1


# ---------------------------------------------------------------------------
# Integration Tests: setting disabled → no expense created
# ---------------------------------------------------------------------------


class TestIntegrationSettingDisabledNoExpense:
    """Integration test: setting disabled → no expense created.

    # Feature: inventory-expense-auto-entry, Integration Tests

    **Validates: Requirements 6.3, 6.4**

    Tests the full create_stock_item() function with the org setting
    auto_expense_on_stock_purchase set to False, verifying that no expense
    is created but the stock item is still created successfully.
    """

    @pytest.mark.asyncio
    async def test_no_expense_when_setting_disabled(self):
        """Verify: auto_expense_on_stock_purchase=False → no expense created.

        Sets the org setting to False, creates a stock item with a valid
        purchase_price, and verifies that ExpenseService.create_expense is
        NOT called while the stock item is still created successfully.
        """
        from app.modules.inventory.stock_items_service import create_stock_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        catalogue_item_id = uuid.uuid4()

        # Build a mock catalogue item (PartsCatalogue)
        mock_catalogue_item = MagicMock()
        mock_catalogue_item.name = "Brake Pad Set"
        mock_catalogue_item.part_number = "BP-001"
        mock_catalogue_item.brand = "Brembo"
        mock_catalogue_item.gst_mode = "exclusive"
        mock_catalogue_item.is_gst_exempt = False
        mock_catalogue_item.gst_inclusive = False
        mock_catalogue_item.supplier_id = None
        mock_catalogue_item.min_stock_threshold = 5
        mock_catalogue_item.reorder_quantity = 10

        # Build the payload with a valid purchase_price
        payload = CreateStockItemRequest(
            catalogue_item_id=catalogue_item_id,
            catalogue_type="part",
            quantity=10,
            reason="Initial stock purchase",
            purchase_price=25.50,
        )

        # Track objects added to the session
        stock_item_holder = [None]
        movement_holder = [None]

        # Mock get_org_settings to return auto_expense_on_stock_purchase = False
        mock_get_settings = AsyncMock(
            return_value={"auto_expense_on_stock_purchase": False}
        )
        mock_expense_svc_cls = MagicMock()
        mock_expense_instance = MagicMock()
        mock_expense_instance.create_expense = AsyncMock()
        mock_expense_svc_cls.return_value = mock_expense_instance

        # Build mock db session
        mock_db = AsyncMock()
        execute_call_count = [0]

        async def mock_execute(query):
            call_idx = execute_call_count[0]
            execute_call_count[0] += 1

            result = MagicMock()
            if call_idx == 0:
                # First call: catalogue item lookup
                result.scalar_one_or_none.return_value = mock_catalogue_item
            else:
                # Supplier name lookup (returns None)
                result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        MockStockItem = _make_mock_stock_item_cls()
        MockMovement = _make_mock_movement_cls()

        def mock_add(obj):
            if isinstance(obj, MockStockItem):
                stock_item_holder[0] = obj
            elif isinstance(obj, MockMovement):
                movement_holder[0] = obj

        mock_db.add = MagicMock(side_effect=mock_add)

        flush_count = [0]

        async def mock_flush():
            flush_count[0] += 1
            if flush_count[0] == 1 and stock_item_holder[0] is not None:
                if stock_item_holder[0].id is None:
                    stock_item_holder[0].id = uuid.uuid4()
            if flush_count[0] == 2 and movement_holder[0] is not None:
                if movement_holder[0].id is None:
                    movement_holder[0].id = uuid.uuid4()

        mock_db.flush = AsyncMock(side_effect=mock_flush)

        async def mock_refresh(obj):
            from datetime import datetime
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now()

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch(
            "app.modules.inventory.stock_items_service.StockItem", MockStockItem
        ), patch(
            "app.modules.inventory.stock_items_service.StockMovement", MockMovement
        ), patch.dict(
            "sys.modules",
            {
                "app.modules.organisations": MagicMock(),
                "app.modules.organisations.service": MagicMock(
                    get_org_settings=mock_get_settings
                ),
                "app.modules.expenses": MagicMock(),
                "app.modules.expenses.schemas": MagicMock(
                    ExpenseCreate=_FakeExpenseCreate
                ),
                "app.modules.expenses.service": MagicMock(
                    ExpenseService=mock_expense_svc_cls
                ),
            },
        ):
            result = await create_stock_item(
                mock_db, org_id, user_id, payload, branch_id=branch_id
            )

        # Verify create_expense was NOT called (setting is disabled)
        mock_expense_instance.create_expense.assert_not_called()

        # Verify stock item was still created successfully
        assert result is not None
        assert stock_item_holder[0] is not None
        assert stock_item_holder[0].id is not None

        # Verify movement was still created
        assert movement_holder[0] is not None
        assert movement_holder[0].id is not None

        # Verify movement.reference_id is NOT set (no expense was created)
        assert movement_holder[0].reference_id is None
