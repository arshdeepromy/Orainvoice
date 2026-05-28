"""Business logic for Payment module — cash payment recording.

Requirements: 24.1, 24.2, 24.3
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import write_audit_log
from app.integrations.stripe_connect import create_payment_intent
from app.modules.in_app_notifications.service import create_in_app_notification
from app.modules.invoices.models import Invoice
from app.modules.invoices.service import _validate_transition
from app.modules.payments.models import Payment
from app.modules.payments.token_service import generate_payment_token

logger = logging.getLogger(__name__)


# Stripe minimum charge amounts per currency.
# Source: https://stripe.com/docs/currencies#minimum-and-maximum-charge-amounts
# Per-currency dict so multi-currency invoicing (when introduced) does not
# require a code change here — only an entry in this dict.
STRIPE_MIN_BY_CURRENCY: dict[str, Decimal] = {
    "NZD": Decimal("0.50"),
    "AUD": Decimal("0.50"),
    "USD": Decimal("0.50"),
    "GBP": Decimal("0.30"),
    "EUR": Decimal("0.50"),
    "JPY": Decimal("50"),
}
DEFAULT_STRIPE_MIN = Decimal("0.50")  # fallback for unlisted currencies


def stripe_min_for_currency(currency: str | None) -> Decimal:
    """Return the documented Stripe minimum charge for the given currency.

    Falls back to DEFAULT_STRIPE_MIN if the currency is not in the dict
    (defensive: better to refuse a sub-minimum charge than to assume).
    """
    if not currency:
        return DEFAULT_STRIPE_MIN
    return STRIPE_MIN_BY_CURRENCY.get(currency.upper(), DEFAULT_STRIPE_MIN)


async def record_cash_payment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Record a cash payment against an invoice.

    - Validates invoice exists and belongs to org
    - Validates payment amount > 0 and <= balance_due
    - Creates Payment record with method='cash'
    - Updates invoice amount_paid and balance_due
    - Transitions invoice status to 'paid' or 'partially_paid'
    - Writes audit log entry

    Requirements: 24.1, 24.2, 24.3
    """
    # Fetch invoice scoped to org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Only allow payments on issued, partially_paid, or overdue invoices
    if invoice.status not in ("issued", "partially_paid", "overdue"):
        raise ValueError(
            f"Cannot record payment on invoice with status '{invoice.status}'. "
            "Invoice must be issued, partially paid, or overdue."
        )

    # Validate amount
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    if amount > invoice.balance_due:
        raise ValueError(
            f"Payment amount ({amount}) exceeds invoice balance due ({invoice.balance_due})"
        )

    # Capture before state for audit
    before_status = invoice.status
    before_amount_paid = invoice.amount_paid
    before_balance_due = invoice.balance_due

    # Create payment record (Req 24.1)
    payment = Payment(
        org_id=org_id,
        invoice_id=invoice_id,
        amount=amount,
        method="cash",
        recorded_by=user_id,
    )
    db.add(payment)
    await db.flush()

    # Update invoice balances
    invoice.amount_paid = invoice.amount_paid + amount
    invoice.balance_due = invoice.balance_due - amount

    # Determine new status (Req 24.2, 24.3)
    if invoice.balance_due == Decimal("0"):
        new_status = "paid"
    else:
        new_status = "partially_paid"

    # Validate and apply status transition
    _validate_transition(invoice.status, new_status)
    invoice.status = new_status

    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payment.cash_recorded",
        entity_type="payment",
        entity_id=payment.id,
        before_value={
            "invoice_id": str(invoice_id),
            "invoice_status": before_status,
            "amount_paid": str(before_amount_paid),
            "balance_due": str(before_balance_due),
        },
        after_value={
            "invoice_id": str(invoice_id),
            "invoice_status": new_status,
            "payment_amount": str(amount),
            "amount_paid": str(invoice.amount_paid),
            "balance_due": str(invoice.balance_due),
            "payment_id": str(payment.id),
        },
        ip_address=ip_address,
    )

    # Auto-post journal entry for the payment (Req 4.2, 4.6, 4.7)
    try:
        from app.modules.ledger.auto_poster import auto_post_payment
        await auto_post_payment(db, payment, invoice, user_id)
    except Exception as exc:
        logger.warning(
            "Auto-post failed for payment %s: %s", payment.id, exc
        )

    # Auto-sweep tax portions into wallets (Req 21.1, 21.2, 21.4, 21.5)
    try:
        from app.modules.tax_wallets.service import sweep_on_payment
        await sweep_on_payment(
            db,
            org_id=org_id,
            payment_amount=amount,
            payment_id=payment.id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "Tax auto-sweep failed for payment %s: %s", payment.id, exc
        )

    return {
        "payment": {
            "id": payment.id,
            "org_id": payment.org_id,
            "invoice_id": payment.invoice_id,
            "amount": payment.amount,
            "method": payment.method,
            "recorded_by": payment.recorded_by,
            "created_at": payment.created_at,
            "notes": notes,
            "invoice_status": invoice.status,
            "invoice_balance_due": invoice.balance_due,
            "invoice_amount_paid": invoice.amount_paid,
        },
        "message": (
            "Payment recorded. Invoice is now paid."
            if new_status == "paid"
            else f"Payment recorded. Remaining balance: {invoice.balance_due}"
        ),
    }


async def generate_stripe_payment_link(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal | None = None,
    send_via: str = "none",
    ip_address: str | None = None,
) -> dict:
    """Generate a Stripe Checkout Session payment link for an invoice.

    - Validates invoice exists and belongs to org
    - Validates org has a connected Stripe account
    - Supports partial payments for deposit scenarios (Req 25.5)
    - Optionally sends the link via email or SMS (Req 25.3)

    Requirements: 25.3, 25.5
    """
    from app.modules.admin.models import Organisation
    from app.modules.customers.models import Customer
    from app.integrations.stripe_connect import create_payment_link

    # Fetch invoice scoped to org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Only allow payment links on payable invoices
    if invoice.status not in ("issued", "partially_paid", "overdue"):
        raise ValueError(
            f"Cannot generate payment link for invoice with status "
            f"'{invoice.status}'. Invoice must be issued, partially paid, "
            f"or overdue."
        )

    # Determine payment amount
    pay_amount = amount if amount is not None else invoice.balance_due
    if pay_amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    if pay_amount > invoice.balance_due:
        raise ValueError(
            f"Payment amount ({pay_amount}) exceeds invoice balance due "
            f"({invoice.balance_due})"
        )

    # Fetch organisation to get Stripe Connect account
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")
    if not org.stripe_connect_account_id:
        raise ValueError(
            "Organisation has not connected a Stripe account. "
            "Please complete Stripe Connect setup first."
        )

    # Convert to smallest currency unit (cents)
    amount_cents = int(pay_amount * 100)

    # Calculate application fee if configured (Req 7.1, 7.2)
    from app.integrations.stripe_billing import get_application_fee_percent

    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(amount_cents * fee_percent / 100)

    # Create Stripe Checkout Session
    stripe_result = await create_payment_link(
        amount=amount_cents,
        currency=invoice.currency,
        invoice_id=str(invoice.id),
        stripe_account_id=org.stripe_connect_account_id,
        application_fee_amount=application_fee_amount,
    )

    payment_url = stripe_result["payment_url"]

    # Optionally send the link via email or SMS
    if send_via == "email":
        customer_result = await db.execute(
            select(Customer).where(Customer.id == invoice.customer_id)
        )
        customer = customer_result.scalar_one_or_none()
        if customer and customer.email:
            # Dispatch email asynchronously (best-effort)
            try:
                await _send_receipt_email(
                    db,
                    to_email=customer.email,
                    invoice=invoice,
                    pay_amount=pay_amount,
                )
            except Exception as exc:
                logger.warning("Failed to send payment link email for invoice %s: %s", invoice.id, exc)
    elif send_via == "sms":
        customer_result = await db.execute(
            select(Customer).where(Customer.id == invoice.customer_id)
        )
        customer = customer_result.scalar_one_or_none()
        if customer and customer.phone:
            try:
                import json as _json

                from app.core.encryption import envelope_decrypt_str
                from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
                from app.integrations.sms_types import SmsMessage
                from app.modules.admin.models import SmsVerificationProvider

                stmt = select(SmsVerificationProvider).where(
                    SmsVerificationProvider.provider_key == "connexus",
                    SmsVerificationProvider.is_active == True,
                )
                prov_result = await db.execute(stmt)
                provider = prov_result.scalar_one_or_none()

                if provider and provider.credentials_encrypted:
                    creds = _json.loads(envelope_decrypt_str(provider.credentials_encrypted))
                    if provider.config and provider.config.get("token_refresh_interval_seconds"):
                        creds["token_refresh_interval_seconds"] = provider.config["token_refresh_interval_seconds"]
                    config = ConnexusConfig.from_dict(creds)
                    client = ConnexusSmsClient(config)

                    sms = SmsMessage(
                        to_number=customer.phone,
                        body=(
                            f"Payment link for invoice "
                            f"{invoice.invoice_number or invoice.id}: "
                            f"{payment_url}"
                        ),
                    )
                    await client.send(sms)
                else:
                    logger.warning(
                        "Connexus SMS provider not configured — skipping SMS for invoice %s",
                        invoice.id,
                    )
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.warning("Failed to send payment link SMS for invoice %s: %s", invoice.id, exc)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payment.stripe_link_generated",
        entity_type="invoice",
        entity_id=invoice.id,
        after_value={
            "invoice_id": str(invoice.id),
            "amount": str(pay_amount),
            "currency": invoice.currency,
            "send_via": send_via,
            "session_id": stripe_result["session_id"],
        },
        ip_address=ip_address,
    )

    return {
        "payment_url": payment_url,
        "invoice_id": invoice.id,
        "amount": pay_amount,
        "send_via": send_via,
    }


