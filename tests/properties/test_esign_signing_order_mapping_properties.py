"""Property-based test for signing-order mapping (task 19.4).

# Feature: esignature-field-placement, Property 22: Signing-order positions and distribution mode map faithfully

The function under test is
:func:`app.modules.esignatures.service.create_and_send_envelope` after tasks
19.2/19.3 wired the signing-order capability (R15). For a send the service:

  * threads each recipient's optional 1-based ``order`` onto the
    :class:`~app.integrations.documenso.RecipientSpec` it passes to
    ``create_document`` (signers carry their position; ``viewer`` recipients
    carry no position but still appear as recipients on the document — R15.6);
  * threads the chosen ``signing_order_mode`` to ``send_document`` so the
    Documenso distribution mode is ``SEQUENTIAL`` when the mode is
    ``sequential`` and ``PARALLEL`` otherwise (R15.4, R15.5).

Property 22: for *any* recipient list mixing signers/viewers and any mode,

  * the distribution mode the service drives is ``SEQUENTIAL`` iff the send's
    ``signing_order_mode`` is ``sequential``, else ``PARALLEL``;
  * in ``sequential`` mode the ``signingOrder`` positions the service passes
    over the **signing** recipients are pairwise distinct, 1-based, and
    contiguous (a permutation of ``1..N``);
  * ``viewer`` recipients receive **no** position yet still appear among the
    recipients the service registers on the document.

This drives the real service flow with a **spy** ``DocumensoClient`` (so the
create → field → distribute sequence runs without a real Documenso) over a
lightweight fake async session, mirroring the established service-level esign
property tests (``test_esign_send_persistence_properties.py`` /
``test_esign_connection_gate_send_properties.py``). The per-org connection gate
is satisfied by patching ``service.get_documenso_connection`` to return a
verified connection, and the best-effort audit/notify side-effect is patched to
a no-op so the fake session needs no SAVEPOINT support. The capability flag
(``esign_signing_order_supported``) gates only whether the position/mode reach
the *wire*; this property concerns how the **service** maps mode + positions to
what it passes the client, so it holds regardless of the flag.

**Validates: Requirements 15.3, 15.4, 15.5, 15.6**
"""

from __future__ import annotations

import asyncio
import uuid
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignEnvelope/EsignRecipient are instantiated
# (mirrors the other esign service-level property tests).
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
    RecipientSpec,
    map_recipient_role,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures.models import EsignEnvelope  # noqa: E402
from app.modules.esignatures.schemas import EnvelopeCreate, RecipientIn  # noqa: E402

_AGREEMENT_TYPES = [
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
]
_ENTITY_TYPES = ["invoice", "quote", "staff"]


# ---------------------------------------------------------------------------
# Spy DocumensoClient — records the recipients passed to create_document (each
# carrying its threaded signing_order) and the signing_order_mode passed to
# send_document. Matches the CURRENT service call shape exactly:
#   create_document(*, title, recipients, pdf_bytes)
#   place_signature_field(document_id, *, recipient_id, page_number, ...)
#   send_document(document_id, *, signing_order_mode)
# ---------------------------------------------------------------------------


class _SpyDocumensoClient:
    def __init__(self, document_id: str = "doc-1") -> None:
        self._document_id = document_id
        self.created_recipients: list[RecipientSpec] = []
        self.field_calls: list[str] = []
        self.send_mode: str | None = None
        self.send_calls: list[str] = []

    async def create_document(self, *, title, recipients, pdf_bytes) -> DocumensoCreateResult:
        # Capture the EXACT RecipientSpec list the service built (with each
        # recipient's threaded signing_order position).
        self.created_recipients = list(recipients)
        created: list[CreatedRecipient] = []
        for i, spec in enumerate(recipients):
            created.append(
                CreatedRecipient(
                    recipient_id=f"r{i}",
                    email=spec.email,
                    role=map_recipient_role(spec.role),
                    token=f"tok{i}",
                    signing_url=f"https://documenso.example.test/sign/tok{i}",
                )
            )
        return DocumensoCreateResult(
            document_id=self._document_id,
            recipients=created,
        )

    async def place_signature_field(
        self,
        document_id,
        *,
        recipient_id,
        page_number,
        page_x,
        page_y,
        page_width,
        page_height,
    ) -> None:
        self.field_calls.append(recipient_id)

    async def create_fields(self, document_id, specs) -> None:
        # Not exercised by this property (sends carry no Field_Set), but present
        # so the spy is a faithful stand-in.
        self.field_calls.extend(str(getattr(s, "recipient_id", "")) for s in specs)

    async def send_document(self, document_id, *, signing_order_mode: str = "parallel") -> None:
        self.send_mode = signing_order_mode
        self.send_calls.append(document_id)


# ---------------------------------------------------------------------------
# Fake async session — captures the added envelope; flush/refresh are no-ops.
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


# A minimal, syntactically valid PDF (the service's is_pdf check needs the %PDF
# prefix; page-count detection falls back to page 1 when undeterminable).
VALID_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _verified_connection() -> DocumensoConnection:
    return DocumensoConnection(
        base_url="https://documenso.example.test",
        service_token="tok_team_scoped_raw",
        webhook_secret="whsec",
        documenso_team_id="team-1",
        webhook_routing_id="route-1",
        is_verified=True,
    )


