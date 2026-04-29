"""Business logic for Invoice module — creation, GST calculation, numbering.

Requirements: 17.1, 17.3, 17.4, 17.5, 17.6, 23.1, 23.2, 23.3
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.catalogue.models import LabourRate, ServiceCatalogue
from app.modules.invoices.models import (
    CreditNote,
    CreditNoteSequence,
    Invoice,
    InvoiceSequence,
    LineItem,
)
from app.modules.payments.models import Payment
from app.modules.catalogue.models import LabourRate, ServiceCatalogue

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
SIX_PLACES = Decimal("0.000001")

# ISO 3166-1 alpha-2 country code mapping for Stripe shipping address
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "new zealand": "NZ", "australia": "AU", "united states": "US",
    "united kingdom": "GB", "canada": "CA", "ireland": "IE",
    "singapore": "SG", "south africa": "ZA", "india": "IN",
    "philippines": "PH", "fiji": "FJ", "samoa": "WS", "tonga": "TO",
    "france": "FR", "germany": "DE", "italy": "IT", "spain": "ES",
    "netherlands": "NL", "belgium": "BE", "austria": "AT",
    "switzerland": "CH", "sweden": "SE", "norway": "NO", "denmark": "DK",
    "finland": "FI", "poland": "PL", "czech republic": "CZ",
    "czechia": "CZ", "romania": "RO", "greece": "GR", "portugal": "PT",
    "japan": "JP", "china": "CN", "south korea": "KR",
}


def _to_iso_country_code(value: str) -> str:
    """Convert a country name or code to ISO 3166-1 alpha-2."""
    if not value:
        return "NZ"
    stripped = value.strip()
    if len(stripped) == 2:
        return stripped.upper()
    return _COUNTRY_NAME_TO_CODE.get(stripped.lower(), stripped)


def validate_invoice_currency(
    currency: str,
    org_settings: dict,
) -> None:
    """Validate currency selection against org multi-currency settings.

    Requirements: 79.1, 79.2
    - If multi-currency is not enabled, only NZD is allowed.
    - If enabled, currency must be in the org's allowed_currencies list.
    """
    from app.modules.invoices.schemas import SUPPORTED_CURRENCIES

    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")

    multi_currency_enabled = org_settings.get("multi_currency_enabled", False)

    if not multi_currency_enabled:
        if currency != "NZD":
            raise ValueError(
                "Multi-currency is not enabled for this organisation. Only NZD is allowed."
            )
        return

    allowed = org_settings.get("allowed_currencies", ["NZD"])
    if currency not in allowed:
        raise ValueError(
            f"Currency {currency} is not in the organisation's allowed currencies: {allowed}"
        )


def calculate_nzd_equivalent(
    total: Decimal,
    exchange_rate_to_nzd: Decimal,
) -> Decimal:
    """Convert a foreign currency total to NZD using the stored exchange rate.

    Requirements: 79.4
    The exchange rate represents how many NZD per 1 unit of the invoice currency.
    For NZD invoices, exchange_rate_to_nzd is always 1.0.
    """
    return (total * exchange_rate_to_nzd).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def get_currency_symbol(currency_code: str) -> str:
    """Return the display symbol for a currency code."""
    from app.modules.invoices.schemas import SUPPORTED_CURRENCIES

    return SUPPORTED_CURRENCIES.get(currency_code, currency_code)


def _calculate_line_total(
    quantity: Decimal,
    unit_price: Decimal,
    discount_type: str | None,
    discount_value: Decimal | None,
) -> Decimal:
    """Calculate the total for a single line item (ex-GST)."""
    gross = (quantity * unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if discount_type and discount_value:
        if discount_type == "percentage":
            discount = (gross * discount_value / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        else:  # fixed
            discount = discount_value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        gross = max(gross - discount, Decimal("0"))
    return gross


def _calculate_invoice_totals(
    line_items_data: list[dict],
    gst_rate: Decimal,
    invoice_discount_type: str | None = None,
    invoice_discount_value: Decimal | None = None,
) -> dict:
    """Calculate subtotal, discount, GST, total for an invoice.

    Returns dict with subtotal, discount_amount, gst_amount, total, balance_due,
    and updated line_totals list.
    """
    line_totals: list[Decimal] = []
    subtotal = Decimal("0")
    gst_amount = Decimal("0")

    for item in line_items_data:
        lt = _calculate_line_total(
            item["quantity"],
            item["unit_price"],
            item.get("discount_type"),
            item.get("discount_value"),
        )
        line_totals.append(lt)
        subtotal += lt

    # Apply invoice-level discount to subtotal
    discount_amount = Decimal("0")
    if invoice_discount_type and invoice_discount_value:
        if invoice_discount_type == "percentage":
            discount_amount = (
                subtotal * invoice_discount_value / Decimal("100")
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            discount_amount = invoice_discount_value.quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
    discount_amount = min(discount_amount, subtotal)

    discounted_subtotal = subtotal - discount_amount

    # Calculate GST only on non-exempt items (proportional after discount)
    taxable_subtotal = Decimal("0")
    # Track GST-inclusive items separately for correct rounding
    inclusive_gst_total = Decimal("0")
    non_inclusive_taxable = Decimal("0")
    for i, item in enumerate(line_items_data):
        if not item.get("is_gst_exempt", False):
            if item.get("gst_inclusive") and item.get("inclusive_price"):
                # For GST-inclusive items, derive GST from the inclusive price
                # to avoid rounding errors. GST = inclusive - ex-GST
                incl_price = Decimal(str(item["inclusive_price"]))
                qty = Decimal(str(item["quantity"]))
                incl_total = (qty * incl_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                ex_gst = line_totals[i]
                inclusive_gst_total += incl_total - ex_gst
                taxable_subtotal += line_totals[i]
            else:
                non_inclusive_taxable += line_totals[i]
                taxable_subtotal += line_totals[i]

    if subtotal > 0 and taxable_subtotal > 0:
        # Proportion of discount applied to taxable items
        taxable_ratio = taxable_subtotal / subtotal
        discount_on_taxable = discount_amount * taxable_ratio

        # GST on non-inclusive taxable items (standard calculation)
        if non_inclusive_taxable > 0:
            non_incl_ratio = non_inclusive_taxable / taxable_subtotal if taxable_subtotal > 0 else Decimal("0")
            non_incl_after_discount = non_inclusive_taxable - (discount_on_taxable * non_incl_ratio)
            non_incl_after_discount = max(non_incl_after_discount, Decimal("0"))
            gst_amount += (non_incl_after_discount * gst_rate / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )

        # GST on inclusive items (already calculated from inclusive price)
        if inclusive_gst_total > 0:
            if discount_amount > 0 and taxable_subtotal > 0:
                incl_ratio = (taxable_subtotal - non_inclusive_taxable) / taxable_subtotal
                discount_on_inclusive = discount_on_taxable * incl_ratio
                # Scale down the inclusive GST proportionally
                incl_subtotal = taxable_subtotal - non_inclusive_taxable
                if incl_subtotal > 0:
                    scale = max(Decimal("0"), (incl_subtotal - discount_on_inclusive) / incl_subtotal)
                    gst_amount += (inclusive_gst_total * scale).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                else:
                    gst_amount += inclusive_gst_total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            else:
                gst_amount += inclusive_gst_total.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    total = (discounted_subtotal + gst_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return {
        "subtotal": subtotal.quantize(TWO_PLACES),
        "discount_amount": discount_amount.quantize(TWO_PLACES),
        "gst_amount": gst_amount,
        "total": total,
        "balance_due": total,
        "line_totals": line_totals,
    }


async def _get_next_invoice_number(
    db: AsyncSession,
    org_id: uuid.UUID,
    prefix: str,
) -> str:
    """Assign the next gap-free invoice number using SELECT ... FOR UPDATE.

    Uses a row-level lock on the ``invoice_sequences`` table to guarantee
    contiguous numbering even under concurrent requests.  The lock is held
    for the duration of the enclosing transaction, so two simultaneous
    ``issue_invoice`` calls for the same org will serialise correctly.

    Requirements: 23.1
    """
    # Acquire an exclusive row lock on the sequence for this org
    result = await db.execute(
        text(
            "SELECT id, last_number FROM invoice_sequences "
            "WHERE org_id = :org_id FOR UPDATE"
        ),
        {"org_id": str(org_id)},
    )
    row = result.first()

    if row is None:
        # First invoice for this org — create sequence row and lock it
        seq_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO invoice_sequences (id, org_id, last_number) "
                "VALUES (:id, :org_id, 1)"
            ),
            {"id": str(seq_id), "org_id": str(org_id)},
        )
        next_number = 1
    else:
        next_number = row.last_number + 1
        await db.execute(
            text(
                "UPDATE invoice_sequences SET last_number = :num "
                "WHERE id = :id"
            ),
            {"num": next_number, "id": str(row.id)},
        )

    return f"{prefix}{next_number:04d}"



async def _maybe_create_stripe_payment_intent(
    db: AsyncSession,
    invoice: "Invoice",
    org: "Organisation",
    *,
    base_url: str | None = None,
) -> None:
    """Auto-generate a Stripe PaymentIntent and payment token when applicable.

    Called after an invoice transitions to "issued" status.  Checks whether
    the invoice has ``payment_gateway == "stripe"`` in its ``invoice_data_json``
    and the org has a Connected Account.  On success, stores the PaymentIntent
    ID, client secret, and payment page URL on the invoice record.

    If PaymentIntent creation fails the invoice is still issued — the error
    is logged and the email will be sent without a payment link.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
    """
    inv_data = invoice.invoice_data_json or {}
    if inv_data.get("payment_gateway") != "stripe":
        return

    # Check org has a Connected Account
    stripe_account_id = getattr(org, "stripe_connect_account_id", None)
    if not stripe_account_id:
        logger.warning(
            "Invoice %s has payment_gateway=stripe but org %s has no "
            "stripe_connect_account_id — skipping PaymentIntent creation",
            invoice.id,
            org.id,
        )
        return

    try:
        from app.integrations.stripe_connect import create_payment_intent
        from app.integrations.stripe_billing import get_application_fee_percent
        from app.modules.payments.token_service import generate_payment_token
        from sqlalchemy.orm.attributes import flag_modified

        # Calculate amount in cents
        amount_cents = int(invoice.balance_due * 100)
        if amount_cents <= 0:
            logger.warning(
                "Invoice %s has balance_due <= 0 (%s) — skipping PaymentIntent",
                invoice.id,
                invoice.balance_due,
            )
            return

        # Calculate application fee if configured
        fee_percent = await get_application_fee_percent()
        application_fee_amount: int | None = None
        if fee_percent and fee_percent > 0:
            application_fee_amount = int(amount_cents * fee_percent / 100)

        # Build shipping/billing address from customer data for Afterpay eligibility
        shipping_data: dict | None = None
        try:
            customer_result = await db.execute(
                select(Customer).where(Customer.id == invoice.customer_id)
            )
            customer = customer_result.scalar_one_or_none()
            if customer:
                billing = customer.billing_address or {}
                customer_name = " ".join(
                    filter(None, [customer.first_name, customer.last_name])
                ) or customer.company_name or org.name
                # Only include shipping if we have at least a country
                if billing.get("country") or billing.get("street"):
                    # Stripe requires ISO 3166-1 alpha-2 country codes
                    raw_country = billing.get("country") or "NZ"
                    country_code = _to_iso_country_code(raw_country)
                    shipping_data = {
                        "name": customer_name,
                        "address": {
                            "line1": billing.get("street") or "N/A",
                            "city": billing.get("city") or "",
                            "state": billing.get("state") or "",
                            "postal_code": billing.get("postal_code") or "",
                            "country": country_code,
                        },
                    }
        except Exception:
            logger.debug("Could not fetch customer address for shipping — continuing without it")

        # Create PaymentIntent on Connected Account
        pi_result = await create_payment_intent(
            amount=amount_cents,
            currency=invoice.currency,
            invoice_id=str(invoice.id),
            stripe_account_id=stripe_account_id,
            application_fee_amount=application_fee_amount,
            shipping=shipping_data,
        )

        # Generate payment token + URL
        _token, payment_url = await generate_payment_token(
            db,
            org_id=invoice.org_id,
            invoice_id=invoice.id,
            base_url=base_url,
        )

        # Store on invoice record
        invoice.stripe_payment_intent_id = pi_result["payment_intent_id"]
        invoice.payment_page_url = payment_url

        # Store client_secret in invoice_data_json
        data_json = dict(invoice.invoice_data_json or {})
        data_json["stripe_client_secret"] = pi_result["client_secret"]
        invoice.invoice_data_json = data_json
        flag_modified(invoice, "invoice_data_json")

        await db.flush()
        await db.refresh(invoice)

        logger.info(
            "Created PaymentIntent %s for invoice %s (amount=%d cents, account=%s)",
            pi_result["payment_intent_id"],
            invoice.id,
            amount_cents,
            stripe_account_id,
        )

    except Exception:
        logger.exception(
            "Failed to create Stripe PaymentIntent for invoice %s — "
            "invoice will be issued without payment link",
            invoice.id,
        )


async def _resolve_vehicle_type(
    db: AsyncSession, vehicle_id: uuid.UUID, org_id: uuid.UUID
) -> tuple[str, Any] | None:
    """Determine whether *vehicle_id* refers to a global or org-scoped vehicle.

    Returns ``("global", vehicle_record)`` when found in ``global_vehicles``,
    ``("org", vehicle_record)`` when found in ``org_vehicles`` (scoped to
    *org_id*), or ``None`` when the ID does not exist in either table.
    """
    from app.modules.admin.models import GlobalVehicle
    from app.modules.vehicles.models import OrgVehicle

    # Check global_vehicles first
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    gv = result.scalar_one_or_none()
    if gv is not None:
        return ("global", gv)

    # Fall back to org_vehicles (scoped by org_id for multi-tenant safety)
    result = await db.execute(
        select(OrgVehicle).where(
            OrgVehicle.id == vehicle_id,
            OrgVehicle.org_id == org_id,
        )
    )
    ov = result.scalar_one_or_none()
    if ov is not None:
        return ("org", ov)

    return None


async def create_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_rego: str | None = None,
    vehicle_make: str | None = None,
    vehicle_model: str | None = None,
    vehicle_year: int | None = None,
    vehicle_odometer: int | None = None,
    global_vehicle_id: uuid.UUID | None = None,
    vehicle_service_due_date: date | None = None,
    vehicle_wof_expiry_date: date | None = None,
    vehicles: list[dict] | None = None,
    branch_id: uuid.UUID | None = None,
    status: str = "draft",
    line_items_data: list[dict] | None = None,
    fluid_usage_data: list[dict] | None = None,
    notes_internal: str | None = None,
    notes_customer: str | None = None,
    due_date: date | None = None,
    issue_date: date | None = None,
    payment_terms: str | None = None,
    discount_type: str | None = None,
    discount_value: Decimal | None = None,
    currency: str = "NZD",
    exchange_rate_to_nzd: Decimal | None = None,
    terms_and_conditions: str | None = None,
    payment_gateway: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new invoice (draft or issued).

    - Draft: no invoice number, fully editable
    - Issued: assigns sequential number with org prefix, locks structural edits
    
    If global_vehicle_id is provided, automatically links the customer to the vehicle
    if not already linked.

    Requirements: 17.1, 17.3, 17.4, 17.5, 17.6, 79.1, 79.2, 79.3, 79.4
    """
    from app.modules.vehicles.models import CustomerVehicle
    
    # Validate branch is active if provided (Req 2.2)
    if branch_id is not None:
        from app.core.branch_validation import validate_branch_active
        await validate_branch_active(db, branch_id)

    # Validate customer exists and belongs to org
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found in this organisation")

    # Get org settings for GST rate and invoice prefix
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    org_settings = org.settings or {}
    gst_rate = Decimal(str(org_settings.get("gst_percentage", 15)))
    invoice_prefix = org_settings.get("invoice_prefix", "INV-")

    # Gate vehicle fields behind vehicles module (Req 3.1–3.4)
    from app.core.modules import ModuleService
    module_svc = ModuleService(db)
    if not await module_svc.is_enabled(str(org_id), "vehicles"):
        vehicle_rego = None
        vehicle_make = None
        vehicle_model = None
        vehicle_year = None
        vehicle_odometer = None
        global_vehicle_id = None

    # Validate currency against org settings (Req 79.1, 79.2)
    validate_invoice_currency(currency, org_settings)

    # Default exchange rate: 1.0 for NZD, required for other currencies
    if currency == "NZD":
        exchange_rate = Decimal("1.000000")
    elif exchange_rate_to_nzd is not None:
        exchange_rate = exchange_rate_to_nzd.quantize(
            SIX_PLACES, rounding=ROUND_HALF_UP
        )
    else:
        raise ValueError(
            "exchange_rate_to_nzd is required for non-NZD currencies"
        )

    # Calculate totals
    items = line_items_data or []
    totals = _calculate_invoice_totals(items, gst_rate, discount_type, discount_value)

    # Determine invoice number
    invoice_number = None
    issue_date_val = issue_date or date.today()  # Always set issue date
    if status == "issued":
        invoice_number = await _get_next_invoice_number(db, org_id, invoice_prefix)

    # Calculate due date based on payment terms
    if due_date is None:
        default_due_days = int(org_settings.get("default_due_days", 0))
        if payment_terms == "due_on_receipt" or default_due_days == 0:
            due_date = issue_date_val
        else:
            terms_days_map = {
                "net_15": 15, "net_30": 30, "net_45": 45, "net_60": 60, "net_90": 90,
            }
            days = terms_days_map.get(payment_terms or "", default_due_days)
            from datetime import timedelta
            due_date = issue_date_val + timedelta(days=days)

    # Create invoice record
    invoice = Invoice(
        org_id=org_id,
        customer_id=customer_id,
        invoice_number=invoice_number,
        vehicle_rego=vehicle_rego,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=vehicle_year,
        vehicle_odometer=vehicle_odometer,
        branch_id=branch_id,
        status=status,
        issue_date=issue_date_val,
        due_date=due_date,
        currency=currency,
        exchange_rate_to_nzd=exchange_rate,
        subtotal=totals["subtotal"],
        discount_amount=totals["discount_amount"],
        discount_type=discount_type,
        discount_value=discount_value,
        gst_amount=totals["gst_amount"],
        total=totals["total"],
        amount_paid=Decimal("0"),
        balance_due=totals["balance_due"],
        notes_internal=notes_internal,
        notes_customer=notes_customer,
        invoice_data_json={
            k: v for k, v in {
                "payment_terms": payment_terms,
                "terms_and_conditions": terms_and_conditions,
                "payment_gateway": payment_gateway,
                "additional_vehicles": [
                    {
                        "id": str(v["id"]) if v.get("id") else "",
                        "rego": v.get("rego") or "",
                        "make": v.get("make"),
                        "model": v.get("model"),
                        "year": v.get("year"),
                        "odometer": v.get("odometer"),
                    }
                    for v in (vehicles or [])[1:]  # Skip first — it's the primary vehicle
                ] if vehicles and len(vehicles) > 1 else None,
            }.items() if v
        },
        created_by=user_id,
    )
    db.add(invoice)
    await db.flush()

    # Create line items
    created_line_items = []
    for i, item_data in enumerate(items):
        li = LineItem(
            invoice_id=invoice.id,
            org_id=org_id,
            item_type=item_data["item_type"],
            description=item_data["description"],
            catalogue_item_id=item_data.get("catalogue_item_id"),
            stock_item_id=item_data.get("stock_item_id"),
            part_number=item_data.get("part_number"),
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            hours=item_data.get("hours"),
            hourly_rate=item_data.get("hourly_rate"),
            discount_type=item_data.get("discount_type"),
            discount_value=item_data.get("discount_value"),
            is_gst_exempt=item_data.get("is_gst_exempt", False),
            warranty_note=item_data.get("warranty_note"),
            line_total=totals["line_totals"][i],
            sort_order=item_data.get("sort_order", i),
        )
        db.add(li)
        await db.flush()
        created_line_items.append(li)

    # Audit log — record creation with before/after values (Req 23.3)
    audit_action = "invoice.created_draft" if status == "draft" else "invoice.issued"

    # Stock handling: reserve for drafts, decrement for issued
    from app.modules.inventory.stock_items_service import (
        reserve_stock, decrement_stock_for_invoice_v2
    )
    from app.modules.inventory.service import decrement_stock_for_invoice
    for li_data, li in zip(items, created_line_items):
        stock_item_id = li_data.get("stock_item_id")
        if stock_item_id and li.quantity:
            sid = uuid.UUID(str(stock_item_id))
            qty = float(li.quantity)
            if status == "draft":
                try:
                    await reserve_stock(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=sid, quantity=qty,
                        reference_type="invoice_draft", reference_id=invoice.id,
                    )
                except Exception:
                    pass
            else:
                try:
                    await decrement_stock_for_invoice_v2(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=sid, quantity=qty, invoice_id=invoice.id,
                    )
                except Exception:
                    pass
        elif li.catalogue_item_id and li.quantity and status != "draft":
            try:
                await decrement_stock_for_invoice(
                    db, org_id=org_id, user_id=user_id,
                    part_id=li.catalogue_item_id,
                    quantity=int(li.quantity), invoice_id=invoice.id,
                )
            except Exception:
                pass

    # Process fluid/oil usage — reserve for drafts, decrement for issued
    fluid_usage_records = []
    if fluid_usage_data:
        for fu in fluid_usage_data:
            stock_item_id = fu.get("stock_item_id")
            litres = float(fu.get("litres", 0))
            if stock_item_id and litres > 0:
                sid = uuid.UUID(str(stock_item_id))
                if status == "draft":
                    try:
                        await reserve_stock(
                            db, org_id=org_id, user_id=user_id,
                            stock_item_id=sid, quantity=litres,
                            reference_type="invoice_draft_fluid", reference_id=invoice.id,
                        )
                    except Exception:
                        pass
                else:
                    try:
                        await decrement_stock_for_invoice_v2(
                            db, org_id=org_id, user_id=user_id,
                            stock_item_id=sid, quantity=litres, invoice_id=invoice.id,
                        )
                    except Exception:
                        pass
                fluid_usage_records.append({
                    "stock_item_id": str(stock_item_id),
                    "catalogue_item_id": str(fu.get("catalogue_item_id", "")),
                    "item_name": fu.get("item_name", ""),
                    "litres": litres,
                    "vehicle_id": str(global_vehicle_id) if global_vehicle_id else None,
                    "vehicle_rego": vehicle_rego,
                })
        # Always store fluid usage in invoice_data_json (even for drafts)
        if fluid_usage_records:
            data_json = dict(invoice.invoice_data_json or {})
            data_json["fluid_usage"] = fluid_usage_records
            invoice.invoice_data_json = data_json
            from sqlalchemy.orm.attributes import flag_modified as _fm_fluid
            _fm_fluid(invoice, "invoice_data_json")
            await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action=audit_action,
        entity_type="invoice",
        entity_id=invoice.id,
        before_value=None,
        after_value={
            "status": status,
            "invoice_number": invoice_number,
            "customer_id": str(customer_id),
            "total": str(totals["total"]),
            "subtotal": str(totals["subtotal"]),
            "gst_amount": str(totals["gst_amount"]),
            "currency": currency,
            "exchange_rate_to_nzd": str(exchange_rate),
            "line_item_count": len(items),
        },
        ip_address=ip_address,
    )

    # Resolve vehicle type (global vs org) before auto-link logic
    vehicle_type: str | None = None
    vehicle_record = None
    if global_vehicle_id:
        resolution = await _resolve_vehicle_type(db, global_vehicle_id, org_id)
        if resolution is not None:
            vehicle_type, vehicle_record = resolution

    # Auto-link customer to vehicle if global_vehicle_id provided and not already linked
    if global_vehicle_id and vehicle_type is not None:
        # Duplicate-link detection: query correct FK column based on vehicle type
        if vehicle_type == "org":
            existing_link = await db.execute(
                select(CustomerVehicle).where(
                    CustomerVehicle.org_id == org_id,
                    CustomerVehicle.customer_id == customer_id,
                    CustomerVehicle.org_vehicle_id == global_vehicle_id,
                )
            )
        else:
            existing_link = await db.execute(
                select(CustomerVehicle).where(
                    CustomerVehicle.org_id == org_id,
                    CustomerVehicle.customer_id == customer_id,
                    CustomerVehicle.global_vehicle_id == global_vehicle_id,
                )
            )
        if existing_link.scalar_one_or_none() is None:
            # Create the link using correct FK column based on vehicle type
            if vehicle_type == "org":
                cv = CustomerVehicle(
                    org_id=org_id,
                    customer_id=customer_id,
                    org_vehicle_id=global_vehicle_id,
                )
            else:
                cv = CustomerVehicle(
                    org_id=org_id,
                    customer_id=customer_id,
                    global_vehicle_id=global_vehicle_id,
                )
            db.add(cv)
            await db.flush()
            
            # Audit log for the link — use correct FK key in after_value
            if vehicle_type == "org":
                link_after_value = {
                    "customer_id": str(customer_id),
                    "org_vehicle_id": str(global_vehicle_id),
                    "linked_via": "invoice_creation",
                    "invoice_id": str(invoice.id),
                }
            else:
                link_after_value = {
                    "customer_id": str(customer_id),
                    "global_vehicle_id": str(global_vehicle_id),
                    "linked_via": "invoice_creation",
                    "invoice_id": str(invoice.id),
                }
            await write_audit_log(
                session=db,
                org_id=org_id,
                user_id=user_id,
                action="customer.vehicle_auto_linked",
                entity_type="customer_vehicle",
                entity_id=cv.id,
                before_value=None,
                after_value=link_after_value,
                ip_address=ip_address,
            )

    # Record odometer reading if provided and vehicle is linked
    if vehicle_odometer and vehicle_odometer > 0 and global_vehicle_id:
        if vehicle_type == "org":
            # Org vehicles: update odometer_last_recorded directly
            # (record_odometer_reading only supports global vehicles via odometer_readings FK)
            vehicle_record.odometer_last_recorded = vehicle_odometer
            await db.flush()
        else:
            # Global vehicles: use existing record_odometer_reading call
            from app.modules.vehicles.service import record_odometer_reading
            await record_odometer_reading(
                db,
                global_vehicle_id=global_vehicle_id,
                reading_km=vehicle_odometer,
                source="invoice",
                recorded_by=user_id,
                invoice_id=invoice.id,
                org_id=org_id,
                notes=f"Invoice {invoice_number or 'draft'}",
            )

    # Update service due date on the vehicle if provided
    if vehicle_service_due_date and global_vehicle_id:
        if vehicle_type == "org":
            # Org vehicles: update directly on the already-resolved record
            vehicle_record.service_due_date = vehicle_service_due_date
            await db.flush()
        else:
            # Global vehicles: existing query and update
            from app.modules.admin.models import GlobalVehicle
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
            )
            gv = gv_result.scalar_one_or_none()
            if gv:
                gv.service_due_date = vehicle_service_due_date

    # Update WOF expiry on the vehicle if provided
    if vehicle_wof_expiry_date and global_vehicle_id:
        if vehicle_type == "org":
            # Org vehicles: update directly on the already-resolved record
            vehicle_record.wof_expiry = vehicle_wof_expiry_date
            await db.flush()
        else:
            # Global vehicles: existing query and update
            from app.modules.admin.models import GlobalVehicle
            if not vehicle_service_due_date:
                gv_result = await db.execute(
                    select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
                )
                gv = gv_result.scalar_one_or_none()
            if gv:
                gv.wof_expiry = vehicle_wof_expiry_date

    # Auto-generate Stripe PaymentIntent when issuing with stripe gateway
    if status == "issued":
        await _maybe_create_stripe_payment_intent(db, invoice, org)

    await db.refresh(invoice)
    return _invoice_to_dict(invoice, created_line_items)


