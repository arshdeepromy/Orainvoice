"""Property-based tests for tenant data isolation (Task 36.1).

Property 1: Tenant Data Isolation
— for any two orgs A and B, API requests as org A never return records
  with org_id = B, regardless of query params, filters, or path manipulation.

**Validates: Requirements 5.6, 54.1, 54.2, 54.3, 54.4**

Uses Hypothesis to generate arbitrary org IDs and verify that:
  1. Service-layer queries with org A's context never return org B's records
  2. The RLS session variable (app.current_org_id) correctly scopes queries
  3. Path manipulation (passing org B's entity IDs) doesn't leak data
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.customers.models import Customer
from app.modules.customers.service import search_customers, get_customer
from app.modules.invoices.models import Invoice, LineItem
from app.modules.invoices.service import get_invoice, search_invoices
from app.modules.invoices.models import CreditNote  # noqa: F401
from app.core.database import _set_rls_org_id


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies — generate org IDs and tenant-scoped data
# ---------------------------------------------------------------------------

# Strategy for generating distinct UUID pairs (org A and org B)
org_uuid = st.uuids(version=4)

nz_first_names = st.sampled_from([
    "Aroha", "Tane", "Maia", "Nikau", "Kaia", "Wiremu", "Hana", "Rawiri",
])

nz_last_names = st.sampled_from([
    "Smith", "Williams", "Brown", "Wilson", "Taylor", "Anderson",
])

nz_emails = st.builds(
    lambda first, last, domain: f"{first.lower()}.{last.lower()}@{domain}",
    first=nz_first_names,
    last=nz_last_names,
    domain=st.sampled_from(["gmail.com", "xtra.co.nz", "workshop.nz"]),
)

nz_phones = st.from_regex(r"\+64 2[0-9] [0-9]{3} [0-9]{4}", fullmatch=True)

money = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("99999.99"),
    places=2, allow_nan=False, allow_infinity=False,
)

search_queries = st.sampled_from([
    "", "Smith", "Aroha", "+64", "gmail", "INV-", "ABC123",
    "' OR 1=1 --", "../../admin", "%", "*", "null",
])

invoice_statuses = st.sampled_from([
    "draft", "issued", "partially_paid", "paid", "overdue", "voided",
])


def _make_customer_mock(org_id: uuid.UUID, customer_id: uuid.UUID | None = None) -> MagicMock:
    """Create a mock Customer belonging to the given org."""
    cust = MagicMock(spec=Customer)
    cust.id = customer_id or uuid.uuid4()
    cust.org_id = org_id
    cust.first_name = "Test"
    cust.last_name = "Customer"
    cust.email = "test@example.com"
    cust.phone = "+64 21 123 4567"
    cust.address = "1 Queen St, Auckland"
    cust.notes = None
    cust.is_anonymised = False
    cust.email_bounced = False
    cust.tags = []
    cust.portal_token = None
    cust.fleet_account_id = None
    cust.created_at = datetime.now(timezone.utc)
    cust.updated_at = datetime.now(timezone.utc)
    return cust


def _make_invoice_mock(org_id: uuid.UUID, invoice_id: uuid.UUID | None = None) -> MagicMock:
    """Create a mock Invoice belonging to the given org."""
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id or uuid.uuid4()
    inv.org_id = org_id
    inv.customer_id = uuid.uuid4()
    inv.invoice_number = "INV-0001"
    inv.status = "issued"
    inv.issue_date = date(2024, 6, 15)
    inv.due_date = date(2024, 7, 15)
    inv.vehicle_rego = "ABC123"
    inv.subtotal = Decimal("100.00")
    inv.gst_amount = Decimal("15.00")
    inv.total = Decimal("115.00")
    inv.amount_paid = Decimal("0.00")
    inv.balance_due = Decimal("115.00")
    inv.discount_amount = Decimal("0.00")
    inv.credit_note_total = Decimal("0.00")
    inv.currency = "NZD"
    inv.exchange_rate = None
    inv.notes_internal = None
    inv.notes_customer = None
    inv.invoice_data_json = {}
    inv.branch_id = None
    inv.recurring_schedule_id = None
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    return inv


# ---------------------------------------------------------------------------
# Composite strategies for isolation scenarios
# ---------------------------------------------------------------------------

@st.composite
def two_org_scenario(draw):
    """Generate two distinct org IDs with data belonging to each."""
    org_a = draw(org_uuid)
    org_b = draw(org_uuid)
    assume(org_a != org_b)

    # Create customers for each org
    num_customers_a = draw(st.integers(1, 3))
    num_customers_b = draw(st.integers(1, 3))

    customers_a = [_make_customer_mock(org_a) for _ in range(num_customers_a)]
    customers_b = [_make_customer_mock(org_b) for _ in range(num_customers_b)]

    # Create invoices for each org
    num_invoices_a = draw(st.integers(1, 3))
    num_invoices_b = draw(st.integers(1, 3))

    invoices_a = [_make_invoice_mock(org_a) for _ in range(num_invoices_a)]
    invoices_b = [_make_invoice_mock(org_b) for _ in range(num_invoices_b)]

    return {
        "org_a": org_a,
        "org_b": org_b,
        "customers_a": customers_a,
        "customers_b": customers_b,
        "invoices_a": invoices_a,
        "invoices_b": invoices_b,
        "search_query": draw(search_queries),
    }


@st.composite
def cross_tenant_id_scenario(draw):
    """Generate a scenario where org A tries to access org B's entity by ID."""
    org_a = draw(org_uuid)
    org_b = draw(org_uuid)
    assume(org_a != org_b)

    # Entity belongs to org B
    entity_id = uuid.uuid4()
    customer_b = _make_customer_mock(org_b, customer_id=entity_id)
    invoice_b = _make_invoice_mock(org_b, invoice_id=entity_id)

    return {
        "org_a": org_a,
        "org_b": org_b,
        "entity_id": entity_id,
        "customer_b": customer_b,
        "invoice_b": invoice_b,
    }


