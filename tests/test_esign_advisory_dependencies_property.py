"""Property-based test: advisory dependencies present every field and degrade
require-effects to optional (task 17.7).

# Feature: esignature-field-placement, Property 21: Advisory dependencies present every field and degrade require-effects to optional

**Validates: Requirements 14.4, 14.6, 14.8**

This test exercises the **advisory-dependency** behaviour of the Field_Set send
path,
:func:`app.modules.esignatures.service.create_and_send_envelope` — which now
re-validates the submitted ``dependencies[]`` with
:func:`app.modules.esignatures.dependency_graph.validate_dependencies` and
builds the Documenso field specs with ``force_optional_client_ids`` derived from
:func:`app.modules.esignatures.service._require_effect_dependents`. Documenso has
no cross-field conditional primitive, so dependencies are **advisory** only.

For every generated scenario the property holds:

* **Valid (acyclic) dependency set (R14.6, R14.8).** The Documenso calls occur
  ``create_document`` → ``create_fields`` → ``send_document``; the created field
  set contains **every** placed field (none is suppressed or hidden by a
  dependency), and **every** field that is the dependent of a ``require``-effect
  advisory dependency is created with ``required = False`` in its ``fieldMeta``,
  while every other field keeps its own required flag.
* **Invalid (cycle / self-loop) dependency set (R14.4).** The send is rejected
  with an ``HTTPException`` **422** carrying ``dependency_cycle`` /
  ``dependency_self`` **before any Documenso call** — the spy client records no
  calls at all.

The flow is driven in-memory with ``asyncio.run`` (mirroring
``test_esign_field_set_faithful_creation_property``): the per-org connection
gate is satisfied with a stub verified connection, a recording spy
``DocumensoClient`` is injected via ``client=`` to capture the created field
specs and the call order, and the best-effort audit/notify side-effect is
stubbed so the assertions are isolated from those writes.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignEnvelope / EsignRecipient are instantiated (mirrors the other esign
# unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    CreatedRecipient,
    DocumensoConnection,
    DocumensoCreateResult,
    DocumensoFieldSpec,
)
from app.modules.esignatures import service as esign_service  # noqa: E402
from app.modules.esignatures.schemas import (  # noqa: E402
    DependencyIn,
    EnvelopeCreate,
    FieldIn,
    RecipientIn,
)

# Hypothesis settings — >= 100 examples per the task; deadline disabled because
# each example drives an asyncio event loop through the full send flow.
PBT_SETTINGS = settings(max_examples=150, deadline=None)

# Distinct base for the spy's Documenso recipient ids (positional).
_RCPT_ID_BASE = 1000

_AGREEMENT_TYPES = (
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
)
_ENTITY_TYPES = ("invoice", "quote", "staff")
_FIELD_TYPES = ("signature", "initials", "name", "date", "email", "text")
_CONDITIONS = (
    "is_checked",
    "is_not_checked",
    "equals",
    "not_equals",
    "is_filled",
    "is_empty",
)

# A minimal but valid PDF byte string (starts with the %PDF magic bytes).
_VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF"


# ---------------------------------------------------------------------------
# Recording spy DocumensoClient — records call ORDER and the Field_Set payload
# ---------------------------------------------------------------------------


class _SpyClient:
    """A DocumensoClient stand-in that captures call order + created field specs.

    ``create_document`` echoes one :class:`CreatedRecipient` per input recipient
    (matched by email, ``recipient_id`` = ``_RCPT_ID_BASE + position``).
    ``create_fields`` captures the exact :class:`DocumensoFieldSpec` list it is
    handed. Every method appends its label to :attr:`calls` so call order — and,
    crucially, the *absence* of any call on the rejection path — is asserted.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, document_id: str = "doc-123") -> None:
        self.document_id = document_id
        self.calls: list[str] = []
        self.created_fields: list[DocumensoFieldSpec] | None = None

    async def create_document(self, *, title, recipients, pdf_bytes, **_kwargs):  # noqa: ANN001
        self.calls.append("create_document")
        created = [
            CreatedRecipient(
                recipient_id=str(_RCPT_ID_BASE + i),
                email=str(spec.email),
                role=(spec.role or "signer").upper(),
                token=f"tok{i}",
                signing_url=f"https://sign.example.test/{i}",
            )
            for i, spec in enumerate(recipients)
        ]
        return DocumensoCreateResult(
            document_id=self.document_id,
            envelope_id=f"envelope_{self.document_id}",
            recipients=created,
        )

    async def create_fields(self, document_id, fields):  # noqa: ANN001
        self.calls.append("create_fields")
        self.created_fields = list(fields)

    async def place_signature_field(self, document_id, **_kwargs):  # noqa: ANN001
        self.calls.append("place_signature_field")

    async def send_document(self, document_id, **_kwargs):  # noqa: ANN001
        self.calls.append("send_document")


