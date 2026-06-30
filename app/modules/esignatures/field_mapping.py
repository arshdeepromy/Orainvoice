"""Pure field-type mapping and ``fieldMeta`` builder for field placement (R2.4, R5.3, R5.4).

Everything in this module is a **pure function**: no DB, no network, no other
I/O and no global state. That keeps the OraInvoice→Documenso field-type mapping
and the per-field ``fieldMeta`` construction directly property-testable
in-memory (Tasks 8.3 / 8.4) and lets the send path compose them without side
effects.

Two responsibilities:

* :func:`map_field_type` — translate one of the ten supported OraInvoice
  (lowercase) field types to its Documenso (UPPERCASE) field type, raising
  :class:`UnsupportedFieldType` on anything else. This is the authoritative
  type gate that guarantees an unsupported type can never reach the
  ``field/create-many`` wire (R2.4).
* :func:`build_field_meta` — build the Documenso ``fieldMeta`` object for a
  placed field. It **always** carries ``required``; ``text`` / ``number``
  fields additionally carry ``label`` / ``placeholder`` (when present) and a
  ``type`` discriminator; ``radio`` / ``checkbox`` / ``dropdown`` carry a
  sender-authored ``values`` options list and a ``type`` discriminator; the
  remaining types carry only ``required`` (R5.3, R5.4).

**Capability note (design "Documenso capability assumptions" #2).** The working
``DocumensoClient`` never sends ``fieldMeta`` today, and whether
``field/create-many`` accepts and honours ``fieldMeta``
(``required`` / ``label`` / ``placeholder``) is **unverified** against the
running Documenso build — it MUST be confirmed by the capability probe
(Task 9.2). If that probe finds ``fieldMeta`` unsupported, the send path simply
**omits** the value this function returns (a no-op on the wire), and
``required`` / ``label`` / ``placeholder`` become advisory / OraInvoice-only —
R14.8's "advisory require ⇒ optional at signing" then holds trivially because
nothing is engine-enforced. This function itself remains correct regardless:
it just builds the object; whether it is put on the wire is the send path's
decision.

Requirements: 2.4, 5.3, 5.4
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "FIELD_TYPE_MAP",
    "SUPPORTED_FIELD_TYPES",
    "UnsupportedFieldType",
    "map_field_type",
    "build_field_meta",
]

# ---------------------------------------------------------------------------
# OraInvoice field type (lowercase) → Documenso field type (UPPERCASE). (R2.4)
# ---------------------------------------------------------------------------
#: The complete, authoritative mapping of the supported field types. Any
#: type string outside these keys is unsupported and is rejected by
#: :func:`map_field_type`.
#:
#: The first six (``signature`` … ``text``) are the original palette; the four
#: advanced types (``number`` / ``radio`` / ``checkbox`` / ``dropdown``) extend
#: it to match Documenso's full field-type palette. ``number`` behaves like
#: ``text`` (label/placeholder); ``radio`` / ``dropdown`` carry a sender-authored
#: options list; ``checkbox`` is a single box. All additive — the original six
#: keep their exact behaviour.
FIELD_TYPE_MAP: dict[str, str] = {
    "signature": "SIGNATURE",
    "initials": "INITIALS",
    "name": "NAME",
    "date": "DATE",
    "email": "EMAIL",
    "text": "TEXT",
    "number": "NUMBER",
    "radio": "RADIO",
    "checkbox": "CHECKBOX",
    "dropdown": "DROPDOWN",
}

#: The set of supported OraInvoice (lowercase) field types, for callers that
#: want to gate without catching :class:`UnsupportedFieldType`.
SUPPORTED_FIELD_TYPES: frozenset[str] = frozenset(FIELD_TYPE_MAP)


class UnsupportedFieldType(ValueError):
    """Raised by :func:`map_field_type` when a field type is not supported.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    keep working; carries the offending ``field_type`` for humanized messaging.
    """

    def __init__(self, field_type: Any) -> None:
        self.field_type = field_type
        super().__init__(f"Unsupported field type: {field_type!r}")


def map_field_type(t: str) -> str:
    """Map an OraInvoice (lowercase) field type to its Documenso (UPPERCASE) type.

    ``signature`` → ``SIGNATURE``, ``initials`` → ``INITIALS``, ``name`` →
    ``NAME``, ``date`` → ``DATE``, ``email`` → ``EMAIL``, ``text`` → ``TEXT``,
    ``number`` → ``NUMBER``, ``radio`` → ``RADIO``, ``checkbox`` → ``CHECKBOX``,
    ``dropdown`` → ``DROPDOWN`` (R2.4).

    The lookup is **exact** on the documented lowercase keys — it does not
    coerce case or strip whitespace, so any other value (including an
    UPPERCASE Documenso type, a typo, ``None``, or a non-string) is rejected.
    This is what guarantees an unsupported type can never reach the
    ``field/create-many`` wire.

    Pure function — no I/O.

    Raises:
        UnsupportedFieldType: when ``t`` is not one of the supported types.
    """
    try:
        return FIELD_TYPE_MAP[t]
    except (KeyError, TypeError):
        # KeyError: a string that is not a supported key.
        # TypeError: an unhashable value (e.g. a list/dict) used as a key.
        raise UnsupportedFieldType(t) from None


def _get(field: Any, name: str) -> Any:
    """Pull ``name`` from a field-like item (mapping or attribute object).

    Defensive: returns ``None`` when the attribute/key is absent. Pure, never
    raises. Supports both a Pydantic ``FieldIn`` (attribute access) and a plain
    mapping so this module does not have to import the schema (which is defined
    in a later task).
    """
    if isinstance(field, Mapping):
        return field.get(name)
    return getattr(field, name, None)


def build_field_meta(field: Any, *, force_optional: bool = False) -> dict:
    """Build the Documenso ``fieldMeta`` object for one placed field.

    The returned object **always** carries ``required`` (R5.3). Beyond that, the
    shape depends on the field's Documenso type:

    * ``TEXT`` / ``NUMBER`` — carry ``label`` and/or ``placeholder`` for
      whichever is actually present (truthy) on the field (R5.4), and a ``type``
      discriminator (``"text"`` / ``"number"``). ``NUMBER`` behaves exactly like
      ``TEXT`` for label/placeholder.
    * ``RADIO`` / ``CHECKBOX`` — carry ``values``: one entry per sender-authored
      option as ``{"id": i, "value": str(opt), "checked": False}`` (an empty list
      when no options are present), plus a ``type`` discriminator
      (``"radio"`` / ``"checkbox"``).
    * ``DROPDOWN`` — carries ``values``: one entry per option as
      ``{"value": str(opt)}``, plus a ``"dropdown"`` ``type`` discriminator.
    * The remaining types (``SIGNATURE`` / ``INITIALS`` / ``NAME`` / ``DATE`` /
      ``EMAIL``) carry **only** ``required`` — no ``type`` discriminator and
      never ``label`` / ``placeholder`` / ``values`` even if those happen to be
      set on the field (their ``fieldMeta`` is exactly ``{"required": ...}``).

    ``required`` is coerced to a plain ``bool`` so the wire value is always a
    JSON boolean regardless of how the caller represented it.

    **Advisory ``require`` ⇒ optional degrade (R14.8).** When ``force_optional``
    is ``True`` the built ``required`` is forced to ``False`` regardless of the
    field's own required flag. Documenso has no cross-field conditional
    primitive, so a conditional dependency is **advisory** only: a field that is
    the dependent of a ``require``-effect advisory dependency MUST degrade to
    OPTIONAL at signing time, so that an unmet advisory condition can never
    block a recipient (the send path passes ``force_optional=True`` for exactly
    those fields — see ``service._require_effect_dependents``). The degrade is
    applied to the built ``fieldMeta`` regardless of whether it is ultimately
    put on the wire (``fieldMeta`` is itself capability-gated).

    ``field`` may be a Pydantic ``FieldIn`` (attribute access) or a mapping
    with ``type`` / ``required`` / ``label`` / ``placeholder`` / ``options``
    keys.

    Pure function — no I/O.

    Raises:
        UnsupportedFieldType: when the field's ``type`` is unsupported
            (delegated to :func:`map_field_type`), so an unsupported type can
            never be silently given a ``fieldMeta``.
    """
    documenso_type = map_field_type(_get(field, "type"))

    required = False if force_optional else bool(_get(field, "required"))
    meta: dict[str, Any] = {"required": required}

    if documenso_type in ("TEXT", "NUMBER"):
        # TEXT and NUMBER share the label/placeholder behaviour (R5.4); NUMBER
        # is identical to TEXT. Both carry a ``type`` discriminator.
        label = _get(field, "label")
        placeholder = _get(field, "placeholder")
        if label:
            meta["label"] = label
        if placeholder:
            meta["placeholder"] = placeholder
        meta["type"] = "text" if documenso_type == "TEXT" else "number"
    elif documenso_type in ("RADIO", "CHECKBOX"):
        # Sender-authored options become checkable values (none checked by
        # default). CHECKBOX is modelled as a single box in the UI but carries
        # the same ``values`` shape so the wire stays uniform.
        options = _get(field, "options") or []
        meta["values"] = [
            {"id": index, "value": str(option), "checked": False}
            for index, option in enumerate(options)
        ]
        meta["type"] = "radio" if documenso_type == "RADIO" else "checkbox"
    elif documenso_type == "DROPDOWN":
        options = _get(field, "options") or []
        meta["values"] = [{"value": str(option)} for option in options]
        meta["type"] = "dropdown"

    return meta
