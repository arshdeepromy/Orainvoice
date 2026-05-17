"""Business logic for Payment module — cash payment recording.

Requirements: 24.1, 24.2, 24.3
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.in_app_notifications.service import create_in_app_notification
from app.modules.invoices.models import Invoice
from app.modules.invoices.service import _validate_transition
from app.modules.payments.models import Payment

logger = logging.getLogger(__name__)


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
) -> None:
    """Send a payment receipt email using the configured SMTP provider.

    Uses the same email provider infrastructure as email_invoice() — reads
    from the email_providers table, not from brevo.py.  Best-effort: logs
    warnings on failure but does not raise.

    Attaches the invoice PDF (with updated payment status) so the customer
    has a complete record.
    """
    import json as _json
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import EmailProvider, Organisation

    # Get org name for the email
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == invoice.org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Your Company"

    inv_number = invoice.invoice_number or str(invoice.id)
    currency = invoice.currency or "NZD"

    # Generate the invoice PDF with updated payment status
    pdf_bytes: bytes | None = None
    try:
        from app.modules.invoices.service import generate_invoice_pdf
        pdf_bytes = await generate_invoice_pdf(
            db, org_id=invoice.org_id, invoice_id=invoice.id,
        )
    except Exception as exc:
        logger.warning("Failed to generate PDF for receipt email (invoice %s): %s", invoice.id, exc)

    # Find active email provider
    provider_result = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)  # noqa: E712
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())
    if not providers:
        logger.warning("No active email provider — cannot send receipt for invoice %s", invoice.id)
        return

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
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            # Attach invoice PDF if generated successfully
            if pdf_bytes:
                pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
                pdf_filename = f"{inv_number}.pdf"
                pdf_attachment.add_header(
                    "Content-Disposition", "attachment", filename=pdf_filename,
                )
                msg.attach(pdf_attachment)

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, to_email, msg.as_string())
            server.quit()
            logger.info("Sent payment receipt email for invoice %s to %s", invoice.id, to_email)
            return
        except Exception as exc:
            logger.warning(
                "Email provider %s failed for receipt (invoice %s): %s",
                provider.provider_key, invoice.id, exc,
            )
            continue

    logger.warning("All email providers failed for receipt email (invoice %s)", invoice.id)
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
            "error_message": "All email providers failed for receipt email",
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

    # Fetch invoice (no org filter — webhook has no auth context, but we
    # trust the payload because signature was already verified)
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
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
) -> dict:
    """Create a QR payment session: issue invoice + create Stripe Checkout Session.

    Issues the invoice (status="sent" which maps to "issued" internally),
    creates a Stripe Checkout Session with both card and afterpay_clearpay
    payment methods, stores the pending session in the DB, and returns
    session details for the frontend.

    Requirements: 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10,
                  3.1, 3.2, 10.1, 10.2, 10.3
    """
    import time
    from datetime import datetime as dt, timezone as tz

    import httpx

    from app.config import settings
    from app.integrations.stripe_billing import (
        get_application_fee_percent,
        get_stripe_secret_key,
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

    # 3. Retrieve Stripe secret key from DB
    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError(
            "Stripe secret key not configured. Set it via Global Admin > Integrations."
        )

    # 4. Calculate amount in cents and application fee
    amount_cents = int(total * 100)
    if amount_cents <= 0:
        raise ValueError("Invoice total must be greater than zero")

    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(amount_cents * fee_percent / 100)

    # 5. Build Stripe Checkout Session payload
    base_url = (settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    expires_at = int(time.time() + 1800)  # 30 minutes from now

    payload: list[tuple[str, str]] = [
        ("mode", "payment"),
        ("payment_method_types[]", "card"),
        ("payment_method_types[]", "afterpay_clearpay"),
        ("line_items[0][price_data][currency]", currency.lower()),
        ("line_items[0][price_data][unit_amount]", str(amount_cents)),
        ("line_items[0][price_data][product_data][name]", f"Invoice {invoice_number}"),
        ("line_items[0][quantity]", "1"),
        ("expires_at", str(expires_at)),
        ("metadata[invoice_id]", str(invoice_id)),
        ("metadata[org_id]", str(org_id)),
        ("metadata[source]", "kiosk_qr"),
        ("metadata[platform]", "orainvoice"),
        ("success_url", f"{base_url}/payments/qr-success?invoice_id={invoice_id}&session_id={{CHECKOUT_SESSION_ID}}"),
        ("cancel_url", f"{base_url}/payments/qr-cancel?invoice_id={invoice_id}"),
    ]

    if application_fee_amount and application_fee_amount > 0:
        payload.append(
            ("payment_intent_data[application_fee_amount]", str(application_fee_amount))
        )

    # 6. Create Stripe Checkout Session via direct API call
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            auth=(secret_key, ""),
            headers={"Stripe-Account": org.stripe_connect_account_id},
        )
        if response.status_code != 200:
            error_body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_body.get("error", {}).get("message", response.text)
            logger.error(
                "Stripe Checkout Session creation failed for org %s: %s",
                org_id, error_msg,
            )
            raise ValueError(f"Failed to create payment session: {error_msg}")

    session_data = response.json()
    session_id = session_data["id"]
    checkout_url = session_data["url"]

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


async def get_pending_qr_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict | None:
    """Retrieve the pending QR session for an organisation.

    Queries the pending_qr_sessions table for the given org_id.
    If the session exists but has expired (expires_at < now), deletes it
    and returns None. If the session exists and is still valid, returns
    it as a dict. If no session exists, returns None.

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

    return {
        "session_id": session.session_id,
        "checkout_url": session.checkout_url,
        "amount": session.amount,
        "invoice_number": session.invoice_number,
        "expires_at": session.expires_at.isoformat(),
        "created_at": session.created_at.isoformat(),
    }


async def get_qr_session_status(
    db: AsyncSession,
    *,
    session_id: str,
    stripe_connect_account_id: str,
) -> dict:
    """Check the status of a Stripe Checkout Session.

    Calls the Stripe API to retrieve the session and returns a simplified
    status (open/complete/expired) along with the payment_intent ID if
    the session is complete.

    Parameters
    ----------
    db:
        Active async database session (unused currently, but kept for
        consistency with other service functions and future use).
    session_id:
        The Stripe Checkout Session ID (e.g. "cs_...").
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

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError(
            "Stripe secret key not configured. Set it via Global Admin > Integrations."
        )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
            auth=(secret_key, ""),
            headers={"Stripe-Account": stripe_connect_account_id},
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
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.stripe.com/v1/checkout/sessions/{session_id}/expire",
            auth=(secret_key, ""),
            headers={"Stripe-Account": stripe_connect_account_id},
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
