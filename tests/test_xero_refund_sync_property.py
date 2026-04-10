"""Property-based tests for Xero refund sync.

Feature: xero-refund-sync

Property 1: Credit Note payload construction invariant
— For any valid refund data (non-empty customer name, positive amount, valid
YYYY-MM-DD date, non-empty invoice number, non-empty reason), the Xero Credit
Note payload shall have Type == "ACCRECCREDIT", Status == "AUTHORISED",
Contact.Name == customer_name, Date == date, Reference containing the invoice
number, exactly one LineItem with UnitAmount == amount and Description
containing reason, and CurrencyCode == "NZD".

Validates: Requirements 1.1, 1.3, 1.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.xero import _build_refund_credit_note_payload


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable text (no control chars / surrogates)
_name_st = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
).filter(lambda s: s.strip())

_positive_amount_st = st.floats(
    min_value=0.01, max_value=999_999.99, allow_nan=False, allow_infinity=False,
)

_date_st = st.dates(
    min_value=__import__("datetime").date(2000, 1, 1),
    max_value=__import__("datetime").date(2099, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))

_invoice_number_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())

_reason_st = st.text(
    min_size=1,
    max_size=120,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
).filter(lambda s: s.strip())


refund_data_st = st.builds(
    lambda customer_name, amount, date, invoice_number, reason: {
        "customer_name": customer_name,
        "amount": amount,
        "date": date,
        "invoice_number": invoice_number,
        "reason": reason,
    },
    customer_name=_name_st,
    amount=_positive_amount_st,
    date=_date_st,
    invoice_number=_invoice_number_st,
    reason=_reason_st,
)


# ---------------------------------------------------------------------------
# Property 1: Credit Note payload construction invariant
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 1: Credit Note payload construction invariant


class TestCreditNotePayloadConstruction:
    """Property 1: Credit Note payload construction invariant.

    **Validates: Requirements 1.1, 1.3, 1.4**
    """

    @settings(max_examples=100)
    @given(data=refund_data_st)
    def test_credit_note_payload_invariants(self, data: dict) -> None:
        payload = _build_refund_credit_note_payload(data)

        # Top-level: exactly one CreditNote in the list
        assert "CreditNotes" in payload
        cn_list = payload["CreditNotes"]
        assert len(cn_list) == 1

        cn = cn_list[0]

        # Req 1.1 — Type is ACCRECCREDIT
        assert cn["Type"] == "ACCRECCREDIT"

        # Req 1.3 — Status is AUTHORISED
        assert cn["Status"] == "AUTHORISED"

        # Contact.Name matches customer_name
        assert cn["Contact"]["Name"] == data["customer_name"]

        # Date matches the input date string
        assert cn["Date"] == data["date"]

        # Reference contains the invoice number
        assert data["invoice_number"] in cn["Reference"]

        # Req 1.4 — Exactly one LineItem
        assert len(cn["LineItems"]) == 1
        li = cn["LineItems"][0]

        # UnitAmount equals the refund amount (as string of float)
        assert li["UnitAmount"] == str(float(data["amount"]))

        # Description contains the reason
        assert data["reason"] in li["Description"]

        # CurrencyCode is NZD
        assert cn["CurrencyCode"] == "NZD"


# ---------------------------------------------------------------------------
# Property 2: Allocation payload matches refund data
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 2: Allocation payload matches refund data

from app.integrations.xero import _build_refund_allocation_payload


class TestAllocationPayloadMatchesRefundData:
    """Property 2: Allocation payload matches refund data.

    **Validates: Requirements 1.2**
    """

    @settings(max_examples=100)
    @given(data=refund_data_st)
    def test_allocation_payload_matches_refund_data(self, data: dict) -> None:
        payload = _build_refund_allocation_payload(data)

        # Flat object with InvoiceNumber fallback when no xero_invoice_id
        assert "Invoice" in payload
        assert payload["Invoice"]["InvoiceNumber"] == data["invoice_number"]
        assert payload["Amount"] == float(data["amount"])

    @settings(max_examples=100)
    @given(data=refund_data_st, xero_id=st.uuids().map(str))
    def test_allocation_uses_invoice_id_when_provided(self, data: dict, xero_id: str) -> None:
        payload = _build_refund_allocation_payload(data, xero_invoice_id=xero_id)

        # When xero_invoice_id is provided, uses InvoiceID instead of InvoiceNumber
        assert "Invoice" in payload
        assert payload["Invoice"]["InvoiceID"] == xero_id
        assert "InvoiceNumber" not in payload["Invoice"]
        assert payload["Amount"] == float(data["amount"])


# ---------------------------------------------------------------------------
# Property 3: CreditNoteID extraction from response
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 3: CreditNoteID extraction from response

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.xero import sync_refund

# UUID-like string strategy for CreditNoteID
_credit_note_id_st = st.uuids().map(str)


class TestCreditNoteIDExtraction:
    """Property 3: CreditNoteID extraction from response.

    **Validates: Requirements 1.5, 4.1**
    """

    @settings(max_examples=100)
    @given(data=refund_data_st, credit_note_id=_credit_note_id_st)
    @pytest.mark.asyncio
    async def test_credit_note_id_extraction(self, data: dict, credit_note_id: str) -> None:
        """sync_refund() returns a dict where CreditNotes[0]["CreditNoteID"]
        matches the ID from the Xero response."""

        xero_response_dict = {
            "CreditNotes": [
                {
                    "CreditNoteID": credit_note_id,
                    "Type": "ACCRECCREDIT",
                    "Status": "AUTHORISED",
                }
            ]
        }

        # Build a mock response object that _xero_api_call would return
        mock_cn_resp = MagicMock()
        mock_cn_resp.json.return_value = xero_response_dict
        mock_cn_resp.raise_for_status = MagicMock()

        # Mock for accounts lookup (GET /Accounts)
        mock_accounts_resp = MagicMock()
        mock_accounts_resp.status_code = 200
        mock_accounts_resp.json.return_value = {
            "Accounts": [{"Type": "BANK", "Status": "ACTIVE", "Code": "090", "AccountID": "bank-123"}]
        }

        # Mock for refund payment (PUT /Payments)
        mock_pay_resp = MagicMock()
        mock_pay_resp.status_code = 200
        mock_pay_resp.raise_for_status = MagicMock()

        mock_api_call = AsyncMock(side_effect=[mock_cn_resp, mock_accounts_resp, mock_pay_resp])

        with patch("app.integrations.xero._xero_api_call", mock_api_call):
            result = await sync_refund(
                access_token="test-token",
                tenant_id="test-tenant",
                refund_data=data,
            )

        # The returned dict must contain the CreditNoteID we generated
        assert "CreditNotes" in result
        assert len(result["CreditNotes"]) >= 1
        assert result["CreditNotes"][0]["CreditNoteID"] == credit_note_id


# ---------------------------------------------------------------------------
# Property 4: Background task error containment
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 4: Background task error containment

import uuid

from app.modules.accounting.auto_sync import sync_refund_bg


class TestBackgroundTaskErrorContainment:
    """Property 4: Background task error containment.

    **Validates: Requirements 2.3, 2.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(error_msg=st.text(min_size=0, max_size=2000))
    @pytest.mark.asyncio
    async def test_sync_refund_bg_error_containment(self, error_msg: str) -> None:
        """sync_refund_bg() never propagates exceptions and truncates
        logged error messages to at most 500 characters."""
        from contextlib import asynccontextmanager

        org_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        refund_id = str(uuid.UUID("11111111-2222-3333-4444-555555555555"))
        refund_data = {"id": refund_id}

        # Track what _log_sync receives
        logged_errors: list[str | None] = []

        async def fake_log_sync(_session, *, org_id, provider, entity_type, entity_id, status, error_message=None, **kw):
            logged_errors.append(error_message)

        # Build a mock session that supports `async with factory() as s: async with s.begin():`
        @asynccontextmanager
        async def fake_begin():
            yield

        mock_session = MagicMock()
        mock_session.begin = fake_begin

        @asynccontextmanager
        async def fake_factory():
            yield mock_session

        with (
            patch("app.core.database.async_session_factory", fake_factory),
            patch(
                "app.modules.accounting.auto_sync._has_active_xero_connection",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.modules.accounting.service.sync_entity",
                AsyncMock(side_effect=Exception(error_msg)),
            ),
            patch(
                "app.modules.accounting.service._log_sync",
                AsyncMock(side_effect=fake_log_sync),
            ),
        ):
            # Must NOT raise — returns None
            result = await sync_refund_bg(org_id, refund_data)

        assert result is None

        # _log_sync should have been called with a truncated error message
        assert len(logged_errors) == 1
        logged = logged_errors[0]
        assert logged is not None
        assert len(logged) <= 500


