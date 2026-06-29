"""Pydantic v2 schemas for the e-signature (``esignatures``) module.

Request/response models for the Agreements feature. These schemas map the
OraInvoice API surface onto the ``esign_envelopes`` / ``esign_recipients``
records.

Conventions and guarantees:

- Pydantic v2 style (``ConfigDict``, ``EmailStr`` from ``pydantic``).
- Array responses are wrapped in ``{ items, total }`` per project convention.
- ``signing_role`` is accepted from the API in **lowercase** (``signer`` /
  ``viewer``); it is persisted and sent to Documenso in **UPPERCASE**
  (``SIGNER`` / ``VIEWER``). The lowercase -> uppercase mapping happens in the
  client/service layer, not here.
- No schema carries plaintext Documenso credentials or signed-document bytes
  (R14.4, R15.3) — the signed document is referenced only by an opaque,
  org-checked URL.

**Validates: Requirements 3.3, 3.6, 11.5, 14.4, 15.3, 16.1, 16.2**
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Agreement categories supported by the module (R3.6).
AgreementType = Literal[
    "sales_agreement",
    "purchase_agreement",
    "nda",
    "employment_agreement",
    "contractor_agreement",
]

# The OraInvoice record an envelope is attached to.
OriginatingEntityType = Literal["invoice", "quote", "staff"]

# Signing roles accepted from the API in lowercase. Mapped to the UPPERCASE
# Documenso role (SIGNER / VIEWER) in the client/service layer before send.
SigningRole = Literal["signer", "viewer"]

# The six supported field types, accepted from the API in lowercase and mapped
# to their UPPERCASE Documenso types (SIGNATURE / INITIALS / NAME / DATE /
# EMAIL / TEXT) by ``field_mapping.map_field_type`` in the service layer (R2.1).
FieldType = Literal["signature", "initials", "name", "date", "email", "text"]

# Signing-order mode (R15). ``parallel`` (the existing default behaviour) lets
# every signer sign at once; ``sequential`` invites each signer only after the
# previous one in the order has signed. Mapped to Documenso's ``PARALLEL`` /
# ``SEQUENTIAL`` distribution mode in the client/service layer (R15.4, R15.5).
SigningOrderMode = Literal["parallel", "sequential"]

# The supported conditional-field trigger conditions (R14.3). ``is_checked`` /
# ``is_not_checked`` apply to checkbox-style triggers; ``equals`` /
# ``not_equals`` (using the optional ``value``) and ``is_filled`` / ``is_empty``
# apply to value-bearing triggers.
DependencyCondition = Literal[
    "is_checked",
    "is_not_checked",
    "equals",
    "not_equals",
    "is_filled",
    "is_empty",
]

# The effect a Field_Dependency has on its dependent field (R14.1). Enforcement
# is **advisory** today (Documenso has no cross-field conditional primitive), so
# a ``require``-effect advisory dependency degrades the dependent field to
# optional at signing time (R14.8) — see ``field_mapping.build_field_meta``.
DependencyEffect = Literal["show", "require"]


class FieldIn(BaseModel):
    """A single sender-placed field carried on a field-placement send.

    Coordinates are **normalized percent** (0–100) with the origin at the
    top-left of the page, independent of the on-screen render scale. The
    Pydantic constraints below are a **first-pass guard** only — the
    authoritative, cross-field rules (every signer carries a signature field,
    every field references a real recipient, full in-bounds check, etc.) live in
    :func:`app.modules.esignatures.field_validation.validate_field_set`, which
    re-validates the whole Field_Set server-side before any Documenso call
    (R6.6). This model mirrors that module's ``FieldIn`` value (R2.1, R5.1,
    R5.2).
    """

    type: FieldType  # R2.1 — one of the six supported types
    page: int = Field(ge=1)  # 1-based page number
    recipient_index: int = Field(ge=0)  # index into the send's recipient list
    position_x: float = Field(ge=0, le=100)  # normalized percent, origin top-left
    position_y: float = Field(ge=0, le=100)
    width: float = Field(gt=0, le=100)
    height: float = Field(gt=0, le=100)
    required: bool = True  # R5.1 — per-field required flag
    label: str | None = None  # R5.2 — text-field label (optional)
    placeholder: str | None = None  # R5.2 — text-field placeholder (optional)
    # Stable per-field key used to reference this field from a Field_Dependency
    # (``DependencyIn.dependent_client_id`` / ``trigger_client_id``, R14).
    # Additive and optional: sends without dependencies never need it.
    client_id: str | None = None


class DependencyIn(BaseModel):
    """A conditional-field dependency carried alongside the Field_Set (R14).

    Records that the ``dependent_client_id`` field's visibility/required state is
    governed by the value of the ``trigger_client_id`` field (R14.1). Enforcement
    is **advisory** today — Documenso has no cross-field conditional primitive —
    so the dependency is stored for the sender's reference and a ``require``
    effect degrades the dependent field to optional at signing (R14.8). The
    authoritative acyclicity / self-loop rules live in the pure
    ``dependency_graph`` validator (R14.2, R14.4); the constraints here are a
    first-pass guard only.
    """

    dependent_client_id: str = Field(min_length=1)  # field governed by the rule
    trigger_client_id: str = Field(min_length=1)  # field whose value is observed
    condition: DependencyCondition  # R14.3
    value: str | None = None  # comparison value for equals / not_equals
    effect: DependencyEffect  # R14.1 — show / require


class RecipientIn(BaseModel):
    """A recipient supplied when creating a send.

    ``signing_role`` is accepted lowercase and mapped to the UPPERCASE
    Documenso role (``SIGNER`` / ``VIEWER``) before calling Documenso (R4.1).
    """

    name: str = Field(min_length=1)
    email: EmailStr  # syntactic validation (R4.2)
    signing_role: SigningRole = "signer"
    # Optional 1-based signing-order position (R15.3, R15.6). Used only when the
    # send's ``signing_order_mode`` is ``sequential``; viewers carry no position
    # but remain on the document. Additive — omitted/``None`` for parallel sends.
    order: int | None = Field(default=None, ge=1)


class EnvelopeCreate(BaseModel):
    """Payload to create and send an envelope.

    The source PDF arrives as a multipart ``UploadFile`` alongside this JSON
    body; it is not part of this schema (no document bytes are carried here).
    """

    agreement_type: AgreementType  # R3.6
    originating_entity_type: OriginatingEntityType
    originating_entity_id: UUID
    recipients: list[RecipientIn] = Field(min_length=1)  # >=1 recipient (R3.3)
    # Sender-defined Field_Set placed in the editor (R2.1, R5.1, R5.2). Additive
    # and backward-compatible: when omitted/``None``/empty the existing
    # single-signature auto-placement path runs unchanged (R8.3 fallback); when
    # non-empty these fields are re-validated server-side and created on the
    # Documenso document via ``field/create-many`` before distribute.
    fields: list[FieldIn] | None = None
    # Signing-order mode (R15.2). Defaults to ``parallel`` so existing callers
    # are unaffected; ``sequential`` uses each recipient's ``order`` position.
    signing_order_mode: SigningOrderMode = "parallel"
    # Advisory conditional-field dependencies over the Field_Set (R14). Additive
    # and optional; re-checked for cycles/self-loops server-side before send.
    dependencies: list[DependencyIn] | None = None


class FieldSetReplace(BaseModel):
    """Body for ``PUT /api/v2/esign/envelopes/{id}/fields`` (edit-after-send, R13).

    Unlike :class:`EnvelopeCreate`, the Field_Set is **required** (≥1 field) here:
    an edit always replaces the whole set, and the server re-validates it with the
    same rules as an initial send before atomically replacing the Documenso fields
    (R13.3). ``dependencies`` is optional and re-checked for cycles/self-loops.
    """

    fields: list[FieldIn] = Field(min_length=1)
    dependencies: list[DependencyIn] | None = None


class RecipientOut(BaseModel):
    """A persisted recipient with its per-recipient signing status.

    ``signing_role`` is returned as the stored UPPERCASE Documenso role.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    signing_role: str
    recipient_status: str


