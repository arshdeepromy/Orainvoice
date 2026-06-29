"""Property-based tests for the Agreements dashboard list / filter / ordering and
the envelope-detail signed-document link (task 9.4).

The dashboard read path lives in
:func:`app.modules.esignatures.service.list_envelopes` and
:func:`app.modules.esignatures.service.get_envelope_detail`:

  * ``list_envelopes`` returns the calling organisation's envelopes wrapped in
    ``{ items, total }``, ordered ``updated_at DESC`` (``id DESC`` tie-break),
    optionally filtered by a valid ``?status=``. An **unapplyable** filter (a
    value outside the 8 valid envelope statuses) is **fail-closed**: it returns
    no envelopes plus a humanized ``filter_unavailable`` error and never issues
    a DB query (so it can never accidentally return an unfiltered list).
  * ``get_envelope_detail`` returns per-recipient status and a
    ``signed_document_url`` **iff** a signed document has actually been stored
    (``signed_doc_status == 'stored'`` AND a ``signed_doc_file_key`` is set);
    a missing or cross-org envelope yields a 404 that never confirms existence.

This module drives both functions over a lightweight fake async session (the
same fake-session pattern used by ``test_esign_credential_storage_properties``
and ``test_documenso_connection_loader``). The fake interprets the ORM
``select`` the service builds — applying the ``org_id`` scope, the optional
``status`` filter, and the ``updated_at DESC, id DESC`` ordering against an
in-memory set of transient :class:`EsignEnvelope` objects — so filtering,
ordering and the fail-closed branch are validated end-to-end without a real DB.
The fail-closed branch is additionally proven by asserting the fake's
``execute`` was **never** called for an unapplyable filter.

# Feature: esignature-integration, Property 21: Dashboard filter, ordering, and detail are correct and fail-closed

**Validates: Requirements 11.2, 11.3, 11.4, 11.5, 11.6**
"""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the credential-storage
# property test) so SQLAlchemy can resolve every string-based relationship
# reference when ``EsignEnvelope`` / ``EsignRecipient`` are instantiated.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures.errors import CODE_FILTER_UNAVAILABLE  # noqa: E402
from app.modules.esignatures.models import (  # noqa: E402
    EsignEnvelope,
    EsignRecipient,
)
from app.modules.esignatures.service import (  # noqa: E402
    get_envelope_detail,
    list_envelopes,
)

# The 8 valid envelope statuses pinned by the migration CHECK constraint and the
# status reducer (the same set the service treats as *applyable* filters).
_VALID_STATUSES = [
    "draft",
    "sent",
    "viewed",
    "partially_signed",
    "completed",
    "declined",
    "voided",
    "error",
]
_AGREEMENT_TYPES = [
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
]
_ENTITY_TYPES = ["invoice", "quote", "staff"]
_SIGNED_DOC_STATUSES = ["none", "pending_retrieval", "stored"]
_RECIPIENT_ROLES = ["SIGNER", "VIEWER"]
_RECIPIENT_STATUSES = ["pending", "viewed", "signed", "declined"]

# A small pool of timestamps so generated envelopes frequently share an
# ``updated_at`` — exercising the ``id DESC`` tie-break in the ordering.
_TS_POOL = [
    datetime.datetime(2026, 1, 1, 9, 0, 0),
    datetime.datetime(2026, 1, 1, 9, 0, 0),  # duplicate -> forces ties
    datetime.datetime(2026, 3, 15, 12, 30, 0),
    datetime.datetime(2026, 6, 28, 18, 45, 0),
]


# ---------------------------------------------------------------------------
# Fake async session — interprets the service's ORM ``select`` against an
# in-memory dataset of transient EsignEnvelope rows.
# ---------------------------------------------------------------------------


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows=None, single=None):
        self._rows = rows or []
        self._single = single

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        return self._single


class _FakeSession:
    """Minimal AsyncSession stand-in driving list/detail reads from memory.

    ``execute`` compiles the statement the service built, extracts the bound
    ``org_id`` / ``status`` / ``id`` parameters, and applies the same WHERE +
    ORDER BY the service requested to the in-memory dataset — so ordering and
    filtering are genuinely validated. ``execute_count`` lets the fail-closed
    test assert the DB was never queried for an unapplyable filter.
    """

    def __init__(self, dataset):
        self._dataset = list(dataset)
        self.execute_count = 0
        self.last_sql: str | None = None

    async def execute(self, stmt, params=None):
        self.execute_count += 1
        compiled = stmt.compile()
        sql = str(compiled).lower()
        self.last_sql = sql
        cparams = compiled.params
        org_id = cparams.get("org_id_1")

        # Detail / ownership load: WHERE id = :id_1 AND org_id = :org_id_1
        if "esign_envelopes.id =" in sql:
            env_id = cparams.get("id_1")
            match = next(
                (
                    e
                    for e in self._dataset
                    if e.id == env_id and e.org_id == org_id
                ),
                None,
            )
            return _FakeResult(single=match)

        # List query: WHERE org_id [AND status] ORDER BY updated_at DESC, id DESC
        rows = [e for e in self._dataset if e.org_id == org_id]
        if "esign_envelopes.status =" in sql:
            status_val = cparams.get("status_1")
            rows = [e for e in rows if e.status == status_val]
        rows = sorted(rows, key=lambda e: (e.updated_at, e.id), reverse=True)
        return _FakeResult(rows=rows)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