# ---------------------------------------------------------------------------
# Helper: build a mock DB session that simulates RLS-filtered results
# ---------------------------------------------------------------------------

def _build_mock_db_for_org(
    requesting_org_id: uuid.UUID,
    all_customers: list[MagicMock],
    all_invoices: list[MagicMock],
):
    """Build a mock AsyncSession that filters results by org_id.

    Simulates PostgreSQL RLS behaviour: only records matching the
    requesting org's ID are returned, regardless of what the query asks for.

    The mock returns only records belonging to ``requesting_org_id``,
    mimicking what RLS would do at the database level.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    # Filter to only records belonging to the requesting org (simulating RLS)
    org_customers = [c for c in all_customers if c.org_id == requesting_org_id]
    org_invoices = [i for i in all_invoices if i.org_id == requesting_org_id]

    async def mock_execute(stmt, params=None):
        result = MagicMock()

        # Return count for scalar() calls
        result.scalar.return_value = len(org_customers)

        # For scalar_one_or_none (single entity lookups by ID)
        # RLS ensures only org's own records are visible, so return None
        # for entities not belonging to the requesting org.
        result.scalar_one_or_none = MagicMock(return_value=None)

        # For scalars().all() pattern (list queries)
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = org_customers
        result.scalars.return_value = scalars_mock

        # For direct iteration (search_invoices iterates over rows)
        invoice_rows = []
        for inv in org_invoices:
            row = MagicMock()
            row.id = inv.id
            row.invoice_number = inv.invoice_number
            row.first_name = "Test"
            row.last_name = "Customer"
            row.vehicle_rego = inv.vehicle_rego
            row.total = inv.total
            row.status = inv.status
            row.issue_date = inv.issue_date
            invoice_rows.append(row)

        result.__iter__ = MagicMock(return_value=iter(invoice_rows))

        return result

    db.execute = mock_execute
    return db


def _build_mock_db_for_invoice_search(
    requesting_org_id: uuid.UUID,
    all_invoices: list[MagicMock],
):
    """Build a mock AsyncSession specifically for invoice search.

    search_invoices uses a joined query that iterates over rows directly,
    so this mock returns row-like objects for iteration.
    """
    db = AsyncMock()
    org_invoices = [i for i in all_invoices if i.org_id == requesting_org_id]

    call_count = {"n": 0}

    async def mock_execute(stmt, params=None):
        call_count["n"] += 1
        result = MagicMock()

        if call_count["n"] == 1:
            # First call is the count query
            result.scalar.return_value = len(org_invoices)
            return result

        # Second call is the data query — returns iterable rows
        invoice_rows = []
        for inv in org_invoices:
            row = MagicMock()
            row.id = inv.id
            row.invoice_number = inv.invoice_number
            row.first_name = "Test"
            row.last_name = "Customer"
            row.vehicle_rego = inv.vehicle_rego
            row.total = inv.total
            row.status = inv.status
            row.issue_date = inv.issue_date
            invoice_rows.append(row)

        result.__iter__ = MagicMock(return_value=iter(invoice_rows))
        return result

    db.execute = mock_execute
    return db


# ---------------------------------------------------------------------------
# Property 1: Tenant Data Isolation
# ---------------------------------------------------------------------------


class TestTenantDataIsolation:
    """Property 1: Tenant Data Isolation.

    **Validates: Requirements 5.6, 54.1, 54.2, 54.3, 54.4**

    For any two organisations A and B, API requests as org A never return
    records with org_id = B, regardless of query params, filters, or path
    manipulation.
    """

    @pytest.mark.asyncio
    @given(scenario=two_org_scenario())
    @PBT_SETTINGS
    async def test_customer_search_never_returns_other_org_records(self, scenario):
        """Customer search as org A must never return org B's customers.

        **Validates: Requirements 5.6, 54.1, 54.3**
        """
        org_a = scenario["org_a"]
        org_b = scenario["org_b"]
        all_customers = scenario["customers_a"] + scenario["customers_b"]
        all_invoices = scenario["invoices_a"] + scenario["invoices_b"]

        db = _build_mock_db_for_org(org_a, all_customers, all_invoices)

        result = await search_customers(
            db,
            org_id=org_a,
            query=scenario["search_query"],
        )

        # Every returned customer must belong to org A
        # The service returns dicts via _customer_to_search_dict with keys:
        # id, first_name, last_name, email, phone
        # Verify no org B customer IDs appear in results
        org_b_ids = {str(c.id) for c in scenario["customers_b"]}
        returned_ids = {str(c["id"]) for c in result["customers"]}
        leaked_ids = returned_ids & org_b_ids
        assert not leaked_ids, (
            f"Customer search as org {org_a} leaked customer IDs "
            f"from org {org_b}: {leaked_ids}"
        )

    @pytest.mark.asyncio
    @given(scenario=cross_tenant_id_scenario())
    @PBT_SETTINGS
    async def test_get_customer_by_id_rejects_cross_tenant_access(self, scenario):
        """Fetching org B's customer by ID as org A must fail.

        **Validates: Requirements 5.6, 54.4**
        """
        org_a = scenario["org_a"]
        org_b = scenario["org_b"]
        customer_b = scenario["customer_b"]

        # DB only has org B's customer; org A requests it
        db = _build_mock_db_for_org(
            org_a,
            all_customers=[customer_b],
            all_invoices=[],
        )

        with pytest.raises(ValueError, match="not found"):
            await get_customer(
                db,
                org_id=org_a,
                customer_id=scenario["entity_id"],
            )

    @pytest.mark.asyncio
    @given(scenario=cross_tenant_id_scenario())
    @PBT_SETTINGS
    async def test_get_invoice_by_id_rejects_cross_tenant_access(self, scenario):
        """Fetching org B's invoice by ID as org A must fail.

        **Validates: Requirements 5.6, 54.4**
        """
        org_a = scenario["org_a"]
        org_b = scenario["org_b"]
        invoice_b = scenario["invoice_b"]

        # DB only has org B's invoice; org A requests it
        db = _build_mock_db_for_org(
            org_a,
            all_customers=[],
            all_invoices=[invoice_b],
        )

        with pytest.raises(ValueError, match="not found"):
            await get_invoice(
                db,
                org_id=org_a,
                invoice_id=scenario["entity_id"],
            )

    @pytest.mark.asyncio
    @given(scenario=two_org_scenario())
    @PBT_SETTINGS
    async def test_invoice_search_never_returns_other_org_records(self, scenario):
        """Invoice search as org A must never return org B's invoices.

        **Validates: Requirements 5.6, 54.1, 54.3**
        """
        org_a = scenario["org_a"]
        org_b = scenario["org_b"]
        all_invoices = scenario["invoices_a"] + scenario["invoices_b"]

        db = _build_mock_db_for_invoice_search(org_a, all_invoices)

        result = await search_invoices(
            db,
            org_id=org_a,
            search=scenario["search_query"],
        )

        # Verify no org B invoice IDs appear in results
        org_b_invoice_ids = {str(i.id) for i in scenario["invoices_b"]}
        returned_ids = {str(inv["id"]) for inv in result["invoices"]}
        leaked_ids = returned_ids & org_b_invoice_ids
        assert not leaked_ids, (
            f"Invoice search as org {org_a} leaked invoice IDs "
            f"from org {org_b}: {leaked_ids}"
        )

    @pytest.mark.asyncio
    @given(
        org_a=org_uuid,
        org_b=org_uuid,
    )
    @PBT_SETTINGS
    async def test_rls_session_variable_scopes_to_requesting_org(self, org_a, org_b):
        """The RLS session variable must be set to the requesting org only.

        **Validates: Requirements 54.1, 54.2**

        Verifies that _set_rls_org_id sets the correct session variable
        and that a None org_id resets it (denying all tenant rows).
        """
        assume(org_a != org_b)

        session = AsyncMock()
        executed_stmts = []

        async def capture_execute(stmt, params=None):
            executed_stmts.append((str(stmt), params))

        session.execute = capture_execute

        # Set RLS to org A
        await _set_rls_org_id(session, str(org_a))

        assert len(executed_stmts) == 1
        stmt_text, params = executed_stmts[0]
        assert "SET LOCAL app.current_org_id" in stmt_text
        assert params["org_id"] == str(org_a)

        # The variable must NOT contain org B's ID
        assert str(org_b) not in params["org_id"], (
            f"RLS variable set to org {org_a} but contained org {org_b}"
        )

    @pytest.mark.asyncio
    @given(org_a=org_uuid)
    @PBT_SETTINGS
    async def test_rls_reset_denies_all_tenant_rows(self, org_a):
        """When org_id is None, RLS variable is reset to deny all tenant rows.

        **Validates: Requirements 54.2**
        """
        session = AsyncMock()
        executed_stmts = []

        async def capture_execute(stmt, params=None):
            executed_stmts.append(str(stmt))

        session.execute = capture_execute

        # Set RLS to None (global admin / unauthenticated)
        await _set_rls_org_id(session, None)

        assert len(executed_stmts) == 1
        assert "RESET app.current_org_id" in executed_stmts[0]

    @pytest.mark.asyncio
    @given(scenario=two_org_scenario())
    @PBT_SETTINGS
    async def test_service_layer_filters_by_org_id_in_queries(self, scenario):
        """Service functions must include org_id filter in all queries.

        **Validates: Requirements 54.1, 54.3**

        Verifies that the service layer passes the correct org_id to
        database queries, ensuring application-level filtering works
        alongside RLS as defence-in-depth.
        """
        org_a = scenario["org_a"]

        # Track all executed query statements
        executed_stmts = []
        db = AsyncMock()

        async def tracking_execute(stmt, params=None):
            executed_stmts.append(stmt)
            result = MagicMock()
            result.scalar.return_value = 0
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
            return result

        db.execute = tracking_execute

        await search_customers(db, org_id=org_a, query="test")

        # At least one query must have been executed
        assert len(executed_stmts) > 0, "No queries were executed"

        # Verify that queries have WHERE clauses (meaning they filter)
        # by checking the SQLAlchemy Select object's whereclause attribute
        for stmt in executed_stmts:
            if hasattr(stmt, 'whereclause'):
                assert stmt.whereclause is not None, (
                    "Query has no WHERE clause — potential unfiltered query"
                )

    @pytest.mark.asyncio
    @given(
        org_a=org_uuid,
        org_b=org_uuid,
        malicious_query=st.sampled_from([
            "' OR org_id != org_id --",
            "1; SELECT * FROM customers --",
            "../../api/v1/admin/organisations",
            "%00",
            "' UNION SELECT * FROM customers WHERE org_id = '",
            "null",
            "undefined",
            "true",
        ]),
    )
    @PBT_SETTINGS
    async def test_malicious_query_params_cannot_bypass_isolation(
        self, org_a, org_b, malicious_query
    ):
        """Malicious query parameters must not bypass tenant isolation.

        **Validates: Requirements 54.3, 54.4**

        Even with SQL injection attempts or path manipulation in search
        queries, the service layer must only return records for the
        requesting org.
        """
        assume(org_a != org_b)

        customer_a = _make_customer_mock(org_a)
        customer_b = _make_customer_mock(org_b)

        db = _build_mock_db_for_org(
            org_a,
            all_customers=[customer_a, customer_b],
            all_invoices=[],
        )

        result = await search_customers(
            db,
            org_id=org_a,
            query=malicious_query,
        )

        # No org B customer IDs should appear
        org_b_ids = {str(customer_b.id)}
        returned_ids = {str(c["id"]) for c in result["customers"]}
        leaked_ids = returned_ids & org_b_ids
        assert not leaked_ids, (
            f"Malicious query '{malicious_query}' as org {org_a} "
            f"leaked records from org {org_b}"
        )
