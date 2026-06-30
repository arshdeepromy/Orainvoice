"""Pure server-side validation of a sender-defined Field_Set.

This module re-validates the Field_Set carried on a field-placement send
**before** any Documenso call (R6.6), mirroring the client-side rules so a
crafted payload can never bypass them. Like :mod:`app.modules.esignatures.validation`
everything here is a **pure function**: no DB, no network, no other I/O and no
global state, which keeps the rules directly unit/property-testable in-memory
(Property 10, task 8.5).

The rules enforced by :func:`validate_field_set`:

* **R6.2** — every field references a real recipient (its ``recipient_index``
  is in range of the send's recipient list); otherwise the field is treated as
  unassigned.
* **R6.3** — every field is in bounds: ``x >= 0``, ``y >= 0``, ``x + w <= 100``,
  ``y + h <= 100``, ``w > 0``, ``h > 0`` (normalized percent coordinates).
* **R2.4** — every field's ``type`` maps to a Documenso field type (an
  unsupported type is rejected).
* **R6.1** — every signer recipient (Documenso ``SIGNER`` / ``APPROVER``) has at
  least one signature-type field. This is the same safety rule as
  ``esignature-integration`` R17, re-expressed over the sender Field_Set.
* **Options present** — every ``radio`` / ``dropdown`` field carries at least
  one non-empty sender-authored option (so a recipient is never shown an empty
  chooser); ``checkbox`` and ``number`` need none.
* **R4.6** — viewer recipients are exempt: a viewer may have no fields at all.

On failure the result carries a humanized, **leak-free** message that names the
offending field (by page) or the unsatisfied signer(s) (by name) — never raw
database or exception text (R12.3).

Requirements: 2.4, 4.6, 6.1, 6.2, 6.3
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Supported field types (R2.4)
# ---------------------------------------------------------------------------
#
# ``field_mapping.map_field_type`` (task 8.1) is the authoritative type->Documenso
# mapping. It is imported lazily/optionally here so this module stays usable
# whether or not that sibling module has landed yet: when it is importable we
# delegate type validation to it (single source of truth); otherwise we fall
# back to the documented supported set defined locally. Either way the set of
# accepted types is identical.
try:  # pragma: no cover - exercised indirectly depending on import availability
    from app.modules.esignatures.field_mapping import (  # type: ignore
        map_field_type as _map_field_type,
    )
except Exception:  # ImportError (module not present yet) or any partial-import issue
    _map_field_type = None

#: The supported lowercase field types (the local fallback / documentation of
#: the accepted set). Mirrors ``field_mapping`` exactly: the original six plus
#: the four advanced types (number / radio / checkbox / dropdown).
SUPPORTED_FIELD_TYPES: frozenset[str] = frozenset(
    {
        "signature",
        "initials",
        "name",
        "date",
        "email",
        "text",
        "number",
        "radio",
        "checkbox",
        "dropdown",
    }
)

#: The signature-type field — the one a signer must carry at least one of (R6.1).
SIGNATURE_FIELD_TYPE = "signature"

#: The field types that require a sender-authored options list (≥1 non-empty
#: option) before they can be sent. ``checkbox`` is a single box and needs no
#: options; ``number`` behaves like ``text``.
OPTION_BEARING_FIELD_TYPES: frozenset[str] = frozenset({"radio", "dropdown"})

# Bounds tolerance: coordinates are normalized percent in [0, 100]. A tiny
# epsilon absorbs floating-point drift on the ``x + w <= 100`` / ``y + h <= 100``
# edge so a field that the client clamped exactly to the page edge is not
# spuriously rejected. Genuine out-of-bounds fields exceed this by orders of
# magnitude.
_BOUNDS_EPS = 1e-9

# ---------------------------------------------------------------------------
# Machine-readable codes (design "Error Handling" table). Registered in the
# central ``ESIGN_ERROR_MESSAGES`` / ``ESIGN_ERROR_STATUS`` tables in
# ``errors.py`` (task 14.1, all HTTP 422). Defined here as constants so this
# pure module carries its own codes without importing the error tables.
# ---------------------------------------------------------------------------
CODE_FIELD_UNASSIGNED = "field_unassigned"
CODE_FIELD_OUT_OF_BOUNDS = "field_out_of_bounds"
CODE_INVALID_FIELD_TYPE = "invalid_field_type"
CODE_SIGNATURE_FIELD_MISSING = "signature_field_missing"
CODE_FIELD_OPTIONS_MISSING = "field_options_missing"


@dataclass(frozen=True)
class FieldIn:
    """One placed field, as re-validated on the server.

    Coordinates are normalized percent (0–100, origin top-left). ``recipient_index``
    is how the client refers to a recipient: an index into the send's recipient
    list. This mirrors the design's ``FieldIn`` value and the ``FieldIn`` Pydantic
    schema (task 9.1); the validator also accepts plain mappings or any object
    exposing these as attributes.
    """

    type: str
    page: int
    recipient_index: int
    position_x: float
    position_y: float
    width: float
    height: float
    required: bool = True
    label: str | None = None
    placeholder: str | None = None
    options: list[str] | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of :func:`validate_field_set`.

    ``ok`` is ``True`` only when every rule holds. When ``ok`` is ``False`` the
    remaining fields describe the **first** offending condition so the caller
    can reject the whole send atomically (no Documenso call, no rows persisted)
    and surface ``message`` directly. ``message`` is always a non-empty,
    human-readable sentence that names the offending field (by page) or the
    unsatisfied signer(s) (by name) and never leaks raw DB/exception text.
    """

    ok: bool
    code: str | None = None
    message: str | None = None
    #: Zero-based index (into ``fields``) of the offending field, when the
    #: failure is field-level (unassigned / out-of-bounds / invalid type).
    field_index: int | None = None
    #: Recipient indices of signers missing a signature field, when the failure
    #: is the R6.1 signature-field rule.
    signer_indices: tuple[int, ...] | None = None