async def send_invoice_payment_link_email(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    base_url: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Email the customer the existing on-domain payment page URL for an invoice.

    Unlike ``generate_stripe_payment_link`` (which creates a Stripe Checkout
    Session and redirects to the Stripe-hosted page), this function uses the
    invoice's ``payment_page_url`` — the token-based public payment page on
    the org's own domain (served by ``invoices/public_router.py`` and backed
    by a Stripe PaymentIntent created via ``_maybe_create_stripe_payment_intent``).

    Flow:
    1. Validate invoice is in a payable state (issued / partially_paid / overdue).
    2. Ensure ``payment_page_url`` exists; regenerate via the same path used
       on issue if it's missing or stale.
    3. Email the link using the org's active ``invoice_issued`` template
       (or the default template with a Pay Now button).

    Reuses the same notification template, email provider, and PaymentIntent
    plumbing as ``email_invoice`` and ``_maybe_create_stripe_payment_intent``.
    No Stripe Checkout Session is created.

    Requirements: 25.3, 25.5
    """
    from app.modules.admin.models import Organisation
    from app.modules.customers.models import Customer
    from app.modules.invoices.service import _maybe_create_stripe_payment_intent

    # Fetch invoice scoped to org
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    if invoice.status not in ("issued", "partially_paid", "overdue"):
        raise ValueError(
            f"Cannot send payment link for invoice with status "
            f"'{invoice.status}'. Invoice must be issued, partially paid, "
            f"or overdue."
        )

    if invoice.balance_due is None or invoice.balance_due <= 0:
        raise ValueError("Invoice has no outstanding balance.")

    # Customer must have an email on file
    cust_result = await db.execute(
        select(Customer).where(Customer.id == invoice.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None or not customer.email:
        raise ValueError(
            "Customer has no email address on file. Cannot send payment link."
        )

    # Org must be Stripe-connected so the payment page can take payments
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None or not getattr(org, "stripe_connect_account_id", None):
        raise ValueError(
            "Organisation has not connected a Stripe account. "
            "Please complete Stripe Connect setup first."
        )

    # Ensure payment_page_url exists / is current. The same helper used on
    # issue regenerates it when missing or stale (e.g. if FRONTEND_BASE_URL
    # changed).  We tag the invoice so the helper proceeds even if it
    # wasn't set up with payment_gateway=stripe at creation time.
    inv_data = dict(invoice.invoice_data_json or {})
    if inv_data.get("payment_gateway") != "stripe":
        inv_data["payment_gateway"] = "stripe"
        invoice.invoice_data_json = inv_data
        flag_modified(invoice, "invoice_data_json")
        await db.flush()

    if not invoice.payment_page_url:
        await _maybe_create_stripe_payment_intent(
            db, invoice, org, base_url=base_url,
        )
        await db.refresh(invoice)

    if not invoice.payment_page_url:
        raise ValueError(
            "Failed to generate payment link. Please try again or check "
            "Stripe Connect configuration."
        )

    # Send the email using the invoice_issued template (default has a
    # Pay Now button; custom templates configured in Settings → Templates
    # are honoured automatically).
    await _send_receipt_email(
        db,
        to_email=customer.email,
        invoice=invoice,
        pay_amount=invoice.balance_due,
        template_type="invoice_issued",
        payment_url=invoice.payment_page_url,
    )

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payment.payment_link_emailed",
        entity_type="invoice",
        entity_id=invoice.id,
        after_value={
            "invoice_id": str(invoice.id),
            "recipient_email": customer.email,
            "payment_page_url": invoice.payment_page_url,
        },
        ip_address=ip_address,
    )

    return {
        "invoice_id": invoice.id,
        "recipient_email": customer.email,
        "payment_page_url": invoice.payment_page_url,
    }


_METHOD_DISPLAY_NAMES: dict[str, str] = {
    "card": "Credit/Debit Card",
    "afterpay_clearpay": "Afterpay",
    "klarna": "Klarna",
    "bank_transfer": "Bank Transfer",
}


def _payment_method_display_name(method_type: str) -> str:
    """Return a human-friendly label for a Stripe payment method type."""
    return _METHOD_DISPLAY_NAMES.get(method_type, method_type.replace("_", " ").title())


async def _send_receipt_email(
    db: AsyncSession,
    *,
    to_email: str,
    invoice: Invoice,
    pay_amount: Decimal,
    surcharge_amount: Decimal = Decimal("0"),
    payment_method_type: str | None = None,
    template_type: str = "payment_received",
    payment_url: str | None = None,
) -> None:
    """Send a payment-related email via the unified sender.

    Dispatch goes through :mod:`app.integrations.email_sender` —
    failover, error classification, and per-attempt + total time
    budgets are all handled inside ``send_email``. This was migrated
    from a hand-rolled ``smtplib`` provider loop in Phase 3 task 3.4
    (A4).

    Reuses the org's email provider infrastructure (same as
    ``email_invoice``) and resolves the customer's active notification
    template (or default).

    Two call modes:

    - ``template_type="payment_received"`` (default): post-payment
      receipt. Body summarises payment details. ``payment_url`` is
      ignored.
    - ``template_type="invoice_issued"``: payment-link request. The
      Stripe payment URL is exposed to the template as the
      ``{{payment_link}}`` variable, so the user's active
      ``invoice_issued`` template (or the default one with a Pay Now
      button) renders correctly.

    The invoice PDF is attached so the customer always has a copy.
    Best-effort: logs warnings on failure and surfaces an in-app
    notification, but does not raise.

    Requirements: 6.1, 6.3, 6.4
    """
    from app.integrations.email_sender import (
        EmailAttachment,
        EmailMessage,
        send_email,
    )
    from app.modules.admin.models import Organisation

    # Get org name for the email
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == invoice.org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Your Company"

    inv_number = invoice.invoice_number or str(invoice.id)
    currency = invoice.currency or "NZD"

    # --- Template resolution for payment_received ---
    from app.modules.notifications.service import resolve_template
    from app.modules.invoices.service import get_currency_symbol
    from app.modules.customers.models import Customer

    # Fetch customer for variable context
    _cust_result = await db.execute(
        select(Customer).where(Customer.id == invoice.customer_id)
    )
    _customer = _cust_result.scalar_one_or_none()
    _customer_first_name = _customer.first_name if _customer else ""
    _customer_last_name = _customer.last_name if _customer else ""

    # Format monetary value using payment currency
    _currency_symbol = get_currency_symbol(currency)
    _total_due_formatted = f"{_currency_symbol}{pay_amount:.2f}"

    # Get org contact details from settings
    _org_settings = org.settings if org else {}
    _org_email = _org_settings.get("email") or _org_settings.get("business_email") or ""
    _org_phone = _org_settings.get("phone") or _org_settings.get("business_phone") or ""

    _template_variables = {
        "customer_first_name": _customer_first_name,
        "customer_last_name": _customer_last_name,
        "customer_email": _customer.email if _customer else "",
        "invoice_number": inv_number,
        "total_due": _total_due_formatted,
        "payment_link": payment_url or invoice.payment_page_url or "",
        "due_date": str(invoice.due_date) if invoice.due_date else "",
        "org_name": org_name,
        "org_email": _org_email,
        "org_phone": _org_phone,
    }

    _rendered_template = await resolve_template(
        db,
        org_id=invoice.org_id,
        template_type=template_type,
        channel="email",
        variables=_template_variables,
    )

    # Generate the invoice PDF with updated payment status
    pdf_bytes: bytes | None = None
    try:
        from app.modules.invoices.service import generate_invoice_pdf
        pdf_bytes = await generate_invoice_pdf(
            db, org_id=invoice.org_id, invoice_id=invoice.id,
        )
    except Exception as exc:
        logger.warning("Failed to generate PDF for receipt email (invoice %s): %s", invoice.id, exc)

    # Find org name for default subject/body fallbacks (provider lookup
    # now happens inside send_email).
    _link_for_body = ""
    if _rendered_template:
        subject = _rendered_template.subject
        body = _rendered_template.body
    elif template_type == "invoice_issued":
        # Fallback when the invoice_issued template can't be resolved —
        # used for the "Send Payment Link" flow.
        subject = f"Payment link for invoice {inv_number} from {org_name}"
        _link_for_body = payment_url or invoice.payment_page_url or ""
        body = (
            f"Hi,\n\n"
            f"Here is the secure online payment link for invoice {inv_number}.\n\n"
            f"Amount due: {currency} {pay_amount}\n\n"
            f"You can pay securely online using the button below.\n\n"
            f"If you have any questions, please don't hesitate to contact us.\n\n"
            f"Kind regards,\n"
            f"{org_name}\n"
        )
    else:
        # Existing hardcoded content for payment_received (unchanged)
        subject = f"Payment receipt for invoice {inv_number}"

        if surcharge_amount > 0:
            method_label = _payment_method_display_name(payment_method_type or "")
            body = (
                f"Hi,\n\n"
                f"Thank you for your payment.\n\n"
                f"Invoice: {inv_number}\n"
                f"Invoice amount: {currency} {pay_amount}\n"
                f"Payment method surcharge ({method_label}): {currency} {surcharge_amount}\n"
                f"Total paid: {currency} {pay_amount + surcharge_amount}\n"
                f"Remaining balance: {currency} {invoice.balance_due}\n\n"
                f"Thank you for your business.\n\n"
                f"{org_name}\n"
            )
        else:
            body = (
                f"Hi,\n\n"
                f"Thank you for your payment of {currency} {pay_amount}.\n\n"
                f"Invoice: {inv_number}\n"
                f"Amount paid: {currency} {pay_amount}\n"
                f"Remaining balance: {currency} {invoice.balance_due}\n\n"
                f"Thank you for your business.\n\n"
                f"{org_name}\n"
            )

    # PDF is NOT attached to avoid Gmail's content filter silently
    # dropping emails with financial PDF attachments. Customers can
    # view/download the invoice via the payment page link instead.
    _email_attachments: list[EmailAttachment] = []

    # The plain-text body is converted to HTML via the unified
    # transactional-HTML renderer so receipts carry a well-formed
    # document (proper <!DOCTYPE>, paragraph structure, <a href> for
    # any embedded URLs) — matches the deliverability fix on A1
    # (email_invoice).
    from app.integrations.email_sender import render_transactional_html
    _cta_url_for_receipt = (
        _link_for_body if template_type == "invoice_issued" and _link_for_body else None
    )
    _html_body = render_transactional_html(
        body, subject=subject,
        cta_url=_cta_url_for_receipt,
        cta_label="Pay Now" if _cta_url_for_receipt else None,
    )

    _message = EmailMessage(
        to_email=to_email,
        to_name="",
        subject=subject,
        html_body=_html_body,
        text_body=body,
        attachments=_email_attachments,
        org_id=invoice.org_id,
    )
    result = await send_email(db, _message)

    if result.success:
        logger.info(
            "Sent payment receipt email for invoice %s to %s via %s",
            invoice.id, to_email, result.provider_key,
        )
        # Success-path notification_log row (Bug 1 / Requirement 3.1).
        # Best-effort: matches the surrounding site's tolerance to logging
        # failures (this function does not raise on send failure either).
        from app.modules.notifications.service import log_email_sent as _log_email_sent
        try:
            await _log_email_sent(
                db, org_id=invoice.org_id, recipient=to_email,
                template_type="payment_receipt", subject=subject,
                status="sent", channel="email",
                provider_key=result.provider_key,
                provider_message_id=result.provider_message_id,
            )
        except Exception:
            logger.warning(
                "Failed to log success for payment receipt email (invoice %s)",
                invoice.id,
            )
        return

    last_error = result.error or "send failed"
    logger.warning(
        "All email providers failed for receipt email (invoice %s): %s",
        invoice.id, last_error,
    )
    await create_in_app_notification(
        db,
        org_id=invoice.org_id,
        category="email_failure",
        severity="error",
        title=f"Failed to email payment receipt for invoice {inv_number} to {to_email}",
        body=f"All email providers failed when sending payment receipt to {to_email}."[:1500],
        link_url=f"/invoices/{invoice.id}",
        entity_type="invoice",
        entity_id=invoice.id,
        audience_roles=["org_admin"],
        metadata={
            "recipient_email": to_email,
            "template_type": "payment_receipt",
            "error_message": str(last_error),
        },
    )


async def handle_stripe_webhook(
    db: AsyncSession,
    *,
    event_type: str,
    event_data: dict,
) -> dict:
    """Process a Stripe webhook event.

    Handles ``checkout.session.completed`` and ``payment_intent.succeeded`` events:
    - Creates a Payment record with method='stripe'
    - Updates invoice amount_paid, balance_due, and status
    - Sends a best-effort payment receipt email

    Parameters
    ----------
    db:
        Active async database session.
    event_type:
        The Stripe event type string (e.g. ``"checkout.session.completed"``
        or ``"payment_intent.succeeded"``).
    event_data:
        The ``data.object`` portion of the Stripe event payload.

    Returns
    -------
    dict
        Summary of the action taken.

    Requirements: 25.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
    """
    if event_type not in ("checkout.session.completed", "payment_intent.succeeded"):
        return {"status": "ignored", "reason": f"Unhandled event type: {event_type}"}

    obj = event_data
    metadata = obj.get("metadata", {})
    invoice_id_str = metadata.get("invoice_id")

    if not invoice_id_str:
        return {"status": "ignored", "reason": "No invoice_id in session metadata"}

    try:
        invoice_id = uuid.UUID(invoice_id_str)
    except (ValueError, TypeError):
        return {"status": "error", "reason": f"Invalid invoice_id: {invoice_id_str}"}

    # Extract amount and payment intent ID based on event type
    if event_type == "payment_intent.succeeded":
        # PaymentIntent object: amount in `amount_received` (cents), PI ID is `id`
        amount_cents = obj.get("amount_received", 0)
        stripe_payment_intent = obj.get("id", "")
    else:
        # Checkout Session object: amount in `amount_total` (cents), PI ID in `payment_intent`
        amount_cents = obj.get("amount_total", 0)
        stripe_payment_intent = obj.get("payment_intent", "")

    # Detect QR payment source (Req 8.1, 8.3, 8.4, 8.5)
    source = metadata.get("source", "")
    is_qr_payment = source == "kiosk_qr"

    # Extract surcharge info from PaymentIntent metadata (Req 6.1, 6.4)
    surcharge_str = metadata.get("surcharge_amount", "0")
    surcharge_method = metadata.get("surcharge_method", "")
    original_amount_str = metadata.get("original_amount")
    try:
        surcharge = Decimal(surcharge_str)
    except Exception:
        surcharge = Decimal("0")

    # The PI amount includes surcharge, but we record them separately.
    # Use original_amount from metadata (the invoice balance_due before surcharge);
    # fall back to subtracting surcharge from the total if metadata is missing.
    if original_amount_str:
        try:
            amount = Decimal(original_amount_str)
        except Exception:
            amount = Decimal(amount_cents) / Decimal("100") - surcharge
    else:
        amount = Decimal(amount_cents) / Decimal("100") - surcharge

    # Fetch invoice with FOR UPDATE lock to serialize concurrent webhook handlers
    # for the same invoice (prevents duplicate payment race condition)
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        return {"status": "error", "reason": f"Invoice {invoice_id} not found"}

    # Only process payments on payable invoices
    if invoice.status not in ("issued", "partially_paid", "overdue"):
        return {
            "status": "ignored",
            "reason": f"Invoice status '{invoice.status}' is not payable",
        }

    # Idempotency check — prevent duplicate payments (Req 6.6)
    # The FOR UPDATE lock on the invoice row above ensures only one concurrent
    # handler proceeds past this point for the same invoice.
    if stripe_payment_intent:
        existing = await db.execute(
            select(Payment).where(
                Payment.stripe_payment_intent_id == stripe_payment_intent,
                Payment.is_refund == False,  # noqa: E712
            )
        )
        if existing.scalar_one_or_none() is not None:
            return {"status": "ignored", "reason": "Duplicate event"}

    # Cap payment at balance_due to avoid overpayment
    pay_amount = min(amount, invoice.balance_due)
    if pay_amount <= 0:
        return {"status": "ignored", "reason": "Payment amount is zero or negative"}

    # Capture before state for audit
    before_status = invoice.status
    before_amount_paid = invoice.amount_paid
    before_balance_due = invoice.balance_due

    # Create payment record with surcharge breakdown (Req 6.1, 6.3)
    # For QR payments, set payment_method_type to "qr_checkout" (Req 8.1)
    if is_qr_payment:
        effective_payment_method_type = "qr_checkout"
    else:
        effective_payment_method_type = surcharge_method or None

    payment = Payment(
        org_id=invoice.org_id,
        invoice_id=invoice.id,
        amount=pay_amount,
        surcharge_amount=surcharge,
        payment_method_type=effective_payment_method_type,
        method="stripe",
        stripe_payment_intent_id=stripe_payment_intent,
        recorded_by=invoice.created_by,  # system-initiated; attribute to invoice creator
    )
    db.add(payment)
    await db.flush()

    # Update invoice balances
    invoice.amount_paid = invoice.amount_paid + pay_amount
    invoice.balance_due = invoice.balance_due - pay_amount

    # Determine new status
    if invoice.balance_due == Decimal("0"):
        new_status = "paid"
    else:
        new_status = "partially_paid"

    _validate_transition(invoice.status, new_status)
    invoice.status = new_status

    await db.flush()

    # Audit log (system-initiated — no user_id)
    await write_audit_log(
        session=db,
        org_id=invoice.org_id,
        action="payment.stripe_webhook_received",
        entity_type="payment",
        entity_id=payment.id,
        before_value={
            "invoice_id": str(invoice.id),
            "invoice_status": before_status,
            "amount_paid": str(before_amount_paid),
            "balance_due": str(before_balance_due),
        },
        after_value={
            "invoice_id": str(invoice.id),
            "invoice_status": new_status,
            "payment_amount": str(pay_amount),
            "surcharge_amount": str(surcharge),
            "payment_method_type": effective_payment_method_type,
            "amount_paid": str(invoice.amount_paid),
            "balance_due": str(invoice.balance_due),
            "payment_id": str(payment.id),
            "stripe_payment_intent": stripe_payment_intent,
        },
    )

    # Auto-post journal entry for the Stripe payment (Req 4.2, 4.6, 4.7)
    try:
        from app.modules.ledger.auto_poster import auto_post_payment
        await auto_post_payment(db, payment, invoice, invoice.created_by)
    except Exception as exc:
        logger.warning(
            "Auto-post failed for Stripe payment %s: %s", payment.id, exc
        )

    # Clear pending QR session if this was a kiosk QR payment (Req 8.5)
    if is_qr_payment:
        try:
            # Use session_id from the checkout session object (the Stripe session ID)
            checkout_session_id = obj.get("id", "")
            org_id_str = metadata.get("org_id")
            if checkout_session_id:
                await clear_pending_qr_session(db, session_id=checkout_session_id)
            elif org_id_str:
                try:
                    qr_org_id = uuid.UUID(org_id_str)
                    await clear_pending_qr_session(db, org_id=qr_org_id)
                except (ValueError, TypeError):
                    logger.warning(
                        "Invalid org_id in QR payment metadata: %s", org_id_str
                    )
        except Exception as exc:
            logger.warning(
                "Failed to clear pending QR session for payment %s: %s",
                payment.id, exc,
            )

    # Clear stale invoice PI fields on the success path (Task 18.1 — qr-partial-payment).
    # After a successful payment the PaymentIntent is in a terminal state
    # (succeeded or canceled) and Stripe rejects further updates with
    # `payment_intent_unexpected_state`. Without this cleanup, the next
    # QR-payment click for this invoice (e.g. the second partial in a
    # multi-partial settlement) enters the reuse-branch in
    # create_qr_session_for_existing_invoice, finds a non-null
    # `invoice.stripe_payment_intent_id` and an active `payment_token`,
    # tries to reuse — and any subsequent `update-surcharge` call from the
    # customer fails on Stripe. Wiping these fields forces the next QR
    # session to create a fresh PaymentIntent + token.
    from sqlalchemy import update as sa_update
    from app.modules.payments.models import PaymentToken

    invoice.stripe_payment_intent_id = None
    invoice.payment_page_url = None
    inv_json = dict(invoice.invoice_data_json or {})
    inv_json.pop("stripe_client_secret", None)
    invoice.invoice_data_json = inv_json
    flag_modified(invoice, "invoice_data_json")
    await db.flush()

    # Deactivate all active payment_tokens for this invoice (Task 18.2 —
    # qr-partial-payment). Closes a re-scan gap on the just-paid URL: without
    # this, the URL stays active for its 72-hour TTL, and a re-scan in the
    # window between payment-completion and the next partial being initiated
    # would render `is_payable=true` with `client_secret=None` (because Task
    # 18.1 cleared the PI fields), leaving the customer with a broken Stripe
    # Elements form. Deactivation here means subsequent scans return a clean
    # HTTP 404 "Invalid payment link" instead. The next partial generates a
    # fresh active token via `generate_payment_token`, which already
    # deactivates active tokens on insert — the just-paid one is safely
    # retired here.
    await db.execute(
        sa_update(PaymentToken)
        .where(
            PaymentToken.invoice_id == invoice.id,
            PaymentToken.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )
    await db.flush()

    # Best-effort payment receipt email (non-blocking)
    try:
        from app.modules.customers.models import Customer

        cust_result = await db.execute(
            select(Customer).where(Customer.id == invoice.customer_id)
        )
        customer = cust_result.scalar_one_or_none()
        if customer and customer.email:
            await _send_receipt_email(
                db,
                to_email=customer.email,
                invoice=invoice,
                pay_amount=pay_amount,
                surcharge_amount=surcharge,
                payment_method_type=surcharge_method or None,
            )
    except Exception as exc:
        logger.warning("Failed to send payment receipt email for invoice %s: %s", invoice.id, exc)

    return {
        "status": "processed",
        "payment_id": str(payment.id),
        "invoice_id": str(invoice.id),
        "invoice_status": new_status,
        "amount": str(pay_amount),
        "surcharge_amount": str(surcharge),
        "payment_method_type": effective_payment_method_type,
    }


async def get_payment_history(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> dict:
    """Return the full payment history for an invoice.

    Returns all payment and refund records ordered by creation date,
    along with computed totals.

    Requirements: 26.1
    """
    # Verify invoice exists and belongs to org
    inv_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Fetch all payments for this invoice, ordered by date
    pay_result = await db.execute(
        select(Payment)
        .where(
            Payment.invoice_id == invoice_id,
            Payment.org_id == org_id,
        )
        .order_by(Payment.created_at.asc())
    )
    payments = list(pay_result.scalars().all())

    total_paid = Decimal("0")
    total_refunded = Decimal("0")
    for p in payments:
        if p.is_refund:
            total_refunded += p.amount
        else:
            total_paid += p.amount

    return {
        "invoice_id": invoice_id,
        "payments": payments,
        "total_paid": total_paid,
        "total_refunded": total_refunded,
        "net_paid": total_paid - total_refunded,
    }


async def process_refund(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal,
    method: str,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Process a refund (cash or Stripe) against an invoice.

    - For Stripe refunds: finds the original Stripe payment, calls the
      Stripe Refund API, then records the refund locally.
    - For cash refunds: records the refund with a note.
    - Updates invoice balance_due and amount_paid.
    - Writes audit log entry.

    Requirements: 26.2, 26.3, 26.4
    """
    from app.modules.admin.models import Organisation
    from app.integrations.stripe_connect import create_stripe_refund

    # Fetch invoice scoped to org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Only allow refunds on invoices that have received payments
    if invoice.status not in ("paid", "partially_paid", "overdue", "refunded", "partially_refunded"):
        raise ValueError(
            f"Cannot refund invoice with status '{invoice.status}'. "
            "Invoice must be paid, partially paid, overdue, or refunded."
        )

    # Validate refund amount
    if amount <= 0:
        raise ValueError("Refund amount must be greater than zero")
    if amount > invoice.amount_paid:
        raise ValueError(
            f"Refund amount ({amount}) exceeds total amount paid "
            f"({invoice.amount_paid})"
        )

    # Capture before state for audit
    before_status = invoice.status
    before_amount_paid = invoice.amount_paid
    before_balance_due = invoice.balance_due

    stripe_refund_id = None

    # Process Stripe refund via API (Req 26.2)
    if method == "stripe":
        # Find the original Stripe payment for this invoice
        stripe_pay_result = await db.execute(
            select(Payment).where(
                Payment.invoice_id == invoice_id,
                Payment.org_id == org_id,
                Payment.method == "stripe",
                Payment.is_refund == False,  # noqa: E712
            ).order_by(Payment.created_at.desc())
        )
        stripe_payment = stripe_pay_result.scalar_one_or_none()
        if stripe_payment is None or not stripe_payment.stripe_payment_intent_id:
            raise ValueError(
                "No Stripe payment found for this invoice. "
                "Use 'cash' method for manual refund."
            )

        # Get org's Stripe Connect account
        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is None or not org.stripe_connect_account_id:
            raise ValueError("Organisation has no connected Stripe account")

        # Call Stripe Refund API
        amount_cents = int(amount * 100)
        stripe_result = await create_stripe_refund(
            payment_intent_id=stripe_payment.stripe_payment_intent_id,
            amount=amount_cents,
            stripe_account_id=org.stripe_connect_account_id,
        )
        stripe_refund_id = stripe_result.get("refund_id")

    # Create refund payment record
    refund_record = Payment(
        org_id=org_id,
        invoice_id=invoice_id,
        amount=amount,
        method=method,
        is_refund=True,
        refund_note=notes,
        stripe_payment_intent_id=stripe_refund_id,
        recorded_by=user_id,
    )
    db.add(refund_record)
    await db.flush()

    # Update invoice balances
    # Refund reduces amount_paid but does NOT increase balance_due.
    # The customer does not owe more money after a refund — the business
    # is paying back. balance_due stays at 0 for fully-paid invoices.
    invoice.amount_paid = invoice.amount_paid - amount

    # Determine new status based on refund
    total_payments = invoice.amount_paid  # net after refund
    if total_payments <= Decimal("0"):
        # Full refund — everything paid has been refunded
        new_status = "refunded"
        invoice.amount_paid = Decimal("0")
    elif total_payments < invoice.total:
        # Partial refund — some amount still retained
        new_status = "partially_refunded"
    else:
        new_status = "paid"

    # Apply status transition (paid→issued is a refund-specific path)
    invoice.status = new_status
    await db.flush()

    # Audit log (Req 26.4)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payment.refund_processed",
        entity_type="payment",
        entity_id=refund_record.id,
        before_value={
            "invoice_id": str(invoice_id),
            "invoice_status": before_status,
            "amount_paid": str(before_amount_paid),
            "balance_due": str(before_balance_due),
        },
        after_value={
            "invoice_id": str(invoice_id),
            "invoice_status": new_status,
            "refund_amount": str(amount),
            "refund_method": method,
            "amount_paid": str(invoice.amount_paid),
            "balance_due": str(invoice.balance_due),
            "refund_id": str(refund_record.id),
            "stripe_refund_id": stripe_refund_id,
            "notes": notes,
        },
        ip_address=ip_address,
    )

    # Auto-post journal entry for the refund (Req 4.5, 4.6, 4.7)
    try:
        from app.modules.ledger.auto_poster import auto_post_refund
        await auto_post_refund(db, refund_record, invoice, user_id)
    except Exception as exc:
        logger.warning(
            "Auto-post failed for refund %s: %s", refund_record.id, exc
        )

    return {
        "refund": refund_record,
        "invoice_id": invoice.id,
        "invoice_status": invoice.status,
        "invoice_balance_due": invoice.balance_due,
        "invoice_amount_paid": invoice.amount_paid,
        "stripe_refund_id": stripe_refund_id,
        "message": (
            f"Refund of {amount} processed via {method}. "
            f"Invoice balance due: {invoice.balance_due}"
        ),
    }