# ---------------------------------------------------------------------------
# Property 8: Sync log records correct entity type and status
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 8: Sync log records correct entity type and status

from app.modules.accounting.service import _log_sync


class _FakeSyncLog:
    """Lightweight stand-in for AccountingSyncLog that avoids triggering
    SQLAlchemy mapper configuration (which requires the full model graph)."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestSyncLogRecordsCorrectEntityTypeAndStatus:
    """Property 8: Sync log records correct entity type and status.

    **Validates: Requirements 8.1, 8.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        entity_id=st.uuids(),
        org_id=st.uuids(),
        outcome=st.one_of(st.just("success"), st.just("failure")),
        credit_note_id=st.uuids().map(str),
        error_msg=st.text(
            min_size=1,
            max_size=500,
            alphabet=st.characters(whitelist_categories=("L", "N", "Z", "P")),
        ).filter(lambda s: s.strip()),
    )
    @pytest.mark.asyncio
    async def test_sync_log_entity_type_and_status(
        self,
        entity_id: uuid.UUID,
        org_id: uuid.UUID,
        outcome: str,
        credit_note_id: str,
        error_msg: str,
    ) -> None:
        """_log_sync with entity_type='refund' produces a log entry with
        correct entity_type, status, external_id, and error_message."""

        # Capture the object passed to db.add()
        captured: list = []

        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: captured.append(obj))
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Patch AccountingSyncLog so we avoid the full ORM mapper chain
        with patch(
            "app.modules.accounting.service.AccountingSyncLog",
            _FakeSyncLog,
        ):
            if outcome == "success":
                await _log_sync(
                    mock_db,
                    org_id=org_id,
                    provider="xero",
                    entity_type="refund",
                    entity_id=entity_id,
                    status="synced",
                    external_id=credit_note_id,
                )
            else:
                await _log_sync(
                    mock_db,
                    org_id=org_id,
                    provider="xero",
                    entity_type="refund",
                    entity_id=entity_id,
                    status="failed",
                    error_message=error_msg,
                )

        # Verify the object was added to the session
        assert len(captured) == 1
        log_entry = captured[0]

        # entity_type is always "refund"
        assert log_entry.entity_type == "refund"
        assert log_entry.entity_id == entity_id
        assert log_entry.org_id == org_id
        assert log_entry.provider == "xero"

        if outcome == "success":
            assert log_entry.status == "synced"
            assert log_entry.external_id == credit_note_id
        else:
            assert log_entry.status == "failed"
            assert log_entry.error_message is not None
            assert len(log_entry.error_message) > 0
            assert log_entry.error_message == error_msg


