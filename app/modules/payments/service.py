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

    # Create Stripe Checkout Session
    stripe_result = await create_payment_link(
        amount=amount_cents,
        currency=invoice.currency,
        invoice_id=str(invoice.id),
        stripe_account_id=org.stripe_connect_account_id,
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
                from app.integrations.brevo import send_email

                await send_email(
                    to_email=customer.email,
                    subject=f"Payment link for invoice {invoice.invoice_number or invoice.id}",
                    body=(
                        f"Please complete your payment of "
                        f"{invoice.currency} {pay_amount} using the "
                        f"following link:\n\n{payment_url}"
                    ),
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
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


async def handle_stripe_webhook(
    db: AsyncSession,
    *,
    event_type: str,
    event_data: dict,
) -> dict:
    """Process a Stripe webhook event.

    Currently handles ``checkout.session.completed`` events:
    - Creates a Payment record with method='stripe'
    - Updates invoice amount_paid, balance_due, and status
    - Sends a best-effort payment receipt email

    Parameters
    ----------
    db:
        Active async database session.
    event_type:
        The Stripe event type string (e.g. ``"checkout.session.completed"``).
    event_data:
        The ``data.object`` portion of the Stripe event payload.

    Returns
    -------
    dict
        Summary of the action taken.

    Requirements: 25.4
    """
    if event_type != "checkout.session.completed":
        return {"status": "ignored", "reason": f"Unhandled event type: {event_type}"}

    session_obj = event_data
    metadata = session_obj.get("metadata", {})
    invoice_id_str = metadata.get("invoice_id")

    if not invoice_id_str:
        return {"status": "ignored", "reason": "No invoice_id in session metadata"}

    try:
        invoice_id = uuid.UUID(invoice_id_str)
    except (ValueError, TypeError):
        return {"status": "error", "reason": f"Invalid invoice_id: {invoice_id_str}"}

    # Amount is in smallest currency unit (cents) — convert to Decimal
    amount_total = session_obj.get("amount_total", 0)
    amount = Decimal(amount_total) / Decimal("100")

    stripe_payment_intent = session_obj.get("payment_intent", "")

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

    # Cap payment at balance_due to avoid overpayment
    pay_amount = min(amount, invoice.balance_due)
    if pay_amount <= 0:
        return {"status": "ignored", "reason": "Payment amount is zero or negative"}

    # Capture before state for audit
    before_status = invoice.status
    before_amount_paid = invoice.amount_paid
    before_balance_due = invoice.balance_due

    # Create payment record
    payment = Payment(
        org_id=invoice.org_id,
        invoice_id=invoice.id,
        amount=pay_amount,
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
            "amount_paid": str(invoice.amount_paid),
            "balance_due": str(invoice.balance_due),
            "payment_id": str(payment.id),
            "stripe_payment_intent": stripe_payment_intent,
        },
    )

    # Best-effort payment receipt email (non-blocking)
    try:
        from app.modules.customers.models import Customer
        from app.integrations.brevo import send_email

        cust_result = await db.execute(
            select(Customer).where(Customer.id == invoice.customer_id)
        )
        customer = cust_result.scalar_one_or_none()
        if customer and customer.email:
            await send_email(
                to_email=customer.email,
                subject=f"Payment receipt for invoice {invoice.invoice_number or invoice.id}",
                body=(
                    f"Thank you for your payment of {invoice.currency} {pay_amount}.\n\n"
                    f"Invoice: {invoice.invoice_number or invoice.id}\n"
                    f"Amount paid: {invoice.currency} {pay_amount}\n"
                    f"Remaining balance: {invoice.currency} {invoice.balance_due}\n"
                ),
            )
    except (ConnectionError, TimeoutError, OSError, ImportError) as exc:
        logger.warning("Failed to send payment receipt email for invoice %s: %s", invoice.id, exc)

    return {
        "status": "processed",
        "payment_id": str(payment.id),
        "invoice_id": str(invoice.id),
        "invoice_status": new_status,
        "amount": str(pay_amount),
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
    if invoice.status not in ("paid", "partially_paid", "overdue"):
        raise ValueError(
            f"Cannot refund invoice with status '{invoice.status}'. "
            "Invoice must be paid, partially paid, or overdue."
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
    invoice.amount_paid = invoice.amount_paid - amount
    invoice.balance_due = invoice.balance_due + amount

    # Determine new status
    if invoice.amount_paid <= Decimal("0"):
        new_status = "issued"
    elif invoice.balance_due > Decimal("0"):
        new_status = "partially_paid"
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