async def create_qr_payment_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    line_items_data: list[dict],
    vehicle_rego: str | None = None,
    vehicle_make: str | None = None,
    vehicle_model: str | None = None,
    vehicle_year: int | None = None,
    vehicle_odometer: int | None = None,
    global_vehicle_id: uuid.UUID | None = None,
    vehicle_service_due_date=None,
    vehicle_wof_expiry_date=None,
    vehicle_cof_expiry_date=None,
    vehicles: list[dict] | None = None,
    branch_id: uuid.UUID | None = None,
    fluid_usage_data: list[dict] | None = None,
    notes_internal: str | None = None,
    notes_customer: str | None = None,
    terms_and_conditions: str | None = None,
    issue_date=None,
    due_date=None,
    payment_terms: str | None = None,
    discount_type: str | None = None,
    discount_value: "Decimal | None" = None,
    currency: str = "NZD",
    exchange_rate_to_nzd: "Decimal | None" = None,
    payment_gateway: str | None = None,
    ip_address: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a QR payment session: issue invoice + create PaymentIntent + token.

    Issues the invoice (status="sent" which maps to "issued" internally),
    creates a Stripe PaymentIntent on the Connected Account, generates a
    payment token for the custom payment page, stores the pending session
    in the DB, and returns session details for the frontend.

    Requirements: 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10,
                  3.1, 3.2, 10.1, 10.2, 10.3
    """
    import time
    from datetime import datetime as dt, timezone as tz

    from app.config import settings
    from app.integrations.stripe_billing import (
        get_application_fee_percent,
    )
    from app.modules.admin.models import Organisation
    from app.modules.invoices.service import create_invoice
    from app.modules.payments.models import PendingQrSession

    # 1. Issue the invoice (status="sent" maps to "issued" internally)
    invoice_result = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=vehicle_year,
        vehicle_odometer=vehicle_odometer,
        global_vehicle_id=global_vehicle_id,
        vehicle_service_due_date=vehicle_service_due_date,
        vehicle_wof_expiry_date=vehicle_wof_expiry_date,
        vehicle_cof_expiry_date=vehicle_cof_expiry_date,
        vehicles=vehicles,
        branch_id=branch_id,
        status="issued",
        line_items_data=line_items_data,
        fluid_usage_data=fluid_usage_data,
        notes_internal=notes_internal,
        notes_customer=notes_customer,
        due_date=due_date,
        issue_date=issue_date,
        payment_terms=payment_terms,
        discount_type=discount_type,
        discount_value=discount_value,
        currency=currency,
        exchange_rate_to_nzd=exchange_rate_to_nzd,
        terms_and_conditions=terms_and_conditions,
        payment_gateway=payment_gateway,
        ip_address=ip_address,
    )

    invoice_id = invoice_result["id"]
    invoice_number = invoice_result["invoice_number"]
    total = invoice_result["total"]

    # 2. Fetch org's stripe_connect_account_id
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")
    if not org.stripe_connect_account_id:
        raise ValueError(
            "Stripe Connect not configured for this organisation"
        )

    # 3. Calculate amount in cents and application fee
    amount_cents = int(total * 100)
    if amount_cents <= 0:
        raise ValueError("Invoice total must be greater than zero")

    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(amount_cents * fee_percent / 100)

    # 4. Create PaymentIntent on Connected Account
    #
    # Pass baseline metadata (source, original_amount, is_partial_payment)
    # at creation time so the webhook handler can detect this as a
    # kiosk-QR full payment without depending on the customer hitting
    # update-surcharge first. Closes the pre-existing detection-bug gap
    # where ``is_qr_payment`` was always False if the customer skipped
    # update-surcharge. Requirements: 4.3, 4.4.
    pi_result = await create_payment_intent(
        amount=amount_cents,
        currency=currency,
        invoice_id=str(invoice_id),
        stripe_account_id=org.stripe_connect_account_id,
        application_fee_amount=application_fee_amount,
        extra_metadata={
            "source": "kiosk_qr",
            "original_amount": str(total),
            "is_partial_payment": "false",
        },
    )

    # 5. Generate payment token + URL for custom payment page
    _resolved_base_url = (base_url or settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    token, payment_url = await generate_payment_token(
        db,
        org_id=org_id,
        invoice_id=invoice_id,
        base_url=_resolved_base_url,
    )

    # 6. Store PaymentIntent on invoice
    inv_result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice_obj = inv_result.scalar_one()
    invoice_obj.stripe_payment_intent_id = pi_result["payment_intent_id"]
    invoice_obj.payment_page_url = payment_url
    data_json = dict(invoice_obj.invoice_data_json or {})
    data_json["stripe_client_secret"] = pi_result["client_secret"]
    invoice_obj.invoice_data_json = data_json
    flag_modified(invoice_obj, "invoice_data_json")
    await db.flush()

    session_id = pi_result["payment_intent_id"]
    checkout_url = payment_url
    expires_at = int(time.time() + 1800)  # 30 minutes from now

    # 7. Convert expires_at to ISO string for frontend
    expires_at_iso = dt.fromtimestamp(expires_at, tz=tz.utc).isoformat()

    # 8. Upsert into pending_qr_sessions (DELETE existing for same org, then INSERT)
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(PendingQrSession).where(PendingQrSession.org_id == org_id)
    )
    await db.flush()

    pending_session = PendingQrSession(
        org_id=org_id,
        session_id=session_id,
        checkout_url=checkout_url,
        amount=total,
        invoice_number=invoice_number,
        invoice_id=invoice_id,
        expires_at=dt.fromtimestamp(expires_at, tz=tz.utc),
    )
    db.add(pending_session)
    await db.flush()
    await db.refresh(pending_session)

    # 9. Return session details
    return {
        "session_id": session_id,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "amount": total,
        "amount_cents": amount_cents,
        "expires_at": expires_at_iso,
        "currency": currency,
    }


async def _cancel_payment_intent(
    *,
    pi_id: str,
    stripe_account_id: str,
) -> dict:
    """Cancel a Stripe PaymentIntent on a connected account.

    Direct httpx call to ``POST /v1/payment_intents/{id}/cancel`` with the
    ``Stripe-Account`` header scoped to the org's connected account.
    Mirrors the auth/header pattern of ``expire_qr_session`` and the
    ``update_surcharge`` direct API call.

    Used by ``create_qr_session_for_existing_invoice`` (Req 5.3) to clean
    up the previous PaymentIntent when the staff member changes the
    requested amount on a follow-up QR Payment click. Cancellation is
    best-effort:

    - 5xx responses raise (transient Stripe outage — caller decides whether
      to retry or swallow).
    - 4xx responses are logged at WARNING and treated as success-shaped
      (PI already in a terminal state — ``canceled``, ``succeeded``, etc.).
      The merchant's Stripe dashboard already shows the correct state in
      that case so no follow-up action is required.

    Returns
    -------
    dict
        ``{"status": "canceled"}`` on success or for already-terminal PIs.

    Requirements: 5.3
    """
    import base64

    import httpx

    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError(
            "Stripe secret key not configured. Set it via Global Admin > Integrations."
        )

    auth_header = base64.b64encode(f"{secret_key}:".encode()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.stripe.com/v1/payment_intents/{pi_id}/cancel",
            headers={
                "Stripe-Account": stripe_account_id,
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"cancellation_reason": "abandoned"},
        )

    if response.status_code == 200:
        logger.info("Stripe PaymentIntent %s cancelled successfully", pi_id)
        return {"status": "canceled"}

    # Inspect error details if Stripe returned JSON.
    error_body: dict = {}
    if response.headers.get("content-type", "").startswith("application/json"):
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
    error_msg = (
        error_body.get("error", {}).get("message")
        or response.text[:200]
        or "unknown error"
    )

    if response.status_code >= 500:
        logger.error(
            "Stripe 5xx cancelling PaymentIntent %s: %s", pi_id, error_msg
        )
        raise RuntimeError(
            f"Failed to cancel PaymentIntent {pi_id}: {error_msg}"
        )

    # 4xx — PI already in a terminal state, or Stripe rejected for some
    # other client-side reason. Log + swallow so the new-session
    # creation can proceed (Req 5.3 — best-effort cancel, do not block
    # the new PI on cancellation success).
    logger.warning(
        "Stripe 4xx cancelling PaymentIntent %s (status %d): %s; continuing",
        pi_id,
        response.status_code,
        error_msg,
    )
    return {"status": "canceled"}


async def create_qr_session_for_existing_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    partial_amount: Decimal | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a QR payment session for an existing invoice.

    Unlike ``create_qr_payment_session`` (which creates a new invoice),
    this function takes an existing invoice (by ID) and creates a Stripe
    PaymentIntent + payment token for either:

    - The invoice's full ``balance_due`` when ``partial_amount`` is
      ``None`` (default; preserves pre-feature behaviour byte-for-byte).
    - A partial amount when ``partial_amount`` is provided. The amount
      is validated against the per-currency Stripe minimum and the
      invoice's outstanding balance before the PaymentIntent is created.

    The invoice status is NOT modified (no status change, no
    amount_paid change, no re-issue).

    Requirements: 2.3, 2.4, 3.1-3.7, 4.1-4.6, 5.1-5.4, 6.1, 9.1, 9.2, 9.3
    """
    import time
    from datetime import datetime as dt, timezone as tz

    from sqlalchemy import update as sa_update

    from app.config import settings
    from app.integrations.stripe_billing import (
        get_application_fee_percent,
    )
    from app.modules.admin.models import Organisation
    from app.modules.payments.models import PaymentToken, PendingQrSession

    # 1. Fetch invoice by ID scoped to org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # 2. Validate invoice status
    if invoice.status not in ("issued", "partially_paid", "overdue"):
        raise ValueError(
            f"Cannot create QR payment session for invoice with status "
            f"'{invoice.status}'. Invoice must be issued, partially paid, "
            f"or overdue."
        )

    # 3. Validate balance_due > 0
    if invoice.balance_due <= 0:
        raise ValueError("Invoice has no outstanding balance")

    # 4. Resolve billing amount and validate (Req 3.2-3.6).
    # Validation runs BEFORE the reuse-branch guard so partial-amount
    # requests pass through the validation gate first (Req 3.7) and never
    # silently return a stale full-balance session.
    currency = invoice.currency or "NZD"
    balance_due_quantized = invoice.balance_due.quantize(Decimal("0.01"))
    if partial_amount is None:
        resolved_amount = balance_due_quantized
        is_partial = False
    else:
        min_amount = stripe_min_for_currency(currency)
        if partial_amount < min_amount:
            raise ValueError(
                f"Partial amount must be at least ${min_amount} {currency}"
            )
        if partial_amount > balance_due_quantized:
            raise ValueError(
                f"Partial amount cannot exceed the outstanding balance "
                f"of ${balance_due_quantized}"
            )
        resolved_amount = partial_amount.quantize(Decimal("0.01"))
        is_partial = True

    target_cents = int(resolved_amount * 100)
    if target_cents <= 0:
        raise ValueError("Resolved billing amount must be greater than zero")

    # Capture the balance-due reading at request time for the audit log
    # (Req 9.1) before any subsequent flushes might touch the row.
    balance_due_at_request_time = invoice.balance_due

    # 5. Reuse-branch guard (Req 5.1, 5.2).
    # Compare the cached PI cents on the active payment_token
    # (``last_pi_amount_cents``, populated on every PI create or
    # update-surcharge call) to the requested ``target_cents``. Reuse
    # only when they match. Cache miss (NULL) is treated as "no existing
    # amount known" and falls through to the create-new path.
    #
    # Out-of-band edge case: a manual amount edit via the Stripe Dashboard
    # bypasses our code and leaves the cached value stale, in which case
    # the reuse decision could be wrong on the very next click. This is
    # accepted as a documented merchant workflow risk — Stripe Dashboard
    # manual edits are out-of-band by definition (qr-partial-payment design).
    existing_token: PaymentToken | None = None
    if invoice.payment_page_url and invoice.stripe_payment_intent_id:
        from datetime import datetime as _dt_check, timezone as _tz_check
        existing_token_result = await db.execute(
            select(PaymentToken).where(
                PaymentToken.invoice_id == invoice_id,
                PaymentToken.is_active == True,  # noqa: E712
                PaymentToken.expires_at > _dt_check.now(_tz_check.utc),
            )
        )
        existing_token = existing_token_result.scalar_one_or_none()
        if (
            existing_token is not None
            and existing_token.last_pi_amount_cents is not None
            and existing_token.last_pi_amount_cents == target_cents
        ):
            # Reuse path: refresh the pending_qr_sessions row only.
            # No new PaymentIntent, no new token, no audit log entry
            # (Req 9.2 — original creation already recorded the session).
            from sqlalchemy import delete as sa_delete

            invoice_number = invoice.invoice_number or str(invoice.id)
            session_id = invoice.stripe_payment_intent_id
            checkout_url = invoice.payment_page_url
            expires_at = int(time.time() + 1800)
            expires_at_iso = dt.fromtimestamp(expires_at, tz=tz.utc).isoformat()

            await db.execute(
                sa_delete(PendingQrSession).where(PendingQrSession.org_id == org_id)
            )
            await db.flush()

            pending_session = PendingQrSession(
                org_id=org_id,
                session_id=session_id,
                checkout_url=checkout_url,
                amount=resolved_amount,
                invoice_number=invoice_number,
                invoice_id=invoice_id,
                expires_at=dt.fromtimestamp(expires_at, tz=tz.utc),
            )
            db.add(pending_session)
            await db.flush()

            return {
                "session_id": session_id,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "amount": resolved_amount,
                "amount_cents": target_cents,
                "expires_at": expires_at_iso,
                "currency": currency,
            }

    # 6. Fetch org's stripe_connect_account_id
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")
    if not org.stripe_connect_account_id:
        raise ValueError(
            "Stripe Connect not configured for this organisation"
        )

    # 7. Cancel orphan PaymentIntent before creating a new one (Req 5.3).
    # Best-effort: log Stripe failures at WARNING and swallow so the new
    # session creation does not depend on cancellation success.
    old_pi_id: str | None = invoice.stripe_payment_intent_id
    if old_pi_id:
        try:
            await _cancel_payment_intent(
                pi_id=old_pi_id,
                stripe_account_id=org.stripe_connect_account_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to cancel orphan PaymentIntent %s: %s; continuing",
                old_pi_id,
                exc,
            )

    # 8. Compute application fee proportionally to the resolved amount
    # (Req 4.2 — partial fee scales with partial amount, never the full
    # balance).
    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(target_cents * fee_percent / 100)

    invoice_number = invoice.invoice_number or str(invoice.id)

    # 9. Create PaymentIntent on the Connected Account.
    #
    # Pass baseline metadata at creation time (Req 4.3, 4.4) so the
    # webhook can detect this as a kiosk-QR payment without depending
    # on update-surcharge to populate it. Sets ``original_amount`` to
    # the resolved amount and ``is_partial_payment`` to "true"/"false"
    # so audit-log filtering and downstream observers have an explicit
    # marker that doesn't require querying ``payment_tokens.amount_override``.
    pi_result = await create_payment_intent(
        amount=target_cents,
        currency=currency,
        invoice_id=str(invoice_id),
        stripe_account_id=org.stripe_connect_account_id,
        application_fee_amount=application_fee_amount,
        extra_metadata={
            "source": "kiosk_qr",
            "original_amount": str(resolved_amount),
            "is_partial_payment": "true" if is_partial else "false",
        },
    )

    new_pi_id = pi_result["payment_intent_id"]

    # 10. Generate a new payment_token (Req 6.1, 6.6).
    # ``generate_payment_token`` already deactivates any prior active
    # tokens for this invoice; we then explicitly mark the captured
    # ``existing_token`` inactive too via an atomic UPDATE (Req 5.4)
    # to make the intent obvious in code review.
    _resolved_base_url = (
        base_url or settings.frontend_base_url or "http://localhost:5173"
    ).rstrip("/")
    token, payment_url = await generate_payment_token(
        db,
        org_id=org_id,
        invoice_id=invoice_id,
        base_url=_resolved_base_url,
        amount_override=resolved_amount if is_partial else None,
    )

    if existing_token is not None:
        # Idempotent — generate_payment_token already flipped is_active
        # for active tokens on this invoice. Explicit per-id update for
        # atomicity and audit-trail clarity (Req 5.4).
        await db.execute(
            sa_update(PaymentToken)
            .where(PaymentToken.id == existing_token.id)
            .values(is_active=False)
        )
        await db.flush()

    # 11. Refresh the cached PI amount on the freshly-inserted token
    # row (Req 6.3.1) so the next reuse-branch decision can be made
    # without a synchronous Stripe API call. Updated by token primary
    # key for atomicity.
    await db.execute(
        sa_update(PaymentToken)
        .where(PaymentToken.token == token)
        .values(last_pi_amount_cents=target_cents)
    )
    await db.flush()

    # 12. Store PaymentIntent on the invoice.
    invoice.stripe_payment_intent_id = new_pi_id
    invoice.payment_page_url = payment_url
    data_json = dict(invoice.invoice_data_json or {})
    data_json["stripe_client_secret"] = pi_result["client_secret"]
    invoice.invoice_data_json = data_json
    flag_modified(invoice, "invoice_data_json")
    await db.flush()

    session_id = new_pi_id
    expires_at = int(time.time() + 1800)  # 30 minutes from now
    expires_at_iso = dt.fromtimestamp(expires_at, tz=tz.utc).isoformat()

    # 13. Upsert into pending_qr_sessions (DELETE existing for same org,
    # then INSERT). The pending session amount tracks the resolved
    # amount (Req 4.5), not the invoice's full balance.
    from sqlalchemy import delete as sa_delete

    await db.execute(
        sa_delete(PendingQrSession).where(PendingQrSession.org_id == org_id)
    )
    await db.flush()

    pending_session = PendingQrSession(
        org_id=org_id,
        session_id=session_id,
        checkout_url=payment_url,
        amount=resolved_amount,
        invoice_number=invoice_number,
        invoice_id=invoice_id,
        expires_at=dt.fromtimestamp(expires_at, tz=tz.utc),
    )
    db.add(pending_session)
    await db.flush()
    await db.refresh(pending_session)

    # 14. Audit log: payment.qr_session_superseded (Req 9.3).
    # Fires only when an old PaymentIntent was cancelled in step 7.
    if old_pi_id:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="payment.qr_session_superseded",
            entity_type="invoice",
            entity_id=invoice_id,
            before_value={"stripe_payment_intent_id": old_pi_id},
            after_value={
                "stripe_payment_intent_id": new_pi_id,
                "reason": "amount_changed",
            },
        )

    # 15. Audit log: payment.qr_session_created (Req 9.1).
    # Fires on every new-PI path (skipped on the reuse branch per Req 9.2).
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payment.qr_session_created",
        entity_type="invoice",
        entity_id=invoice_id,
        before_value=None,
        after_value={
            "stripe_payment_intent_id": new_pi_id,
            "amount": str(resolved_amount),
            "balance_due_at_request_time": str(balance_due_at_request_time),
            "is_partial_payment": is_partial,
        },
    )

    # 16. Return session details (invoice payment record is NOT modified).
    # The response amount is the resolved amount (Req 4.6) — the org user's
    # waiting popup displays this value, not the invoice balance.
    return {
        "session_id": session_id,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "amount": resolved_amount,
        "amount_cents": target_cents,
        "expires_at": expires_at_iso,
        "currency": currency,
    }


