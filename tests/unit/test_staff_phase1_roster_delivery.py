"""Unit tests for the SMS path of ``app.modules.staff.roster_delivery``.

Covers task C6 from ``.kiro/specs/staff-management-p1``:

- :func:`compose_roster_sms_body` produces a body containing the
  staff first name, shift count, and viewer URL (R9.3).
- :func:`_detect_encoding_and_segments` correctly classifies ASCII vs
  Māori-macron bodies as GSM-7 vs UCS-2 with the right segment count
  (R9.3 / G7).
- :func:`_mask_phone_number` returns the ``*****1234`` form expected
  by the audit log row (R9.3 / P1-N12).
- :func:`send_roster_sms` refuses with the right ``reason`` when phone
  is missing / blank, opt-out is set, or there are no shifts in the
  week (R9.2).
- :func:`send_roster_sms` happy path: mints viewer token, composes
  body, calls ``send_sms`` with ``dlq_task_name='roster_sms'`` and the
  expected ``dlq_task_args``, and surfaces the encoding/segments/
  masked-phone on ``audit_extras`` for the router to fold into the
  audit row.
- :func:`send_roster_sms` send-failure path returns ``send_failed``
  while still populating ``audit_extras`` so the audit row captures
  the encoding/segments of the attempted send.

**Validates: Requirement R9** — Staff Management Phase 1 task C6.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.staff.roster_delivery import (
    REASON_NO_PHONE,
    REASON_NO_SHIFTS_IN_WEEK,
    REASON_OPT_OUT,
    REASON_SEND_FAILED,
    RosterDeliveryResult,
    _detect_encoding_and_segments,
    _mask_phone_number,
    compose_roster_sms_body,
    send_roster_sms,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_staff_stub(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    phone: str | None = "+64 21 555 1234",
    weekly_roster_sms_enabled: bool = True,
    first_name: str = "Jane",
    last_name: str | None = "Doe",
):
    """Build a minimal ``StaffMember``-shaped stub.

    The roster_delivery helper accesses: ``id``, ``phone``,
    ``weekly_roster_sms_enabled``, ``first_name``, and ``name``. A
    ``SimpleNamespace`` is enough — we never persist it.
    """
    return SimpleNamespace(
        id=staff_id,
        org_id=org_id,
        phone=phone,
        weekly_roster_sms_enabled=weekly_roster_sms_enabled,
        first_name=first_name,
        last_name=last_name,
        name=f"{first_name} {last_name or ''}".strip(),
    )


def _make_entry(start: datetime, end: datetime, notes: str | None = None):
    """Build a minimal ``ScheduleEntry``-shaped stub for the SMS body
    composer + the renderer."""
    return SimpleNamespace(
        start_time=start,
        end_time=end,
        notes=notes,
        title=None,
    )


# ---------------------------------------------------------------------------
# compose_roster_sms_body
# ---------------------------------------------------------------------------


class TestComposeRosterSmsBody:
    """The composed body must include the staff first_name, shift
    count, and viewer URL so the SMS is actionable on its own.

    **Validates: Requirement R9.3**.
    """

    def test_body_contains_first_name_count_and_url(self):
        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(), org_id=org_id, first_name="Jane",
        )
        entries = [
            _make_entry(
                datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            ),
            _make_entry(
                datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 6, 10, 17, 0, tzinfo=timezone.utc),
            ),
        ]
        viewer_url = "https://app.example/public/staff-roster/abc123"

        body = compose_roster_sms_body(staff, entries, viewer_url)

        assert "Jane" in body
        # 2 shifts → "2 shifts" (plural)
        assert "2 shifts" in body
        assert viewer_url in body

    def test_singular_shift_word_when_one_shift(self):
        """One shift → "1 shift" (no plural)."""
        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(), org_id=org_id, first_name="Aroha",
        )
        entries = [
            _make_entry(
                datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            ),
        ]
        body = compose_roster_sms_body(
            staff, entries,
            "https://app.example/public/staff-roster/abc123",
        )
        assert "1 shift," in body
        assert "1 shifts" not in body

    def test_falls_back_to_name_when_first_name_missing(self):
        """When ``first_name`` is empty/whitespace, fall back to the
        full name field. Defensive against legacy rows where the
        ``first_name`` column was added later (server_default ='').
        """
        staff = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            phone="+64 21 555 1234",
            weekly_roster_sms_enabled=True,
            first_name="",
            last_name=None,
            name="Old Bob",
        )
        entries = [
            _make_entry(
                datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
                datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            ),
        ]
        body = compose_roster_sms_body(
            staff, entries, "https://x/y/z",
        )
        assert "Old Bob" in body


# ---------------------------------------------------------------------------
# _detect_encoding_and_segments
# ---------------------------------------------------------------------------


class TestDetectEncodingAndSegments:
    """Encoding detection must classify Māori-macron-containing bodies
    as UCS-2 (never transliterate) and pure-ASCII bodies as GSM-7,
    with correct multi-part segment counts (R9.3 / G7).

    **Validates: Requirement R9.3**.
    """

    def test_short_ascii_body_is_single_gsm7_segment(self):
        body = "A" * 100
        encoding, segments = _detect_encoding_and_segments(body)
        assert encoding == "gsm7"
        assert segments == 1

    def test_long_ascii_body_is_multi_part_gsm7(self):
        # 200 chars > 160 single-segment limit → multi-part
        # 200 / 153 = 1.30 → ceil → 2 segments
        body = "A" * 200
        encoding, segments = _detect_encoding_and_segments(body)
        assert encoding == "gsm7"
        assert segments == 2

    def test_macron_body_under_70_chars_is_single_ucs2_segment(self):
        # Body containing 'ā' (Māori macron) at 50 chars → ucs2, 1 segment
        body = "ā" * 50
        encoding, segments = _detect_encoding_and_segments(body)
        assert encoding == "ucs2"
        assert segments == 1

    def test_macron_body_over_70_chars_is_multi_part_ucs2(self):
        # 100 chars of 'ā' → ucs2, ceil(100/67) = 2 segments
        body = "ā" * 100
        encoding, segments = _detect_encoding_and_segments(body)
        assert encoding == "ucs2"
        assert segments == 2

    def test_single_macron_in_ascii_body_downgrades_to_ucs2(self):
        """Even one non-GSM-7 char downgrades the entire SMS.

        This is the core G7 case: a staff named "Tāmaki" in an
        otherwise-ASCII template body MUST send as UCS-2 rather than
        being silently transliterated to "Tamaki".
        """
        body = "Kia ora Tāmaki, your roster..."
        encoding, _ = _detect_encoding_and_segments(body)
        assert encoding == "ucs2"

    def test_gsm7_extended_chars_count_double_in_slot_budget(self):
        """Each character from the GSM-7 extension table (e.g. ``{``
        ``}`` ``[`` ``]`` ``\\`` ``|`` ``^`` ``~`` ``€``) consumes
        two 7-bit slots. A 100-char body of pure extended chars
        therefore takes 200 slots → multi-part GSM-7 (2 segments).
        """
        body = "{" * 100
        encoding, segments = _detect_encoding_and_segments(body)
        assert encoding == "gsm7"
        assert segments == 2


# ---------------------------------------------------------------------------
# _mask_phone_number
# ---------------------------------------------------------------------------


class TestMaskPhoneNumber:
    """Phone-number masking for the audit log row (R9.3 / P1-N12)."""

    def test_masks_to_last_four_digits(self):
        # 11 digits in "+64 21 555 1234" → 7 stars + "1234".
        assert _mask_phone_number("+64 21 555 1234") == "*******1234"

    def test_short_number_is_fully_masked(self):
        assert _mask_phone_number("123") == "***"

    def test_empty_returns_empty_string(self):
        assert _mask_phone_number("") == ""
        assert _mask_phone_number(None) == ""


# ---------------------------------------------------------------------------
# send_roster_sms — refusal paths
# ---------------------------------------------------------------------------


class TestSendRosterSmsRefusals:
    """Precondition refusals must surface the right ``reason`` without
    minting tokens or calling the SMS provider.

    **Validates: Requirement R9.2**.
    """

    @pytest.mark.asyncio
    async def test_no_phone_returns_no_phone_reason(self):
        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(), org_id=org_id, phone=None,
        )
        db = AsyncMock()

        with patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
        ) as mock_token, patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
        ) as mock_send_sms:
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://x/public/staff-roster",
            )

        assert result.ok is False
        assert result.reason == REASON_NO_PHONE
        assert result.message_id is None
        # Short-circuits before token mint or send.
        mock_token.assert_not_awaited()
        mock_send_sms.assert_not_awaited()
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blank_phone_returns_no_phone_reason(self):
        """Whitespace-only phone numbers are treated the same as None."""
        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(), org_id=org_id, phone="   ",
        )
        db = AsyncMock()

        result = await send_roster_sms(
            db,
            org_id=org_id,
            staff=staff,
            week_start=date(2026, 6, 8),
            viewer_base_url="https://x/public/staff-roster",
        )

        assert result.ok is False
        assert result.reason == REASON_NO_PHONE

    @pytest.mark.asyncio
    async def test_opt_out_returns_opt_out_reason(self):
        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            weekly_roster_sms_enabled=False,
        )
        db = AsyncMock()

        with patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
        ) as mock_token, patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
        ) as mock_send_sms:
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://x/public/staff-roster",
            )

        assert result.ok is False
        assert result.reason == REASON_OPT_OUT
        mock_token.assert_not_awaited()
        mock_send_sms.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_entries_returns_no_shifts_in_week_reason(self):
        org_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=uuid.uuid4(), org_id=org_id)
        db = AsyncMock()

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
        ) as mock_token, patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
        ) as mock_send_sms:
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://x/public/staff-roster",
            )

        assert result.ok is False
        assert result.reason == REASON_NO_SHIFTS_IN_WEEK
        # Token mint + SMS send skipped when there's nothing to send.
        mock_token.assert_not_awaited()
        mock_send_sms.assert_not_awaited()


# ---------------------------------------------------------------------------
# send_roster_sms — happy + send-failure paths
# ---------------------------------------------------------------------------


class TestSendRosterSmsHappyPath:
    """Happy path: mint token, compose body, dispatch, surface
    ``audit_extras``. Plus the chain-exhausted send case still
    captures the encoding/segments for the audit row.

    **Validates: Requirement R9** (R9.3, R9.4, R9.5, R9.6).
    """

    @pytest.mark.asyncio
    async def test_happy_path_calls_send_sms_with_dlq(self):
        from app.integrations.sms_sender import SmsSendResult

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=staff_id, org_id=org_id)
        db = AsyncMock()

        entry = _make_entry(
            datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            notes="Reception",
        )

        token_obj = SimpleNamespace(
            token="tok-abc-123",
            week_start=date(2026, 6, 8),
        )

        sms_result = SmsSendResult(
            ok=True,
            message_id="prov-msg-789",
            provider_key="connexus",
        )

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
            return_value=token_obj,
        ) as mock_token, patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
            return_value=sms_result,
        ) as mock_send_sms:
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://app.example/public/staff-roster",
            )

        assert result.ok is True
        assert result.message_id == "prov-msg-789"
        assert result.reason is None
        # ASCII first_name → GSM-7 single segment.
        assert result.audit_extras["encoding"] == "gsm7"
        assert result.audit_extras["segments"] == 1
        # Last 4 digits of "+64 21 555 1234" → "1234"
        assert result.audit_extras["phone_number_masked"].endswith("1234")
        assert result.audit_extras["phone_number_masked"].startswith("*")

        # Token mint by (staff, week).
        mock_token.assert_awaited_once()
        token_kwargs = mock_token.await_args.kwargs
        assert token_kwargs["org_id"] == org_id
        assert token_kwargs["staff_id"] == staff_id
        assert token_kwargs["week_start"] == date(2026, 6, 8)

        # send_sms wired with the right body + DLQ args.
        mock_send_sms.assert_awaited_once()
        send_kwargs = mock_send_sms.await_args.kwargs
        assert send_kwargs["to_phone"] == "+64 21 555 1234"
        assert "Jane" in send_kwargs["body"]
        assert (
            "https://app.example/public/staff-roster/tok-abc-123"
            in send_kwargs["body"]
        )
        assert send_kwargs["dlq_task_name"] == "roster_sms"
        assert send_kwargs["dlq_task_args"] == {
            "staff_id": str(staff_id),
            "week_start": "2026-06-08",
            "org_id": str(org_id),
        }
        assert send_kwargs["org_id"] == org_id

    @pytest.mark.asyncio
    async def test_macron_first_name_marks_audit_as_ucs2(self):
        """G7 case — staff named ``Aroha Tāmaki`` triggers UCS-2
        encoding because of the ``ā`` macron. The audit row must
        record ``encoding='ucs2'`` (and segments >= 1).
        """
        from app.integrations.sms_sender import SmsSendResult

        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            first_name="Aroha Tāmaki",
        )
        db = AsyncMock()

        entry = _make_entry(
            datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
        )
        token_obj = SimpleNamespace(token="tok-xyz", week_start=date(2026, 6, 8))

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
            return_value=token_obj,
        ), patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
            return_value=SmsSendResult(
                ok=True, message_id="m-1", provider_key="connexus",
            ),
        ):
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://app.example/public/staff-roster",
            )

        assert result.ok is True
        assert result.audit_extras["encoding"] == "ucs2"
        assert result.audit_extras["segments"] >= 1

    @pytest.mark.asyncio
    async def test_send_failure_returns_send_failed_with_audit_extras(self):
        """When ``send_sms`` returns ``ok=False`` (provider chain
        exhausted) the helper surfaces ``reason='send_failed'`` AND
        still populates ``audit_extras`` so the router can capture the
        encoding/segments of the attempted send in the audit row.
        """
        from app.integrations.sms_sender import SmsSendResult

        org_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=uuid.uuid4(), org_id=org_id)
        db = AsyncMock()

        entry = _make_entry(
            datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
        )
        token_obj = SimpleNamespace(token="t", week_start=date(2026, 6, 8))

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
            return_value=token_obj,
        ), patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
            return_value=SmsSendResult(
                ok=False,
                provider_key="connexus",
                reason="provider_error",
            ),
        ):
            result = await send_roster_sms(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
                viewer_base_url="https://x/public/staff-roster",
            )

        assert result.ok is False
        assert result.reason == REASON_SEND_FAILED
        assert result.message_id is None
        # Encoding/segments are still captured on the failed send.
        assert result.audit_extras["encoding"] == "gsm7"
        assert result.audit_extras["segments"] == 1
        assert "phone_number_masked" in result.audit_extras


# ---------------------------------------------------------------------------
# RosterDeliveryResult dataclass shape
# ---------------------------------------------------------------------------


class TestRosterDeliveryResultShape:
    """The C6 task extends ``RosterDeliveryResult`` with
    ``audit_extras``. Lock the shape so future refactors don't drop it.
    """

    def test_default_audit_extras_is_empty_dict(self):
        result = RosterDeliveryResult(ok=False, reason="no_phone")
        assert result.audit_extras == {}

    def test_audit_extras_can_be_set(self):
        result = RosterDeliveryResult(
            ok=True,
            message_id="m-1",
            audit_extras={"encoding": "gsm7", "segments": 1},
        )
        assert result.audit_extras["encoding"] == "gsm7"
        assert result.audit_extras["segments"] == 1