def _invoice_to_dict(invoice: Invoice, line_items: list[LineItem]) -> dict:
    """Convert Invoice + LineItems to a serialisable dict."""
    total_nzd = calculate_nzd_equivalent(invoice.total, invoice.exchange_rate_to_nzd)
    return {
        "id": invoice.id,
        "org_id": invoice.org_id,
        "invoice_number": invoice.invoice_number,
        "customer_id": invoice.customer_id,
        "vehicle_rego": invoice.vehicle_rego,
        "vehicle_make": invoice.vehicle_make,
        "vehicle_model": invoice.vehicle_model,
        "vehicle_year": invoice.vehicle_year,
        "vehicle_odometer": invoice.vehicle_odometer,
        "branch_id": invoice.branch_id,
        "status": invoice.status,
        "issue_date": invoice.issue_date,
        "due_date": invoice.due_date,
        "currency": invoice.currency,
        "exchange_rate_to_nzd": invoice.exchange_rate_to_nzd,
        "subtotal": invoice.subtotal,
        "discount_amount": invoice.discount_amount,
        "discount_type": invoice.discount_type,
        "discount_value": invoice.discount_value,
        "gst_amount": invoice.gst_amount,
        "total": invoice.total,
        "total_nzd": total_nzd,
        "amount_paid": invoice.amount_paid,
        "balance_due": invoice.balance_due,
        "notes_internal": invoice.notes_internal,
        "notes_customer": invoice.notes_customer,
        "void_reason": invoice.void_reason,
        "voided_at": invoice.voided_at,
        "voided_by": invoice.voided_by,
        "line_items": [_line_item_to_dict(li) for li in line_items],
        "created_by": invoice.created_by,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
        "payment_terms": (invoice.invoice_data_json or {}).get("payment_terms"),
        "terms_and_conditions": (invoice.invoice_data_json or {}).get("terms_and_conditions"),
        "additional_vehicles": (invoice.invoice_data_json or {}).get("additional_vehicles", []),
        "fluid_usage": (invoice.invoice_data_json or {}).get("fluid_usage", []),
        "payment_page_url": invoice.payment_page_url,
        "payment_gateway": (invoice.invoice_data_json or {}).get("payment_gateway"),
        "job_card_appendix_html": invoice.job_card_appendix_html,
    }


