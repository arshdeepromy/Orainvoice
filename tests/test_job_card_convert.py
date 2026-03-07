"""Unit tests for Task 18.4 — Job Card conversion to invoice.

Requirements: 59.3, 59.4
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem
from app.modules.job_cards.service import (
    convert_job_card_to_invoice,
    combine_job_cards_to_invoice,
)
from app.modules.job_cards.schemas import (
    JobCardConvertResponse,
    JobCardCombineRequest,
    JobCardCombineResponse,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
JOB_CARD_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_job_card_dict(status="completed", customer_id=None, vehicle_rego="ABC123"):
    """Create a fake job card dict as returned by get_job_card."""
    return {
        "id": JOB_CARD_ID,
        "org_id": ORG_ID,
        "customer_id": customer_id or CUSTOMER_ID,
        "vehicle_rego": vehicle_rego,
        "status": status,
        "description": "Full service",
        "notes": "Check brakes",
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Oil Change",
                "quantity": Decimal("1"),
                "unit_price": Decimal("50.00"),
                "is_completed": False,
                "is_gst_exempt": False,
                "line_total": Decimal("50.00"),
                "sort_order": 0,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "part",
                "description": "Oil Filter",
                "quantity": Decimal("1"),
                "unit_price": Decimal("25.00"),
                "is_completed": False,
                "is_gst_exempt": False,
                "line_total": Decimal("25.00"),
                "sort_order": 1,
            },
        ],
        "created_by": USER_ID,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_job_card_obj(status="completed"):
    """Create a mock JobCard ORM object."""
    jc = MagicMock(spec=JobCard)
    jc.id = JOB_CARD_ID
    jc.org_id = ORG_ID
    jc.customer_id = CUSTOMER_ID
    jc.vehicle_rego = "ABC123"
    jc.status = status
    return jc


# ---------------------------------------------------------------------------
# convert_job_card_to_invoice tests
# ---------------------------------------------------------------------------


class TestConvertJobCardToInvoice:
    """Test convert_job_card_to_invoice service function.

    Validates: Requirements 59.3
    """

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_convert_completed_job_card_creates_draft_invoice(
        self, mock_get_jc, mock_audit
    ):
        """Converting a completed job card creates a draft invoice with all line items."""
        jc_dict = _make_job_card_dict(status="completed")
        mock_get_jc.return_value = jc_dict

        db = _mock_db()
        jc_obj = _make_job_card_obj(status="completed")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jc_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice_id = uuid.uuid4()
        fake_invoice = {"id": fake_invoice_id, "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create_inv:
            result = await convert_job_card_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

            mock_create_inv.assert_called_once()
            call_kwargs = mock_create_inv.call_args.kwargs
            assert call_kwargs["customer_id"] == CUSTOMER_ID
            assert call_kwargs["vehicle_rego"] == "ABC123"
            assert call_kwargs["status"] == "draft"
            assert call_kwargs["notes_customer"] == "Check brakes"
            assert len(call_kwargs["line_items_data"]) == 2

        assert result["invoice_id"] == fake_invoice_id
        assert result["invoice_status"] == "draft"
        assert result["job_card_id"] == JOB_CARD_ID
        # Job card should transition to invoiced
        assert jc_obj.status == "invoiced"

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_convert_open_job_card_raises(self, mock_get_jc):
        """Cannot convert an open job card — must be completed first."""
        mock_get_jc.return_value = _make_job_card_dict(status="open")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a job card"):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=JOB_CARD_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_convert_in_progress_job_card_raises(self, mock_get_jc):
        """Cannot convert an in-progress job card."""
        mock_get_jc.return_value = _make_job_card_dict(status="in_progress")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a job card"):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=JOB_CARD_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_convert_already_invoiced_raises(self, mock_get_jc):
        """Cannot convert a job card that is already invoiced."""
        mock_get_jc.return_value = _make_job_card_dict(status="invoiced")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a job card"):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=JOB_CARD_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_convert_preserves_line_item_details(self, mock_get_jc, mock_audit):
        """All line item fields are carried over to the invoice."""
        jc_dict = _make_job_card_dict(status="completed")
        mock_get_jc.return_value = jc_dict

        db = _mock_db()
        jc_obj = _make_job_card_obj(status="completed")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jc_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create_inv:
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=JOB_CARD_ID,
            )

            call_kwargs = mock_create_inv.call_args.kwargs
            line_items = call_kwargs["line_items_data"]
            assert len(line_items) == 2

            assert line_items[0]["item_type"] == "service"
            assert line_items[0]["description"] == "Oil Change"
            assert line_items[0]["quantity"] == Decimal("1")
            assert line_items[0]["unit_price"] == Decimal("50.00")

            assert line_items[1]["item_type"] == "part"
            assert line_items[1]["description"] == "Oil Filter"


# ---------------------------------------------------------------------------
# combine_job_cards_to_invoice tests
# ---------------------------------------------------------------------------


class TestCombineJobCardsToInvoice:
    """Test combine_job_cards_to_invoice service function.

    Validates: Requirements 59.4
    """

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_combine_two_job_cards_creates_single_invoice(
        self, mock_get_jc, mock_audit
    ):
        """Combining two completed job cards creates one draft invoice with all items."""
        jc_id_1 = uuid.uuid4()
        jc_id_2 = uuid.uuid4()

        jc_dict_1 = _make_job_card_dict(status="completed")
        jc_dict_1["id"] = jc_id_1

        jc_dict_2 = _make_job_card_dict(status="completed")
        jc_dict_2["id"] = jc_id_2
        jc_dict_2["line_items"] = [
            {
                "id": uuid.uuid4(),
                "item_type": "labour",
                "description": "Brake inspection",
                "quantity": Decimal("2"),
                "unit_price": Decimal("60.00"),
                "is_completed": False,
                "is_gst_exempt": False,
                "line_total": Decimal("120.00"),
                "sort_order": 0,
            },
        ]

        mock_get_jc.side_effect = [jc_dict_1, jc_dict_2]

        db = _mock_db()
        jc_obj_1 = _make_job_card_obj(status="completed")
        jc_obj_2 = _make_job_card_obj(status="completed")
        mock_result_1 = MagicMock()
        mock_result_1.scalar_one_or_none.return_value = jc_obj_1
        mock_result_2 = MagicMock()
        mock_result_2.scalar_one_or_none.return_value = jc_obj_2
        db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        fake_invoice_id = uuid.uuid4()
        fake_invoice = {"id": fake_invoice_id, "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create_inv:
            result = await combine_job_cards_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_ids=[jc_id_1, jc_id_2],
            )

            mock_create_inv.assert_called_once()
            call_kwargs = mock_create_inv.call_args.kwargs
            # 2 items from first + 1 from second = 3 total
            assert len(call_kwargs["line_items_data"]) == 3
            assert call_kwargs["customer_id"] == CUSTOMER_ID
            assert call_kwargs["status"] == "draft"

        assert result["invoice_id"] == fake_invoice_id
        assert result["invoice_status"] == "draft"
        assert len(result["job_card_ids"]) == 2
        # Both job cards should be invoiced
        assert jc_obj_1.status == "invoiced"
        assert jc_obj_2.status == "invoiced"

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_combine_rejects_non_completed_job_cards(self, mock_get_jc):
        """Cannot combine job cards that are not all completed."""
        jc_id_1 = uuid.uuid4()
        jc_id_2 = uuid.uuid4()

        jc_dict_1 = _make_job_card_dict(status="completed")
        jc_dict_1["id"] = jc_id_1
        jc_dict_2 = _make_job_card_dict(status="open")
        jc_dict_2["id"] = jc_id_2

        mock_get_jc.side_effect = [jc_dict_1, jc_dict_2]
        db = _mock_db()

        with pytest.raises(ValueError, match="must be completed"):
            await combine_job_cards_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_ids=[jc_id_1, jc_id_2],
            )

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_combine_rejects_different_customers(self, mock_get_jc):
        """Cannot combine job cards from different customers."""
        jc_id_1 = uuid.uuid4()
        jc_id_2 = uuid.uuid4()
        other_customer = uuid.uuid4()

        jc_dict_1 = _make_job_card_dict(status="completed", customer_id=CUSTOMER_ID)
        jc_dict_1["id"] = jc_id_1
        jc_dict_2 = _make_job_card_dict(status="completed", customer_id=other_customer)
        jc_dict_2["id"] = jc_id_2

        mock_get_jc.side_effect = [jc_dict_1, jc_dict_2]
        db = _mock_db()

        with pytest.raises(ValueError, match="same customer"):
            await combine_job_cards_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_ids=[jc_id_1, jc_id_2],
            )

    @pytest.mark.asyncio
    async def test_combine_rejects_empty_list(self):
        """Cannot combine with an empty list of job card IDs."""
        db = _mock_db()

        with pytest.raises(ValueError, match="At least one"):
            await combine_job_cards_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_ids=[],
            )


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestConvertSchemas:
    """Test Pydantic schemas for job card conversion."""

    def test_convert_response_schema(self):
        resp = JobCardConvertResponse(
            job_card_id=JOB_CARD_ID,
            invoice_id=uuid.uuid4(),
            invoice_status="draft",
            message="Converted",
        )
        assert resp.invoice_status == "draft"

    def test_combine_request_requires_ids(self):
        with pytest.raises(Exception):
            JobCardCombineRequest(job_card_ids=[])

    def test_combine_request_valid(self):
        req = JobCardCombineRequest(job_card_ids=[uuid.uuid4()])
        assert len(req.job_card_ids) == 1

    def test_combine_response_schema(self):
        resp = JobCardCombineResponse(
            job_card_ids=[uuid.uuid4(), uuid.uuid4()],
            invoice_id=uuid.uuid4(),
            invoice_status="draft",
            message="Combined",
        )
        assert len(resp.job_card_ids) == 2