async def get_pending_qr_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict | None:
    """Retrieve the pending QR session for an organisation.

    Queries the pending_qr_sessions table for the given org_id.
    If the session exists but has expired (expires_at < now), deletes it
    and returns None. If the session exists but has been dismissed by
    the kiosk (``dismissed_at IS NOT NULL``), returns None — the row
    stays in the DB so the customer can still complete payment via
    their phone, but the kiosk popup does not re-appear on a refresh.
    If the session exists and is still valid, returns it as a dict.
    If no session exists, returns None.

    Requirements: 3.1, 4.1, 4.2, 4.3
    """
    from datetime import datetime, timezone

    from app.modules.payments.models import PendingQrSession

    result = await db.execute(
        select(PendingQrSession).where(PendingQrSession.org_id == org_id)
    )
    session = result.scalar_one_or_none()

    if session is None:
        return None

    # Check if session has expired
    if session.expires_at < datetime.now(timezone.utc):
        await db.delete(session)
        await db.flush()
        return None

    # Kiosk has dismissed the popup display for this session — hide it
    # from the kiosk poll. The Stripe PI + the row stay alive so a
    # customer who already scanned can complete payment from their phone.
    if session.dismissed_at is not None:
        return None

    return {
        "session_id": session.session_id,
        "checkout_url": session.checkout_url,
        "amount": session.amount,
        "invoice_number": session.invoice_number,
        "expires_at": session.expires_at.isoformat(),
        "created_at": session.created_at.isoformat(),
    }