def _line_item_to_dict(li: LineItem) -> dict:
    """Convert a LineItem ORM instance to a serialisable dict."""
    return {
        "id": li.id,
        "item_type": li.item_type,
        "description": li.description,
        "catalogue_item_id": li.catalogue_item_id,
        "stock_item_id": li.stock_item_id,
        "part_number": li.part_number,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "hours": li.hours,
        "hourly_rate": li.hourly_rate,
        "discount_type": li.discount_type,
        "discount_value": li.discount_value,
        "is_gst_exempt": li.is_gst_exempt,
        "warranty_note": li.warranty_note,
        "line_total": li.line_total,
        "sort_order": li.sort_order,
    }


async def _recalculate_invoice(
    db: AsyncSession,
    invoice: Invoice,
    org_id: uuid.UUID,
) -> dict:
    """Recalculate totals for an invoice from its current line items.

    Returns the updated invoice dict.
    """
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    gst_rate = Decimal(str((org.settings or {}).get("gst_percentage", 15)))

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    items_data = [
        {
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "discount_type": li.discount_type,
            "discount_value": li.discount_value,
            "is_gst_exempt": li.is_gst_exempt,
        }
        for li in line_items
    ]

    totals = _calculate_invoice_totals(
        items_data, gst_rate, invoice.discount_type, invoice.discount_value
    )

    # Update each line item's line_total
    for i, li in enumerate(line_items):
        li.line_total = totals["line_totals"][i]

    invoice.subtotal = totals["subtotal"]
    invoice.discount_amount = totals["discount_amount"]
    invoice.gst_amount = totals["gst_amount"]
    invoice.total = totals["total"]
    invoice.balance_due = totals["total"] - invoice.amount_paid

    await db.flush()
    await db.refresh(invoice)
    return _invoice_to_dict(invoice, line_items)


async def add_line_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    item_data: dict,
    ip_address: str | None = None,
) -> dict:
    """Add a line item to an existing draft invoice.

    Supports catalogue pre-fill for service items and labour rate lookup.
    Recalculates invoice totals after adding.

    Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")
    if invoice.status != "draft":
        raise ValueError("Line items can only be modified on draft invoices")

    # Pre-fill from catalogue for service items
    catalogue_item_id = item_data.get("catalogue_item_id")
    if item_data["item_type"] == "service" and catalogue_item_id:
        cat_result = await db.execute(
            select(ServiceCatalogue).where(
                ServiceCatalogue.id == catalogue_item_id,
                ServiceCatalogue.org_id == org_id,
                ServiceCatalogue.is_active.is_(True),
            )
        )
        cat_item = cat_result.scalar_one_or_none()
        if cat_item:
            if not item_data.get("description"):
                item_data["description"] = cat_item.name
            if item_data.get("unit_price") is None:
                item_data["unit_price"] = cat_item.default_price

    # Pre-fill hourly rate for labour items
    if item_data["item_type"] == "labour" and item_data.get("labour_rate_id"):
        rate_result = await db.execute(
            select(LabourRate).where(
                LabourRate.id == item_data["labour_rate_id"],
                LabourRate.org_id == org_id,
                LabourRate.is_active.is_(True),
            )
        )
        rate = rate_result.scalar_one_or_none()
        if rate and item_data.get("hourly_rate") is None:
            item_data["hourly_rate"] = rate.hourly_rate
            if item_data.get("unit_price") is None:
                hours = item_data.get("hours") or Decimal("0")
                item_data["unit_price"] = rate.hourly_rate * hours

    # Determine sort order
    existing_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice_id)
        .order_by(LineItem.sort_order.desc())
    )
    existing = existing_result.scalars().first()
    next_sort = (existing.sort_order + 1) if existing else 0

    quantity = Decimal(str(item_data.get("quantity", 1)))
    unit_price = Decimal(str(item_data["unit_price"]))
    line_total = _calculate_line_total(
        quantity, unit_price,
        item_data.get("discount_type"), item_data.get("discount_value"),
    )

    li = LineItem(
        invoice_id=invoice_id,
        org_id=org_id,
        item_type=item_data["item_type"],
        description=item_data["description"],
        catalogue_item_id=catalogue_item_id,
        part_number=item_data.get("part_number"),
        quantity=quantity,
        unit_price=unit_price,
        hours=item_data.get("hours"),
        hourly_rate=item_data.get("hourly_rate"),
        discount_type=item_data.get("discount_type"),
        discount_value=item_data.get("discount_value"),
        is_gst_exempt=item_data.get("is_gst_exempt", False),
        warranty_note=item_data.get("warranty_note"),
        line_total=line_total,
        sort_order=item_data.get("sort_order", next_sort),
    )
    db.add(li)
    await db.flush()

    result = await _recalculate_invoice(db, invoice, org_id)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.line_item_added",
        entity_type="invoice",
        entity_id=invoice_id,
        after_value={
            "line_item_id": str(li.id),
            "item_type": item_data["item_type"],
            "description": item_data["description"],
            "total": str(result["total"]),
        },
        ip_address=ip_address,
    )

    return result


async def delete_line_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    line_item_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Remove a line item from a draft invoice and recalculate totals.

    Requirements: 18.1
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")
    if invoice.status != "draft":
        raise ValueError("Line items can only be modified on draft invoices")

    li_result = await db.execute(
        select(LineItem).where(
            LineItem.id == line_item_id,
            LineItem.invoice_id == invoice_id,
        )
    )
    li = li_result.scalar_one_or_none()
    if li is None:
        raise ValueError("Line item not found on this invoice")

    li_desc = li.description
    await db.delete(li)
    await db.flush()

    result = await _recalculate_invoice(db, invoice, org_id)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.line_item_removed",
        entity_type="invoice",
        entity_id=invoice_id,
        after_value={
            "line_item_id": str(line_item_id),
            "description": li_desc,
            "total": str(result["total"]),
        },
        ip_address=ip_address,
    )

    return result


# ---------------------------------------------------------------------------
# Invoice lifecycle (Task 10.3)
# Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7
# ---------------------------------------------------------------------------

# Valid status transitions (state machine)
VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"issued", "voided"},
    "issued": {"partially_paid", "paid", "overdue", "voided"},
    "partially_paid": {"partially_paid", "paid", "overdue", "voided"},
    "overdue": {"partially_paid", "paid", "voided"},
    "paid": {"voided"},
    # voided is a terminal state — no transitions out
    "voided": set(),
}


def _validate_transition(current: str, target: str) -> None:
    """Raise ValueError if the status transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid status transition: {current} → {target}"
        )


# ---------------------------------------------------------------------------
# NZ Tax Invoice Compliance (Task 10.8)
# Requirements: 80.1, 80.2, 80.3
# ---------------------------------------------------------------------------

NZ_HIGH_VALUE_THRESHOLD = Decimal("1000.00")


def validate_tax_invoice_compliance(
    *,
    invoice: Invoice,
    line_items: list[LineItem],
    org_name: str | None,
    gst_number: str | None,
) -> dict:
    """Validate that an invoice meets NZ IRD tax invoice requirements.

    If the org has no GST number configured, this is treated as a regular
    invoice (not a tax invoice) and GST-specific checks are skipped.

    Returns a dict with:
      - is_compliant: bool
      - is_high_value: bool (total > $1,000 NZD incl. GST)
      - issues: list of {field, message, requirement}
      - document_label: "Tax Invoice" or "Invoice"

    Requirements: 80.1, 80.2, 80.3
    """
    issues: list[dict] = []
    is_gst_registered = bool(gst_number)

    # Basic checks for all invoices
    if not org_name:
        issues.append({
            "field": "supplier_name",
            "message": "Supplier (organisation) name is required",
            "requirement": "80.1",
        })

    if invoice.issue_date is None:
        issues.append({
            "field": "issue_date",
            "message": "Invoice date is required",
            "requirement": "80.1",
        })

    if not line_items:
        issues.append({
            "field": "line_items",
            "message": "At least one line item with a description of goods/services is required",
            "requirement": "80.1",
        })
    else:
        for idx, li in enumerate(line_items):
            if not li.description or not li.description.strip():
                issues.append({
                    "field": f"line_items[{idx}].description",
                    "message": f"Line item {idx + 1} must have a description of goods/services",
                    "requirement": "80.1",
                })

    if invoice.total is None:
        issues.append({
            "field": "total",
            "message": "Total amount is required",
            "requirement": "80.1",
        })

    # GST-specific checks only when org is GST-registered
    if is_gst_registered:
        if invoice.gst_amount is None:
            issues.append({
                "field": "gst_amount",
                "message": "GST amount is required on tax invoices",
                "requirement": "80.1",
            })

    # Req 80.2 — high-value invoices (>$1,000 NZD incl. GST) need buyer details
    is_high_value = (invoice.total or Decimal("0")) > NZ_HIGH_VALUE_THRESHOLD

    if is_high_value and is_gst_registered:
        customer = getattr(invoice, "_compliance_customer", None)
        customer_name = None
        customer_address = None
        if customer is not None:
            customer_name = f"{customer.first_name} {customer.last_name}".strip()
            customer_address = customer.address

        if not customer_name:
            issues.append({
                "field": "customer_name",
                "message": "Buyer name is required for invoices over $1,000 NZD (incl. GST)",
                "requirement": "80.2",
            })
        if not customer_address:
            issues.append({
                "field": "customer_address",
                "message": "Buyer address is required for invoices over $1,000 NZD (incl. GST)",
                "requirement": "80.2",
            })

    return {
        "is_compliant": len(issues) == 0,
        "is_high_value": is_high_value,
        "issues": issues,
        "document_label": "Tax Invoice" if is_gst_registered else "Invoice",
    }



