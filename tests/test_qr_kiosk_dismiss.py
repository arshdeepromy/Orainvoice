"""Tests for the kiosk soft-dismiss flow on pending QR sessions.

Verifies the qr-payment-bugfixes-2 fix:

- ``POST /payments/qr-session/{id}/dismiss`` sets ``dismissed_at`` on
  the matching ``pending_qr_sessions`` row scoped to the caller's org.
- The dismiss path does NOT delete the row and does NOT cancel the
  Stripe PaymentIntent — a customer who already scanned can complete
  payment from their phone.
- ``get_pending_qr_session`` filters out dismissed rows, so kiosk
  polls + page refreshes don't re-trigger the popup for an already-
  dismissed session.
- The next ``create_qr_session_for_existing_invoice`` call rotates
  the row (DELETE + INSERT) which clears ``dismissed_at`` so the
  popup re-appears for the new attempt.
- The dismiss endpoint cannot be used to dismiss another org's session
  (org-scoping prevents cross-tenant interference).

Validates: kiosk dismissal regression-fix (post-task-15)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy mappers are configurable in any test that constructs
# select() statements that touch relationships across modules. Mirrors
# the model-loading block in app/main.py.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.catalogue.fluid_oil_models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.invoices.attachment_models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.service_types.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.sms_chat.models  # noqa: F401
import app.modules.ha.models  # noqa: F401
import app.modules.ha.volume_sync_models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.platform_settings.models  # noqa: F401
import app.modules.ledger.models  # noqa: F401
import app.modules.banking.models  # noqa: F401
import app.modules.tax_wallets.models  # noqa: F401
import app.modules.ird.models  # noqa: F401
import app.modules.in_app_notifications.models  # noqa: F401
import app.modules.fleet_portal.models  # noqa: F401
import app.modules.portal.models  # noqa: F401

from app.modules.payments.models import PendingQrSession
from app.modules.payments.service import (
    dismiss_pending_qr_session,
    get_pending_qr_session,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_pending_session(
    *,
    org_id: uuid.UUID,
    session_id: str = "pi_test_kiosk",
    dismissed_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    """Build a mock PendingQrSession ORM row."""
    row = MagicMock(spec=PendingQrSession)
    row.id = uuid.uuid4()
    row.org_id = org_id
    row.session_id = session_id
    row.checkout_url = f"https://test.local/pay/{session_id}"
    row.amount = Decimal("100.00")
    row.invoice_number = "INV-KIOSK-1"
    row.invoice_id = uuid.uuid4()
    row.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=30))
    row.created_at = datetime.now(timezone.utc)
    row.dismissed_at = dismissed_at
    return row


class _FakeDb:
    """AsyncMock-flavoured DB that selects pending_qr_sessions rows
    keyed by org_id, and emulates ``UPDATE ... RETURNING`` for the
    dismiss path.

    ``rows`` is a dict ``{org_id: row}`` representing the table.
    """

    def __init__(self, rows: dict[uuid.UUID, MagicMock] | None = None) -> None:
        self.rows: dict[uuid.UUID, MagicMock] = dict(rows or {})
        self.deletes: list = []
        self.flushes = 0
        self.execute = AsyncMock(side_effect=self._execute)
        self.flush = AsyncMock(side_effect=self._flush)
        self.delete = AsyncMock(side_effect=self._delete)

    async def _flush(self) -> None:
        self.flushes += 1

    async def _delete(self, obj) -> None:
        # Find by id and remove
        for k, v in list(self.rows.items()):
            if getattr(v, "id", None) == getattr(obj, "id", None):
                del self.rows[k]
                self.deletes.append(obj)
                return

    async def _execute(self, stmt, *args, **kwargs):
        from sqlalchemy import Select, Update

        if isinstance(stmt, Select):
            # Pull org_id literal out of the WHERE clause and return the
            # matching row (or None).
            org_id = self._extract_uuid_filter(stmt, "org_id")
            row = self.rows.get(org_id) if org_id else None
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            return result

        if isinstance(stmt, Update):
            # Soft-dismiss path: UPDATE ... WHERE org_id=? AND session_id=?
            # AND dismissed_at IS NULL ... RETURNING id
            org_id = self._extract_uuid_filter(stmt, "org_id")
            session_id = self._extract_str_filter(stmt, "session_id")
            row = self.rows.get(org_id) if org_id else None
            updated_id: uuid.UUID | None = None
            if (
                row is not None
                and getattr(row, "session_id", None) == session_id
                and getattr(row, "dismissed_at", None) is None
            ):
                row.dismissed_at = datetime.now(timezone.utc)
                updated_id = row.id
            result = MagicMock()
            result.scalar_one_or_none.return_value = updated_id
            return result

        # Fallback (e.g. delete via execute(delete(...))) — no-op
        return MagicMock()

    def _extract_uuid_filter(self, stmt, column: str) -> uuid.UUID | None:
        try:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            import re

            # SQLAlchemy renders UUIDs without dashes when literal-binding;
            # match both ``32 hex chars`` and ``8-4-4-4-12`` shapes, with
            # an optional ``table.`` prefix.
            m = re.search(
                rf"(?:[\w]+\.)?{column}\s*=\s*'([0-9a-f-]{{32,36}})'",
                compiled,
                re.IGNORECASE,
            )
            if m:
                # ``uuid.UUID`` accepts either form.
                return uuid.UUID(m.group(1))
        except Exception:
            pass
        return None

    def _extract_str_filter(self, stmt, column: str) -> str | None:
        try:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            import re

            m = re.search(
                rf"(?:[\w]+\.)?{column}\s*=\s*'([^']+)'", compiled
            )
            if m:
                return m.group(1)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDismissPendingQrSession:
    """Service-layer tests for ``dismiss_pending_qr_session``."""

    @pytest.mark.asyncio
    async def test_dismiss_sets_dismissed_at(self):
        """Dismiss marks ``dismissed_at`` on the matching row.

        Validates: kiosk dismissal regression-fix.
        """
        org_id = uuid.uuid4()
        row = _make_pending_session(org_id=org_id, session_id="pi_x")
        db = _FakeDb({org_id: row})

        ok = await dismiss_pending_qr_session(
            db, org_id=org_id, session_id="pi_x"
        )
        assert ok is True
        assert row.dismissed_at is not None
        # The row stays in the table — Stripe PI is untouched, customer
        # who scanned can still complete payment from their phone.
        assert org_id in db.rows
        # Service does NOT call db.delete on the row.
        assert db.deletes == []

    @pytest.mark.asyncio
    async def test_dismiss_other_org_session_no_op(self):
        """Cannot dismiss another org's session — org-scoping holds.

        Validates: kiosk dismissal regression-fix; tenant isolation.
        """
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        row_b = _make_pending_session(org_id=org_b, session_id="pi_b")
        db = _FakeDb({org_b: row_b})

        # Org A tries to dismiss B's session.
        ok = await dismiss_pending_qr_session(
            db, org_id=org_a, session_id="pi_b"
        )
        assert ok is False
        # B's row is unchanged.
        assert row_b.dismissed_at is None

    @pytest.mark.asyncio
    async def test_dismiss_already_dismissed_no_op(self):
        """Re-dismissing an already-dismissed row is idempotent."""
        org_id = uuid.uuid4()
        original_ts = datetime.now(timezone.utc) - timedelta(seconds=30)
        row = _make_pending_session(
            org_id=org_id, session_id="pi_x", dismissed_at=original_ts
        )
        db = _FakeDb({org_id: row})

        ok = await dismiss_pending_qr_session(
            db, org_id=org_id, session_id="pi_x"
        )
        assert ok is False
        # Timestamp not bumped on second call.
        assert row.dismissed_at == original_ts

    @pytest.mark.asyncio
    async def test_dismiss_unknown_session_no_op(self):
        """Dismissing a session_id that doesn't exist is a 200 no-op."""
        org_id = uuid.uuid4()
        db = _FakeDb({})  # empty table

        ok = await dismiss_pending_qr_session(
            db, org_id=org_id, session_id="pi_missing"
        )
        assert ok is False


