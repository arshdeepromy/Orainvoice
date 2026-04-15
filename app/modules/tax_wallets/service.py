"""Tax wallet service — CRUD, auto-sweep, summary with traffic lights.

Requirements: 20.1–20.4, 21.1–21.5, 22.1–22.4, 23.1, 23.2
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tax_wallets.models import TaxWallet, TaxWalletTransaction

logger = logging.getLogger(__name__)

WALLET_TYPES = ("gst", "income_tax", "provisional_tax")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _round2(value: Decimal) -> Decimal:
    """Round to 2 decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_traffic_light(balance: Decimal, obligation: Decimal) -> str:
    """Return traffic light colour based on coverage ratio.

    green  ≥ 100% of obligation covered
    amber  50–99% covered
    red    < 50% covered
    """
    if obligation <= 0:
        return "green"
    ratio = balance / obligation
    if ratio >= Decimal("1"):
        return "green"
    if ratio >= Decimal("0.5"):
        return "amber"
    return "red"


async def _get_or_create_wallet(
    db: AsyncSession,
    org_id: uuid.UUID,
    wallet_type: str,
) -> TaxWallet:
    """Get existing wallet or create on first access."""
    result = await db.execute(
        select(TaxWallet).where(
            TaxWallet.org_id == org_id,
            TaxWallet.wallet_type == wallet_type,
        )
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        wallet = TaxWallet(
            org_id=org_id,
            wallet_type=wallet_type,
            balance=Decimal("0"),
        )
        db.add(wallet)
        await db.flush()
        await db.refresh(wallet)
    return wallet


async def _get_org_settings(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Read organisation settings JSONB."""
    from app.modules.organisations.models import Organisation

    result = await db.execute(
        select(Organisation.settings).where(Organisation.id == org_id)
    )
    settings = result.scalar_one_or_none()
    return settings or {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_wallets(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[TaxWallet]:
    """List all wallets for an org, creating missing ones on first access."""
    wallets = []
    for wt in WALLET_TYPES:
        wallets.append(await _get_or_create_wallet(db, org_id, wt))
    return wallets


async def get_wallet_transactions(
    db: AsyncSession,
    org_id: uuid.UUID,
    wallet_type: str,
) -> list[TaxWalletTransaction]:
    """Get transaction history for a specific wallet type."""
    wallet = await _get_or_create_wallet(db, org_id, wallet_type)
    result = await db.execute(
        select(TaxWalletTransaction)
        .where(TaxWalletTransaction.wallet_id == wallet.id)
        .order_by(TaxWalletTransaction.created_at.desc())
    )
    return list(result.scalars().all())


async def manual_deposit(
    db: AsyncSession,
    org_id: uuid.UUID,
    wallet_type: str,
    amount: Decimal,
    description: str | None,
    user_id: uuid.UUID,
) -> TaxWalletTransaction:
    """Create a manual deposit transaction and update wallet balance."""
    wallet = await _get_or_create_wallet(db, org_id, wallet_type)

    txn = TaxWalletTransaction(
        org_id=org_id,
        wallet_id=wallet.id,
        amount=_round2(amount),
        transaction_type="manual_deposit",
        description=description,
        created_by=user_id,
    )
    db.add(txn)

    wallet.balance = wallet.balance + _round2(amount)
    await db.flush()
    await db.refresh(txn)
    await db.refresh(wallet)
    return txn


async def manual_withdrawal(
    db: AsyncSession,
    org_id: uuid.UUID,
    wallet_type: str,
    amount: Decimal,
    description: str | None,
    user_id: uuid.UUID,
) -> TaxWalletTransaction:
    """Create a manual withdrawal. Reject if amount > balance."""
    wallet = await _get_or_create_wallet(db, org_id, wallet_type)

    rounded = _round2(amount)
    if rounded > wallet.balance:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_BALANCE",
                "message": (
                    f"Withdrawal of ${rounded} exceeds wallet balance of ${wallet.balance}"
                ),
            },
        )

    txn = TaxWalletTransaction(
        org_id=org_id,
        wallet_id=wallet.id,
        amount=-rounded,  # negative for withdrawal
        transaction_type="manual_withdrawal",
        description=description,
        created_by=user_id,
    )
    db.add(txn)

    wallet.balance = wallet.balance - rounded
    await db.flush()
    await db.refresh(txn)
    await db.refresh(wallet)
    return txn


async def sweep_on_payment(
    db: AsyncSession,
    org_id: uuid.UUID,
    payment_amount: Decimal,
    payment_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[TaxWalletTransaction]:
    """Auto-sweep GST and income tax portions on payment received.

    GST sweep   = payment × (15/115)
    Income tax  = payment × effective_rate

    Respects tax_sweep_enabled and tax_sweep_gst_auto org settings.
    """
    settings = await _get_org_settings(db, org_id)

    if not settings.get("tax_sweep_enabled", False):
        return []

    if payment_amount <= 0:
        return []

    created_txns: list[TaxWalletTransaction] = []

    # ── GST sweep ─────────────────────────────────────────────────────
    if settings.get("tax_sweep_gst_auto", True):
        gst_amount = _round2(payment_amount * Decimal("15") / Decimal("115"))
        if gst_amount > 0:
            gst_wallet = await _get_or_create_wallet(db, org_id, "gst")
            gst_txn = TaxWalletTransaction(
                org_id=org_id,
                wallet_id=gst_wallet.id,
                amount=gst_amount,
                transaction_type="auto_sweep",
                source_payment_id=payment_id,
                description=f"Auto-sweep GST from payment ${payment_amount}",
            )
            db.add(gst_txn)
            gst_wallet.balance = gst_wallet.balance + gst_amount
            created_txns.append(gst_txn)

    # ── Income tax sweep ──────────────────────────────────────────────
    effective_rate = await _get_effective_tax_rate(db, org_id, settings)
    if effective_rate and effective_rate > 0:
        it_amount = _round2(payment_amount * effective_rate)
        if it_amount > 0:
            it_wallet = await _get_or_create_wallet(db, org_id, "income_tax")
            it_txn = TaxWalletTransaction(
                org_id=org_id,
                wallet_id=it_wallet.id,
                amount=it_amount,
                transaction_type="auto_sweep",
                source_payment_id=payment_id,
                description=f"Auto-sweep income tax from payment ${payment_amount}",
            )
            db.add(it_txn)
            it_wallet.balance = it_wallet.balance + it_amount
            created_txns.append(it_txn)

    if created_txns:
        await db.flush()
        # Refresh all created transactions
        for txn in created_txns:
            await db.refresh(txn)

        # Create notification
        try:
            parts = []
            for txn in created_txns:
                wallet_name = "GST" if "GST" in (txn.description or "") else "income tax"
                parts.append(f"${txn.amount} swept to {wallet_name} wallet")
            msg = f"Payment of ${payment_amount} received. {'. '.join(parts)}."
            await _create_sweep_notification(db, org_id, msg)
        except Exception as exc:
            logger.warning("Failed to create sweep notification: %s", exc)

    return created_txns


async def _get_effective_tax_rate(
    db: AsyncSession,
    org_id: uuid.UUID,
    settings: dict,
) -> Decimal | None:
    """Get the effective tax rate for income tax sweep.

    Uses income_tax_sweep_pct override if set, otherwise derives from
    the organisation's business_type.
    """
    override = settings.get("income_tax_sweep_pct")
    if override is not None:
        return Decimal(str(override)) / Decimal("100")

    # Fall back to business_type-based rate
    from app.modules.organisations.models import Organisation

    result = await db.execute(
        select(Organisation.business_type).where(Organisation.id == org_id)
    )
    business_type = result.scalar_one_or_none() or "sole_trader"

    if business_type == "company":
        return Decimal("0.28")
    # Default sole trader effective rate ~20% (mid-range estimate)
    return Decimal("0.20")


async def _create_sweep_notification(
    db: AsyncSession,
    org_id: uuid.UUID,
    message: str,
) -> None:
    """Create a notification for auto-sweep events."""
    try:
        from app.modules.notifications.models import Notification

        notif = Notification(
            org_id=org_id,
            title="Tax Auto-Sweep",
            message=message,
            notification_type="info",
        )
        db.add(notif)
        await db.flush()
    except Exception as exc:
        logger.warning("Could not create sweep notification: %s", exc)


async def get_wallet_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Wallet summary with balances, obligations, shortfall, traffic lights.

    Requirements: 22.2, 23.1, 23.2
    """
    import calendar
    from app.modules.reports.service import get_gst_return, get_tax_estimate

    today = date.today()

    # Ensure all wallets exist
    wallets = await list_wallets(db, org_id)
    wallet_map = {w.wallet_type: w for w in wallets}

    gst_balance = wallet_map.get("gst", TaxWallet(balance=Decimal("0"))).balance
    it_balance = wallet_map.get("income_tax", TaxWallet(balance=Decimal("0"))).balance

    # Current GST period
    gst_period_start_month = today.month if today.month % 2 == 1 else today.month - 1
    gst_period_start = today.replace(month=gst_period_start_month, day=1)
    if gst_period_start_month + 1 <= 12:
        gst_period_end_month = gst_period_start_month + 1
        gst_period_end_year = today.year
    else:
        gst_period_end_month = 1
        gst_period_end_year = today.year + 1
    last_day = calendar.monthrange(gst_period_end_year, gst_period_end_month)[1]
    gst_period_end = date(gst_period_end_year, gst_period_end_month, last_day)

    gst_return = await get_gst_return(db, org_id, gst_period_start, gst_period_end)
    gst_owing = gst_return.get("net_gst_payable", Decimal("0"))

    # Next GST due date
    if gst_period_end_month + 1 <= 12:
        next_gst_due = date(gst_period_end_year, gst_period_end_month + 1, 28)
    else:
        next_gst_due = date(gst_period_end_year + 1, 1, 28)

    # Income tax estimate for current tax year
    if today.month >= 4:
        tax_year_start = date(today.year, 4, 1)
        tax_year_end = date(today.year + 1, 3, 31)
    else:
        tax_year_start = date(today.year - 1, 4, 1)
        tax_year_end = date(today.year, 3, 31)

    tax_estimate = await get_tax_estimate(db, org_id, tax_year_start, tax_year_end)
    income_tax_est = tax_estimate.get("estimated_tax", Decimal("0"))
    next_it_due = tax_estimate.get("next_provisional_due_date")

    gst_shortfall = max(Decimal("0"), gst_owing - gst_balance)
    it_shortfall = max(Decimal("0"), income_tax_est - it_balance)

    wallet_lights = [
        {
            "wallet_type": "gst",
            "balance": gst_balance,
            "obligation": gst_owing,
            "shortfall": gst_shortfall,
            "traffic_light": compute_traffic_light(gst_balance, gst_owing),
            "next_due": next_gst_due,
        },
        {
            "wallet_type": "income_tax",
            "balance": it_balance,
            "obligation": income_tax_est,
            "shortfall": it_shortfall,
            "traffic_light": compute_traffic_light(it_balance, income_tax_est),
            "next_due": next_it_due,
        },
    ]

    return {
        "currency": "NZD",
        "wallets": wallet_lights,
        "gst_wallet_balance": gst_balance,
        "gst_owing": gst_owing,
        "gst_shortfall": gst_shortfall,
        "income_tax_wallet_balance": it_balance,
        "income_tax_estimate": income_tax_est,
        "income_tax_shortfall": it_shortfall,
        "next_gst_due": next_gst_due,
        "next_income_tax_due": next_it_due,
    }