def get_line_item_tax_details(
    line_items: list[LineItem],
    gst_percentage: Decimal,
) -> list[dict]:
    """Return tax detail for each line item, distinguishing taxable vs exempt.

    Requirements: 80.3
    """
    details = []
    for li in line_items:
        if li.is_gst_exempt:
            gst_amt = Decimal("0.00")
            tax_label = "GST Exempt"
        else:
            gst_amt = (li.line_total * gst_percentage / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            tax_label = f"GST {gst_percentage}%"

        details.append({
            "line_item_id": li.id,
            "description": li.description,
            "is_gst_exempt": li.is_gst_exempt,
            "line_total": li.line_total,
            "gst_amount": gst_amt,
            "tax_label": tax_label,
        })
    return details


async def get_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> dict:
    """Retrieve a single invoice by ID within an organisation.

    Requirements: 19.1
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    result = _invoice_to_dict(invoice, line_items)

    # Include organisation details for invoice preview
    from app.modules.admin.models import Organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org:
        settings = org.settings or {}
        org_tz = getattr(org, "timezone", None) or "UTC"
        result["org_timezone"] = org_tz
        result["org_name"] = org.name
        result["org_address"] = ", ".join(filter(None, [
            settings.get("address_unit"),
            settings.get("address_street"),
            settings.get("address_city"),
            settings.get("address_state"),
            settings.get("address_postcode"),
            settings.get("address_country"),
        ])) or settings.get("address") or settings.get("business_address")
        result["org_address_unit"] = settings.get("address_unit")
        result["org_address_street"] = settings.get("address_street")
        result["org_address_city"] = settings.get("address_city")
        result["org_address_state"] = settings.get("address_state")
        result["org_address_country"] = settings.get("address_country")
        result["org_address_postcode"] = settings.get("address_postcode")
        result["org_phone"] = settings.get("phone") or settings.get("business_phone")
        result["org_email"] = settings.get("email") or settings.get("business_email")
        result["org_logo_url"] = settings.get("logo_url")
        result["org_gst_number"] = settings.get("gst_number") or settings.get("tax_number")
        result["org_website"] = settings.get("website")
        result["invoice_template_id"] = settings.get("invoice_template_id")
        result["invoice_template_colours"] = settings.get("invoice_template_colours")

    # Include customer details
    if invoice.customer_id:
        cust_result = await db.execute(
            select(Customer).where(Customer.id == invoice.customer_id)
        )
        customer = cust_result.scalar_one_or_none()
        if customer:
            # Build address: prefer plain text `address`, fall back to structured billing_address
            cust_address = getattr(customer, "address", None)
            if not cust_address:
                ba = getattr(customer, "billing_address", None) or {}
                if isinstance(ba, dict) and any(ba.values()):
                    cust_address = ", ".join(filter(None, [
                        ba.get("street"),
                        ba.get("city"),
                        ba.get("state"),
                        ba.get("postal_code"),
                        ba.get("country"),
                    ]))
            result["customer"] = {
                "id": str(customer.id),
                "first_name": customer.first_name,
                "last_name": customer.last_name,
                "email": customer.email,
                "phone": customer.phone or customer.mobile_phone,
                "address": cust_address or None,
                "company_name": getattr(customer, "company_name", None),
                "display_name": getattr(customer, "display_name", None),
            }

    # Include vehicle details from global vehicle table (rego, make, model, year, odometer, WOF expiry)
    # Falls back to org_vehicles if not found in global_vehicles
    if invoice.vehicle_rego:
        from app.modules.admin.models import GlobalVehicle
        gv_result = await db.execute(
            select(GlobalVehicle).where(
                func.upper(GlobalVehicle.rego) == invoice.vehicle_rego.upper()
            )
        )
        gv = gv_result.scalar_one_or_none()
        if gv:
            result["vehicle"] = {
                "rego": gv.rego,
                "make": gv.make,
                "model": gv.model,
                "year": gv.year,
                "wof_expiry": gv.wof_expiry.isoformat() if getattr(gv, "wof_expiry", None) else None,
                "odometer": getattr(gv, "odometer_last_recorded", None),
                "service_due_date": gv.service_due_date.isoformat() if getattr(gv, "service_due_date", None) else None,
            }
        else:
            # Fallback: check org_vehicles for org-scoped vehicles
            from app.modules.vehicles.models import OrgVehicle
            ov_result = await db.execute(
                select(OrgVehicle).where(
                    OrgVehicle.org_id == invoice.org_id,
                    func.upper(OrgVehicle.rego) == invoice.vehicle_rego.upper(),
                )
            )
            ov = ov_result.scalar_one_or_none()
            if ov:
                result["vehicle"] = {
                    "rego": ov.rego,
                    "make": ov.make,
                    "model": ov.model,
                    "year": ov.year,
                    "wof_expiry": ov.wof_expiry.isoformat() if getattr(ov, "wof_expiry", None) else None,
                    "odometer": getattr(ov, "odometer_last_recorded", None),
                    "service_due_date": ov.service_due_date.isoformat() if getattr(ov, "service_due_date", None) else None,
                }
            elif invoice.vehicle_make or invoice.vehicle_model or invoice.vehicle_year:
                # Last resort: use the flat fields stored on the invoice itself
                result["vehicle"] = {
                    "rego": invoice.vehicle_rego,
                    "make": invoice.vehicle_make,
                    "model": invoice.vehicle_model,
                    "year": invoice.vehicle_year,
                    "wof_expiry": None,
                    "odometer": invoice.vehicle_odometer,
                    "service_due_date": None,
                }

    # Enrich additional vehicles from invoice_data_json with GlobalVehicle data
    additional_vehicles_raw = (invoice.invoice_data_json or {}).get("additional_vehicles", [])
    if additional_vehicles_raw:
        from app.modules.admin.models import GlobalVehicle
        enriched_vehicles = []
        for av in additional_vehicles_raw:
            av_rego = av.get("rego", "")
            if av_rego:
                av_gv_result = await db.execute(
                    select(GlobalVehicle).where(
                        func.upper(GlobalVehicle.rego) == av_rego.upper()
                    )
                )
                av_gv = av_gv_result.scalar_one_or_none()
                if av_gv:
                    enriched_vehicles.append({
                        "rego": av_gv.rego,
                        "make": av_gv.make,
                        "model": av_gv.model,
                        "year": av_gv.year,
                        "wof_expiry": av_gv.wof_expiry.isoformat() if getattr(av_gv, "wof_expiry", None) else None,
                        "odometer": getattr(av_gv, "odometer_last_recorded", None),
                    })
                else:
                    enriched_vehicles.append(av)
            else:
                enriched_vehicles.append(av)
        result["additional_vehicles"] = enriched_vehicles

    # Include payments
    pay_result = await db.execute(
        select(Payment).where(Payment.invoice_id == invoice.id).order_by(Payment.created_at)
    )
    payments = list(pay_result.scalars().all())

    # Resolve recorded_by UUIDs to user emails
    recorder_ids = {p.recorded_by for p in payments if hasattr(p, "recorded_by") and p.recorded_by}
    recorder_map: dict[uuid.UUID, str] = {}
    if recorder_ids:
        from app.modules.auth.models import User
        user_result = await db.execute(
            select(User.id, User.email).where(User.id.in_(recorder_ids))
        )
        for uid, uemail in user_result.all():
            recorder_map[uid] = uemail

    # Org timezone for converting UTC timestamps to local time
    from app.core.timezone_utils import to_org_timezone
    org_tz = result.get("org_timezone", "UTC")

    # Convert invoice-level UTC timestamps to org-local ISO strings
    if result.get("created_at") and hasattr(result["created_at"], "isoformat"):
        local_dt = to_org_timezone(result["created_at"], org_tz)
        result["created_at_local"] = local_dt.isoformat() if local_dt else None
    if result.get("voided_at") and hasattr(result["voided_at"], "isoformat"):
        local_dt = to_org_timezone(result["voided_at"], org_tz)
        result["voided_at_local"] = local_dt.isoformat() if local_dt else None

    result["payments"] = [
        {
            "id": str(p.id),
            "date": (
                to_org_timezone(
                    p.payment_date if hasattr(p, "payment_date") and p.payment_date else p.created_at,
                    org_tz,
                ).isoformat()
                if (hasattr(p, "payment_date") and p.payment_date) or p.created_at
                else None
            ),
            "amount": float(p.amount),
            "method": p.method if hasattr(p, "method") else "cash",
            "recorded_by": recorder_map.get(p.recorded_by, str(p.recorded_by)) if hasattr(p, "recorded_by") and p.recorded_by else "",
            "note": getattr(p, "note", None) or getattr(p, "notes", None),
            "is_refund": bool(getattr(p, "is_refund", False)),
            "refund_note": getattr(p, "refund_note", None),
        }
        for p in payments
    ]

    # Include credit notes
    cn_result = await db.execute(
        select(CreditNote).where(CreditNote.invoice_id == invoice.id).order_by(CreditNote.created_at)
    )
    credit_notes = list(cn_result.scalars().all())
    result["credit_notes"] = [
        {
            "id": str(cn.id),
            "reference_number": cn.credit_note_number if hasattr(cn, "credit_note_number") else str(cn.id)[:8],
            "amount": float(cn.amount),
            "reason": cn.reason if hasattr(cn, "reason") else "",
            "created_at": to_org_timezone(cn.created_at, org_tz).isoformat() if cn.created_at else None,
        }
        for cn in credit_notes
    ]

    return result


async def issue_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Transition a draft invoice to issued status.

    - Assigns a sequential invoice number with the org prefix
    - Sets issue_date to today
    - Calculates due_date from org default_due_days if not already set
    - Locks structural edits (line items, pricing)

    Requirements: 19.2, 19.3
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    _validate_transition(invoice.status, "issued")

    # Get org settings
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    org_settings = org.settings or {}
    invoice_prefix = org_settings.get("invoice_prefix", "INV-")

    # Assign sequential number
    invoice_number = await _get_next_invoice_number(db, org_id, invoice_prefix)
    invoice.invoice_number = invoice_number
    invoice.status = "issued"
    invoice.issue_date = date.today()

    # Set due date if not already set
    before_due_date = invoice.due_date
    if invoice.due_date is None:
        default_due_days = int(org_settings.get("default_due_days", 30))
        from datetime import timedelta
        invoice.due_date = date.today() + timedelta(days=default_due_days)

    await db.flush()
    await db.refresh(invoice)

    # Audit log — record issuance with before/after values (Req 23.3)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.issued",
        entity_type="invoice",
        entity_id=invoice.id,
        before_value={
            "status": "draft",
            "invoice_number": None,
            "issue_date": None,
            "due_date": str(before_due_date) if before_due_date else None,
        },
        after_value={
            "status": "issued",
            "invoice_number": invoice_number,
            "issue_date": str(invoice.issue_date),
            "due_date": str(invoice.due_date),
            "total": str(invoice.total),
        },
        ip_address=ip_address,
    )

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    # NZ Tax Invoice Compliance validation (Req 80.1, 80.2, 80.3)
    gst_number = org_settings.get("gst_number")

    # Fetch customer for high-value invoice buyer details check (Req 80.2)
    cust_result = await db.execute(
        select(Customer).where(Customer.id == invoice.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    invoice._compliance_customer = customer

    compliance = validate_tax_invoice_compliance(
        invoice=invoice,
        line_items=line_items,
        org_name=org.name,
        gst_number=gst_number,
    )

    if not compliance["is_compliant"]:
        field_msgs = "; ".join(
            f"{i['field']}: {i['message']}" for i in compliance["issues"]
        )
        raise ValueError(
            f"Invoice does not meet NZ tax invoice requirements: {field_msgs}"
        )

    gst_pct = Decimal(str(org_settings.get("gst_percentage", 15)))
    tax_details = get_line_item_tax_details(line_items, gst_pct)

    # Convert reservations to actual sales when issuing a draft
    from app.modules.inventory.stock_items_service import convert_reservation_to_sale
    from app.modules.inventory.service import decrement_stock_for_invoice
    for li in line_items:
        if li.stock_item_id and li.quantity:
            try:
                await convert_reservation_to_sale(
                    db, org_id=org_id, user_id=user_id,
                    stock_item_id=li.stock_item_id,
                    quantity=float(li.quantity), invoice_id=invoice.id,
                )
            except Exception:
                pass
        elif li.catalogue_item_id and li.quantity:
            try:
                await decrement_stock_for_invoice(
                    db, org_id=org_id, user_id=user_id,
                    part_id=li.catalogue_item_id,
                    quantity=int(li.quantity), invoice_id=invoice.id,
                )
            except Exception:
                pass

    # Convert fluid reservations to sales
    fluid_usage = (invoice.invoice_data_json or {}).get("fluid_usage", [])
    if fluid_usage:
        for fu in fluid_usage:
            fu_stock_id = fu.get("stock_item_id")
            fu_litres = float(fu.get("litres", 0))
            if fu_stock_id and fu_litres > 0:
                try:
                    await convert_reservation_to_sale(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=uuid.UUID(str(fu_stock_id)),
                        quantity=fu_litres, invoice_id=invoice.id,
                    )
                except Exception:
                    pass

    # Auto-post journal entry for the issued invoice (Req 4.1, 4.6, 4.7, 4.8)
    try:
        from app.modules.ledger.auto_poster import auto_post_invoice
        await auto_post_invoice(db, invoice, user_id)
    except Exception as exc:
        logger.warning(
            "Auto-post failed for invoice %s: %s", invoice.id, exc
        )

    # Auto-generate Stripe PaymentIntent when issuing with stripe gateway
    await _maybe_create_stripe_payment_intent(db, invoice, org)

    result = _invoice_to_dict(invoice, line_items)
    result["tax_compliance"] = compliance
    result["line_item_tax_details"] = tax_details

    return result


async def void_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    reason: str,
    ip_address: str | None = None,
) -> dict:
    """Void any non-voided invoice.

    - Retains the invoice number in sequence
    - Records void reason and timestamp
    - Writes to audit log
    - Voided invoices are excluded from revenue reporting

    Requirements: 19.7
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    _validate_transition(invoice.status, "voided")

    previous_status = invoice.status
    invoice.status = "voided"
    invoice.void_reason = reason
    invoice.voided_at = datetime.now(timezone.utc)
    invoice.voided_by = user_id

    await db.flush()

    # Audit log — record voiding with before/after values (Req 23.3)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.voided",
        entity_type="invoice",
        entity_id=invoice.id,
        before_value={
            "status": previous_status,
            "invoice_number": invoice.invoice_number,
            "total": str(invoice.total),
            "balance_due": str(invoice.balance_due),
        },
        after_value={
            "status": "voided",
            "invoice_number": invoice.invoice_number,
            "void_reason": reason,
            "voided_at": str(invoice.voided_at),
            "voided_by": str(user_id),
        },
        ip_address=ip_address,
    )

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    await db.refresh(invoice)
    return _invoice_to_dict(invoice, line_items)


async def update_invoice_notes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    notes_internal: str | None = None,
    notes_customer: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update notes on an invoice (allowed even on issued invoices).

    Notes are the only field editable after issuing.

    Requirements: 19.3
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    if invoice.status == "voided":
        raise ValueError("Cannot update notes on a voided invoice")

    before = {
        "notes_internal": invoice.notes_internal,
        "notes_customer": invoice.notes_customer,
    }

    if notes_internal is not None:
        invoice.notes_internal = notes_internal
    if notes_customer is not None:
        invoice.notes_customer = notes_customer

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.notes_updated",
        entity_type="invoice",
        entity_id=invoice.id,
        before_value=before,
        after_value={
            "notes_internal": invoice.notes_internal,
            "notes_customer": invoice.notes_customer,
        },
        ip_address=ip_address,
    )

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    await db.refresh(invoice)
    return _invoice_to_dict(invoice, line_items)


# ---------------------------------------------------------------------------
# Invoice update with number immutability (Task 10.4)
# Requirements: 23.2, 23.3
# ---------------------------------------------------------------------------