def _get(item: Any, field: str) -> Any:
    """Read ``field`` from a field-like item (mapping or attribute object).

    Defensive: returns ``None`` when absent. Pure, never raises.
    """
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _is_supported_type(type_value: Any) -> bool:
    """Return ``True`` when ``type_value`` maps to a Documenso field type (R2.4).

    Delegates to ``field_mapping.map_field_type`` when that module is available
    (single source of truth) and otherwise checks the local supported set.
    """
    if _map_field_type is not None:
        try:
            _map_field_type(type_value)
            return True
        except Exception:
            return False
    return isinstance(type_value, str) and type_value in SUPPORTED_FIELD_TYPES


def _as_float(value: Any) -> float | None:
    """Best-effort float coercion; ``None`` for non-numeric input. Never raises."""
    if isinstance(value, bool):  # bool is an int subclass — exclude explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _in_bounds(field: Any) -> bool:
    """Return ``True`` when ``field`` is fully within the page (R6.3).

    ``x >= 0``, ``y >= 0``, ``x + w <= 100``, ``y + h <= 100``, ``w > 0``, ``h > 0``.
    A missing/non-numeric coordinate is out of bounds (rejected).
    """
    x = _as_float(_get(field, "position_x"))
    y = _as_float(_get(field, "position_y"))
    w = _as_float(_get(field, "width"))
    h = _as_float(_get(field, "height"))
    if x is None or y is None or w is None or h is None:
        return False
    if w <= 0 or h <= 0:
        return False
    if x < 0 or y < 0:
        return False
    if x + w > 100 + _BOUNDS_EPS or y + h > 100 + _BOUNDS_EPS:
        return False
    return True


def _has_nonempty_option(field: Any) -> bool:
    """Return ``True`` when a field carries at least one non-empty option.

    Options arrive as a list of strings (``radio`` / ``dropdown``). An option is
    "non-empty" when, coerced to ``str`` and stripped, it is not blank. A
    missing/empty/non-iterable options value yields ``False``. Pure, never
    raises.
    """
    options = _get(field, "options")
    if not isinstance(options, (list, tuple)):
        return False
    return any(str(option).strip() for option in options)


def _page_label(field: Any) -> str:
    """Human-friendly page reference for a field's message. Falls back safely."""
    page = _get(field, "page")
    if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
        return str(page)
    return "?"