class EnvelopeOut(BaseModel):
    """A single envelope with its recipients and current status.

    ``signed_document_url`` is populated only when a signed document has been
    stored for the envelope (R11.5); it is an opaque, org-checked link and
    never the document bytes themselves.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agreement_type: str
    originating_entity_type: str
    originating_entity_id: UUID
    status: str
    recipients: list[RecipientOut]
    signed_document_url: str | None = None  # present only when stored (R11.5)
    created_at: datetime
    updated_at: datetime


class EnvelopeListResponse(BaseModel):
    """Array response wrapped in ``{ items, total }`` per project convention."""

    items: list[EnvelopeOut]
    total: int


class FieldOut(BaseModel):
    """A field read back from the Documenso document (edit-after-send, R13).

    Mirrors :class:`FieldIn` so the editor can be seeded from the live field set
    via ``GET /envelopes/{id}/fields`` and re-submitted through
    :class:`FieldSetReplace`. Coordinates are normalized percent, origin top-left.
    """

    model_config = ConfigDict(from_attributes=True)

    type: FieldType
    page: int
    recipient_index: int
    position_x: float
    position_y: float
    width: float
    height: float
    required: bool = True
    label: str | None = None
    placeholder: str | None = None
    client_id: str | None = None


class EnvelopeFieldsOut(BaseModel):
    """Response for ``GET /api/v2/esign/envelopes/{id}/fields`` (R13.1).

    Seeds the editor with the envelope's current Field_Set, its recipients (so
    fields can be re-assigned), and the ``editable`` flag computed by the pure
    ``editable_state`` gate (``status == "sent"`` AND no recipient has signed).
    When ``editable`` is false the editor surfaces the Non_Editable_State banner
    and offers Void_And_Recreate (R13.4).
    """

    fields: list[FieldOut]
    recipients: list[RecipientOut]
    editable: bool


class TemplateFieldIn(BaseModel):
    """A single field stored on a Field_Template (R17.1).

    Carries geometry/type/required/label/placeholder plus a
    ``template_role`` — an abstract recipient slot (e.g. ``"signer 1"``) rather
    than a specific person, so applying the template maps each role to one of
    the current send's recipients without ever storing a name or email.
    """

    type: FieldType
    page: int = Field(ge=1)
    position_x: float = Field(ge=0, le=100)
    position_y: float = Field(ge=0, le=100)
    width: float = Field(gt=0, le=100)
    height: float = Field(gt=0, le=100)
    required: bool = True
    label: str | None = None
    placeholder: str | None = None
    template_role: str = Field(min_length=1)  # abstract recipient slot (R17.1)


class FieldTemplateCreate(BaseModel):
    """Payload to save the current Field_Set as a reusable template (R17.1-R17.3).

    Org-scoped and durable; stores roles, never specific recipients. ``roles`` is
    the set of distinct Template_Recipient_Role slots the template's fields refer
    to, used at apply time to drive role→recipient mapping (R17.5, R17.6).
    """

    name: str = Field(min_length=1)
    agreement_type: AgreementType | None = None  # optional association (R17.2)
    fields: list[TemplateFieldIn] = Field(min_length=1)
    roles: list[str] = Field(min_length=1)


class FieldTemplateOut(BaseModel):
    """A persisted, org-scoped Field_Template (R17)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agreement_type: str | None = None
    fields: list[TemplateFieldIn]
    roles: list[str]
    created_at: datetime
    updated_at: datetime


class FieldTemplateListResponse(BaseModel):
    """Array response wrapped in ``{ items, total }`` per project convention."""

    items: list[FieldTemplateOut]
    total: int


class EsignError(BaseModel):
    """Error response shape (R16).

    ``message`` is always present and human-readable; ``code`` is an optional
    secondary machine-readable code. Raw database/exception text is never
    carried here (R15.5).
    """

    message: str
    code: str | None = None
