"""Property-based tests for multi-tenant isolation on the envelope read / list
paths (task 9.5).

The read path lives in
:func:`app.modules.esignatures.service.list_envelopes` and
:func:`app.modules.esignatures.service.get_envelope_detail`, both of which load
through :func:`app.modules.esignatures.service._load_envelope_for_org`:

  * ``list_envelopes`` applies an explicit ``org_id`` predicate (in addition to
    the request session's RLS scoping) and so returns **only** the calling
    organisation's envelopes, wrapped in ``{ items, total }`` — never another
    organisation's rows, and an empty ``{items: [], total: 0}`` when the org
    owns none (R11.1, R13.3).
  * ``get_envelope_detail`` loads via ``_load_envelope_for_org``, whose query is
    ``WHERE id == envelope_id AND org_id == org_id``. A cross-org or missing
    envelope returns ``None`` from the load and the service raises a humanized
    **404** (``not_found``) that never confirms the envelope exists for another
    organisation (R13.4, R13.5). A same-org envelope is returned (R13.6).

This module drives both functions over the same lightweight fake async session
used by ``test_esign_dashboard_list_detail_properties`` (task 9.4). The fake
interprets the ORM ``select`` the service builds against an in-memory dataset,
applying the ``org_id`` WHERE filter for the list query and the
``id``/``org_id`` ownership predicate for the detail load — so org-scoping is
genuinely validated end-to-end across multiple organisations without a real DB.
The DB-backed RLS isolation smoke (org A cannot see org B's rows at the
PostgreSQL layer) is covered separately by ``tests/test_esign_migration_rls.py``
(task 1.4); this module focuses on the service-layer org-scoping that is the
Property 20 concern.

# Feature: esignature-integration, Property 20: Multi-tenant isolation on read and list

**Validates: Requirements 11.1, 13.3, 13.4, 13.5, 13.6**
"""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the sibling dashboard
# property test) so SQLAlchemy can resolve every string-based relationship
# reference when ``EsignEnvelope`` / ``EsignRecipient`` are instantiated.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.modules.esignatures.models import (  # noqa: E402
    EsignEnvelope,
    EsignRecipient,
)
from app.modules.esignatures.service import (  # noqa: E402
    get_envelope_detail,
    list_envelopes,
)

# The 8 valid envelope statuses pinned by the migration CHECK constraint.
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

_TS_POOL = [
    datetime.datetime(2026, 1, 1, 9, 0, 0),
    datetime.datetime(2026, 3, 15, 12, 30, 0),
    datetime.datetime(2026, 6, 28, 18, 45, 0),
]


# ---------------------------------------------------------------------------
# Fake async session — interprets the service's ORM ``select`` against an
# in-memory dataset of transient EsignEnvelope rows spanning multiple orgs.
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
    ORDER BY the service requested to the in-memory dataset — so the org_id
    predicate (list) and id/org_id ownership predicate (detail) are genuinely
    enforced exactly as the service constructed them.
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


# A list of per-org envelope-spec lists: 2..4 organisations, each owning 0..6
# envelopes (some orgs deliberately own zero, exercising the empty-list case).
@st.composite
def _multi_org_dataset(draw):
    n_orgs = draw(st.integers(min_value=2, max_value=4))
    return [
        draw(st.lists(_envelope_spec(), min_size=0, max_size=6))
        for _ in range(n_orgs)
    ]


