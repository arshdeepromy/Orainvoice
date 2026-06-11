"""Customer address utilities.

This module provides a single source of truth for resolving a customer's
display address for "Bill To" / "Prepared For" rendering across invoices and
quotes (in-app previews, generated PDFs, and public/shared links).

Historically the address-resolution logic was duplicated inline in several
call sites (``get_invoice``, ``generate_invoice_pdf``, the public invoice and
quote routers, etc.). Some surfaces only read the plain-text ``address``
column and silently omitted the address for customers whose address lived only
in the structured ``billing_address`` JSONB column. Centralising the logic
here keeps every rendering surface consistent.
"""


def resolve_customer_display_address(customer) -> str | None:
    """Resolve a customer's display address for Bill To rendering.

    Precedence:
      1. Plain-text ``customers.address`` column (verbatim) when non-empty.
      2. Structured ``customers.billing_address`` JSONB — comma-joins the
         non-empty parts in order: street, city, state, postal_code, country.
      3. None when neither source has content.
    """
    plain = (getattr(customer, "address", None) or "").strip()
    if plain:
        return plain
    ba = getattr(customer, "billing_address", None) or {}
    if isinstance(ba, dict):
        joined = ", ".join(
            str(ba.get(k)).strip()
            for k in ("street", "city", "state", "postal_code", "country")
            if ba.get(k) and str(ba.get(k)).strip()
        )
        return joined or None
    return None
