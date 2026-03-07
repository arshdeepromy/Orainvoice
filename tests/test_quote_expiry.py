"""Test: quote expiry auto-updates status after expiry_date.

**Validates: Requirement 12.3**

Verifies that the check_expiry() static method correctly marks
sent quotes past their expiry_date as expired, and leaves other
quotes untouched.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.quotes_v2.models import Quote
from app.modules.quotes_v2.service import QuoteService


def _make_mock_db_for_expiry(quotes: list[Quote]):
    """Create a mock async DB session that simulates the update query."""
    mock_db = AsyncMock()

    expired_ids = []
    for q in quotes:
        if q.status == "sent" and q.expiry_date and q.expiry_date < date.today():
            expired_ids.append(q.id)
            q.status = "expired"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = expired_ids

    async def fake_execute(stmt):
        return mock_result

    mock_db.execute = fake_execute
    return mock_db, expired_ids


class TestQuoteExpiry:
    """Validates: Requirement 12.3"""

    @pytest.mark.asyncio
    async def test_expired_sent_quotes_are_marked(self):
        """Sent quotes past expiry_date are marked as expired."""
        yesterday = date.today() - timedelta(days=1)
        quotes = [
            Quote(
                id=uuid.uuid4(), org_id=uuid.uuid4(),
                quote_number="QT-00001", customer_id=uuid.uuid4(),
                status="sent", expiry_date=yesterday,
            ),
            Quote(
                id=uuid.uuid4(), org_id=uuid.uuid4(),
                quote_number="QT-00002", customer_id=uuid.uuid4(),
                status="sent", expiry_date=yesterday,
            ),
        ]
        mock_db, expired_ids = _make_mock_db_for_expiry(quotes)
        count = await QuoteService.check_expiry(mock_db)
        assert count == 2

    @pytest.mark.asyncio
    async def test_non_expired_quotes_are_not_marked(self):
        """Sent quotes with future expiry_date are not marked."""
        tomorrow = date.today() + timedelta(days=1)
        quotes = [
            Quote(
                id=uuid.uuid4(), org_id=uuid.uuid4(),
                quote_number="QT-00003", customer_id=uuid.uuid4(),
                status="sent", expiry_date=tomorrow,
            ),
        ]
        mock_db, expired_ids = _make_mock_db_for_expiry(quotes)
        count = await QuoteService.check_expiry(mock_db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_draft_quotes_are_not_expired(self):
        """Draft quotes past expiry_date are not marked (only sent)."""
        yesterday = date.today() - timedelta(days=1)
        quotes = [
            Quote(
                id=uuid.uuid4(), org_id=uuid.uuid4(),
                quote_number="QT-00004", customer_id=uuid.uuid4(),
                status="draft", expiry_date=yesterday,
            ),
        ]
        mock_db, expired_ids = _make_mock_db_for_expiry(quotes)
        count = await QuoteService.check_expiry(mock_db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_accept_rejects_expired_quote(self):
        """Accepting a quote past its expiry_date raises ValueError."""
        yesterday = date.today() - timedelta(days=1)
        quote = Quote(
            id=uuid.uuid4(), org_id=uuid.uuid4(),
            quote_number="QT-00005", customer_id=uuid.uuid4(),
            status="sent", expiry_date=yesterday,
            acceptance_token="test-token-123",
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = quote

        async def fake_execute(stmt):
            return mock_result

        async def fake_flush():
            pass

        mock_db.execute = fake_execute
        mock_db.flush = fake_flush

        svc = QuoteService(mock_db)
        with pytest.raises(ValueError, match="expired"):
            await svc.accept_quote("test-token-123")
        assert quote.status == "expired"