# ---------------------------------------------------------------------------
# Fake async session — add / flush / refresh are the only success-path hooks.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


@st.composite
def _in_bounds_field(draw, *, recipient_index: int, force_type: str | None = None):
    """A single in-bounds FieldIn assigned to ``recipient_index`` (no client_id yet).

    Coordinates satisfy ``x+w <= 100`` and ``y+h <= 100`` with ``w,h > 0`` so the
    field is always valid for both Pydantic and ``validate_field_set``.
    """
    ftype = force_type or draw(st.sampled_from(_FIELD_TYPES))
    page = draw(st.integers(min_value=1, max_value=5))
    x = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    w = draw(st.floats(min_value=1, max_value=100 - x, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(min_value=0, max_value=95, allow_nan=False, allow_infinity=False))
    h = draw(st.floats(min_value=1, max_value=100 - y, allow_nan=False, allow_infinity=False))
    required = draw(st.booleans())
    label = None
    placeholder = None
    if ftype == "text":
        label = draw(st.one_of(st.none(), st.text(min_size=1, max_size=12)))
        placeholder = draw(st.one_of(st.none(), st.text(min_size=1, max_size=12)))
    return FieldIn(
        type=ftype,
        page=page,
        recipient_index=recipient_index,
        position_x=x,
        position_y=y,
        width=w,
        height=h,
        required=required,
        label=label,
        placeholder=placeholder,
    )


@st.composite
def _scenario(draw):
    """Build a valid Field_Set plus either a valid (acyclic) or invalid
    (cycle/self-loop) advisory dependency set.

    Returns ``(payload, is_valid)``. Each field carries a stable ``client_id``
    (``f0``, ``f1``, …) so dependencies can reference it. The dependency set is
    constructed deterministically acyclic (edges always run from a higher-index
    field to a lower-index field, so the ``dependent -> trigger`` graph is a DAG)
    or, on the invalid branch, with a self-loop or a 2-cycle.
    """
    n = draw(st.integers(min_value=1, max_value=4))
    roles = draw(st.lists(st.sampled_from(["signer", "viewer"]), min_size=n, max_size=n))
    # Guarantee >=1 signer (a zero-signer send is a different validation error).
    if "signer" not in roles:
        roles[0] = "signer"
    recipients = [
        RecipientIn(name=f"R{i}", email=f"r{i}@example.com", signing_role=roles[i])
        for i in range(n)
    ]
    signer_indices = [i for i, r in enumerate(recipients) if r.signing_role == "signer"]

    raw_fields: list[FieldIn] = []
    # Every signer carries >=1 signature field (keeps the Field_Set valid).
    for idx in signer_indices:
        raw_fields.append(draw(_in_bounds_field(recipient_index=idx, force_type="signature")))
    # Extra arbitrary (valid) fields assigned to any recipient.
    n_extra = draw(st.integers(min_value=0, max_value=5))
    for _ in range(n_extra):
        ri = draw(st.integers(min_value=0, max_value=n - 1))
        raw_fields.append(draw(_in_bounds_field(recipient_index=ri)))

    # Assign a stable client_id to every field (f0, f1, …).
    fields = [f.model_copy(update={"client_id": f"f{i}"}) for i, f in enumerate(raw_fields)]
    n_fields = len(fields)

    is_valid = draw(st.booleans())
    deps: list[DependencyIn] = []

    def _edge(dependent_idx: int, trigger_idx: int) -> DependencyIn:
        return DependencyIn(
            dependent_client_id=f"f{dependent_idx}",
            trigger_client_id=f"f{trigger_idx}",
            condition=draw(st.sampled_from(_CONDITIONS)),
            value=None,
            effect=draw(st.sampled_from(["show", "require"])),
        )

    if is_valid:
        # Acyclic by construction: every edge runs dependent(high) -> trigger(low).
        if n_fields >= 2:
            n_edges = draw(st.integers(min_value=0, max_value=5))
            for _ in range(n_edges):
                i = draw(st.integers(min_value=1, max_value=n_fields - 1))
                j = draw(st.integers(min_value=0, max_value=i - 1))
                deps.append(_edge(i, j))
    else:
        # Invalid: a self-loop, or (when possible) a 2-cycle.
        if n_fields >= 2 and draw(st.booleans()):
            a = draw(st.integers(min_value=0, max_value=n_fields - 1))
            b = draw(st.integers(min_value=0, max_value=n_fields - 1).filter(lambda v: v != a))
            deps.append(_edge(a, b))  # a -> b
            deps.append(_edge(b, a))  # b -> a  → 2-cycle
        else:
            k = draw(st.integers(min_value=0, max_value=n_fields - 1))
            deps.append(_edge(k, k))  # self-loop

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=uuid.uuid4(),
        recipients=recipients,
        fields=fields,
        dependencies=deps,
    )
    return payload, is_valid


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _run(payload: EnvelopeCreate):
    """Drive the send flow; returns ``(envelope_or_None, spy, exc_or_None)``."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    spy = _SpyClient()
    conn = _verified_connection()
    session = _FakeSession()

    async def _fake_get_conn(_db, _org_id):
        return conn

    async def _noop_audit(*_args, **_kwargs):
        return None

    import unittest.mock as _mock

    with _mock.patch.object(
        esign_service, "get_documenso_connection", _fake_get_conn
    ), _mock.patch.object(esign_service, "_audit_and_notify_send", _noop_audit):
        try:
            envelope = asyncio.run(
                esign_service.create_and_send_envelope(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    payload=payload,
                    pdf_bytes=_VALID_PDF,
                    client=spy,  # type: ignore[arg-type]
                )
            )
            return envelope, spy, None
        except HTTPException as exc:
            return None, spy, exc


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


class TestAdvisoryDependencies:
    """Property 21: advisory dependencies present every field and degrade
    require-effects to optional.

    **Validates: Requirements 14.4, 14.6, 14.8**
    """

    @given(scenario=_scenario())
    @PBT_SETTINGS
    def test_advisory_dependencies_present_all_and_degrade_require(self, scenario):
        payload, is_valid = scenario
        envelope, spy, exc = _run(payload)

        if not is_valid:
            # --- Invalid (cycle / self-loop) rejected before any Documenso call (R14.4)
            assert exc is not None, "expected a rejection for a cyclic/self-loop set"
            assert exc.status_code == 422
            code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
            assert code in {"dependency_cycle", "dependency_self"}
            # No Documenso call whatsoever (atomic pre-Documenso rejection).
            assert spy.calls == []
            assert spy.created_fields is None
            return

        # --- Valid (acyclic) advisory set ------------------------------------
        assert exc is None
        assert spy.calls == ["create_document", "create_fields", "send_document"]
        assert "place_signature_field" not in spy.calls

        specs = spy.created_fields
        assert specs is not None
        # Every placed field is created — none suppressed/hidden (R14.6).
        assert len(specs) == len(payload.fields)

        # The set of client_ids that are the dependent of a require-effect dep.
        require_dependents = {
            dep.dependent_client_id
            for dep in (payload.dependencies or [])
            if dep.effect == "require"
        }

        for placed, spec in zip(payload.fields, specs):
            # Order/identity preserved — confirms this spec is that placed field.
            assert spec.page_number == placed.page
            # required-degrade: a require-effect dependent is forced optional
            # (R14.8); every other field keeps its own required flag.
            expected_required = (
                False
                if placed.client_id in require_dependents
                else bool(placed.required)
            )
            assert spec.field_meta["required"] is expected_required
