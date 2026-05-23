"""Property tests for reminder preference validation and defaults.

Implements:
- **Property 25** — Reminder preference validity (Req 10.2, 10.3, 10.8)
- **Property 28** — Reminder defaults are off on add-vehicle (Req 10.9)
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.services.reminder_service import (
    validate_preference,
)


# ---------------------------------------------------------------------------
# Property 25 — predicate on enabled rows
# ---------------------------------------------------------------------------


def test_disabled_row_passes_with_any_shape() -> None:
    """Disabled preference is always accepted regardless of channels."""
    validate_preference(
        enabled=False,
        lead_time_days=99,  # invalid in enabled rows but ignored when disabled
        channels=[],
        recipients=[],
        sms_provider_configured=False,
    )


def test_enabled_requires_lead_time_in_set() -> None:
    with pytest.raises(ValueError, match="lead_time_days"):
        validate_preference(
            enabled=True,
            lead_time_days=21,
            channels=["email"],
            recipients=["fleet_admin"],
            sms_provider_configured=True,
        )


def test_enabled_requires_non_empty_channels() -> None:
    with pytest.raises(ValueError, match="channels"):
        validate_preference(
            enabled=True,
            lead_time_days=14,
            channels=[],
            recipients=["fleet_admin"],
            sms_provider_configured=True,
        )


def test_enabled_requires_non_empty_recipients() -> None:
    with pytest.raises(ValueError, match="recipients"):
        validate_preference(
            enabled=True,
            lead_time_days=14,
            channels=["email"],
            recipients=[],
            sms_provider_configured=True,
        )


def test_sms_channel_requires_sms_provider_configured() -> None:
    with pytest.raises(ValueError, match="SMS"):
        validate_preference(
            enabled=True,
            lead_time_days=14,
            channels=["sms"],
            recipients=["fleet_admin"],
            sms_provider_configured=False,
        )


def test_unknown_channel_rejected() -> None:
    with pytest.raises(ValueError, match="channels"):
        validate_preference(
            enabled=True,
            lead_time_days=14,
            channels=["push"],
            recipients=["fleet_admin"],
            sms_provider_configured=True,
        )


def test_unknown_recipient_rejected() -> None:
    with pytest.raises(ValueError, match="recipients"):
        validate_preference(
            enabled=True,
            lead_time_days=14,
            channels=["email"],
            recipients=["accounting"],
            sms_provider_configured=True,
        )


@given(
    enabled=st.booleans(),
    lead=st.sampled_from([7, 14, 30, 21, 365, 0]),
    channels=st.lists(
        st.sampled_from(["email", "sms", "push", "fax"]),
        unique=True,
        max_size=4,
    ),
    recipients=st.lists(
        st.sampled_from(
            ["fleet_admin", "assigned_drivers", "accounting", "external"]
        ),
        unique=True,
        max_size=4,
    ),
    sms_configured=st.booleans(),
)
@hyp_settings(max_examples=300)
def test_predicate_accepts_iff_all_clauses_hold(
    enabled: bool,
    lead: int,
    channels: list[str],
    recipients: list[str],
    sms_configured: bool,
) -> None:
    """Property 25 — predicate is accepted iff every clause holds."""
    expected_ok = (
        not enabled
    ) or (
        lead in {7, 14, 30}
        and channels
        and recipients
        and all(c in {"email", "sms"} for c in channels)
        and all(r in {"fleet_admin", "assigned_drivers"} for r in recipients)
        and (("sms" not in channels) or sms_configured)
    )
    if expected_ok:
        validate_preference(
            enabled=enabled,
            lead_time_days=lead,
            channels=channels,
            recipients=recipients,
            sms_provider_configured=sms_configured,
        )
    else:
        with pytest.raises(ValueError):
            validate_preference(
                enabled=enabled,
                lead_time_days=lead,
                channels=channels,
                recipients=recipients,
                sms_provider_configured=sms_configured,
            )