async def update_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    updates: dict,
    ip_address: str | None = None,
) -> dict:
    """Update a draft invoice's editable fields.

    Prevents modification of assigned invoice numbers (Req 23.2).
    Only draft invoices allow structural edits; issued invoices only
    allow notes updates via ``update_invoice_notes``.

    Requirements: 23.2, 23.3
    """
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # GST lock check — reject edits on locked invoices (Req 14.2)
    try:
        if getattr(invoice, "is_gst_locked", False):
            raise ValueError(
                "GST_LOCKED: This invoice is locked because its GST filing period has been filed. "
                "Edits are not permitted on GST-locked invoices."
            )
    except Exception as exc:
        if "GST_LOCKED" in str(exc):
            raise
        pass  # Column may not exist yet — ignore

    # Req 23.2 — invoice_number is immutable once assigned
    if "invoice_number" in updates:
        if invoice.invoice_number is not None:
            raise ValueError(
                "Invoice number cannot be modified once assigned"
            )
        # Even for drafts, don't allow manual number assignment
        raise ValueError(
            "Invoice numbers are system-assigned and cannot be set manually"
        )

    # Only drafts allow structural edits
    if invoice.status != "draft":
        raise ValueError(
            "Only draft invoices can be updated. Use notes endpoint for issued invoices."
        )

    # Capture before state for audit log
    before_value = {
        "customer_id": str(invoice.customer_id),
        "vehicle_rego": invoice.vehicle_rego,
        "notes_internal": invoice.notes_internal,
        "notes_customer": invoice.notes_customer,
        "due_date": str(invoice.due_date) if invoice.due_date else None,
    }

    # Apply allowed field updates (direct model columns)
    allowed_fields = {
        "customer_id", "vehicle_rego", "vehicle_make", "vehicle_model",
        "vehicle_year", "vehicle_odometer", "branch_id",
        "notes_internal", "notes_customer", "due_date", "issue_date",
        "discount_type", "discount_value", "currency",
    }
    # Fields stored in invoice_data_json (no direct column)
    json_fields = {
        "payment_terms", "terms_and_conditions",
        "shipping_charges", "adjustment", "payment_gateway",
    }
    applied = {}
    for field, value in updates.items():
        if field in allowed_fields:
            setattr(invoice, field, value)
            applied[field] = str(value) if value is not None else None

    # Store JSON-backed fields in invoice_data_json
    json_updates = {k: updates[k] for k in json_fields if k in updates}
    if json_updates:
        inv_json = dict(invoice.invoice_data_json or {})
        for k, v in json_updates.items():
            if v is not None:
                inv_json[k] = str(v) if isinstance(v, Decimal) else v
            else:
                inv_json.pop(k, None)
            applied[k] = str(v) if v is not None else None
        invoice.invoice_data_json = inv_json
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(invoice, "invoice_data_json")

    # Handle line_items — replace all line items if provided
    if "line_items" in updates and updates["line_items"] is not None:
        new_items = updates["line_items"]

        # Release old reservations before deleting line items
        from app.modules.inventory.stock_items_service import release_reservation, reserve_stock
        old_li_result = await db.execute(
            select(LineItem).where(LineItem.invoice_id == invoice.id)
        )
        for old_li in old_li_result.scalars().all():
            if old_li.stock_item_id and old_li.quantity:
                try:
                    await release_reservation(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=old_li.stock_item_id,
                        quantity=float(old_li.quantity),
                        reference_type="invoice_draft", reference_id=invoice.id,
                    )
                except Exception:
                    pass

        # Delete existing line items
        await db.execute(
            delete(LineItem).where(LineItem.invoice_id == invoice.id)
        )
        await db.flush()

        org_result_li = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org_li = org_result_li.scalar_one_or_none()
        gst_rate_li = Decimal(str((org_li.settings or {}).get("gst_percentage", 15))) if org_li else Decimal("15")

        for idx, item_data in enumerate(new_items):
            qty = Decimal(str(item_data.get("quantity", 1)))
            rate = Decimal(str(item_data.get("rate") or item_data.get("unit_price", 0)))
            amount = Decimal(str(item_data.get("amount", 0))) or (qty * rate)
            tax_rate = Decimal(str(item_data.get("tax_rate", gst_rate_li)))
            is_exempt = tax_rate == 0

            li = LineItem(
                invoice_id=invoice.id,
                org_id=org_id,
                item_type=item_data.get("item_type", "service"),
                description=item_data.get("description", ""),
                catalogue_item_id=item_data.get("catalogue_item_id"),
                stock_item_id=item_data.get("stock_item_id"),
                quantity=qty,
                unit_price=rate,
                is_gst_exempt=is_exempt,
                line_total=amount,
                sort_order=idx,
            )
            db.add(li)
        await db.flush()

        # Reserve stock for new line items (draft only)
        for item_data in new_items:
            sid = item_data.get("stock_item_id")
            qty_val = float(item_data.get("quantity", 0))
            if sid and qty_val > 0:
                try:
                    await reserve_stock(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=uuid.UUID(str(sid)) if not isinstance(sid, uuid.UUID) else sid,
                        quantity=qty_val,
                        reference_type="invoice_draft", reference_id=invoice.id,
                    )
                except Exception:
                    pass

        applied["line_items"] = f"{len(new_items)} items"

    # Handle vehicles array — store additional vehicles in invoice_data_json
    if "vehicles" in updates:
        vehicles_data = updates["vehicles"]
        inv_json = dict(invoice.invoice_data_json or {})
        if vehicles_data and len(vehicles_data) > 1:
            inv_json["additional_vehicles"] = [
                {
                    "id": str(v["id"]) if v.get("id") else "",
                    "rego": v.get("rego") or "",
                    "make": v.get("make"),
                    "model": v.get("model"),
                    "year": v.get("year"),
                    "odometer": v.get("odometer"),
                }
                for v in vehicles_data[1:]
            ]
        else:
            inv_json.pop("additional_vehicles", None)
        invoice.invoice_data_json = inv_json
        from sqlalchemy.orm.attributes import flag_modified as _flag_modified
        _flag_modified(invoice, "invoice_data_json")

    # Handle fluid_usage — release old reservations, store new data, reserve new
    if "fluid_usage" in updates and updates["fluid_usage"] is not None:
        from app.modules.inventory.stock_items_service import release_reservation as _rel_res, reserve_stock as _res_stock

        # Release old fluid reservations
        old_fluid = (invoice.invoice_data_json or {}).get("fluid_usage", [])
        for ofu in old_fluid:
            ofu_sid = ofu.get("stock_item_id")
            ofu_litres = float(ofu.get("litres", 0))
            if ofu_sid and ofu_litres > 0:
                try:
                    await _rel_res(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=uuid.UUID(str(ofu_sid)), quantity=ofu_litres,
                        reference_type="invoice_draft_fluid", reference_id=invoice.id,
                    )
                except Exception:
                    pass

        fluid_data = updates["fluid_usage"]
        inv_json = dict(invoice.invoice_data_json or {})
        fluid_records = []
        for fu in fluid_data:
            stock_item_id = fu.get("stock_item_id")
            litres = float(fu.get("litres", 0))
            if stock_item_id and litres > 0:
                # Reserve new fluid
                sid = uuid.UUID(str(stock_item_id)) if not isinstance(stock_item_id, uuid.UUID) else stock_item_id
                try:
                    await _res_stock(
                        db, org_id=org_id, user_id=user_id,
                        stock_item_id=sid, quantity=litres,
                        reference_type="invoice_draft_fluid", reference_id=invoice.id,
                    )
                except Exception:
                    pass
                fluid_records.append({
                    "stock_item_id": str(stock_item_id),
                    "catalogue_item_id": str(fu.get("catalogue_item_id", "")),
                    "item_name": fu.get("item_name", ""),
                    "litres": litres,
                    "vehicle_id": str(updates.get("global_vehicle_id", "")) if updates.get("global_vehicle_id") else None,
                    "vehicle_rego": updates.get("vehicle_rego") or invoice.vehicle_rego,
                })
        if fluid_records:
            inv_json["fluid_usage"] = fluid_records
        else:
            inv_json.pop("fluid_usage", None)
        invoice.invoice_data_json = inv_json
        from sqlalchemy.orm.attributes import flag_modified as _flag_modified2
        _flag_modified2(invoice, "invoice_data_json")

    await db.flush()

    # Resolve vehicle type before metadata updates (Task 5.1)
    vehicle_service_due_date = updates.get("vehicle_service_due_date")
    vehicle_wof_expiry_date = updates.get("vehicle_wof_expiry_date")
    global_vehicle_id = updates.get("global_vehicle_id")
    vehicle_type = None
    vehicle_record = None
    if global_vehicle_id and (vehicle_service_due_date or vehicle_wof_expiry_date):
        resolution = await _resolve_vehicle_type(db, global_vehicle_id, org_id)
        if resolution is not None:
            vehicle_type, vehicle_record = resolution

    # Update service due date on the vehicle if provided (Task 5.2)
    if vehicle_service_due_date and global_vehicle_id and vehicle_type is not None:
        if vehicle_type == "org":
            # Org vehicles: update directly on the already-resolved record
            vehicle_record.service_due_date = vehicle_service_due_date
            await db.flush()
        else:
            # Global vehicles: existing query and update
            from app.modules.admin.models import GlobalVehicle
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
            )
            gv = gv_result.scalar_one_or_none()
            if gv:
                gv.service_due_date = vehicle_service_due_date

    # Update WOF expiry on the vehicle if provided (Task 5.3)
    if vehicle_wof_expiry_date and global_vehicle_id and vehicle_type is not None:
        if vehicle_type == "org":
            # Org vehicles: update directly on the already-resolved record
            vehicle_record.wof_expiry = vehicle_wof_expiry_date
            await db.flush()
        else:
            # Global vehicles: existing query and update
            from app.modules.admin.models import GlobalVehicle
            if not vehicle_service_due_date:
                gv_result = await db.execute(
                    select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
                )
                gv = gv_result.scalar_one_or_none()
            if gv:
                gv.wof_expiry = vehicle_wof_expiry_date

    # Recalculate totals if discount, line items, or financial fields changed
    needs_recalc = (
        "discount_type" in applied
        or "discount_value" in applied
        or "shipping_charges" in applied
        or "adjustment" in applied
        or "line_items" in applied
    )
    if needs_recalc:
        await _recalculate_invoice(db, invoice, org_id)

    # Audit log with before/after values (Req 23.3)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.updated",
        entity_type="invoice",
        entity_id=invoice.id,
        before_value=before_value,
        after_value=applied,
        ip_address=ip_address,
    )

    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    await db.refresh(invoice)
    return _invoice_to_dict(invoice, line_items)


async def mark_invoices_overdue(
    db: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> int:
    """Mark issued/partially_paid invoices as overdue when due date has passed.

    This is intended to be called by a scheduled task (Celery Beat) at midnight.
    Returns the number of invoices updated.

    Requirements: 19.6
    """
    check_date = as_of_date or date.today()

    result = await db.execute(
        select(Invoice).where(
            Invoice.status.in_(["issued", "partially_paid"]),
            Invoice.due_date.isnot(None),
            Invoice.due_date < check_date,
            Invoice.balance_due > 0,
        )
    )
    invoices = list(result.scalars().all())

    count = 0
    for invoice in invoices:
        invoice.status = "overdue"
        count += 1

    if count > 0:
        await db.flush()

    return count


# ---------------------------------------------------------------------------
# Credit note functions (Task 10.5)
# Requirements: 20.1, 20.2, 20.3, 20.4
# ---------------------------------------------------------------------------


async def _get_next_credit_note_number(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> str:
    """Assign the next gap-free credit note number using SELECT ... FOR UPDATE.

    Uses the same row-level locking pattern as invoice numbering to guarantee
    contiguous CN-prefixed numbers.

    Requirements: 20.1
    """
    result = await db.execute(
        text(
            "SELECT id, last_number FROM credit_note_sequences "
            "WHERE org_id = :org_id FOR UPDATE"
        ),
        {"org_id": str(org_id)},
    )
    row = result.first()

    if row is None:
        seq_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO credit_note_sequences (id, org_id, last_number) "
                "VALUES (:id, :org_id, 1)"
            ),
            {"id": str(seq_id), "org_id": str(org_id)},
        )
        next_number = 1
    else:
        next_number = row.last_number + 1
        await db.execute(
            text(
                "UPDATE credit_note_sequences SET last_number = :num "
                "WHERE id = :id"
            ),
            {"num": next_number, "id": str(row.id)},
        )

    return f"CN-{next_number:04d}"


def _credit_note_to_dict(cn: CreditNote) -> dict:
    """Convert a CreditNote ORM instance to a serialisable dict."""
    return {
        "id": cn.id,
        "org_id": cn.org_id,
        "invoice_id": cn.invoice_id,
        "credit_note_number": cn.credit_note_number,
        "amount": cn.amount,
        "reason": cn.reason,
        "items": cn.items if cn.items else [],
        "stripe_refund_id": cn.stripe_refund_id,
        "created_by": cn.created_by,
        "created_at": cn.created_at,
    }