# ---------------------------------------------------------------------------
# Strategy — a recipient list mixing signers/viewers (>= 1 signer) under either
# signing-order mode. In SEQUENTIAL mode the signing recipients are assigned a
# permutation of 1..N as their 1-based ``order`` (exactly what the SigningOrder
# UI produces); viewers always carry ``order=None``. In PARALLEL mode no
# recipient carries a position (the backward-compatible default).
# ---------------------------------------------------------------------------


@st.composite
def _send_with_mode(draw):
    n = draw(st.integers(min_value=1, max_value=5))
    roles = [draw(st.sampled_from(["signer", "viewer"])) for _ in range(n)]
    # Guarantee >= 1 signer so the no-signers guard passes.
    if "signer" not in roles:
        roles[draw(st.integers(min_value=0, max_value=n - 1))] = "signer"

    mode = draw(st.sampled_from(["parallel", "sequential"]))

    signer_positions: list[int] = []
    if mode == "sequential":
        n_signers = roles.count("signer")
        # A permutation of 1..n_signers, handed out to signers in list order.
        signer_positions = draw(st.permutations(list(range(1, n_signers + 1))))

    recipients: list[RecipientIn] = []
    pos_iter = iter(signer_positions)
    for i, role in enumerate(roles):
        local = draw(st.from_regex(r"[a-z]{1,8}", fullmatch=True))
        name = draw(st.from_regex(r"[A-Za-z][A-Za-z ]{0,18}", fullmatch=True))
        order = None
        if mode == "sequential" and role == "signer":
            order = next(pos_iter)
        recipients.append(
            RecipientIn(
                name=name,
                email=f"{local}{i}@mailhost.io",
                signing_role=role,
                order=order,
            )
        )

    payload = EnvelopeCreate(
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        originating_entity_type=draw(st.sampled_from(_ENTITY_TYPES)),
        originating_entity_id=draw(st.uuids()),
        recipients=recipients,
        signing_order_mode=mode,
    )
    return payload, mode


@settings(max_examples=200, deadline=None)
@given(send=_send_with_mode(), org_id=st.uuids(), user_id=st.uuids())
def test_signing_order_positions_and_mode_map_faithfully(send, org_id, user_id):
    payload, mode = send

    session = _FakeSession()
    spy = _SpyDocumensoClient()
    conn = _verified_connection()

    async def _fake_get_conn(_db, _org_id):
        return conn

    async def _noop_audit(*_args, **_kwargs):
        return None

    with mock.patch.object(service, "get_documenso_connection", _fake_get_conn), \
            mock.patch.object(service, "_audit_and_notify_send", _noop_audit):
        envelope = asyncio.run(
            service.create_and_send_envelope(
                session,
                org_id=org_id,
                user_id=user_id,
                payload=payload,
                pdf_bytes=VALID_PDF,
                client=spy,
            )
        )

    # The send actually reached the (spy) Documenso distribute step.
    assert isinstance(envelope, EsignEnvelope)
    assert spy.send_calls, "send_document was never called"
    assert spy.created_recipients, "create_document was never called"

    # ----- Distribution mode maps faithfully (R15.4, R15.5) ----------------
    # The service threads the chosen mode to send_document unchanged; the
    # Documenso distribution mode is SEQUENTIAL iff sequential, else PARALLEL.
    assert spy.send_mode == mode
    expected_distribution = "SEQUENTIAL" if mode == "sequential" else "PARALLEL"
    actual_distribution = "SEQUENTIAL" if spy.send_mode == "sequential" else "PARALLEL"
    assert actual_distribution == expected_distribution

    # ----- Every recipient still appears on the document (R15.6) -----------
    # Signers AND viewers are all registered, in input order, matched by email.
    assert len(spy.created_recipients) == len(payload.recipients)
    for spec, r_in in zip(spy.created_recipients, payload.recipients):
        assert spec.email == str(r_in.email)
        assert spec.role == r_in.signing_role
        # The service threads each recipient's ``order`` through verbatim.
        assert spec.signing_order == r_in.order

    # Partition the registered specs by whether they sign.
    signing_specs = [
        s for s in spy.created_recipients if map_recipient_role(s.role) in {"SIGNER", "APPROVER"}
    ]
    viewer_specs = [
        s for s in spy.created_recipients if map_recipient_role(s.role) not in {"SIGNER", "APPROVER"}
    ]

    # ----- Viewers receive no position but remain recipients (R15.6) -------
    for v in viewer_specs:
        assert v.signing_order is None

    # ----- Positions over signing recipients (R15.3) -----------------------
    positions = [s.signing_order for s in signing_specs]
    if mode == "sequential":
        n = len(signing_specs)
        # Pairwise distinct, 1-based, contiguous → a permutation of 1..N.
        assert all(p is not None for p in positions)
        assert sorted(positions) == list(range(1, n + 1))
        assert len(set(positions)) == len(positions)  # pairwise distinct
    else:
        # Parallel: no recipient carries an explicit position.
        assert all(p is None for p in positions)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
