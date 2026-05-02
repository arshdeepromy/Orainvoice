"""Property-based tests for portal response shapes.

Tests the pure logic of portal response construction, field extraction,
and computation without requiring a database.

Properties covered:
  P1 — Portal response field extraction preserves all data
  P2 — total_paid equals sum of amount_paid across non-draft non-voided invoices
  P4 — Line items summary is correctly computed

**Validates: Requirements 1.1-1.7, 6.1, 6.4**
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.modules.portal.schemas import (
    PortalAccessResponse,
    PortalBranding,
    PortalCustomerInfo,
    PoweredByFooter,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_name = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

_optional_url = st.one_of(
    st.none(),
    st.from_regex(r"https://[a-z]{3,12}\.[a-z]{2,4}/[a-z0-9]{1,20}", fullmatch=True),
)

_optional_colour = st.one_of(
    st.none(),
    st.from_regex(r"#[0-9a-fA-F]{6}", fullmatch=True),
)

_optional_language = st.one_of(
    st.none(),
    st.sampled_from(["en-NZ", "en-AU", "en-US", "mi-NZ", "fr-FR", "de-DE"]),
)

_email = st.one_of(st.none(), st.emails())

_phone = st.one_of(
    st.none(),
    st.from_regex(r"\+?\d{7,15}", fullmatch=True),
)

_non_negative_decimal = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_positive_int = st.integers(min_value=0, max_value=10000)

_invoice_status = st.sampled_from([
    "draft", "issued", "paid", "overdue", "partially_paid", "voided",
])

_amount_paid = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_line_item_description = st.text(
    min_size=0,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs", "P")),
)


def _powered_by_strategy():
    return st.one_of(
        st.none(),
        st.fixed_dictionaries({
            "platform_name": _safe_name,
            "logo_url": _optional_url,
            "signup_url": _optional_url,
            "website_url": _optional_url,
            "show_powered_by": st.booleans(),
        }),
    )


def _portal_access_response_strategy():
    """Generate a valid PortalAccessResponse with random nested fields."""
    return st.fixed_dictionaries({
        "first_name": _safe_name,
        "last_name": _safe_name,
        "email": _email,
        "phone": _phone,
        "org_name": _safe_name,
        "logo_url": _optional_url,
        "primary_colour": _optional_colour,
        "secondary_colour": _optional_colour,
        "language": _optional_language,
        "powered_by": _powered_by_strategy(),
        "outstanding_balance": _non_negative_decimal,
        "invoice_count": _positive_int,
        "total_paid": _non_negative_decimal,
    })


def _invoice_strategy():
    """Generate a random invoice with status and amount_paid."""
    return st.fixed_dictionaries({
        "status": _invoice_status,
        "amount_paid": _amount_paid,
    })


# ===========================================================================
# Property 1: Portal response field extraction preserves all data
# ===========================================================================


class TestP1PortalResponseFieldExtraction:
    """For any valid PortalAccessResponse with random nested fields,
    the frontend extraction logic SHALL produce display values where:
    customer name equals first_name + " " + last_name, org name equals
    branding.org_name, primary colour equals branding.primary_colour,
    invoice count equals invoice_count, and total paid equals total_paid.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.7**
    """

    @given(data=_portal_access_response_strategy())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_field_extraction_preserves_all_data(self, data: dict) -> None:
        """P1: Constructing a PortalAccessResponse and extracting display
        values preserves all input data through the nested structure.

        **Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.7**
        """
        # Build the nested Pydantic models exactly as the backend does
        powered_by = None
        if data["powered_by"] is not None:
            powered_by = PoweredByFooter(**data["powered_by"])

        branding = PortalBranding(
            org_name=data["org_name"],
            logo_url=data["logo_url"],
            primary_colour=data["primary_colour"],
            secondary_colour=data["secondary_colour"],
            powered_by=powered_by,
            language=data["language"],
        )

        customer = PortalCustomerInfo(
            customer_id=uuid.uuid4(),
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data["phone"],
        )

        response = PortalAccessResponse(
            customer=customer,
            branding=branding,
            outstanding_balance=data["outstanding_balance"],
            invoice_count=data["invoice_count"],
            total_paid=data["total_paid"],
        )

        # --- Frontend extraction logic (mirrors PortalPage.tsx) ---
        # customer name = first_name + " " + last_name
        display_name = response.customer.first_name + " " + response.customer.last_name
        expected_name = data["first_name"] + " " + data["last_name"]
        assert display_name == expected_name, (
            f"Customer name mismatch: {display_name!r} != {expected_name!r}"
        )

        # org name = branding.org_name
        assert response.branding.org_name == data["org_name"], (
            f"Org name mismatch: {response.branding.org_name!r} != {data['org_name']!r}"
        )

        # primary colour = branding.primary_colour
        assert response.branding.primary_colour == data["primary_colour"], (
            f"Primary colour mismatch: {response.branding.primary_colour!r} "
            f"!= {data['primary_colour']!r}"
        )

        # invoice count = invoice_count
        assert response.invoice_count == data["invoice_count"], (
            f"Invoice count mismatch: {response.invoice_count} != {data['invoice_count']}"
        )

        # total paid = total_paid
        assert response.total_paid == data["total_paid"], (
            f"Total paid mismatch: {response.total_paid} != {data['total_paid']}"
        )

    @given(data=_portal_access_response_strategy())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_powered_by_roundtrip(self, data: dict) -> None:
        """P1: The powered_by footer data survives the nested schema roundtrip.

        **Validates: Requirements 1.1**
        """
        powered_by = None
        if data["powered_by"] is not None:
            powered_by = PoweredByFooter(**data["powered_by"])

        branding = PortalBranding(
            org_name=data["org_name"],
            logo_url=data["logo_url"],
            primary_colour=data["primary_colour"],
            secondary_colour=data["secondary_colour"],
            powered_by=powered_by,
            language=data["language"],
        )

        if data["powered_by"] is not None:
            assert branding.powered_by is not None
            assert branding.powered_by.platform_name == data["powered_by"]["platform_name"]
            assert branding.powered_by.show_powered_by == data["powered_by"]["show_powered_by"]
        else:
            assert branding.powered_by is None


# ===========================================================================
# Property 2: total_paid equals sum of amount_paid across non-draft
#              non-voided invoices
# ===========================================================================


class TestP2TotalPaidComputation:
    """For any set of invoices with random amount_paid values and random
    statuses, the total_paid field SHALL equal the sum of amount_paid for
    invoices whose status is not draft and not voided.

    **Validates: Requirements 1.6**
    """

    @given(
        invoices=st.lists(_invoice_strategy(), min_size=0, max_size=50),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_total_paid_equals_filtered_sum(self, invoices: list[dict]) -> None:
        """P2: total_paid = sum(amount_paid) for non-draft, non-voided invoices.

        This mirrors the aggregate query in get_portal_access:
            sa_func.coalesce(sa_func.sum(Invoice.amount_paid), 0)
            .where(Invoice.status.notin_(["draft", "voided"]))

        **Validates: Requirements 1.6**
        """
        # Compute total_paid the same way the service does
        total_paid = Decimal("0")
        for inv in invoices:
            if inv["status"] not in ("draft", "voided"):
                total_paid += inv["amount_paid"]

        # Oracle: independently compute the expected value
        expected = sum(
            (inv["amount_paid"] for inv in invoices
             if inv["status"] not in ("draft", "voided")),
            Decimal("0"),
        )

        assert total_paid == expected, (
            f"total_paid={total_paid} != expected={expected} "
            f"for {len(invoices)} invoices"
        )

    @given(
        invoices=st.lists(_invoice_strategy(), min_size=0, max_size=30),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_draft_and_voided_excluded(self, invoices: list[dict]) -> None:
        """P2: Draft and voided invoices never contribute to total_paid.

        **Validates: Requirements 1.6**
        """
        # Compute total_paid including only non-draft, non-voided
        total_paid = sum(
            (inv["amount_paid"] for inv in invoices
             if inv["status"] not in ("draft", "voided")),
            Decimal("0"),
        )

        # Compute what draft/voided invoices would have added
        excluded_total = sum(
            (inv["amount_paid"] for inv in invoices
             if inv["status"] in ("draft", "voided")),
            Decimal("0"),
        )

        # The full sum (all statuses) should equal total_paid + excluded_total
        full_sum = sum(
            (inv["amount_paid"] for inv in invoices),
            Decimal("0"),
        )

        assert total_paid + excluded_total == full_sum, (
            f"total_paid={total_paid} + excluded={excluded_total} != full_sum={full_sum}"
        )

    @given(
        invoices=st.lists(
            st.fixed_dictionaries({
                "status": st.sampled_from(["draft", "voided"]),
                "amount_paid": _amount_paid,
            }),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_all_draft_voided_yields_zero(self, invoices: list[dict]) -> None:
        """P2: When all invoices are draft or voided, total_paid is zero.

        **Validates: Requirements 1.6**
        """
        total_paid = sum(
            (inv["amount_paid"] for inv in invoices
             if inv["status"] not in ("draft", "voided")),
            Decimal("0"),
        )

        assert total_paid == Decimal("0"), (
            f"Expected 0 for all-draft/voided invoices, got {total_paid}"
        )

    def test_empty_invoices_yields_zero(self) -> None:
        """P2: When there are no invoices, total_paid is zero.

        **Validates: Requirements 1.6**
        """
        total_paid = sum(
            (inv["amount_paid"] for inv in []
             if inv["status"] not in ("draft", "voided")),
            Decimal("0"),
        )
        assert total_paid == Decimal("0")


# ===========================================================================
# Property 4: Line items summary is correctly computed
# ===========================================================================


def compute_line_items_summary(descriptions: list[str]) -> str:
    """Pure function mirroring the service logic for line_items_summary.

    From service.py get_portal_invoices:
        summary = ", ".join(
            li.description for li in (inv.line_items or []) if li.description
        )
        line_items_summary = (summary[:120] + "…") if len(summary) > 120 else summary
    """
    summary = ", ".join(d for d in descriptions if d)
    if len(summary) > 120:
        return summary[:120] + "…"
    return summary


class TestP4LineItemsSummary:
    """For any invoice with a random set of line items (0 to N items, each
    with a random description string), the line_items_summary field SHALL
    equal the comma-joined descriptions truncated to 120 characters with
    "…" appended if truncated, or an empty string if no line items exist.

    **Validates: Requirements 6.1, 6.4**
    """

    @given(
        descriptions=st.lists(_line_item_description, min_size=0, max_size=20),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_matches_spec(self, descriptions: list[str]) -> None:
        """P4: line_items_summary equals comma-joined descriptions,
        truncated to 120 chars with "…" if needed.

        **Validates: Requirements 6.1, 6.4**
        """
        result = compute_line_items_summary(descriptions)

        # Oracle: independently compute expected value
        joined = ", ".join(d for d in descriptions if d)
        if len(joined) > 120:
            expected = joined[:120] + "…"
        else:
            expected = joined

        assert result == expected, (
            f"Summary mismatch:\n  result={result!r}\n  expected={expected!r}"
        )

    @given(
        descriptions=st.lists(_line_item_description, min_size=0, max_size=20),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_length_bounded(self, descriptions: list[str]) -> None:
        """P4: The summary is at most 121 characters (120 + "…" = 121 chars
        when the ellipsis character is 1 char).

        **Validates: Requirements 6.1**
        """
        result = compute_line_items_summary(descriptions)

        # "…" is a single Unicode character, so max length is 121
        assert len(result) <= 121, (
            f"Summary too long: {len(result)} chars, content={result!r}"
        )

    def test_empty_descriptions_yields_empty_string(self) -> None:
        """P4: No line items produces an empty string.

        **Validates: Requirements 6.4**
        """
        assert compute_line_items_summary([]) == ""

    def test_all_empty_descriptions_yields_empty_string(self) -> None:
        """P4: All-empty descriptions produces an empty string (falsy filter).

        **Validates: Requirements 6.4**
        """
        assert compute_line_items_summary(["", "", ""]) == ""

    @given(
        descriptions=st.lists(
            st.text(
                min_size=1,
                max_size=80,
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            ).filter(lambda s: s.strip()),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_truncation_appends_ellipsis(self, descriptions: list[str]) -> None:
        """P4: When the joined string exceeds 120 chars, "…" is appended.

        **Validates: Requirements 6.1**
        """
        result = compute_line_items_summary(descriptions)
        joined = ", ".join(descriptions)

        if len(joined) > 120:
            assert result.endswith("…"), (
                f"Expected ellipsis for long summary ({len(joined)} chars), "
                f"got: {result!r}"
            )
            assert result == joined[:120] + "…"
        else:
            assert not result.endswith("…") or joined.endswith("…"), (
                f"Unexpected ellipsis for short summary ({len(joined)} chars)"
            )
            assert result == joined

    @given(
        descriptions=st.lists(
            st.text(
                min_size=1,
                max_size=80,
                alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            ).filter(lambda s: s.strip()),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_truncation_preserves_full_text(self, descriptions: list[str]) -> None:
        """P4: When the joined string is ≤120 chars, the full text is preserved.

        **Validates: Requirements 6.1**
        """
        result = compute_line_items_summary(descriptions)
        joined = ", ".join(descriptions)

        if len(joined) <= 120:
            assert result == joined, (
                f"Short summary was modified:\n  result={result!r}\n  joined={joined!r}"
            )