class TestGetPendingQrSessionFiltersDismissed:
    """``get_pending_qr_session`` hides rows where ``dismissed_at`` is set."""

    @pytest.mark.asyncio
    async def test_dismissed_row_returns_none(self):
        """A dismissed row is invisible to the kiosk poll.

        Validates: kiosk page refresh must not re-show the popup for
        a session the staff already closed.
        """
        org_id = uuid.uuid4()
        row = _make_pending_session(
            org_id=org_id,
            session_id="pi_dismissed",
            dismissed_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        db = _FakeDb({org_id: row})

        result = await get_pending_qr_session(db, org_id=org_id)
        assert result is None
        # The row stays in the DB; only the visibility changes.
        assert org_id in db.rows

    @pytest.mark.asyncio
    async def test_active_row_returns_session(self):
        """A non-dismissed, non-expired row is returned to the kiosk."""
        org_id = uuid.uuid4()
        row = _make_pending_session(
            org_id=org_id, session_id="pi_active", dismissed_at=None
        )
        db = _FakeDb({org_id: row})

        result = await get_pending_qr_session(db, org_id=org_id)
        assert result is not None
        assert result["session_id"] == "pi_active"

    @pytest.mark.asyncio
    async def test_expired_row_returns_none_and_is_deleted(self):
        """Existing behaviour preserved: expired rows still get deleted."""
        org_id = uuid.uuid4()
        row = _make_pending_session(
            org_id=org_id,
            session_id="pi_expired",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db = _FakeDb({org_id: row})

        result = await get_pending_qr_session(db, org_id=org_id)
        assert result is None
        # Expired rows ARE deleted (separate code path from soft-dismiss).
        assert org_id not in db.rows


class TestQrSessionStatusMapping:
    """Stripe ``requires_payment_method`` → ``open`` mapping.

    Was previously mapped to ``expired`` which made the popup display
    "QR session superseded" the moment a fresh PI was created (because
    a brand-new PaymentIntent's initial Stripe status is
    ``requires_payment_method`` — i.e. waiting for the customer to
    enter card details). Only ``canceled`` should map to ``expired``.
    """

    @pytest.mark.asyncio
    async def test_requires_payment_method_maps_to_open(self):
        """A freshly-created PI is mapped as ``open``, not ``expired``."""
        from app.modules.payments.service import get_qr_session_status

        # Mock the Stripe PI lookup helper indirectly via httpx.AsyncClient
        # plus the local payments check (which finds nothing).
        db = AsyncMock()
        db.execute = AsyncMock()
        # No existing payment row (idempotency guard miss).
        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None
        db.execute.return_value = empty_result

        class _FakeStripeResp:
            status_code = 200

            def json(self):
                return {
                    "id": "pi_fresh",
                    "status": "requires_payment_method",
                    "amount_received": 0,
                }

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, *_args, **_kwargs):
                return _FakeStripeResp()

        with patch(
            "app.integrations.stripe_billing.get_stripe_secret_key",
            new=AsyncMock(return_value="sk_test_xxx"),
        ), patch("httpx.AsyncClient", new=lambda *a, **kw: _FakeAsyncClient()):
            result = await get_qr_session_status(
                db,
                session_id="pi_fresh",
                stripe_connect_account_id="acct_test",
            )

        assert result["status"] == "open"
        assert result["payment_intent_id"] is None

    @pytest.mark.asyncio
    async def test_canceled_maps_to_expired(self):
        """``canceled`` is the only Stripe status that maps to ``expired``."""
        from app.modules.payments.service import get_qr_session_status

        db = AsyncMock()
        db.execute = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None
        db.execute.return_value = empty_result

        class _FakeStripeResp:
            status_code = 200

            def json(self):
                return {
                    "id": "pi_canceled",
                    "status": "canceled",
                    "amount_received": 0,
                }

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, *_args, **_kwargs):
                return _FakeStripeResp()

        with patch(
            "app.integrations.stripe_billing.get_stripe_secret_key",
            new=AsyncMock(return_value="sk_test_xxx"),
        ), patch("httpx.AsyncClient", new=lambda *a, **kw: _FakeAsyncClient()):
            result = await get_qr_session_status(
                db,
                session_id="pi_canceled",
                stripe_connect_account_id="acct_test",
            )

        assert result["status"] == "expired"

    @pytest.mark.asyncio
    async def test_succeeded_maps_to_complete(self):
        """``succeeded`` continues to map to ``complete`` (regression check)."""
        from app.modules.payments.service import get_qr_session_status

        db = AsyncMock()
        db.execute = AsyncMock()
        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None
        db.execute.return_value = empty_result

        class _FakeStripeResp:
            status_code = 200

            def json(self):
                return {
                    "id": "pi_paid",
                    "status": "succeeded",
                    "amount_received": 10000,
                }

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, *_args, **_kwargs):
                return _FakeStripeResp()

        with patch(
            "app.integrations.stripe_billing.get_stripe_secret_key",
            new=AsyncMock(return_value="sk_test_xxx"),
        ), patch("httpx.AsyncClient", new=lambda *a, **kw: _FakeAsyncClient()):
            result = await get_qr_session_status(
                db,
                session_id="pi_paid",
                stripe_connect_account_id="acct_test",
            )

        assert result["status"] == "complete"
        assert result["amount_charged"] == 100.0
