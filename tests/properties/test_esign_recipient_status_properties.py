"""Property-based test for per-recipient signing-status updates (task 12.6).

# Feature: esignature-integration, Property 11: Per-recipient status reflects the latest recipient event

When Documenso reports a status change for an individual recipient, the
persisted per-recipient signing status is updated to reflect it (R4.5).

Two pure, in-memory helpers in :mod:`app.modules.esignatures.service` own this
behaviour:

  * :func:`_recipient_status_from_payload` maps a Documenso webhook recipient
    entry's ``signingStatus`` / ``readStatus`` to the persisted per-recipient
    status:

        signingStatus SIGNED / COMPLETED   -> "signed"
        signingStatus REJECTED / DECLINED  -> "declined"
        readStatus OPENED (else)           -> "viewed"
        otherwise                          -> "pending"

  * :func:`_apply_recipient_updates` matches each payload recipient to a
    persisted :class:`EsignRecipient` row by ``documenso_recipient_id`` first,
    then by case-insensitive email, writes the mapped status onto the matched
    row (bumping ``updated_at`` only when the status actually changes), leaves
    unmatched rows untouched, and returns the ``RecipientState`` list the status
    reducer consumes (``signed`` iff the payload recipient mapped to "signed").

These helpers are pure and operate on ORM objects held in memory, so no DB is
required — the property is exercised directly over many generated recipient
sets and payloads.

**Validates: Requirements 4.5**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignEnvelope / EsignRecipient are instantiated
# (mirrors the other esign property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures.models import EsignEnvelope, EsignRecipient  # noqa: E402
from app.modules.esignatures.service import (  # noqa: E402
    _apply_recipient_updates,
    _recipient_status_from_payload,
)

# ---------------------------------------------------------------------------
# Fixed timestamps so we can detect whether ``updated_at`` was bumped.
# ---------------------------------------------------------------------------
OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)
NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

PERSISTED_STATUSES = ("pending", "viewed", "signed", "declined")

# Documenso ``signingStatus`` values that drive the mapping, plus some noise.
SIGNING_VALUES = (
    "",
    "NOT_SIGNED",
    "SIGNED",
    "COMPLETED",
    "REJECTED",
    "DECLINED",
    "BOGUS",
    # lowercase to prove the helper upper-cases before comparing
    "signed",
    "rejected",
)
READ_VALUES = ("", "NOT_OPENED", "OPENED", "opened", "WAT")


def _expected_mapped_status(signing: str, read: str) -> str:
    """Reference implementation of the spec mapping (R4.5)."""
    s = str(signing or "").upper()
    r = str(read or "").upper()
    if s in {"SIGNED", "COMPLETED"}:
        return "signed"
    if s in {"REJECTED", "DECLINED"}:
        return "declined"
    if r in {"OPENED"}:
        return "viewed"
    return "pending"


# ===========================================================================
# Part A — the pure mapping helper covers every signing/read combination.
# ===========================================================================


@settings(max_examples=300, deadline=None)
@given(
    signing=st.sampled_from(SIGNING_VALUES),
    read=st.sampled_from(READ_VALUES),
    use_status_key=st.booleans(),
)
def test_recipient_status_from_payload_mapping(
    signing: str, read: str, use_status_key: bool
) -> None:
    """``_recipient_status_from_payload`` maps every signingStatus/readStatus
    combination to the persisted status the spec prescribes, whether the
    signing value arrives under ``signingStatus`` or the ``status`` fallback."""
    rec: dict[str, object] = {"readStatus": read}
    # The helper reads ``signingStatus`` first, falling back to ``status``.
    if use_status_key:
        rec["status"] = signing
    else:
        rec["signingStatus"] = signing

    assert _recipient_status_from_payload(rec) == _expected_mapped_status(
        signing, read
    )


# ===========================================================================
# Part B — applying a webhook payload updates exactly the matched recipients.
# ===========================================================================

# Per-recipient spec (email + documenso_recipient_id are assigned by index in
# the test to guarantee uniqueness).
recipient_spec_st = st.fixed_dictionaries(
    {
        "initial_status": st.sampled_from(PERSISTED_STATUSES),
        "has_doc_id": st.booleans(),
        "in_payload": st.booleans(),
        "match_by": st.sampled_from(("id", "email")),
        "signing": st.sampled_from(SIGNING_VALUES),
        "read": st.sampled_from(READ_VALUES),
        "upper_email": st.booleans(),
    }
)


def _make_recipient(idx: int, spec: dict) -> EsignRecipient:
    return EsignRecipient(
        id=uuid.uuid4(),
        envelope_id=uuid.uuid4(),
        name=f"Recipient {idx}",
        email=f"user{idx}@example.com",
        signing_role="SIGNER",
        recipient_status=spec["initial_status"],
        documenso_recipient_id=(f"rid-{idx}" if spec["has_doc_id"] else None),
        signing_url=None,
        created_at=OLD,
        updated_at=OLD,
    )


@settings(max_examples=200, deadline=None)
@given(specs=st.lists(recipient_spec_st, min_size=1, max_size=6))
def test_apply_recipient_updates_reflects_latest_event(specs: list[dict]) -> None:
    """For any envelope + webhook recipients payload:

    * each matched recipient's persisted ``recipient_status`` becomes the
      status mapped from its payload entry (matched by documenso_recipient_id,
      else by case-insensitive email);
    * ``updated_at`` is bumped to ``now`` exactly when the status changed;
    * recipients not referenced in the payload are left untouched;
    * the returned ``RecipientState`` list has ``signed`` True exactly for the
      payload recipients whose mapped status is ``signed``;
    * email matching works even when the row has no documenso_recipient_id.
    """
    # ``match_by == 'id'`` requires the row to actually carry a documenso id.
    for spec in specs:
        if spec["in_payload"] and spec["match_by"] == "id":
            spec["has_doc_id"] = True

    recipients = [_make_recipient(i, spec) for i, spec in enumerate(specs)]

    envelope = EsignEnvelope(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        agreement_type="nda",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id="doc-1",
        status="sent",
    )
    envelope.recipients = recipients

    # Build the payload (and remember, per matched recipient, the status we
    # expect it to take). ``payload_entries`` preserves build order so we can
    # check the returned RecipientState list element-by-element.
    payload: list[dict[str, object]] = []
    payload_entries: list[dict] = []  # {"idx", "mapped"}

    for i, spec in enumerate(specs):
        if not spec["in_payload"]:
            continue
        mapped = _expected_mapped_status(spec["signing"], spec["read"])
        entry: dict[str, object] = {
            "signingStatus": spec["signing"],
            "readStatus": spec["read"],
        }
        if spec["match_by"] == "id":
            entry["id"] = f"rid-{i}"
        else:
            # Match by email only (no id present) — exercises the email path,
            # including when the row itself has no documenso_recipient_id.
            email = f"user{i}@example.com"
            entry["email"] = email.upper() if spec["upper_email"] else email
        payload.append(entry)
        payload_entries.append({"idx": i, "mapped": mapped})

    now = NOW
    states = _apply_recipient_updates(envelope, payload, now=now)

    # --- Returned RecipientState list: one entry per payload recipient, in
    #     order, signed iff its mapped status is "signed". ------------------
    assert len(states) == len(payload_entries)
    for state, pe in zip(states, payload_entries):
        assert state.signed is (pe["mapped"] == "signed")

    # --- Per-recipient persisted status + updated_at bump semantics. -------
    matched_by_idx = {pe["idx"]: pe["mapped"] for pe in payload_entries}
    for i, (spec, rec) in enumerate(zip(specs, recipients)):
        if i in matched_by_idx:
            expected = matched_by_idx[i]
            assert rec.recipient_status == expected, (
                f"recipient {i}: expected {expected!r}, got "
                f"{rec.recipient_status!r}"
            )
            if expected != spec["initial_status"]:
                assert rec.updated_at == now, (
                    f"recipient {i}: status changed but updated_at not bumped"
                )
            else:
                assert rec.updated_at == OLD, (
                    f"recipient {i}: status unchanged but updated_at bumped"
                )
        else:
            # Not referenced in the payload — must be untouched.
            assert rec.recipient_status == spec["initial_status"]
            assert rec.updated_at == OLD


@settings(max_examples=100, deadline=None)
@given(
    signing=st.sampled_from(SIGNING_VALUES),
    read=st.sampled_from(READ_VALUES),
)
def test_apply_recipient_updates_matches_by_email_without_doc_id(
    signing: str, read: str
) -> None:
    """A row with no ``documenso_recipient_id`` is still updated when the
    payload references it by email (case-insensitively)."""
    rec = EsignRecipient(
        id=uuid.uuid4(),
        envelope_id=uuid.uuid4(),
        name="No Id",
        email="Person@Example.com",
        signing_role="SIGNER",
        recipient_status="pending",
        documenso_recipient_id=None,
        signing_url=None,
        created_at=OLD,
        updated_at=OLD,
    )
    envelope = EsignEnvelope(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        agreement_type="nda",
        originating_entity_type="staff",
        originating_entity_id=uuid.uuid4(),
        documenso_document_id="doc-1",
        status="sent",
    )
    envelope.recipients = [rec]

    expected = _expected_mapped_status(signing, read)
    states = _apply_recipient_updates(
        envelope,
        [{"email": "PERSON@example.COM", "signingStatus": signing, "readStatus": read}],
        now=NOW,
    )

    assert len(states) == 1
    assert states[0].signed is (expected == "signed")
    assert rec.recipient_status == expected
    if expected != "pending":
        assert rec.updated_at == NOW
    else:
        assert rec.updated_at == OLD