async def create_credit_note(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal,
    reason: str,
    items: list[dict],
    process_stripe_refund: bool = False,
    ip_address: str | None = None,
) -> dict:
    """Create a credit note against an issued/paid invoice.

    - Validates the invoice exists and is in a creditable status (issued,
      partially_paid, paid, overdue).
    - Validates the credit amount does not exceed the remaining balance_due
      plus amount_paid (i.e. cannot credit more than the invoice total minus
      already-credited amounts).
    - Assigns a gap-free CN-prefixed number.
    - Updates the invoice balance_due.
    - Checks for Stripe payments and flags if refund should be prompted.

    Requirements: 20.1, 20.2, 20.3, 20.4
    """
    # Fetch the invoice
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.org_id == org_id
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Only allow credit notes on issued/partially_paid/paid/overdue invoices
    creditable_statuses = {"issued", "partially_paid", "paid", "overdue"}
    if invoice.status not in creditable_statuses:
        raise ValueError(
            f"Cannot create credit note for invoice with status '{invoice.status}'. "
            f"Invoice must be in one of: {', '.join(sorted(creditable_statuses))}"
        )

    # Calculate total already credited
    existing_cn_result = await db.execute(
        select(CreditNote).where(
            CreditNote.invoice_id == invoice_id,
            CreditNote.org_id == org_id,
        )
    )
    existing_credit_notes = list(existing_cn_result.scalars().all())
    total_already_credited = sum(cn.amount for cn in existing_credit_notes)

    # Credit amount cannot exceed invoice total minus already credited
    max_creditable = invoice.total - total_already_credited
    if amount > max_creditable:
        raise ValueError(
            f"Credit amount {amount} exceeds maximum creditable amount {max_creditable}"
        )

    # Assign gap-free credit note number
    cn_number = await _get_next_credit_note_number(db, org_id)

    # Create the credit note record
    credit_note = CreditNote(
        org_id=org_id,
        invoice_id=invoice_id,
        credit_note_number=cn_number,
        amount=amount,
        reason=reason,
        items=items,
        created_by=user_id,
    )
    db.add(credit_note)
    await db.flush()

    # Update invoice balance_due
    before_balance = invoice.balance_due
    invoice.balance_due = invoice.balance_due - amount
    if invoice.balance_due < Decimal("0"):
        invoice.balance_due = Decimal("0")

    # Update invoice status based on new balance
    if invoice.balance_due == Decimal("0") and invoice.status != "voided":
        invoice.status = "paid"
    elif invoice.amount_paid > Decimal("0") and invoice.balance_due > Decimal("0"):
        invoice.status = "partially_paid"

    await db.flush()

    # Check for Stripe payments to prompt refund
    stripe_refund_prompted = False
    if process_stripe_refund:
        payment_result = await db.execute(
            select(Payment).where(
                Payment.invoice_id == invoice_id,
                Payment.org_id == org_id,
                Payment.method == "stripe",
                Payment.is_refund == False,  # noqa: E712
            )
        )
        stripe_payments = list(payment_result.scalars().all())
        if stripe_payments:
            stripe_refund_prompted = True

    # Write audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="credit_note.created",
        entity_type="credit_note",
        entity_id=credit_note.id,
        before_value={"balance_due": str(before_balance)},
        after_value={
            "credit_note_number": cn_number,
            "amount": str(amount),
            "reason": reason,
            "invoice_id": str(invoice_id),
            "balance_due": str(invoice.balance_due),
            "stripe_refund_prompted": stripe_refund_prompted,
        },
        ip_address=ip_address,
    )

    await db.flush()

    # Don't commit here — let the session dependency handle it.
    # Refresh to get server-generated values (expire is sync-only, causes MissingGreenlet).
    await db.refresh(credit_note)
    await db.refresh(invoice)

    # Fetch line items for invoice response
    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    # Auto-post journal entry for the credit note (Req 4.4, 4.6, 4.7)
    try:
        from app.modules.ledger.auto_poster import auto_post_credit_note
        await auto_post_credit_note(db, credit_note, invoice, user_id)
    except Exception as exc:
        logger.warning(
            "Auto-post failed for credit note %s: %s", credit_note.id, exc
        )

    return {
        "credit_note": _credit_note_to_dict(credit_note),
        "invoice": _invoice_to_dict(invoice, line_items),
        "stripe_refund_prompted": stripe_refund_prompted,
    }


async def get_credit_notes_for_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> dict:
    """Retrieve all credit notes for an invoice.

    Requirements: 20.1, 20.2
    """
    # Verify invoice exists in this org
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.org_id == org_id
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    cn_result = await db.execute(
        select(CreditNote)
        .where(
            CreditNote.invoice_id == invoice_id,
            CreditNote.org_id == org_id,
        )
        .order_by(CreditNote.created_at)
    )
    credit_notes = list(cn_result.scalars().all())

    total_credited = sum(cn.amount for cn in credit_notes)

    return {
        "credit_notes": [_credit_note_to_dict(cn) for cn in credit_notes],
        "total_credited": total_credited,
    }


# ---------------------------------------------------------------------------
# Invoice search and filtering (Task 10.6)
# Requirements: 21.1, 21.2, 21.3, 21.4
# ---------------------------------------------------------------------------


async def search_invoices(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    issue_date_from: date | None = None,
    issue_date_to: date | None = None,
    limit: int = 25,
    offset: int = 0,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Search and filter invoices with pagination.

    Supports:
    - Text search across invoice_number, vehicle_rego, and customer
      name/phone/email (via join to customers table)
    - Status filtering
    - Date range filtering on issue_date
    - Pagination via limit/offset

    Filters are stackable (Req 21.3).
    Returns results showing invoice number, customer name, rego, total,
    status, and issue date (Req 21.4).

    Requirements: 21.1, 21.2, 21.3, 21.4
    """
    from sqlalchemy import func as sa_func, or_

    # Base query: join invoices with customers to enable customer field search
    base_filter = [Invoice.org_id == org_id]

    # Branch filter — include NULL branch_id records (legacy/org-wide)
    if branch_id is not None:
        from sqlalchemy import or_
        base_filter.append(or_(Invoice.branch_id == branch_id, Invoice.branch_id.is_(None)))

    # Status filter
    if status:
        base_filter.append(Invoice.status == status)

    # Date range filters
    if issue_date_from:
        base_filter.append(Invoice.issue_date >= issue_date_from)
    if issue_date_to:
        base_filter.append(Invoice.issue_date <= issue_date_to)

    # Text search across invoice_number, vehicle_rego, customer fields
    if search:
        search_term = f"%{search}%"
        base_filter.append(
            or_(
                Invoice.invoice_number.ilike(search_term),
                Invoice.vehicle_rego.ilike(search_term),
                Customer.first_name.ilike(search_term),
                Customer.last_name.ilike(search_term),
                Customer.phone.ilike(search_term),
                Customer.email.ilike(search_term),
                (Customer.first_name + " " + Customer.last_name).ilike(search_term),
            )
        )

    # Count query
    count_q = (
        select(sa_func.count(Invoice.id))
        .join(Customer, Invoice.customer_id == Customer.id, isouter=True)
        .where(*base_filter)
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Correlated subquery: has at least one non-refund Stripe payment (Req 8.1)
    has_stripe_payment = (
        select(sa_func.count(Payment.id))
        .where(
            Payment.invoice_id == Invoice.id,
            Payment.method == "stripe",
            Payment.is_refund == False,
        )
        .correlate(Invoice)
        .scalar_subquery()
        > 0
    ).label("has_stripe_payment")

    # Data query — select only the fields needed for the list view
    data_q = (
        select(
            Invoice.id,
            Invoice.invoice_number,
            Customer.first_name,
            Customer.last_name,
            Invoice.vehicle_rego,
            Invoice.total,
            Invoice.status,
            Invoice.issue_date,
            has_stripe_payment,
        )
        .join(Customer, Invoice.customer_id == Customer.id, isouter=True)
        .where(*base_filter)
        .order_by(Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(data_q)

    invoices = []
    for row in rows:
        first = row.first_name or ""
        last = row.last_name or ""
        customer_name = f"{first} {last}".strip() or None
        invoices.append(
            {
                "id": row.id,
                "invoice_number": row.invoice_number,
                "customer_name": customer_name,
                "vehicle_rego": row.vehicle_rego,
                "total": row.total,
                "status": row.status,
                "issue_date": row.issue_date,
                "has_stripe_payment": row.has_stripe_payment,
            }
        )

    return {
        "invoices": invoices,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Invoice duplication (Task 10.7)
# Requirements: 22.1, 22.2
# ---------------------------------------------------------------------------


async def duplicate_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Duplicate an existing invoice as a new Draft.

    Creates a new draft invoice pre-filled with the same customer, vehicle
    fields, and line items as the source invoice. The duplicate does NOT
    receive an invoice number until it is issued (Req 22.2).

    Totals are recalculated from the copied line items.

    Requirements: 22.1, 22.2
    """
    # Fetch the source invoice
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.org_id == org_id
        )
    )
    source = inv_result.scalar_one_or_none()
    if source is None:
        raise ValueError("Invoice not found in this organisation")

    # Fetch source line items
    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == source.id)
        .order_by(LineItem.sort_order)
    )
    source_line_items = list(li_result.scalars().all())

    # Build line items data for total calculation
    items_data = [
        {
            "item_type": li.item_type,
            "description": li.description,
            "catalogue_item_id": li.catalogue_item_id,
            "part_number": li.part_number,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "hours": li.hours,
            "hourly_rate": li.hourly_rate,
            "discount_type": li.discount_type,
            "discount_value": li.discount_value,
            "is_gst_exempt": li.is_gst_exempt,
            "warranty_note": li.warranty_note,
            "sort_order": li.sort_order,
        }
        for li in source_line_items
    ]

    # Get org GST rate for recalculation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    gst_rate = Decimal(str((org.settings or {}).get("gst_percentage", 15)))

    # Recalculate totals from copied line items
    totals = _calculate_invoice_totals(
        items_data, gst_rate, source.discount_type, source.discount_value
    )

    # Create the new draft invoice — no number, no issue date
    new_invoice = Invoice(
        org_id=org_id,
        customer_id=source.customer_id,
        invoice_number=None,
        vehicle_rego=source.vehicle_rego,
        vehicle_make=source.vehicle_make,
        vehicle_model=source.vehicle_model,
        vehicle_year=source.vehicle_year,
        vehicle_odometer=source.vehicle_odometer,
        branch_id=source.branch_id,
        status="draft",
        issue_date=None,
        due_date=None,
        subtotal=totals["subtotal"],
        discount_amount=totals["discount_amount"],
        discount_type=source.discount_type,
        discount_value=source.discount_value,
        gst_amount=totals["gst_amount"],
        total=totals["total"],
        amount_paid=Decimal("0"),
        balance_due=totals["balance_due"],
        notes_internal=source.notes_internal,
        notes_customer=source.notes_customer,
        created_by=user_id,
    )
    db.add(new_invoice)
    await db.flush()

    # Copy line items
    new_line_items = []
    for i, li in enumerate(source_line_items):
        new_li = LineItem(
            invoice_id=new_invoice.id,
            org_id=org_id,
            item_type=li.item_type,
            description=li.description,
            catalogue_item_id=li.catalogue_item_id,
            part_number=li.part_number,
            quantity=li.quantity,
            unit_price=li.unit_price,
            hours=li.hours,
            hourly_rate=li.hourly_rate,
            discount_type=li.discount_type,
            discount_value=li.discount_value,
            is_gst_exempt=li.is_gst_exempt,
            warranty_note=li.warranty_note,
            line_total=totals["line_totals"][i],
            sort_order=li.sort_order,
        )
        db.add(new_li)
        await db.flush()
        new_line_items.append(new_li)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="invoice.duplicated",
        entity_type="invoice",
        entity_id=new_invoice.id,
        before_value=None,
        after_value={
            "source_invoice_id": str(invoice_id),
            "source_invoice_number": source.invoice_number,
            "status": "draft",
            "customer_id": str(source.customer_id),
            "total": str(totals["total"]),
            "line_item_count": len(new_line_items),
        },
        ip_address=ip_address,
    )

    await db.refresh(new_invoice)
    return _invoice_to_dict(new_invoice, new_line_items)


# ---------------------------------------------------------------------------
# Recurring Invoice Schedules (Task 10.9)
# Requirements: 60.1, 60.2, 60.3, 60.4
# ---------------------------------------------------------------------------

from dateutil.relativedelta import relativedelta

from app.modules.recurring_invoices.models import RecurringSchedule


_FREQUENCY_DELTAS = {
    "weekly": relativedelta(weeks=1),
    "fortnightly": relativedelta(weeks=2),
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
    "annually": relativedelta(years=1),
}

VALID_FREQUENCIES = frozenset(_FREQUENCY_DELTAS.keys())


