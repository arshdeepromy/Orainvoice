"""Unit tests for staff Pydantic schemas (Phase 1, task B3).

Covers ``StaffMemberCreate``, ``StaffMemberUpdate``, ``StaffMemberResponse``,
``StaffPayRateResponse``, ``StaffPayRateListResponse``,
``RosterEmailRequest`` / ``RosterSmsRequest`` / ``RosterSendResponse``.

Focus areas (per task B3 verify line):
- Happy-path acceptance of all new Phase 1 fields.
- Mask round-trip — plaintext ``ird_number`` / ``bank_account_number``
  is masked on the response model.
- Mask-pattern values rejected on UPDATE (fast 422 feedback).
- Enum values (``employment_type``, ``residency_type``, ``tax_code``)
  reject invalid input.
- Default values applied when fields omitted.
- KiwiSaver employee rate must be one of the allowed IRD rates.

**Validates: Requirements R2, R3, R4, R8, R9 — Staff Phase 1 schemas**
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.staff.schemas import (
    RosterEmailRequest,
    RosterSendResponse,
    RosterSmsRequest,
    StaffMemberCreate,
    StaffMemberResponse,
    StaffMemberUpdate,
    StaffPayRateListResponse,
    StaffPayRateResponse,
)


# ---------------------------------------------------------------------------
# StaffMemberCreate — happy path + defaults + enums + KiwiSaver rate
# ---------------------------------------------------------------------------


class TestStaffMemberCreateHappyPath:
    """``StaffMemberCreate`` accepts the full Phase 1 payload."""

    def test_full_phase1_payload_parses(self) -> None:
        payload = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@acme.co.nz",
            "phone": "021999000",
            "employee_id": "EMP-001",
            "position": "Mechanic",
            "hourly_rate": Decimal("28.50"),
            "overtime_rate": Decimal("42.75"),
            # Phase 1 employment record
            "employment_start_date": date(2024, 1, 15),
            "employment_end_date": None,
            "employment_type": "permanent",
            "standard_hours_per_week": Decimal("40.00"),
            "tax_code": "M",
            "ird_number": "123456789",
            "student_loan": True,
            "kiwisaver_enrolled": True,
            "kiwisaver_employee_rate": Decimal("3"),
            "kiwisaver_employer_rate": Decimal("3.00"),
            "bank_account_number": "02-1234-56789012-23",
            "probation_end_date": date(2024, 4, 15),
            "residency_type": "citizen",
            "visa_expiry_date": None,
            "self_service_clock_enabled": True,
            "on_file_photo_url": "https://uploads.example/photo.jpg",
            "emergency_contact_name": "John Doe",
            "emergency_contact_phone": "021999111",
            "weekly_roster_email_enabled": True,
            "weekly_roster_sms_enabled": False,
            "minimum_wage_override": False,
        }

        m = StaffMemberCreate(**payload)

        # The schema preserves the plaintext on input — the service
        # encrypts before storage; masking happens on response only.
        assert m.first_name == "Jane"
        assert m.tax_code == "M"
        assert m.ird_number == "123456789"
        assert m.bank_account_number == "02-1234-56789012-23"
        assert m.kiwisaver_enrolled is True
        assert m.kiwisaver_employee_rate == Decimal("3")
        assert m.residency_type == "citizen"
        assert m.employment_type == "permanent"
        assert m.minimum_wage_override is False

    def test_defaults_applied_when_phase1_fields_omitted(self) -> None:
        m = StaffMemberCreate(first_name="Jane")

        # Defaults documented in R2.1 + design §3.1.
        assert m.employment_type == "permanent"
        assert m.residency_type == "citizen"
        assert m.student_loan is False
        assert m.kiwisaver_enrolled is False
        assert m.kiwisaver_employer_rate == Decimal("3.00")
        # Phase 3 task B3a (G9): tri-state — schema default is now
        # ``None`` so the service can distinguish "caller didn't say"
        # from "explicitly false". The service then resolves the value
        # from ``organisations.clock_in_policy.default_channel``.
        assert m.self_service_clock_enabled is None
        assert m.weekly_roster_email_enabled is True
        assert m.weekly_roster_sms_enabled is False
        assert m.minimum_wage_override is False
        # Optional Phase 1 fields default to None.
        assert m.tax_code is None
        assert m.ird_number is None
        assert m.bank_account_number is None
        assert m.employment_start_date is None
        assert m.visa_expiry_date is None

    def test_minimum_wage_override_flag_accepted(self) -> None:
        m = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=True,
        )
        assert m.minimum_wage_override is True


class TestStaffMemberCreateEnums:
    """Invalid enum values are rejected at the schema layer."""

    def test_invalid_employment_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberCreate(first_name="Jane", employment_type="freelancer")

    def test_invalid_residency_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberCreate(first_name="Jane", residency_type="alien")

    def test_invalid_tax_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberCreate(first_name="Jane", tax_code="ZZ")

    def test_all_residency_types_accepted(self) -> None:
        for rt in (
            "citizen",
            "permanent_resident",
            "work_visa",
            "student_visa",
            "other",
        ):
            assert StaffMemberCreate(first_name="J", residency_type=rt).residency_type == rt

    def test_all_employment_types_accepted(self) -> None:
        for et in ("permanent", "casual", "fixed_term"):
            assert StaffMemberCreate(first_name="J", employment_type=et).employment_type == et

    def test_all_tax_codes_accepted(self) -> None:
        for tc in ("M", "ME", "S", "SH", "ST", "SB", "CAE", "NSW", "ND"):
            assert StaffMemberCreate(first_name="J", tax_code=tc).tax_code == tc


class TestKiwisaverRateValidation:
    """``kiwisaver_employee_rate`` accepts any custom value in 0–100 (the
    IRD-standard-only restriction was lifted per org request)."""

    @pytest.mark.parametrize(
        "rate",
        [
            Decimal("3"), Decimal("3.5"), Decimal("4"), Decimal("5"),
            Decimal("6"), Decimal("8"), Decimal("10"), Decimal("0"),
            Decimal("12.5"),
        ],
    )
    def test_custom_rates_accepted(self, rate: Decimal) -> None:
        m = StaffMemberCreate(
            first_name="Jane",
            kiwisaver_enrolled=True,
            kiwisaver_employee_rate=rate,
        )
        assert m.kiwisaver_employee_rate == rate

    @pytest.mark.parametrize("rate", [Decimal("-1"), Decimal("101"), Decimal("200")])
    def test_out_of_range_rate_raises(self, rate: Decimal) -> None:
        with pytest.raises(ValidationError):
            StaffMemberCreate(
                first_name="Jane",
                kiwisaver_enrolled=True,
                kiwisaver_employee_rate=rate,
            )

    def test_none_accepted(self) -> None:
        # Allows clearing the field on update / leaving it unset on create
        # for staff who haven't enrolled in KiwiSaver yet.
        m = StaffMemberCreate(first_name="Jane", kiwisaver_employee_rate=None)
        assert m.kiwisaver_employee_rate is None


# ---------------------------------------------------------------------------
# StaffMemberUpdate — mask-pattern rejection (R2.4)
# ---------------------------------------------------------------------------


class TestStaffMemberUpdateMaskRejection:
    """UPDATE rejects mask-pattern values for IRD + bank with HTTP 422."""

    def test_masked_ird_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            StaffMemberUpdate(ird_number="***789")
        # Exception text mentions the field for client clarity.
        assert "ird_number" in str(exc_info.value)

    def test_masked_ird_with_four_stars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberUpdate(ird_number="****789")

    def test_masked_bank_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            StaffMemberUpdate(bank_account_number="**-****-****12-**")
        assert "bank_account_number" in str(exc_info.value)

    def test_plaintext_ird_accepted(self) -> None:
        m = StaffMemberUpdate(ird_number="123456789")
        assert m.ird_number == "123456789"

    def test_plaintext_bank_accepted(self) -> None:
        m = StaffMemberUpdate(bank_account_number="02-1234-56789012-23")
        assert m.bank_account_number == "02-1234-56789012-23"

    def test_none_accepted_for_ird(self) -> None:
        # ``None`` means "don't change this field" — must not trip the
        # mask-rejection validator.
        m = StaffMemberUpdate(ird_number=None)
        assert m.ird_number is None

    def test_none_accepted_for_bank(self) -> None:
        m = StaffMemberUpdate(bank_account_number=None)
        assert m.bank_account_number is None

    def test_masked_ird_rejected_with_whitespace(self) -> None:
        # The mask detector strips surrounding whitespace.
        with pytest.raises(ValidationError):
            StaffMemberUpdate(ird_number="  ***789  ")


class TestStaffMemberUpdateEnums:
    """UPDATE shares the same enum constraints as CREATE."""

    def test_invalid_employment_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberUpdate(employment_type="freelancer")

    def test_invalid_residency_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberUpdate(residency_type="alien")

    def test_invalid_tax_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            StaffMemberUpdate(tax_code="ZZ")

    def test_omitted_fields_default_to_none(self) -> None:
        # Empty update body should produce an all-None model so service
        # can iterate ``model_dump(exclude_none=True)`` and write nothing.
        m = StaffMemberUpdate()
        assert m.first_name is None
        assert m.employment_type is None
        assert m.residency_type is None
        assert m.tax_code is None
        assert m.minimum_wage_override is False  # only request flag with default


# ---------------------------------------------------------------------------
# StaffMemberResponse — masking on outbound serialisation
# ---------------------------------------------------------------------------


def _response_kwargs(**overrides):
    """Helper — minimum valid kwargs for ``StaffMemberResponse``."""
    base = {
        "id": uuid4(),
        "org_id": uuid4(),
        "user_id": None,
        "name": "Jane Doe",
        "first_name": "Jane",
        "role_type": "employee",
        "is_active": True,
        "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


class TestStaffMemberResponseMasking:
    """IRD + bank are returned in FULL on the outbound model.

    Masking was removed (operationally required full visibility on the
    staff details page, which is RBAC-gated to staff-management roles).
    The values remain envelope-encrypted at rest; the router decrypts
    them only for this trusted serialisation path.
    """

    def test_plaintext_ird_is_returned_in_full(self) -> None:
        r = StaffMemberResponse(**_response_kwargs(ird_number="123456789"))
        assert r.ird_number == "123456789"

    def test_none_ird_stays_none(self) -> None:
        r = StaffMemberResponse(**_response_kwargs(ird_number=None))
        assert r.ird_number is None

    def test_plaintext_bank_is_returned_in_full(self) -> None:
        r = StaffMemberResponse(
            **_response_kwargs(bank_account_number="02-1234-56789012-23"),
        )
        assert r.bank_account_number == "02-1234-56789012-23"

    def test_none_bank_stays_none(self) -> None:
        r = StaffMemberResponse(**_response_kwargs(bank_account_number=None))
        assert r.bank_account_number is None


class TestMaskRoundTrip:
    """Service-emulation round-trip: input plaintext → response full value."""

    def test_create_then_response_returns_full_ird(self) -> None:
        # Caller submits plaintext (CREATE).
        c = StaffMemberCreate(first_name="Jane", ird_number="123456789")
        assert c.ird_number == "123456789"

        # Service stores the ciphertext, then on read constructs a
        # response model with the plaintext (decrypted) — returned in full.
        r = StaffMemberResponse(**_response_kwargs(ird_number=c.ird_number))
        assert r.ird_number == "123456789"

    def test_create_then_response_returns_full_bank(self) -> None:
        c = StaffMemberCreate(
            first_name="Jane", bank_account_number="02-1234-56789012-23",
        )
        assert c.bank_account_number == "02-1234-56789012-23"

        r = StaffMemberResponse(
            **_response_kwargs(bank_account_number=c.bank_account_number),
        )
        assert r.bank_account_number == "02-1234-56789012-23"


class TestStaffMemberResponseDefaults:
    """Phase 1 fields default to their documented values."""

    def test_defaults_applied_when_omitted(self) -> None:
        r = StaffMemberResponse(**_response_kwargs())

        assert r.employment_type == "permanent"
        assert r.residency_type == "citizen"
        assert r.student_loan is False
        assert r.kiwisaver_enrolled is False
        assert r.kiwisaver_employer_rate == Decimal("3.00")
        assert r.self_service_clock_enabled is False
        assert r.weekly_roster_email_enabled is True
        assert r.weekly_roster_sms_enabled is False
        assert r.tax_code is None
        assert r.ird_number is None
        assert r.bank_account_number is None


# ---------------------------------------------------------------------------
# StaffPayRateResponse + StaffPayRateListResponse (R3)
# ---------------------------------------------------------------------------


class TestStaffPayRateSchemas:
    """Pay rate audit ledger schemas."""

    def test_pay_rate_response_parses(self) -> None:
        r = StaffPayRateResponse(
            id=uuid4(),
            effective_from=date(2024, 1, 1),
            hourly_rate=Decimal("28.50"),
            overtime_rate=Decimal("42.75"),
            change_reason="initial_rate",
            changed_by_email="admin@acme.co.nz",
        )
        assert r.change_reason == "initial_rate"
        assert r.changed_by_email == "admin@acme.co.nz"

    def test_pay_rate_response_optional_fields(self) -> None:
        r = StaffPayRateResponse(
            id=uuid4(),
            effective_from=date(2024, 1, 1),
        )
        assert r.hourly_rate is None
        assert r.overtime_rate is None
        assert r.change_reason is None
        assert r.changed_by_email is None

    def test_list_response_uses_items_and_total(self) -> None:
        # Per project-overview rule: arrays go in ``{ items, total }``.
        item = StaffPayRateResponse(
            id=uuid4(), effective_from=date(2024, 1, 1),
        )
        lr = StaffPayRateListResponse(items=[item], total=1)
        assert lr.total == 1
        assert len(lr.items) == 1
        # JSON round-trip uses the canonical keys.
        dumped = lr.model_dump()
        assert "items" in dumped
        assert "total" in dumped


# ---------------------------------------------------------------------------
# Roster delivery schemas (R8, R9)
# ---------------------------------------------------------------------------


class TestRosterDeliverySchemas:
    """Email / SMS roster request + response shapes."""

    def test_email_request_requires_week_start(self) -> None:
        with pytest.raises(ValidationError):
            RosterEmailRequest()  # type: ignore[call-arg]

    def test_email_request_parses_iso_date(self) -> None:
        r = RosterEmailRequest(week_start=date(2024, 1, 1))
        assert r.week_start == date(2024, 1, 1)

    def test_email_request_coerces_iso_string(self) -> None:
        r = RosterEmailRequest.model_validate({"week_start": "2024-01-01"})
        assert r.week_start == date(2024, 1, 1)

    def test_sms_request_requires_week_start(self) -> None:
        with pytest.raises(ValidationError):
            RosterSmsRequest()  # type: ignore[call-arg]

    def test_send_response_success(self) -> None:
        r = RosterSendResponse(ok=True, message_id="msg_123")
        assert r.ok is True
        assert r.message_id == "msg_123"
        assert r.reason is None

    def test_send_response_failure(self) -> None:
        r = RosterSendResponse(ok=False, reason="no_shifts_in_week")
        assert r.ok is False
        assert r.message_id is None
        assert r.reason == "no_shifts_in_week"

    def test_send_response_requires_ok(self) -> None:
        with pytest.raises(ValidationError):
            RosterSendResponse()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Cross-schema sanity: UUID + datetime fields coerce
# ---------------------------------------------------------------------------


class TestCoercion:
    """Ensure ISO strings coerce into the proper Python types."""

    def test_response_accepts_uuid_string(self) -> None:
        kwargs = _response_kwargs()
        kwargs["id"] = str(kwargs["id"])
        kwargs["org_id"] = str(kwargs["org_id"])
        r = StaffMemberResponse.model_validate(kwargs)
        assert isinstance(r.id, UUID)
        assert isinstance(r.org_id, UUID)
