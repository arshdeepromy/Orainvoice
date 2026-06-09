"""F7 — `has_reminder_consent` on the customer search result.

Feature: customer-reminder-consent

Asserts the search dict derives `has_reminder_consent` from a single
`custom_fields["reminder_consent"]` lookup (no extra query) and that the
field is exposed on the `CustomerSearchResult` schema (Pydantic Rule 8).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

# Configure ORM mappers.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.customers.schemas import CustomerSearchResult
from app.modules.customers.service import _customer_to_search_dict


def _customer(custom_fields: dict) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.customer_type = "individual"
    c.first_name = "Jane"
    c.last_name = "Smith"
    c.company_name = None
    c.display_name = None
    c.email = None
    c.phone = None
    c.mobile_phone = None
    c.work_phone = None
    c.last_portal_access_at = None
    c.custom_fields = custom_fields
    return c


def test_has_reminder_consent_false_for_fresh_customer():
    d = _customer_to_search_dict(_customer({}))
    assert d["has_reminder_consent"] is False


def test_has_reminder_consent_true_after_consent_written():
    d = _customer_to_search_dict(
        _customer({"reminder_consent": {"source": "kiosk_self_checkin"}})
    )
    assert d["has_reminder_consent"] is True


def test_schema_exposes_field_and_round_trips():
    # Pydantic Rule 8: the field must be on the schema or it is dropped.
    assert "has_reminder_consent" in CustomerSearchResult.model_fields
    d = _customer_to_search_dict(
        _customer({"reminder_consent": {"source": "kiosk_self_checkin"}})
    )
    result = CustomerSearchResult(**d)
    assert result.has_reminder_consent is True