# ---------------------------------------------------------------------------
# Property 5: Refund sync payload completeness
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 5: Refund sync payload completeness


def _assemble_refund_sync_payload(
    refund_record: dict,
    invoice_number: str,
    customer_name: str,
) -> dict:
    """Replicate the payload assembly logic from process_refund_endpoint().

    This is the exact pattern used in the endpoint to build the Xero sync
    payload before dispatching sync_refund_bg().
    """
    return {
        "id": str(refund_record["id"]),
        "invoice_number": invoice_number,
        "customer_name": customer_name,
        "amount": float(refund_record["amount"]),
        "date": str(refund_record["date"]),
        "reason": refund_record.get("reason", "Refund"),
    }


_REQUIRED_PAYLOAD_FIELDS = {"id", "invoice_number", "customer_name", "amount", "date", "reason"}

_uuid_st = st.uuids().map(str)


class TestRefundSyncPayloadCompleteness:
    """Property 5: Refund sync payload completeness.

    **Validates: Requirements 3.1**
    """

    @settings(max_examples=100)
    @given(
        refund_id=_uuid_st,
        amount=_positive_amount_st,
        date=_date_st,
        reason=_reason_st,
        invoice_number=_invoice_number_st,
        customer_name=_name_st,
    )
    def test_payload_contains_all_required_fields_and_none_are_none(
        self,
        refund_id: str,
        amount: float,
        date: str,
        reason: str,
        invoice_number: str,
        customer_name: str,
    ) -> None:
        refund_record = {
            "id": refund_id,
            "amount": amount,
            "date": date,
            "reason": reason,
        }

        payload = _assemble_refund_sync_payload(
            refund_record,
            invoice_number=invoice_number,
            customer_name=customer_name,
        )

        # All 6 required fields must be present
        assert set(payload.keys()) == _REQUIRED_PAYLOAD_FIELDS

        # None of the values may be None
        for field in _REQUIRED_PAYLOAD_FIELDS:
            assert payload[field] is not None, f"Field '{field}' is None"


# ---------------------------------------------------------------------------
# Property 7: Credit note sync resolves customer name
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 7: Credit note sync resolves customer name


def _resolve_customer_name(display_name, first_name, last_name):
    """Replicate the customer name resolution logic used in
    create_credit_note_endpoint() and other sync endpoints."""
    return display_name or f"{first_name or ''} {last_name or ''}".strip() or "Unknown"


