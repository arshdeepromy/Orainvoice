"""IRD filing service — orchestrates IRD Gateway operations.

Provides high-level filing operations: connect, preflight, file GST,
file income tax, status polling, and audit log retrieval.

Rate limit: max 1 filing per period per org.
Credentials stored with envelope encryption in accounting_integrations.

Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3,
              33.1–33.3, 37.1, 37.2
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.accounting.models import AccountingIntegration
from app.modules.ird.gateway import (
    IrdSoapClient,
    IrdSoapClientProtocol,
    IrdSoapResponse,
    _log_soap_interaction,
    _retry_with_backoff,
    get_error_message,
    serialize_gst_to_xml,
    serialize_income_tax_to_xml,
)
from app.modules.ird.models import IrdFilingLog
from app.modules.ird.schemas import (
    IrdFilingLogResponse,
    IrdFilingResponse,
    IrdPreflightResponse,
    IrdStatusResponse,
    _is_masked,
    _mask_credential,
    validate_ird_number,
)
from app.modules.ledger.models import GstFilingPeriod

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting helper
# ---------------------------------------------------------------------------

async def _check_filing_rate_limit(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    filing_type: str,
) -> None:
    """Enforce max 1 filing per period per org.

    Raises HTTPException 429 if a filing already exists for this period.
    Requirements: 25.5 (Property 38)
    """
    result = await db.execute(
        select(func.count(IrdFilingLog.id)).where(
            IrdFilingLog.org_id == org_id,
            IrdFilingLog.period_id == period_id,
            IrdFilingLog.filing_type == filing_type,
            IrdFilingLog.status.in_(["submitted", "accepted", "filed"]),
        )
    )
    count = result.scalar() or 0
    if count > 0:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "FILING_RATE_LIMITED",
                "message": "Only one filing per period is allowed",
            },
        )


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------

async def _get_ird_integration(
    db: AsyncSession, org_id: uuid.UUID
) -> AccountingIntegration | None:
    """Get the IRD integration record for an org."""
    result = await db.execute(
        select(AccountingIntegration).where(
            AccountingIntegration.org_id == org_id,
            AccountingIntegration.provider == "ird",
        )
    )
    return result.scalar_one_or_none()


async def _get_ird_credentials(
    db: AsyncSession, org_id: uuid.UUID
) -> dict[str, str]:
    """Decrypt and return IRD credentials for an org."""
    integration = await _get_ird_integration(db, org_id)
    if not integration or not integration.is_connected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IRD_NOT_CONNECTED",
                "message": "IRD Gateway is not connected — configure in Settings > Integrations",
            },
        )
    creds: dict[str, str] = {}
    if integration.access_token_encrypted:
        try:
            creds["ird_number"] = envelope_decrypt_str(integration.access_token_encrypted)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "DECRYPTION_FAILED",
                    "message": "Failed to decrypt stored credentials — contact support",
                },
            )
    if integration.refresh_token_encrypted:
        try:
            raw = envelope_decrypt_str(integration.refresh_token_encrypted)
            # Format: "username:password"
            parts = raw.split(":", 1)
            creds["username"] = parts[0]
            creds["password"] = parts[1] if len(parts) > 1 else ""
        except Exception:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "DECRYPTION_FAILED",
                    "message": "Failed to decrypt stored credentials — contact support",
                },
            )
    creds["environment"] = integration.account_name or "sandbox"
    return creds


def _create_soap_client(
    ird_number: str, credentials: dict[str, str], environment: str = "sandbox"
) -> IrdSoapClient:
    """Create an IRD SOAP client instance."""
    return IrdSoapClient(
        ird_number=ird_number,
        credentials=credentials,
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

async def connect_ird(
    db: AsyncSession,
    org_id: uuid.UUID,
    ird_number: str,
    username: str,
    password: str,
    environment: str = "sandbox",
) -> IrdStatusResponse:
    """Connect IRD Gateway — validate IRD number, store encrypted credentials.

    Requirements: 25.1, 25.2, 25.3, 33.1
    """
    # Validate IRD number
    if not validate_ird_number(ird_number):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_IRD",
                "message": "IRD number fails mod-11 check digit validation",
            },
        )

    # Check for existing integration
    integration = await _get_ird_integration(db, org_id)

    # Encrypt credentials
    encrypted_ird = envelope_encrypt(ird_number)
    # Only update credentials if not masked
    cred_string = f"{username}:{password}"
    encrypted_creds = None
    if not _is_masked(username) and not _is_masked(password):
        encrypted_creds = envelope_encrypt(cred_string)

    if integration:
        # Update existing
        integration.access_token_encrypted = encrypted_ird
        if encrypted_creds is not None:
            integration.refresh_token_encrypted = encrypted_creds
        integration.is_connected = True
        integration.account_name = environment
    else:
        # Create new
        integration = AccountingIntegration(
            org_id=org_id,
            provider="ird",
            access_token_encrypted=encrypted_ird,
            refresh_token_encrypted=encrypted_creds or envelope_encrypt(cred_string),
            is_connected=True,
            account_name=environment,
        )
        db.add(integration)

    await db.flush()
    await db.refresh(integration)

    return IrdStatusResponse(
        connected=True,
        ird_number=_mask_credential(ird_number),
        environment=environment,
        active_services=["gst", "income_tax"],
    )


async def get_ird_status(
    db: AsyncSession, org_id: uuid.UUID
) -> IrdStatusResponse:
    """Get IRD connection status + active services.

    Requirements: 25.1
    """
    integration = await _get_ird_integration(db, org_id)
    if not integration or not integration.is_connected:
        return IrdStatusResponse(connected=False)

    # Get last filing timestamp
    last_filing_result = await db.execute(
        select(func.max(IrdFilingLog.created_at)).where(
            IrdFilingLog.org_id == org_id,
        )
    )
    last_filing_at = last_filing_result.scalar()

    # Mask the IRD number for display
    ird_number_masked = None
    if integration.access_token_encrypted:
        try:
            raw_ird = envelope_decrypt_str(integration.access_token_encrypted)
            ird_number_masked = _mask_credential(raw_ird)
        except Exception:
            ird_number_masked = "****"

    return IrdStatusResponse(
        connected=True,
        ird_number=ird_number_masked,
        environment=integration.account_name or "sandbox",
        active_services=["gst", "income_tax"],
        last_filing_at=last_filing_at,
    )


async def preflight_gst(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    soap_client: IrdSoapClientProtocol | None = None,
) -> IrdPreflightResponse:
    """Preflight check before GST filing — calls RFO + RR.

    Requirements: 26.1, 26.2
    """
    creds = await _get_ird_credentials(db, org_id)
    ird_number = creds.get("ird_number", "")

    if soap_client is None:
        soap_client = _create_soap_client(ird_number, creds, creds.get("environment", "sandbox"))

    # Get the GST period
    period_result = await db.execute(
        select(GstFilingPeriod).where(
            GstFilingPeriod.id == period_id,
            GstFilingPeriod.org_id == org_id,
        )
    )
    period = period_result.scalar_one_or_none()
    if not period:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "GST period not found"})

    # RFO — Retrieve Filing Obligation
    rfo_response = await soap_client.retrieve_filing_obligation(ird_number, period_id, "gst")
    await _log_soap_interaction(
        db, org_id, "gst", period_id,
        rfo_response.request_xml, rfo_response.response_xml,
        "rfo_check",
    )

    # RR — Retrieve Return (check for existing)
    rr_response = await soap_client.retrieve_return(ird_number, period_id, "gst")
    await _log_soap_interaction(
        db, org_id, "gst", period_id,
        rr_response.request_xml, rr_response.response_xml,
        "rr_check",
    )

    # Get GST return data for preview
    from app.modules.reports.service import get_gst_return
    gst_data = await get_gst_return(db, org_id, period.period_start, period.period_end)

    obligation_met = rfo_response.data.get("obligation_met", False)
    existing_return = rr_response.data.get("existing_return", False)

    return IrdPreflightResponse(
        period_id=period_id,
        obligation_met=obligation_met,
        existing_return=existing_return,
        period_start=period.period_start,
        period_end=period.period_end,
        gst_data=gst_data,
        message="Ready to file" if obligation_met and not existing_return else "Filing not available",
    )


async def file_gst_return(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    soap_client: IrdSoapClientProtocol | None = None,
) -> IrdFilingResponse:
    """Submit GST return to IRD.

    Maps get_gst_return() to IRD XML, submits, polls status.
    Rate limited: max 1 filing per period per org.

    Requirements: 25.5, 26.3, 26.4, 26.5, 26.6
    """
    # Rate limit check
    await _check_filing_rate_limit(db, org_id, period_id, "gst")

    creds = await _get_ird_credentials(db, org_id)
    ird_number = creds.get("ird_number", "")

    if soap_client is None:
        soap_client = _create_soap_client(ird_number, creds, creds.get("environment", "sandbox"))

    # Get the GST period
    period_result = await db.execute(
        select(GstFilingPeriod).where(
            GstFilingPeriod.id == period_id,
            GstFilingPeriod.org_id == org_id,
        )
    )
    period = period_result.scalar_one_or_none()
    if not period:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "GST period not found"})

    # Get GST return data and serialize to XML
    from app.modules.reports.service import get_gst_return
    gst_data = await get_gst_return(db, org_id, period.period_start, period.period_end)
    return_xml = serialize_gst_to_xml(gst_data)

    # Submit to IRD
    try:
        file_response = await _retry_with_backoff(
            lambda: soap_client.file_return(ird_number, return_xml, "gst")
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        await _log_soap_interaction(
            db, org_id, "gst", period_id,
            return_xml, str(exc), "error",
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "IRD_GATEWAY_ERROR",
                "message": "IRD Gateway temporarily unavailable — please retry",
            },
        )

    # Log the filing
    await _log_soap_interaction(
        db, org_id, "gst", period_id,
        file_response.request_xml, file_response.response_xml,
        file_response.data.get("status", "submitted"),
        file_response.ird_reference,
    )

    if not file_response.success:
        error_msg = get_error_message(file_response.error_code or "")
        return IrdFilingResponse(
            success=False,
            filing_type="gst",
            status="rejected",
            error_code=file_response.error_code,
            message=error_msg,
        )

    # Update GST period status
    period.status = "filed"
    period.filed_at = datetime.utcnow()
    period.filed_by = user_id
    period.ird_reference = file_response.ird_reference
    await db.flush()

    return IrdFilingResponse(
        success=True,
        filing_type="gst",
        status="filed",
        ird_reference=file_response.ird_reference,
        message="GST return submitted successfully",
    )


async def file_income_tax(
    db: AsyncSession,
    org_id: uuid.UUID,
    tax_year: int,
    user_id: uuid.UUID | None = None,
    soap_client: IrdSoapClientProtocol | None = None,
) -> IrdFilingResponse:
    """Submit income tax return to IRD.

    Maps P&L to IR3 (sole_trader) or IR4 (company).
    Requirements: 27.1, 27.2, 27.3, 27.4
    """
    creds = await _get_ird_credentials(db, org_id)
    ird_number = creds.get("ird_number", "")

    if soap_client is None:
        soap_client = _create_soap_client(ird_number, creds, creds.get("environment", "sandbox"))

    # Determine return type based on business_type
    from app.modules.organisations.models import Organisation
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    business_type = getattr(org, "business_type", "sole_trader") or "sole_trader"
    return_type = "IR4" if business_type == "company" else "IR3"

    # Get P&L data for the tax year
    from app.modules.reports.service import get_tax_estimate
    tax_year_start = date(tax_year - 1, 4, 1)  # NZ tax year: Apr 1 – Mar 31
    tax_year_end = date(tax_year, 3, 31)

    try:
        tax_data = await get_tax_estimate(db, org_id, tax_year)
    except Exception:
        tax_data = {
            "tax_year": tax_year,
            "total_revenue": 0,
            "total_expenses": 0,
            "taxable_income": 0,
            "estimated_tax": 0,
        }

    # Serialize to XML
    return_xml = serialize_income_tax_to_xml(return_type, tax_data)

    # Submit to IRD
    try:
        file_response = await _retry_with_backoff(
            lambda: soap_client.file_return(ird_number, return_xml, "income_tax")
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "IRD_GATEWAY_ERROR",
                "message": "IRD Gateway temporarily unavailable — please retry",
            },
        )

    # Log the filing
    await _log_soap_interaction(
        db, org_id, "income_tax", None,
        file_response.request_xml, file_response.response_xml,
        file_response.data.get("status", "submitted"),
        file_response.ird_reference,
    )

    if not file_response.success:
        error_msg = get_error_message(file_response.error_code or "")
        return IrdFilingResponse(
            success=False,
            filing_type="income_tax",
            status="rejected",
            error_code=file_response.error_code,
            message=error_msg,
        )

    return IrdFilingResponse(
        success=True,
        filing_type="income_tax",
        status="filed",
        ird_reference=file_response.ird_reference,
        message=f"Income tax return ({return_type}) submitted successfully",
    )


async def get_filing_log(
    db: AsyncSession, org_id: uuid.UUID
) -> list[IrdFilingLogResponse]:
    """List filing audit log for an org.

    Requirements: 28.1, 28.3
    """
    result = await db.execute(
        select(IrdFilingLog)
        .where(IrdFilingLog.org_id == org_id)
        .order_by(IrdFilingLog.created_at.desc())
    )
    logs = result.scalars().all()
    return [
        IrdFilingLogResponse(
            id=log.id,
            filing_type=log.filing_type,
            period_id=log.period_id,
            status=log.status,
            ird_reference=log.ird_reference,
            created_at=log.created_at,
        )
        for log in logs
    ]