def _schedule_to_dict(schedule: RecurringSchedule) -> dict:
    """Convert a RecurringSchedule ORM object to a plain dict."""
    return {
        "id": schedule.id,
        "org_id": schedule.org_id,
        "customer_id": schedule.customer_id,
        "frequency": schedule.frequency,
        "line_items": schedule.line_items or [],
        "auto_issue": schedule.auto_issue,
        "is_active": schedule.status == "active",
        "status": schedule.status,
        "next_due_date": schedule.next_generation_date.isoformat() if schedule.next_generation_date else None,
        "start_date": schedule.start_date.isoformat() if schedule.start_date else None,
        "end_date": schedule.end_date.isoformat() if schedule.end_date else None,
        "auto_email": schedule.auto_email,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


async def create_recurring_schedule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    frequency: str,
    line_items: list[dict],
    next_due_date: date,
    auto_issue: bool = False,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a recurring invoice schedule linked to a customer.

    Requirements: 60.1
    """
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(f"Invalid frequency: {frequency}")

    # Validate customer belongs to org
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    if cust_result.scalar_one_or_none() is None:
        raise ValueError("Customer not found in this organisation")

    # Validate at least one line item
    if not line_items:
        raise ValueError("At least one line item is required")

    schedule = RecurringSchedule(
        org_id=org_id,
        customer_id=customer_id,
        frequency=frequency,
        line_items=line_items,
        start_date=next_due_date,
        next_generation_date=next_due_date,
        auto_issue=auto_issue,
        status="active",
    )
    db.add(schedule)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="recurring_schedule.created",
        entity_type="recurring_schedule",
        entity_id=schedule.id,
        before_value=None,
        after_value={
            "customer_id": str(customer_id),
            "frequency": frequency,
            "auto_issue": auto_issue,
            "next_due_date": str(next_due_date),
            "line_item_count": len(line_items),
        },
        ip_address=ip_address,
    )

    return _schedule_to_dict(schedule)


async def update_recurring_schedule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID,
    frequency: str | None = None,
    line_items: list[dict] | None = None,
    next_due_date: date | None = None,
    auto_issue: bool | None = None,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update an existing recurring invoice schedule.

    Requirements: 60.3
    """
    result = await db.execute(
        select(RecurringSchedule).where(
            RecurringSchedule.id == schedule_id,
            RecurringSchedule.org_id == org_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ValueError("Recurring schedule not found in this organisation")

    if schedule.status != "active":
        raise ValueError("Cannot update a cancelled schedule")

    before = _schedule_to_dict(schedule)

    if frequency is not None:
        if frequency not in VALID_FREQUENCIES:
            raise ValueError(f"Invalid frequency: {frequency}")
        schedule.frequency = frequency

    if line_items is not None:
        if not line_items:
            raise ValueError("At least one line item is required")
        schedule.line_items = line_items

    if next_due_date is not None:
        schedule.next_generation_date = next_due_date

    if auto_issue is not None:
        schedule.auto_issue = auto_issue

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="recurring_schedule.updated",
        entity_type="recurring_schedule",
        entity_id=schedule.id,
        before_value=before,
        after_value=_schedule_to_dict(schedule),
        ip_address=ip_address,
    )

    return _schedule_to_dict(schedule)


async def list_recurring_schedules(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
) -> list[dict]:
    """List recurring schedules for an organisation.

    Requirements: 60.3
    """
    stmt = select(RecurringSchedule).where(
        RecurringSchedule.org_id == org_id,
    ).order_by(RecurringSchedule.created_at.desc())

    if active_only:
        stmt = stmt.where(RecurringSchedule.status == "active")

    result = await db.execute(stmt)
    schedules = list(result.scalars().all())
    return [_schedule_to_dict(s) for s in schedules]


async def pause_recurring_schedule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Pause an active recurring schedule (sets status='paused', reversible).

    Requirements: 60.3
    """
    result = await db.execute(
        select(RecurringSchedule).where(
            RecurringSchedule.id == schedule_id,
            RecurringSchedule.org_id == org_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ValueError("Recurring schedule not found in this organisation")

    if schedule.status != "active":
        raise ValueError("Schedule is already paused or cancelled")

    schedule.status = "paused"
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="recurring_schedule.paused",
        entity_type="recurring_schedule",
        entity_id=schedule.id,
        before_value={"status": "active"},
        after_value={"status": "paused"},
        ip_address=ip_address,
    )

    return _schedule_to_dict(schedule)


async def cancel_recurring_schedule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Cancel a recurring schedule permanently.

    Requirements: 60.3
    """
    result = await db.execute(
        select(RecurringSchedule).where(
            RecurringSchedule.id == schedule_id,
            RecurringSchedule.org_id == org_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ValueError("Recurring schedule not found in this organisation")

    schedule.status = "cancelled"
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="recurring_schedule.cancelled",
        entity_type="recurring_schedule",
        entity_id=schedule.id,
        before_value={"status": schedule.status},
        after_value={"status": "cancelled"},
        ip_address=ip_address,
    )

    return _schedule_to_dict(schedule)


async def _notify_org_admins_recurring_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_data: dict,
    schedule: RecurringSchedule,
) -> None:
    """Notify Org_Admin(s) that a recurring invoice was generated.

    Finds all active org_admin users for the organisation and logs a
    notification for each.  In production this dispatches via the
    notification infrastructure (Celery email task).

    Requirements: 60.4
    """
    import logging

    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent

    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(User).where(
            User.org_id == org_id,
            User.role == "org_admin",
            User.is_active.is_(True),
        )
    )
    admins = list(result.scalars().all())

    invoice_number = invoice_data.get("invoice_number") or "Draft"
    status = invoice_data.get("status", "draft")
    total = invoice_data.get("total", "0.00")
    subject = f"Recurring invoice generated: {invoice_number}"

    for admin in admins:
        if not admin.email:
            continue
        await log_email_sent(
            db,
            org_id=org_id,
            recipient=admin.email,
            template_type="recurring_invoice_generated",
            subject=subject,
            status="queued",
        )

    logger.info(
        "Recurring invoice notification queued: org=%s, invoice=%s, status=%s, total=%s, admins=%d",
        org_id,
        invoice_number,
        status,
        total,
        len(admins),
    )


async def generate_recurring_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Generate an invoice from a recurring schedule.

    Creates a Draft or Issued invoice (based on auto_issue flag) using the
    schedule's line items, then advances next_generation_date by the frequency delta.

    Requirements: 60.2, 60.4
    """
    result = await db.execute(
        select(RecurringSchedule).where(
            RecurringSchedule.id == schedule_id,
            RecurringSchedule.org_id == org_id,
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise ValueError("Recurring schedule not found in this organisation")

    if schedule.status != "active":
        raise ValueError("Cannot generate invoice from inactive schedule")

    # Use create_invoice to generate the invoice
    status = "issued" if schedule.auto_issue else "draft"
    invoice_data = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=schedule.customer_id,
        status=status,
        line_items_data=schedule.line_items or [],
        ip_address=ip_address,
    )

    # Link the invoice to the recurring schedule
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_data["id"])
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice:
        invoice.recurring_schedule_id = schedule.id
        await db.flush()

    # Advance next_generation_date
    delta = _FREQUENCY_DELTAS[schedule.frequency]
    schedule.next_generation_date = schedule.next_generation_date + delta
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="recurring_schedule.invoice_generated",
        entity_type="recurring_schedule",
        entity_id=schedule.id,
        before_value=None,
        after_value={
            "invoice_id": str(invoice_data["id"]),
            "status": status,
            "next_due_date": str(schedule.next_generation_date.isoformat()),
        },
        ip_address=ip_address,
    )

    # Notify Org_Admin(s) about the generated invoice (Req 60.4)
    await _notify_org_admins_recurring_invoice(
        db,
        org_id=org_id,
        invoice_data=invoice_data,
        schedule=schedule,
    )

    return invoice_data


async def _notify_org_admins_recurring_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_data: dict,
    schedule: RecurringSchedule,
) -> None:
    """Notify Org_Admin(s) that a recurring invoice was generated.

    Finds all active org_admin users for the organisation and logs a
    notification for each.  In production this dispatches via the
    notification infrastructure (Celery email task).

    Requirements: 60.4
    """
    import logging

    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent

    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(User).where(
            User.org_id == org_id,
            User.role == "org_admin",
            User.is_active.is_(True),
        )
    )
    admins = list(result.scalars().all())

    invoice_number = invoice_data.get("invoice_number") or "Draft"
    status = invoice_data.get("status", "draft")
    total = invoice_data.get("total", "0.00")
    subject = f"Recurring invoice generated: {invoice_number}"

    for admin in admins:
        if not admin.email:
            continue
        await log_email_sent(
            db,
            org_id=org_id,
            recipient=admin.email,
            template_type="recurring_invoice_generated",
            subject=subject,
            status="queued",
        )

    logger.info(
        "Recurring invoice notification queued: org=%s, invoice=%s, status=%s, total=%s, admins=%d",
        org_id,
        invoice_number,
        status,
        total,
        len(admins),
    )



# ---------------------------------------------------------------------------
# Bulk Export & Archive — Requirements: 31.1, 31.2, 31.3
# ---------------------------------------------------------------------------


async def bulk_export_invoices(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    start_date: date,
    end_date: date,
    export_format: str,
) -> tuple[list[dict], list["Invoice"]]:
    """Fetch invoices in a date range for bulk export.

    Returns a tuple of (invoice_dicts, invoice_objects).
    The caller (router) is responsible for formatting as CSV or ZIP of PDFs.

    Requirements: 31.1
    """
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(
            Invoice.org_id == org_id,
            Invoice.issue_date >= start_date,
            Invoice.issue_date <= end_date,
            Invoice.status != "draft",
        )
        .order_by(Invoice.issue_date, Invoice.invoice_number)
    )
    result = await db.execute(stmt)
    invoices = list(result.scalars().all())

    invoice_dicts = [
        _invoice_to_dict(inv, list(inv.line_items)) for inv in invoices
    ]
    return invoice_dicts, invoices


def invoices_to_csv(invoice_dicts: list[dict]) -> str:
    """Convert invoice dicts to CSV string.

    Requirements: 31.1
    """
    import csv
    import io

    if not invoice_dicts:
        return ""

    fieldnames = [
        "invoice_number",
        "status",
        "issue_date",
        "due_date",
        "customer_id",
        "vehicle_rego",
        "vehicle_make",
        "vehicle_model",
        "vehicle_year",
        "currency",
        "subtotal",
        "discount_amount",
        "gst_amount",
        "total",
        "amount_paid",
        "balance_due",
        "notes_customer",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for inv in invoice_dicts:
        row = {}
        for f in fieldnames:
            val = inv.get(f)
            if isinstance(val, (date, datetime)):
                row[f] = val.isoformat() if val else ""
            elif isinstance(val, Decimal):
                row[f] = str(val)
            elif isinstance(val, uuid.UUID):
                row[f] = str(val)
            else:
                row[f] = val if val is not None else ""
        writer.writerow(row)

    return output.getvalue()


async def bulk_delete_invoices(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_ids: list[uuid.UUID],
    ip_address: str | None = None,
) -> tuple[int, int]:
    """Permanently delete invoices and return (deleted_count, bytes_recovered).

    Deleted invoices are irrecoverable (Req 31.3).
    Records the action in the audit log (Req 31.2).

    Returns (deleted_count, estimated_bytes_recovered).
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy.dialects.postgresql import array as pg_array

    # Fetch matching invoices scoped to org
    stmt = select(Invoice).where(
        Invoice.org_id == org_id,
        Invoice.id.in_(invoice_ids),
    )
    result = await db.execute(stmt)
    invoices = list(result.scalars().all())

    if not invoices:
        return 0, 0

    # Estimate space recovered from invoice JSON data
    total_bytes = 0
    deleted_ids = []
    for inv in invoices:
        json_str = str(inv.invoice_data_json) if inv.invoice_data_json else "{}"
        total_bytes += len(json_str.encode("utf-8"))
        deleted_ids.append(inv.id)

    # Null out nullable invoice FKs in related tables before deleting
    from app.modules.vehicles.models import OdometerReading
    from app.modules.tipping.models import Tip
    from app.modules.pos.models import POSTransaction

    for model_cls in (OdometerReading, Tip, POSTransaction):
        await db.execute(
            update(model_cls)
            .where(model_cls.invoice_id.in_(deleted_ids))
            .values(invoice_id=None)
        )

    # Delete invoices (cascade deletes line_items, credit_notes, payments)
    for inv in invoices:
        await db.delete(inv)

    # Audit log
    await write_audit_log(
        db,
        action="invoice.bulk_delete",
        entity_type="invoice",
        org_id=org_id,
        user_id=user_id,
        after_value={
            "deleted_count": len(deleted_ids),
            "invoice_ids": [str(i) for i in deleted_ids],
            "estimated_bytes_recovered": total_bytes,
        },
        ip_address=ip_address,
    )

    await db.flush()
    return len(deleted_ids), total_bytes


# ---------------------------------------------------------------------------
# PDF Generation (on-demand)
# Requirements: 32.1, 32.2, 32.3, 32.4
# ---------------------------------------------------------------------------


async def generate_invoice_pdf(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> bytes:
    """Generate a PDF for an invoice on-the-fly using WeasyPrint.

    The PDF is rendered from the stored invoice data combined with current
    organisation branding.  The result is returned as raw bytes and is
    **never** written to permanent storage (Requirement 32.2).

    Requirements: 32.1, 32.2, 32.3, 32.4
    """
    import pathlib

    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    # Fetch invoice --------------------------------------------------------
    invoice_dict = await get_invoice(db, org_id=org_id, invoice_id=invoice_id)

    # Fetch organisation (current branding) --------------------------------
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Format date fields for PDF display using org timezone
    from app.core.timezone_utils import format_date_local
    if invoice_dict.get("issue_date"):
        d = invoice_dict["issue_date"]
        if hasattr(d, "strftime"):
            invoice_dict["issue_date"] = d.strftime("%d %b %Y")
    if invoice_dict.get("due_date"):
        d = invoice_dict["due_date"]
        if hasattr(d, "strftime"):
            invoice_dict["due_date"] = d.strftime("%d %b %Y")

    settings = org.settings or {}

    # Resolve country code to full name for display
    _raw_country = settings.get("address_country") or ""
    _COUNTRY_NAMES = {
        "NZ": "New Zealand", "AU": "Australia", "US": "United States",
        "GB": "United Kingdom", "CA": "Canada", "IE": "Ireland",
        "SG": "Singapore", "ZA": "South Africa", "IN": "India",
        "PH": "Philippines", "FJ": "Fiji", "WS": "Samoa", "TO": "Tonga",
    }
    _display_country = _COUNTRY_NAMES.get(_raw_country.upper(), _raw_country) if len(_raw_country) == 2 else _raw_country

    org_context = {
        "name": org.name,
        "logo_url": settings.get("logo_url"),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
        "secondary_colour": settings.get("secondary_colour"),
        "address": ", ".join(filter(None, [
            settings.get("address_unit"),
            settings.get("address_street"),
            settings.get("address_city"),
            settings.get("address_state"),
            settings.get("address_postcode"),
        ])) or settings.get("address"),
        "address_unit": settings.get("address_unit"),
        "address_street": settings.get("address_street"),
        "address_city": settings.get("address_city"),
        "address_state": settings.get("address_state"),
        "address_country": _display_country if _display_country else None,
        "address_postcode": settings.get("address_postcode"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "website": settings.get("website"),
        "gst_number": settings.get("gst_number"),
        "invoice_header": settings.get("invoice_header_text"),
        "invoice_footer": settings.get("invoice_footer_text"),
    }

    gst_percentage = settings.get("gst_percentage", 15)
    payment_terms = settings.get("payment_terms_text", "")
    # Per-invoice terms_and_conditions take priority over org-level default
    terms_and_conditions = invoice_dict.get("terms_and_conditions") or settings.get("terms_and_conditions", "")
    currency_symbol = get_currency_symbol(invoice_dict.get("currency", "NZD"))

    # Fetch customer -------------------------------------------------------
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == invoice_dict["customer_id"],
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    # Build address: prefer plain text, fall back to structured billing_address
    _cust_addr = customer.address if customer else None
    _cust_billing_addr = None
    if customer:
        _ba = getattr(customer, "billing_address", None) or {}
        if isinstance(_ba, dict) and any(_ba.values()):
            _cust_billing_addr = ", ".join(filter(None, [
                _ba.get("street"),
                _ba.get("city"),
                _ba.get("state"),
                _ba.get("postal_code"),
                _ba.get("country"),
            ]))
            if not _cust_addr:
                _cust_addr = _cust_billing_addr
    customer_context = {
        "first_name": customer.first_name if customer else "Unknown",
        "last_name": customer.last_name if customer else "",
        "display_name": getattr(customer, "display_name", None) if customer else None,
        "company_name": getattr(customer, "company_name", None) if customer else None,
        "email": customer.email if customer else None,
        "phone": customer.phone if customer else None,
        "address": _cust_addr or None,
        "billing_address": _cust_billing_addr or None,
    }

    # I18n labels for PDF --------------------------------------------------
    from app.core.i18n_pdf import get_pdf_context

    org_locale = getattr(org, "locale", "en") or "en"
    # Extract the language code from locale (e.g. "en-NZ" -> "en")
    lang_code = org_locale.split("-")[0] if "-" in org_locale else org_locale
    i18n_ctx = get_pdf_context(lang_code)

    # Render HTML ----------------------------------------------------------
    template_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)

    # Add custom date filter for PDF rendering
    def _pdf_format_date(value):
        """Format a date/datetime/ISO string for PDF display."""
        if not value:
            return ""
        if isinstance(value, str):
            # Already formatted string like "22 Mar 2026"
            if not value.startswith("20") or "T" not in value:
                return value
            # ISO string — parse and format
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(value)
                return dt.strftime("%d %b %Y %I:%M %p")
            except (ValueError, TypeError):
                return value
        if hasattr(value, "strftime"):
            return value.strftime("%d %b %Y")
        return str(value)

    env.filters["pdfdate"] = _pdf_format_date

    # Template resolution: use org's selected template or default -----------
    template_id = settings.get("invoice_template_id")
    template_colours = settings.get("invoice_template_colours") or {}
    template_file = "invoice.html"  # default
    colour_context: dict = {}

    if template_id:
        from app.modules.invoices.template_registry import get_template_metadata

        meta = get_template_metadata(template_id)
        if meta:
            template_file = meta.template_file
            # Resolve colours: org override > template default
            colour_context = {
                "primary_colour": template_colours.get("primary_colour") or meta.default_primary_colour,
                "accent_colour": template_colours.get("accent_colour") or meta.default_accent_colour,
                "header_bg_colour": template_colours.get("header_bg_colour") or meta.default_header_bg_colour,
            }
        else:
            logger.warning("Template '%s' not found in registry, using default", template_id)

    template = env.get_template(template_file)

    html_content = template.render(
        invoice=invoice_dict,
        org=org_context,
        customer=customer_context,
        currency_symbol=currency_symbol,
        gst_percentage=gst_percentage,
        payment_terms=payment_terms,
        terms_and_conditions=terms_and_conditions,
        colours=colour_context,
        job_card_appendix_html=invoice_dict.get("job_card_appendix_html"),
        **i18n_ctx,
    )

    # Generate PDF (in-memory only) ----------------------------------------
    pdf_bytes: bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


async def email_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
    recipient_email: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Generate the invoice PDF and send an email to the customer.

    Uses the highest-priority active email provider configured in the system.
    If *recipient_email* is not provided the customer's email on file is used.
    Returns a summary dict with the recipient and status.

    Requirements: 32.3
    """
    import json as _json
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import EmailProvider

    # Fetch invoice to get customer email if needed
    invoice_dict = await get_invoice(db, org_id=org_id, invoice_id=invoice_id)

    if recipient_email is None:
        cust_result = await db.execute(
            select(Customer).where(
                Customer.id == invoice_dict["customer_id"],
                Customer.org_id == org_id,
            )
        )
        customer = cust_result.scalar_one_or_none()
        if customer is None or not customer.email:
            raise ValueError(
                "Customer has no email address on file. Provide a recipient_email."
            )
        recipient_email = customer.email

    # Generate PDF bytes
    pdf_bytes = await generate_invoice_pdf(db, org_id=org_id, invoice_id=invoice_id)

    inv_number = invoice_dict.get("invoice_number") or "DRAFT"
    org_name = invoice_dict.get("org_name") or "Your Company"
    balance_due = invoice_dict.get("balance_due", 0)
    currency = invoice_dict.get("currency", "NZD")
    payment_page_url = invoice_dict.get("payment_page_url")

    # For already-issued invoices with Stripe gateway: ensure payment link
    # exists and uses the current FRONTEND_BASE_URL.  If the stored URL is
    # stale (e.g. http://localhost from before the domain was configured) or
    # missing, regenerate it so the email contains a working link.
    inv_gateway = invoice_dict.get("payment_gateway")
    inv_status = invoice_dict.get("status")
    if (
        inv_gateway == "stripe"
        and inv_status in ("issued", "partially_paid", "overdue")
        and balance_due
        and float(balance_due) > 0
    ):
        from app.config import settings as app_settings
        frontend_base = (base_url or app_settings.frontend_base_url or "http://localhost").rstrip("/")
        needs_regen = (
            not payment_page_url
            or not payment_page_url.startswith(frontend_base)
        )
        if needs_regen:
            try:
                inv_obj_result = await db.execute(
                    select(Invoice).where(
                        Invoice.id == invoice_id, Invoice.org_id == org_id
                    )
                )
                inv_obj_for_regen = inv_obj_result.scalar_one_or_none()
                org_regen_result = await db.execute(
                    select(Organisation).where(Organisation.id == org_id)
                )
                org_for_regen = org_regen_result.scalar_one_or_none()
                if inv_obj_for_regen and org_for_regen:
                    await _maybe_create_stripe_payment_intent(
                        db, inv_obj_for_regen, org_for_regen,
                        base_url=base_url,
                    )
                    await db.refresh(inv_obj_for_regen)
                    payment_page_url = inv_obj_for_regen.payment_page_url
                    logger.info(
                        "Regenerated payment link for invoice %s on resend",
                        invoice_id,
                    )
            except Exception:
                logger.exception(
                    "Failed to regenerate payment link for invoice %s on resend",
                    invoice_id,
                )

    # Find all active email providers ordered by priority (failover)
    provider_result = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        raise ValueError(
            "No active email provider configured. Please set up an email provider in Admin > Email Providers."
        )

    # Build the email message (reusable across provider attempts)
    def _build_message(from_name: str, from_email: str) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = recipient_email
        msg["Subject"] = f"Invoice {inv_number} from {org_name}"

        body = (
            f"Hi,\n\n"
            f"Please find attached invoice {inv_number} from {org_name}.\n\n"
            f"Amount Due: {currency} {balance_due}\n\n"
        )
        if payment_page_url:
            body += f"Pay online: {payment_page_url}\n\n"
        body += (
            f"If you have any questions, please don't hesitate to contact us.\n\n"
            f"Thank you for your business.\n\n"
            f"{org_name}\n"
        )
        msg.attach(MIMEText(body, "plain"))

        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header(
            "Content-Disposition", "attachment", filename=f"{inv_number}.pdf"
        )
        msg.attach(pdf_attachment)
        return msg

    # Try each provider in priority order until one succeeds
    last_error = None
    used_provider = None

    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = _json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or org_name

            msg = _build_message(from_name, from_email)

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, recipient_email, msg.as_string())
            server.quit()
            used_provider = provider
            break
        except Exception as e:
            last_error = e
            continue

    if used_provider is None:
        raise ValueError(
            f"All email providers failed. Last error: {last_error}"
        )

    # Auto-issue the invoice if it's still a draft
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.org_id == org_id)
    )
    invoice_obj = inv_result.scalar_one_or_none()
    if invoice_obj and invoice_obj.status == "draft":
        invoice_obj.status = "issued"
        if not invoice_obj.issue_date:
            invoice_obj.issue_date = date.today()
        if not invoice_obj.due_date:
            # Use payment terms from invoice_data_json, or default to issue date (due on receipt)
            inv_data = invoice_obj.invoice_data_json or {}
            pt = inv_data.get("payment_terms", "due_on_receipt")
            terms_days_map = {
                "due_on_receipt": 0, "net_15": 15, "net_30": 30,
                "net_45": 45, "net_60": 60, "net_90": 90,
            }
            from datetime import timedelta
            days = terms_days_map.get(pt, 0)
            invoice_obj.due_date = invoice_obj.issue_date + timedelta(days=days)
        if not invoice_obj.invoice_number:
            # Get prefix from org settings
            org_result2 = await db.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org2 = org_result2.scalar_one_or_none()
            prefix = (org2.settings or {}).get("invoice_prefix", "INV-") if org2 else "INV-"
            invoice_obj.invoice_number = await _get_next_invoice_number(
                db, org_id, prefix
            )
        await db.flush()
        await db.refresh(invoice_obj)
        inv_number = invoice_obj.invoice_number or inv_number

        # Auto-generate Stripe PaymentIntent for newly issued invoice
        _org_result_pi = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org_for_pi = _org_result_pi.scalar_one_or_none()
        if org_for_pi:
            await _maybe_create_stripe_payment_intent(db, invoice_obj, org_for_pi)

    # Audit log
    await write_audit_log(
        db,
        action="invoice.email_sent",
        entity_type="invoice",
        entity_id=invoice_id,
        org_id=org_id,
        after_value={
            "recipient": recipient_email,
            "invoice_number": inv_number,
            "pdf_size_bytes": len(pdf_bytes),
            "provider": used_provider.provider_key,
        },
    )
    await db.flush()

    return {
        "invoice_id": invoice_id,
        "invoice_number": inv_number,
        "recipient_email": recipient_email,
        "pdf_size_bytes": len(pdf_bytes),
        "status": "sent",
    }


async def send_payment_reminder(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
    channel: str,
) -> dict:
    """Send a payment reminder via email or SMS for an outstanding invoice.

    Uses the existing email/SMS provider infrastructure. Logs the send to
    notification_log for audit trail.

    Requirements: 38.1
    """
    from app.modules.notifications.service import log_email_sent, log_sms_sent

    invoice_dict = await get_invoice(db, org_id=org_id, invoice_id=invoice_id)

    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == invoice_dict["customer_id"],
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found.")

    inv_number = invoice_dict.get("invoice_number") or "DRAFT"
    balance_due = invoice_dict.get("balance_due", 0)
    org_name = invoice_dict.get("org_name") or "Your Company"
    currency = invoice_dict.get("currency", "NZD")
    customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"

    if channel == "email":
        if not customer.email:
            raise ValueError("Customer has no email address on file.")

        # Reuse the email_invoice infrastructure but with reminder subject/body
        import json as _json
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from app.core.encryption import envelope_decrypt_str
        from app.modules.admin.models import EmailProvider

        provider_result = await db.execute(
            select(EmailProvider)
            .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
            .order_by(EmailProvider.priority)
        )
        providers = list(provider_result.scalars().all())
        if not providers:
            raise ValueError("No active email provider configured.")

        subject = f"Payment Reminder — Invoice {inv_number} from {org_name}"
        body_text = (
            f"Hi {customer_name},\n\n"
            f"This is a friendly reminder that invoice {inv_number} "
            f"has an outstanding balance of {currency} {balance_due:.2f}.\n\n"
            f"Please arrange payment at your earliest convenience.\n\n"
            f"Thank you,\n{org_name}"
        )

        used_provider = None
        last_error = None
        for provider in providers:
            try:
                creds_json = envelope_decrypt_str(provider.credentials_encrypted)
                credentials = _json.loads(creds_json)
                smtp_host = provider.smtp_host
                smtp_port = provider.smtp_port or 587
                smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
                username = credentials.get("username") or credentials.get("api_key", "")
                password = credentials.get("password") or credentials.get("api_key", "")
                config = provider.config or {}
                from_email = config.get("from_email") or username
                from_name = config.get("from_name") or org_name

                msg = MIMEMultipart("mixed")
                msg["From"] = f"{from_name} <{from_email}>"
                msg["To"] = customer.email
                msg["Subject"] = subject
                msg.attach(MIMEText(body_text, "plain", "utf-8"))

                if smtp_encryption == "ssl":
                    server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
                else:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                    if smtp_encryption == "tls":
                        server.starttls()
                if username and password:
                    server.login(username, password)
                server.sendmail(from_email, customer.email, msg.as_string())
                server.quit()
                used_provider = provider
                break
            except Exception as e:
                last_error = e
                continue

        if used_provider is None:
            raise ValueError(f"All email providers failed. Last error: {last_error}")

        await log_email_sent(
            db,
            org_id=org_id,
            recipient=customer.email,
            template_type="payment_reminder",
            subject=subject,
            status="sent",
            channel="email",
        )

        await write_audit_log(
            db,
            action="invoice.reminder_email_sent",
            entity_type="invoice",
            entity_id=invoice_id,
            org_id=org_id,
            after_value={"recipient": customer.email, "invoice_number": inv_number},
        )
        await db.flush()

        return {"status": "sent", "channel": "email", "recipient": customer.email}

    elif channel == "sms":
        phone = customer.phone or customer.mobile_phone
        if not phone:
            raise ValueError("Customer has no phone number on file.")

        sms_body = (
            f"Hi {customer_name}, this is a reminder that invoice "
            f"{inv_number} has a balance of {currency} {balance_due:.2f} outstanding. "
            f"Please pay at your earliest convenience. — {org_name}"
        )

        sms_log = await log_sms_sent(
            db,
            org_id=org_id,
            recipient=phone,
            template_type="payment_reminder",
            body=sms_body,
            status="queued",
        )

        # Flush so the notification_log row is visible to send_sms_task's
        # independent session (it opens its own connection).
        await db.flush()

        from app.tasks.notifications import send_sms_task
        result = await send_sms_task(
            str(org_id),
            sms_log["id"],
            phone,
            sms_body,
            None,
            "payment_reminder",
        )

        if not result.get("success"):
            error_msg = result.get("error", "SMS send failed")
            raise ValueError(f"SMS reminder failed: {error_msg}")

        # Track SMS usage
        try:
            from app.modules.admin.service import increment_sms_usage
            await increment_sms_usage(db, org_id)
        except Exception:
            pass

        await write_audit_log(
            db,
            action="invoice.reminder_sms_sent",
            entity_type="invoice",
            entity_id=invoice_id,
            org_id=org_id,
            after_value={"recipient": phone, "invoice_number": inv_number},
        )
        await db.flush()

        status = "sent"
        return {"status": status, "channel": "sms", "recipient": phone}

    else:
        raise ValueError(f"Invalid channel: {channel}. Must be 'email' or 'sms'.")