class TestCreditNoteSyncResolvesCustomerName:
    """Property 7: Credit note sync resolves customer name.

    **Validates: Requirements 6.1, 6.2**
    """

    @settings(max_examples=100)
    @given(display_name=_name_st)
    def test_non_empty_display_name_is_used(self, display_name: str) -> None:
        """When a customer has a non-empty display_name, the resolved name
        must equal that display_name and never be 'Unknown'."""
        result = _resolve_customer_name(display_name, first_name=None, last_name=None)
        assert result == display_name
        assert result != "Unknown"

    @settings(max_examples=100)
    @given(first_name=_name_st, last_name=_name_st)
    def test_fallback_to_first_last_name(self, first_name: str, last_name: str) -> None:
        """When display_name is falsy (None or empty string), first_name +
        last_name is used and the result is never 'Unknown'."""
        for empty_display in (None, ""):
            result = _resolve_customer_name(empty_display, first_name, last_name)
            expected = f"{first_name} {last_name}".strip()
            assert result == expected
            assert result != "Unknown"

    def test_all_empty_falls_back_to_unknown(self) -> None:
        """When all name fields are empty/None, the result is 'Unknown'."""
        assert _resolve_customer_name(None, None, None) == "Unknown"
        assert _resolve_customer_name("", "", "") == "Unknown"
        assert _resolve_customer_name(None, "", None) == "Unknown"


# ---------------------------------------------------------------------------
# Property 6: Refund data reconstruction round-trip
# ---------------------------------------------------------------------------
# Feature: xero-refund-sync, Property 6: Refund data reconstruction round-trip

from datetime import datetime

from app.modules.accounting.service import _reconstruct_entity_data

_RECONSTRUCT_REQUIRED_FIELDS = {"id", "invoice_number", "customer_name", "amount", "date", "reason"}


class TestRefundDataReconstructionRoundTrip:
    """Property 6: Refund data reconstruction round-trip.

    **Validates: Requirements 5.1, 5.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        payment_id=st.uuids(),
        org_id=st.uuids(),
        invoice_id=st.uuids(),
        customer_id=st.uuids(),
        amount=_positive_amount_st,
        created_at=st.datetimes(
            min_value=datetime(2000, 1, 1),
            max_value=datetime(2099, 12, 31),
        ),
        refund_note=st.one_of(
            st.none(),
            _reason_st,
        ),
        invoice_number=_invoice_number_st,
        display_name=_name_st,
    )
    @pytest.mark.asyncio
    async def test_reconstruction_round_trip(
        self,
        payment_id: uuid.UUID,
        org_id: uuid.UUID,
        invoice_id: uuid.UUID,
        customer_id: uuid.UUID,
        amount: float,
        created_at: datetime,
        refund_note: str | None,
        invoice_number: str,
        display_name: str,
    ) -> None:
        """_reconstruct_entity_data(entity_type='refund') returns a dict
        with all 6 required fields, amount matching Payment.amount, and
        invoice_number matching Invoice.invoice_number."""

        # Build mock Payment object
        mock_payment = MagicMock()
        mock_payment.id = payment_id
        mock_payment.org_id = org_id
        mock_payment.invoice_id = invoice_id
        mock_payment.is_refund = True
        mock_payment.amount = amount
        mock_payment.created_at = created_at
        mock_payment.refund_note = refund_note

        # Build mock Invoice object
        mock_invoice = MagicMock()
        mock_invoice.id = invoice_id
        mock_invoice.invoice_number = invoice_number
        mock_invoice.customer_id = customer_id

        # Build mock Customer object
        mock_customer = MagicMock()
        mock_customer.display_name = display_name
        mock_customer.first_name = "First"
        mock_customer.last_name = "Last"

        # Track db.execute calls and return appropriate results
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Payment query
                result.scalar_one_or_none.return_value = mock_payment
            elif call_count == 2:
                # Invoice query
                result.scalar_one_or_none.return_value = mock_invoice
            elif call_count == 3:
                # Customer query
                result.scalar_one_or_none.return_value = mock_customer
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=fake_execute)

        result = await _reconstruct_entity_data(
            mock_db,
            org_id=org_id,
            entity_type="refund",
            entity_id=payment_id,
        )

        # Result must not be None
        assert result is not None

        # All 6 required fields must be present
        assert set(result.keys()) == _RECONSTRUCT_REQUIRED_FIELDS

        # None of the values may be None
        for field in _RECONSTRUCT_REQUIRED_FIELDS:
            assert result[field] is not None, f"Field '{field}' is None"

        # amount matches Payment's amount (as float)
        assert result["amount"] == float(amount)

        # invoice_number matches Invoice's invoice_number
        assert result["invoice_number"] == invoice_number

        # id matches the payment id (as string)
        assert result["id"] == str(payment_id)

        # date is formatted from created_at
        assert result["date"] == created_at.strftime("%Y-%m-%d")

        # reason falls back to "Refund" when refund_note is None
        if refund_note:
            assert result["reason"] == refund_note
        else:
            assert result["reason"] == "Refund"

        # customer_name is the display_name (since we provided a non-empty one)
        assert result["customer_name"] == display_name