# ---------------------------------------------------------------------------
# Property 20 — list_envelopes returns ONLY the calling org's envelopes.
# ---------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(per_org_specs=_multi_org_dataset())
def test_list_is_strictly_org_scoped(per_org_specs):
    # Build distinct orgs each owning its own (disjoint-id) envelopes.
    orgs = [uuid.uuid4() for _ in per_org_specs]
    envelopes_by_org = {
        org: [_build_envelope(org, s) for s in specs]
        for org, specs in zip(orgs, per_org_specs)
    }
    dataset = [e for envs in envelopes_by_org.values() for e in envs]

    for org in orgs:
        session = _FakeSession(dataset)
        resp, err = asyncio.run(list_envelopes(session, org_id=org, status=None))
        assert err is None

        own = envelopes_by_org[org]
        own_ids = {e.id for e in own}
        returned_ids = {item.id for item in resp.items}

        # Exactly this org's envelopes, no more, no less (R11.1, R13.3).
        assert returned_ids == own_ids
        assert resp.total == len(own)

        # No envelope owned by ANY other org leaks in (R13.3).
        foreign_ids = {
            e.id
            for other, envs in envelopes_by_org.items()
            if other != org
            for e in envs
        }
        assert foreign_ids.isdisjoint(returned_ids)

        # An org owning zero envelopes gets a genuinely empty {items, total}.
        if not own:
            assert resp.items == []
            assert resp.total == 0


@settings(max_examples=100, deadline=None)
@given(specs=st.lists(_envelope_spec(), min_size=1, max_size=6))
def test_list_empty_for_org_with_no_envelopes(specs):
    """An org that owns no envelopes always gets an empty list, even when other
    orgs in the same dataset own many (R11.1, R13.3)."""
    owning_org = uuid.uuid4()
    empty_org = uuid.uuid4()
    dataset = [_build_envelope(owning_org, s) for s in specs]

    session = _FakeSession(dataset)
    resp, err = asyncio.run(
        list_envelopes(session, org_id=empty_org, status=None)
    )
    assert err is None
    assert resp.items == []
    assert resp.total == 0


# ---------------------------------------------------------------------------
# Property 20 — get_envelope_detail: own → returned; cross-org/missing → 404.
# ---------------------------------------------------------------------------


@settings(max_examples=150, deadline=None)
@given(per_org_specs=_multi_org_dataset(), data=st.data())
def test_detail_cross_org_is_404_and_own_is_returned(per_org_specs, data):
    orgs = [uuid.uuid4() for _ in per_org_specs]
    envelopes_by_org = {
        org: [_build_envelope(org, s) for s in specs]
        for org, specs in zip(orgs, per_org_specs)
    }
    dataset = [e for envs in envelopes_by_org.values() for e in envs]

    # Pick an org that actually owns at least one envelope as the "owner".
    owners = [org for org in orgs if envelopes_by_org[org]]
    if not owners:
        # Degenerate dataset (every org owns zero) — still assert a missing id
        # under any org is a 404.
        session = _FakeSession(dataset)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                get_envelope_detail(
                    session, org_id=orgs[0], envelope_id=uuid.uuid4()
                )
            )
        assert exc.value.status_code == 404
        return

    owner = data.draw(st.sampled_from(owners))
    target = data.draw(st.sampled_from(envelopes_by_org[owner]))

    # Same-org read returns the envelope (R13.6).
    session = _FakeSession(dataset)
    out = asyncio.run(
        get_envelope_detail(session, org_id=owner, envelope_id=target.id)
    )
    assert out.id == target.id
    assert out.status == target.status

    # Cross-org read of that same envelope → 404 for EVERY other org (R13.5).
    for other in orgs:
        if other == owner:
            continue
        session_x = _FakeSession(dataset)
        with pytest.raises(HTTPException) as cross_exc:
            asyncio.run(
                get_envelope_detail(
                    session_x, org_id=other, envelope_id=target.id
                )
            )
        assert cross_exc.value.status_code == 404

    # A completely unknown id under the owner org → 404 (never confirms
    # existence elsewhere, R13.5).
    session_m = _FakeSession(dataset)
    with pytest.raises(HTTPException) as missing_exc:
        asyncio.run(
            get_envelope_detail(
                session_m, org_id=owner, envelope_id=uuid.uuid4()
            )
        )
    assert missing_exc.value.status_code == 404
