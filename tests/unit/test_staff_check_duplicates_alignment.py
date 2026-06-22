"""Unit tests for ``StaffService._check_duplicates`` DB-constraint alignment.

Covers task 4.1 from `.kiro/specs/organisation-employee-portal`:

The application-level duplicate check must reach an *identical* duplicate
determination to the database partial unique indexes created by migration
0224 (R1.9):

- ``uq_staff_active_email_per_org`` keys on
  ``(org_id, lower(btrim(email))) WHERE is_active AND ...`` — so the app
  email comparison must be trim + lowercase, case-insensitive, active-scoped.
- ``uq_staff_active_employee_id_per_org`` keys on
  ``(org_id, employee_id) WHERE is_active AND ...`` — active-scoped exact match.

A duplicate create/update is rejected with a human-readable ``{message, code}``
error (R1.5).

These tests stub the DB session so they exercise the pure query-building and
rejection branching of ``_check_duplicates`` without a live PostgreSQL.

**Validates: Requirements 1.1, 1.5, 1.9**
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

# Pre-import the full set of model modules so SQLAlchemy can resolve every
# string-based relationship reference when ``configure_mappers()`` runs.
# Without this, compiling a ``select()`` against StaffMember initialises the
# full mapper graph and fails on cross-module references (e.g. Customer).
# Mirrors the model-loading block in app/main.py.
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
from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.modules.staff.service import DuplicateStaffError, StaffService


class _CapturingDB:
    """Minimal async DB stub that records executed statements and returns a
    duplicate match (or not) from ``scalar_one_or_none``.
    """

    def __init__(self, *, found: bool) -> None:
        self._found = found
        self.statements: list = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = uuid.uuid4() if self._found else None
        return result


def _compiled_sql(stmt) -> str:
    """Render a statement to SQL text with literal binds for inspection."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()


# ---------------------------------------------------------------------------
# R1.9 — comparison alignment with the DB partial unique indexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_branch_is_normalised_case_insensitive_active_scoped():
    """Email comparison mirrors uq_staff_active_email_per_org:
    lower(btrim(email)) == normalised value, scoped to active rows."""
    db = _CapturingDB(found=False)
    svc = StaffService(db)

    await svc._check_duplicates(uuid.uuid4(), "  Jane@Example.COM ", None, None)

    assert len(db.statements) == 1
    sql = _compiled_sql(db.statements[0])
    flattened = sql.replace(" ", "")
    # normalised, case-insensitive comparison on the email column
    assert "lower(btrim(staff_members.email))" in flattened
    # the candidate value is normalised to trimmed + lowercased
    assert "jane@example.com" in sql
    assert "jane@example.com " not in sql  # trailing space trimmed
    # active-scoped
    assert "is_active" in sql


@pytest.mark.asyncio
async def test_employee_id_branch_is_active_scoped_exact_match():
    """Employee-id comparison mirrors uq_staff_active_employee_id_per_org:
    exact match on the raw column, scoped to active rows (no lower/btrim)."""
    db = _CapturingDB(found=False)
    svc = StaffService(db)

    await svc._check_duplicates(uuid.uuid4(), None, None, "EMP-001")

    assert len(db.statements) == 1
    sql = _compiled_sql(db.statements[0])
    assert "staff_members.employee_id" in sql
    assert "is_active" in sql
    # raw column comparison — not normalised through lower(btrim(...))
    assert "lower(btrim(staff_members.employee_id))" not in sql.replace(" ", "")


@pytest.mark.asyncio
async def test_exclude_id_applied_on_update_path():
    """When excluding the current staff member (update), the query carries
    an id != exclude_id predicate so a row never collides with itself."""
    db = _CapturingDB(found=False)
    svc = StaffService(db)
    exclude_id = uuid.uuid4()

    await svc._check_duplicates(uuid.uuid4(), "a@b.com", None, None, exclude_id=exclude_id)

    sql = _compiled_sql(db.statements[0])
    assert "staff_members.id !=" in sql


# ---------------------------------------------------------------------------
# R1.5 — duplicate rejection with the {message, code} contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_email_raises_with_code_and_message():
    db = _CapturingDB(found=True)
    svc = StaffService(db)

    with pytest.raises(DuplicateStaffError) as exc_info:
        await svc._check_duplicates(uuid.uuid4(), "jane@example.com", None, None)

    err = exc_info.value
    assert err.code == "duplicate_email"
    assert "Email" in err.message
    assert "already in use" in err.message
    # backwards compatible with existing `except ValueError` handlers
    assert isinstance(err, ValueError)


@pytest.mark.asyncio
async def test_duplicate_employee_id_raises_with_code():
    db = _CapturingDB(found=True)
    svc = StaffService(db)

    with pytest.raises(DuplicateStaffError) as exc_info:
        await svc._check_duplicates(uuid.uuid4(), None, None, "EMP-001")

    assert exc_info.value.code == "duplicate_employee_id"


@pytest.mark.asyncio
async def test_code_reflects_first_conflicting_field():
    """When multiple fields collide, the code reflects the first one (email)."""
    db = _CapturingDB(found=True)
    svc = StaffService(db)

    with pytest.raises(DuplicateStaffError) as exc_info:
        await svc._check_duplicates(uuid.uuid4(), "jane@example.com", "021", "EMP-1")

    err = exc_info.value
    assert err.code == "duplicate_email"
    # message aggregates every conflicting field
    assert err.message.count("already in use") == 3


@pytest.mark.asyncio
async def test_no_duplicate_does_not_raise_and_skips_empty_fields():
    db = _CapturingDB(found=False)
    svc = StaffService(db)

    # email + employee_id present; phone is whitespace-only → skipped
    await svc._check_duplicates(uuid.uuid4(), "a@b.com", "   ", "EMP")

    # only the two non-empty fields are queried
    assert len(db.statements) == 2