async def dismiss_pending_qr_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: str,
) -> bool:
    """Mark a pending QR session as dismissed by the kiosk display.

    Soft-dismiss (sets ``dismissed_at = now()``) — the row + the
    underlying Stripe PaymentIntent are NOT touched. The customer who
    already scanned can complete payment from their phone; the kiosk
    poll just stops re-showing the popup.

    Scoped to org_id so a kiosk cannot dismiss another org's session.
    Returns True if the row was found and updated, False otherwise.

    Requirements: kiosk dismissal must not break in-flight customer payments.
    """
    from datetime import datetime, timezone

    from sqlalchemy import update as sa_update

    from app.modules.payments.models import PendingQrSession

    result = await db.execute(
        sa_update(PendingQrSession)
        .where(
            PendingQrSession.org_id == org_id,
            PendingQrSession.session_id == session_id,
            PendingQrSession.dismissed_at.is_(None),
        )
        .values(dismissed_at=datetime.now(timezone.utc))
        .returning(PendingQrSession.id)
    )
    await db.flush()
    return result.scalar_one_or_none() is not None


async def get_qr_session_status(
    db: AsyncSession,
    *,
    session_id: str,
    stripe_connect_account_id: str,
) -> dict:
    """Check the status of a Stripe Checkout Session or Payment Intent.

    Calls the Stripe API to retrieve the session/PI and returns a simplified
    status (open/complete/expired) along with the payment_intent ID if
    the session is complete.

    If session_id starts with "pi_" (payment intent ID), checks the local
    payments table first — if a payment exists for that PI, returns "complete"
    immediately without calling Stripe. This handles the race condition where
    the webhook records the payment before the frontend polls.

    Parameters
    ----------
    db:
        Active async database session.
    session_id:
        The Stripe Checkout Session ID (e.g. "cs_...") or Payment Intent
        ID (e.g. "pi_...").
    stripe_connect_account_id:
        The organisation's Stripe Connect account ID for the
        Stripe-Account header.

    Returns
    -------
    dict
        {"status": "open"|"complete"|"expired", "payment_intent_id": str|None}

    Raises
    ------
    ValueError
        If the session is not found (404 from Stripe) or Stripe returns
        an error.

    Requirements: 11.1, 11.2, 11.4
    """
    import httpx

    from app.integrations.stripe_billing import get_stripe_secret_key

    # If session_id is a payment intent ID, check local DB first
    if session_id.startswith("pi_"):
        existing_payment = await db.execute(
            select(Payment).where(
                Payment.stripe_payment_intent_id == session_id,
                Payment.is_refund == False,  # noqa: E712
            )
        )
        payment_row = existing_payment.scalar_one_or_none()
        if payment_row is not None:
            # Return the actual amount charged (payment amount + surcharge)
            amount_charged = float(payment_row.amount) + float(payment_row.surcharge_amount or 0)
            return {
                "status": "complete",
                "payment_intent_id": session_id,
                "amount_charged": amount_charged,
            }

        # Not in DB yet — check Stripe PaymentIntent API directly
        secret_key = await get_stripe_secret_key()
        if not secret_key:
            raise RuntimeError(
                "Stripe secret key not configured. Set it via Global Admin > Integrations."
            )

        import base64
        auth_header = base64.b64encode(f"{secret_key}:".encode()).decode()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.stripe.com/v1/payment_intents/{session_id}",
                headers={
                    "Stripe-Account": stripe_connect_account_id,
                    "Authorization": f"Basic {auth_header}",
                },
            )

        if response.status_code == 404:
            raise ValueError("Payment intent not found")

        if response.status_code != 200:
            error_body = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            error_msg = error_body.get("error", {}).get("message", response.text)
            raise ValueError(f"Failed to retrieve payment intent status: {error_msg}")

        pi_data = response.json()
        pi_status = pi_data.get("status", "")

        if pi_status == "succeeded":
            # amount_received is in cents
            amount_cents = pi_data.get("amount_received", 0)
            return {"status": "complete", "payment_intent_id": session_id, "amount_charged": amount_cents / 100}
        elif pi_status == "canceled":
            return {"status": "expired", "payment_intent_id": None, "amount_charged": None}
        else:
            return {"status": "open", "payment_intent_id": None, "amount_charged": None}

    # Standard path: session_id is a Checkout Session ID (cs_...)
    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError(
            "Stripe secret key not configured. Set it via Global Admin > Integrations."
        )

    import base64
    auth_header = base64.b64encode(f"{secret_key}:".encode()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
            headers={
                "Stripe-Account": stripe_connect_account_id,
                "Authorization": f"Basic {auth_header}",
            },
        )

    if response.status_code == 404:
        raise ValueError("Session not found")

    if response.status_code != 200:
        error_body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        error_msg = error_body.get("error", {}).get("message", response.text)
        logger.error(
            "Stripe session status check failed for session %s: %s",
            session_id,
            error_msg,
        )
        raise ValueError(f"Failed to retrieve session status: {error_msg}")

    session_data = response.json()

    # Map Stripe session status to simplified status
    stripe_status = session_data.get("status", "open")
    if stripe_status == "complete":
        status = "complete"
    elif stripe_status == "expired":
        status = "expired"
    else:
        status = "open"

    # Include payment_intent ID only when session is complete (Req 11.4)
    payment_intent_id: str | None = None
    if status == "complete":
        payment_intent_id = session_data.get("payment_intent")

    return {
        "status": status,
        "payment_intent_id": payment_intent_id,
    }