def _recipient_name(recipients: Sequence[Any], index: int) -> str:
    """Best-effort display name for the recipient at ``index``.

    Falls back to the recipient's email, then a generic label, so the message is
    always human-readable and never leaks internal detail.
    """
    if 0 <= index < len(recipients):
        recipient = recipients[index]
        name = _get(recipient, "name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        email = _get(recipient, "email")
        if isinstance(email, str) and email.strip():
            return email.strip()
    return "this signer"


def _humanize_names(names: Sequence[str]) -> str:
    """Join recipient names into a natural-language list.

    ``["A"] -> "A"``, ``["A", "B"] -> "A and B"``,
    ``["A", "B", "C"] -> "A, B, and C"``.
    """
    if not names:
        return "this signer"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def validate_field_set(
    fields: Sequence[Any] | None,
    recipients: Sequence[Any] | None,
    signer_indices: Iterable[int] | None,
) -> ValidationResult:
    """Re-validate a sender-defined Field_Set server-side (pure).

    ``fields`` is the placed Field_Set (each item a :class:`FieldIn`, a mapping,
    or an object exposing the same attributes). ``recipients`` is the send's
    recipient list (used only to range-check ``recipient_index`` and to name
    signers in messages). ``signer_indices`` are the indices into ``recipients``
    that are signers (Documenso ``SIGNER`` / ``APPROVER``) and therefore must
    each carry at least one signature field; recipients not in this set
    (viewers) are exempt (R4.6).

    Returns a :class:`ValidationResult`. ``ok`` is ``True`` only when **every**
    rule holds. On the first failure it returns ``ok=False`` with a humanized,
    leak-free ``message`` naming the offending field or signer(s).

    Pure function — no I/O, never raises.
    """
    field_list: list[Any] = list(fields) if fields else []
    recipient_list: list[Any] = list(recipients) if recipients else []
    recipient_count = len(recipient_list)

    # Field-level rules (R6.2, R2.4, R6.3). Scanned in order; the first offending
    # field rejects the whole set so the caller stays atomic.
    for index, field in enumerate(field_list):
        # R6.2 — assigned to a real recipient (recipient_index in range).
        recipient_index = _get(field, "recipient_index")
        if (
            not isinstance(recipient_index, int)
            or isinstance(recipient_index, bool)
            or recipient_index < 0
            or recipient_index >= recipient_count
        ):
            return ValidationResult(
                ok=False,
                code=CODE_FIELD_UNASSIGNED,
                message=(
                    f"A field on page {_page_label(field)} isn't assigned to a "
                    "recipient. Assign it before sending."
                ),
                field_index=index,
            )

        # R2.4 — type maps to a supported Documenso type.
        if not _is_supported_type(_get(field, "type")):
            return ValidationResult(
                ok=False,
                code=CODE_INVALID_FIELD_TYPE,
                message="One of the fields has an unsupported type.",
                field_index=index,
            )

        # R6.3 — fully within the page bounds.
        if not _in_bounds(field):
            return ValidationResult(
                ok=False,
                code=CODE_FIELD_OUT_OF_BOUNDS,
                message=(
                    f"A field on page {_page_label(field)} extends past the edge "
                    "of the page. Move it fully onto the page."
                ),
                field_index=index,
            )

        # A radio/dropdown field MUST carry at least one non-empty option, so a
        # recipient is never shown an empty chooser. ``checkbox`` (a single box)
        # and ``number`` (text-like) need no options.
        field_type = _get(field, "type")
        if field_type in OPTION_BEARING_FIELD_TYPES and not _has_nonempty_option(field):
            return ValidationResult(
                ok=False,
                code=CODE_FIELD_OPTIONS_MISSING,
                message=f"Add at least one option to the {field_type} field.",
                field_index=index,
            )

    # R6.1 — every signer recipient has >=1 signature-type field; viewers exempt.
    # Only consider signer indices that actually reference a real recipient.
    signers = sorted(
        {
            idx
            for idx in (signer_indices or ())
            if isinstance(idx, int)
            and not isinstance(idx, bool)
            and 0 <= idx < recipient_count
        }
    )
    signers_with_signature = {
        _get(field, "recipient_index")
        for field in field_list
        if _get(field, "type") == SIGNATURE_FIELD_TYPE
    }
    missing = [idx for idx in signers if idx not in signers_with_signature]
    if missing:
        names = [_recipient_name(recipient_list, idx) for idx in missing]
        return ValidationResult(
            ok=False,
            code=CODE_SIGNATURE_FIELD_MISSING,
            message=f"Add a signature field for {_humanize_names(names)} before sending.",
            signer_indices=tuple(missing),
        )

    return ValidationResult(ok=True)


# ---------------------------------------------------------------------------
# Edit-after-send gate (R13) — pure Editable_State predicate.
# ---------------------------------------------------------------------------
#
# A sent envelope's Field_Set may only be edited while the envelope is in the
# Editable_State: its ``status`` is exactly ``"sent"`` AND **no** recipient has
# signed. Every other condition is a Non_Editable_State (R13.4, R13.6):
#
#   * any non-``sent`` envelope status — ``draft`` (not yet sent),
#     ``viewed`` (a recipient is mid-signing), ``partially_signed``,
#     ``completed``, ``declined``, ``voided``, or ``error``; and
#   * a ``sent`` envelope where any recipient has already signed.
#
# The predicate is **pure** (no I/O, no DB, no network) so it is directly
# property-testable, and it reads each recipient's signed state from the
# persisted ``esign_recipients.recipient_status`` column — the same column the
# Documenso webhook handler maintains via the pure ``status.py`` reducer.

#: The single ``recipient_status`` value that counts as "signed". This MUST stay
#: aligned with the value the webhook handler persists:
#: ``service._recipient_status_from_payload`` writes ``"signed"`` (alongside
#: ``"declined"`` / ``"viewed"`` / ``"pending"``), and ``status.RecipientState``
#: derives its ``signed`` flag from ``mapped_status == "signed"``. We reuse that
#: exact vocabulary here rather than inventing a parallel type.
SIGNED_RECIPIENT_STATUSES: frozenset[str] = frozenset({"signed"})

#: The envelope status in which the Field_Set may be edited (R13.4).
EDITABLE_ENVELOPE_STATUS = "sent"


def _recipient_has_signed(recipient: Any) -> bool:
    """Return ``True`` when ``recipient`` has signed.

    Reads the persisted ``recipient_status`` column (a mapping key or an
    attribute) and compares it against :data:`SIGNED_RECIPIENT_STATUSES` — the
    exact vocabulary the webhook handler writes. As a defensive fallback (e.g.
    when handed a ``status.RecipientState``) a truthy ``signed`` attribute/key is
    also treated as signed. Pure, never raises.
    """
    status_value = _get(recipient, "recipient_status")
    if isinstance(status_value, str) and status_value.strip().lower() in SIGNED_RECIPIENT_STATUSES:
        return True
    # Fallback for a RecipientState-like object carrying a boolean ``signed``.
    signed_flag = _get(recipient, "signed")
    return signed_flag is True


def editable_state(status: Any, recipients: Sequence[Any] | None) -> bool:
    """Return ``True`` iff a sent envelope's Field_Set may still be edited (R13).

    The Editable_State is: ``status == "sent"`` **AND** no recipient has signed.
    Every other condition — any non-``sent`` status (``draft``, ``viewed``,
    ``partially_signed``, ``completed``, ``declined``, ``voided``, ``error``) or
    a ``sent`` envelope with at least one signed recipient — is a
    Non_Editable_State and returns ``False`` (R13.4, R13.6).

    ``status`` is the envelope status. ``recipients`` is the envelope's recipient
    list; each recipient's signed state is read from its persisted
    ``recipient_status`` (mapping key or attribute) per
    :data:`SIGNED_RECIPIENT_STATUSES`. An empty/absent recipient list with a
    ``sent`` status is editable (nobody has signed).

    Pure function — no I/O, never raises.
    """
    if status != EDITABLE_ENVELOPE_STATUS:
        return False
    for recipient in recipients or ():
        if _recipient_has_signed(recipient):
            return False
    return True