@st.composite
def _envelope_spec(draw):
    """A plain spec dict for one envelope (ORM objects are built per example)."""
    signed_doc_status = draw(st.sampled_from(_SIGNED_DOC_STATUSES))
    # A file key is present sometimes regardless of status, so the "iff"
    # (status == stored AND key set) is genuinely exercised in every combination.
    has_key = draw(st.booleans())
    return {
        "id": uuid.uuid4(),
        "agreement_type": draw(st.sampled_from(_AGREEMENT_TYPES)),
        "originating_entity_type": draw(st.sampled_from(_ENTITY_TYPES)),
        "originating_entity_id": uuid.uuid4(),
        "status": draw(st.sampled_from(_VALID_STATUSES)),
        "signed_doc_status": signed_doc_status,
        "signed_doc_file_key": (f"esign/{uuid.uuid4().hex}.pdf" if has_key else None),
        "updated_at": draw(st.sampled_from(_TS_POOL)),
        "created_at": draw(st.sampled_from(_TS_POOL)),
        "recipients": draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        "role": st.sampled_from(_RECIPIENT_ROLES),
                        "recipient_status": st.sampled_from(_RECIPIENT_STATUSES),
                    }
                ),
                min_size=1,
                max_size=3,
            )
        ),
    }


def _build_envelope(org_id: uuid.UUID, spec: dict) -> EsignEnvelope:
    recipients = [
        EsignRecipient(
            id=uuid.uuid4(),
            name=f"Recipient {i}",
            email=f"recipient{i}@example.test",
            signing_role=r["role"],
            recipient_status=r["recipient_status"],
        )
        for i, r in enumerate(spec["recipients"])
    ]
    return EsignEnvelope(
        id=spec["id"],
        org_id=org_id,
        agreement_type=spec["agreement_type"],
        originating_entity_type=spec["originating_entity_type"],
        originating_entity_id=spec["originating_entity_id"],
        documenso_document_id=f"doc-{spec['id'].hex[:8]}",
        status=spec["status"],
        signed_doc_status=spec["signed_doc_status"],
        signed_doc_file_key=spec["signed_doc_file_key"],
        created_at=spec["created_at"],
        updated_at=spec["updated_at"],
        recipients=recipients,
    )


def _expected_url(env: EsignEnvelope) -> str | None:
    if env.signed_doc_status == "stored" and env.signed_doc_file_key:
        return f"/api/v2/esign/envelopes/{env.id}/signed-document"
    return None


# Unapplyable filter strings: any non-blank text that is not one of the 8 valid
# statuses (blank/None means "no filter", a different, valid path).
_invalid_status_strategy = st.text(min_size=1, max_size=24).filter(
    lambda s: s.strip() != "" and s.strip() not in _VALID_STATUSES
)