async def expire_qr_session(
    db: AsyncSession,
    *,
    session_id: str,
    stripe_connect_account_id: str,
) -> dict:
    """Expire a Stripe Checkout Session and remove the pending QR session.

    Calls the Stripe API to expire the session, then deletes the
    corresponding row from pending_qr_sessions. If Stripe returns an
    error because the session is already expired or complete, the error
    is handled gracefully and the DB row is still deleted.

    Parameters
    ----------
    db:
        Active async database session.
    session_id:
        The Stripe Checkout Session ID (e.g. "cs_...").
    stripe_connect_account_id:
        The organisation's Stripe Connect account ID for the
        Stripe-Account header.

    Returns
    -------
    dict
        {"status": "expired"}

    Requirements: 3.3
    """
    import httpx

    from sqlalchemy import delete as sa_delete

    from app.integrations.stripe_billing import get_stripe_secret_key
    from app.modules.payments.models import PendingQrSession

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError(
            "Stripe secret key not configured. Set it via Global Admin > Integrations."
        )

    # Call Stripe API to expire the session
    import base64
    auth_header = base64.b64encode(f"{secret_key}:".encode()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}/expire",
            headers={
                "Stripe-Account": stripe_connect_account_id,
                "Authorization": f"Basic {auth_header}",
            },
        )

    # Handle response — if session is already expired or complete,
    # Stripe returns a 400 with resource_already_expired or similar.
    # We handle this gracefully and still clean up the DB row.
    if response.status_code == 200:
        logger.info("Stripe session %s expired successfully", session_id)
    else:
        error_body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        error_code = error_body.get("error", {}).get("code", "")
        error_msg = error_body.get("error", {}).get("message", response.text)

        # Gracefully handle already-expired or completed sessions
        if error_code in (
            "resource_already_expired",
            "checkout_session_already_expired",
        ) or "already expired" in error_msg.lower() or "complete" in error_msg.lower():
            logger.info(
                "Stripe session %s already expired/complete: %s",
                session_id,
                error_msg,
            )
        else:
            logger.error(
                "Failed to expire Stripe session %s: %s",
                session_id,
                error_msg,
            )
            raise ValueError(f"Failed to expire session: {error_msg}")

    # Delete the pending_qr_sessions row
    await db.execute(
        sa_delete(PendingQrSession).where(
            PendingQrSession.session_id == session_id
        )
    )
    await db.flush()

    return {"status": "expired"}


async def clear_pending_qr_session(
    db: AsyncSession,
    *,
    session_id: str | None = None,
    org_id: uuid.UUID | None = None,
) -> None:
    """Delete a pending QR session row after payment completes.

    Called by the webhook handler to clean up the pending_qr_sessions
    table once a payment has been recorded. At least one of session_id
    or org_id must be provided.

    Parameters
    ----------
    db:
        Active async database session.
    session_id:
        The Stripe Checkout Session ID to match (optional).
    org_id:
        The organisation UUID to match (optional).

    Raises
    ------
    ValueError
        If neither session_id nor org_id is provided.

    Requirements: 3.3, 8.5
    """
    from sqlalchemy import delete as sa_delete

    from app.modules.payments.models import PendingQrSession

    if session_id is None and org_id is None:
        raise ValueError(
            "At least one of session_id or org_id must be provided"
        )

    if session_id is not None:
        await db.execute(
            sa_delete(PendingQrSession).where(
                PendingQrSession.session_id == session_id
            )
        )
    elif org_id is not None:
        await db.execute(
            sa_delete(PendingQrSession).where(
                PendingQrSession.org_id == org_id
            )
        )

    await db.flush()