# ---------------------------------------------------------------------------
# Property 21 — list: org-scope, valid-status filter, ordering, fail-closed.
# ---------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(
    org_specs=st.lists(_envelope_spec(), min_size=0, max_size=10),
    other_specs=st.lists(_envelope_spec(), min_size=0, max_size=5),
    invalid_status=_invalid_status_strategy,
    data=st.data(),
)
def test_list_filter_ordering_and_fail_closed(
    org_specs, other_specs, invalid_status, data
):
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()

    org_envelopes = [_build_envelope(org_id, s) for s in org_specs]
    other_envelopes = [_build_envelope(other_org_id, s) for s in other_specs]
    dataset = org_envelopes + other_envelopes

    # --- No filter: all of THIS org's envelopes, newest-updated first -----
    session = _FakeSession(dataset)
    resp, err = asyncio.run(list_envelopes(session, org_id=org_id, status=None))

    assert err is None
    assert resp.total == len(org_envelopes)
    assert len(resp.items) == len(org_envelopes)

    returned_ids = [item.id for item in resp.items]
    # Org isolation (R11.1): no foreign-org envelope leaks into the list.
    other_ids = {e.id for e in other_envelopes}
    assert other_ids.isdisjoint(set(returned_ids))
    # Exactly this org's envelopes are present.
    assert set(returned_ids) == {e.id for e in org_envelopes}

    # Ordering (R11.4): updated_at DESC, id DESC tie-break.
    expected_order = [
        e.id
        for e in sorted(
            org_envelopes, key=lambda e: (e.updated_at, e.id), reverse=True
        )
    ]
    assert returned_ids == expected_order
    # The service genuinely requested that ordering in SQL.
    assert "order by" in session.last_sql
    assert "updated_at desc" in session.last_sql
    assert "id desc" in session.last_sql

    # Each row exposes the required dashboard fields (R11.2).
    by_id = {e.id: e for e in org_envelopes}
    for item in resp.items:
        src = by_id[item.id]
        assert item.agreement_type == src.agreement_type
        assert item.status == src.status
        assert item.originating_entity_type == src.originating_entity_type
        assert item.originating_entity_id == src.originating_entity_id
        assert len(item.recipients) == len(src.recipients)
        assert item.signed_document_url == _expected_url(src)

    # --- Valid-status filter: only matching envelopes (R11.3) -------------
    chosen_status = data.draw(st.sampled_from(_VALID_STATUSES))
    session_f = _FakeSession(dataset)
    resp_f, err_f = asyncio.run(
        list_envelopes(session_f, org_id=org_id, status=chosen_status)
    )
    assert err_f is None
    expected_matches = [e for e in org_envelopes if e.status == chosen_status]
    assert resp_f.total == len(expected_matches)
    assert all(item.status == chosen_status for item in resp_f.items)
    assert {item.id for item in resp_f.items} == {e.id for e in expected_matches}
    # Filtered list is still ordered updated_at DESC, id DESC.
    expected_filtered_order = [
        e.id
        for e in sorted(
            expected_matches, key=lambda e: (e.updated_at, e.id), reverse=True
        )
    ]
    assert [item.id for item in resp_f.items] == expected_filtered_order

    # --- Unapplyable filter: fail-closed (R11.6) --------------------------
    session_x = _FakeSession(dataset)
    resp_x, err_x = asyncio.run(
        list_envelopes(session_x, org_id=org_id, status=invalid_status)
    )
    # No envelopes (never an unfiltered list) + a humanized error.
    assert resp_x.items == []
    assert resp_x.total == 0
    assert err_x is not None
    assert err_x.code == CODE_FILTER_UNAVAILABLE
    assert isinstance(err_x.message, str) and err_x.message.strip() != ""
    # Fail-closed proof: the DB was never queried for an unapplyable filter.
    assert session_x.execute_count == 0


# ---------------------------------------------------------------------------
# Property 21 — detail: per-recipient status + signed-document link iff stored.
# ---------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(specs=st.lists(_envelope_spec(), min_size=1, max_size=8), data=st.data())
def test_detail_signed_url_present_iff_stored(specs, data):
    org_id = uuid.uuid4()
    envelopes = [_build_envelope(org_id, s) for s in specs]
    dataset = list(envelopes)
    session = _FakeSession(dataset)

    target = data.draw(st.sampled_from(envelopes))
    out = asyncio.run(
        get_envelope_detail(session, org_id=org_id, envelope_id=target.id)
    )

    # signed_document_url present IFF a signed doc is genuinely stored (R11.5).
    assert out.signed_document_url == _expected_url(target)
    if target.signed_doc_status == "stored" and target.signed_doc_file_key:
        assert out.signed_document_url is not None
    else:
        assert out.signed_document_url is None

    # Per-recipient signing status is exposed (R11.5).
    assert len(out.recipients) == len(target.recipients)
    assert [r.recipient_status for r in out.recipients] == [
        r.recipient_status for r in target.recipients
    ]


# ---------------------------------------------------------------------------
# Property 21 — detail: missing / cross-org reads are 404 (never leak).
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(specs=st.lists(_envelope_spec(), min_size=1, max_size=6), data=st.data())
def test_detail_missing_or_cross_org_is_404(specs, data):
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    envelopes = [_build_envelope(org_id, s) for s in specs]
    dataset = list(envelopes)
    session = _FakeSession(dataset)

    # A completely unknown id within the org → 404.
    with pytest.raises(HTTPException) as missing_exc:
        asyncio.run(
            get_envelope_detail(session, org_id=org_id, envelope_id=uuid.uuid4())
        )
    assert missing_exc.value.status_code == 404

    # A real envelope requested under a DIFFERENT org → 404 (cross-org, R13.5).
    target = data.draw(st.sampled_from(envelopes))
    with pytest.raises(HTTPException) as cross_exc:
        asyncio.run(
            get_envelope_detail(
                session, org_id=other_org_id, envelope_id=target.id
            )
        )
    assert cross_exc.value.status_code == 404
