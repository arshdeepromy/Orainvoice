"""Error logging service with severity, category, and PII sanitisation.

Every exception, integration failure, and unexpected state is captured here
and written to the ``error_log`` table for the Global Admin Console.

Usage::

    from app.core.errors import log_error, Severity, Category

    await log_error(
        session=db,
        severity=Severity.ERROR,
        category=Category.PAYMENT,
        module="modules.payments.service",
        function_name="process_stripe_webhook",
        message="Stripe webhook signature verification failed",
        stack_trace=traceback.format_exc(),
        org_id=org_id,
    )
"""

from __future__ import annotations

import re
import traceback
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Category(StrEnum):
    PAYMENT = "payment"
    INTEGRATION = "integration"
    STORAGE = "storage"
    AUTHENTICATION = "authentication"
    DATA = "data"
    BACKGROUND_JOB = "background_job"
    APPLICATION = "application"


# ---------------------------------------------------------------------------
# PII sanitisation
# ---------------------------------------------------------------------------

# Patterns that match common PII tokens in JSON / text.
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email addresses
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL_REDACTED]"),
    # NZ phone numbers (various formats)
    (re.compile(r"\b(?:\+?64|0)\d[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b"), "[PHONE_REDACTED]"),
    # Generic phone-like sequences (7+ digits)
    (re.compile(r"\b\d{7,15}\b"), "[PHONE_REDACTED]"),
    # Credit card numbers (basic pattern)
    (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "[CARD_REDACTED]"),
]

# Keys whose values should always be redacted in dicts.
_SENSITIVE_KEYS: set[str] = {
    "password", "password_hash", "secret", "token", "api_key",
    "auth_token", "refresh_token", "access_token", "authorization",
    "credit_card", "card_number", "cvv", "ssn", "mfa_secret",
    "backup_codes", "passkey_credentials", "stripe_secret_key",
    "twilio_auth_token", "smtp_api_key", "encryption_master_key",
    "first_name", "last_name", "name", "email", "phone",
    "address", "phone_number", "mobile",
}


def sanitise_value(value: Any) -> Any:
    """Recursively sanitise a value, redacting PII and secrets."""
    if value is None:
        return None

    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in _SENSITIVE_KEYS else sanitise_value(v)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [sanitise_value(item) for item in value]

    if isinstance(value, str):
        result = value
        for pattern, replacement in _PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    return value


# ---------------------------------------------------------------------------
# Auto-categorisation
# ---------------------------------------------------------------------------

_MODULE_CATEGORY_MAP: dict[str, Category] = {
    "payments": Category.PAYMENT,
    "stripe": Category.PAYMENT,
    "integrations": Category.INTEGRATION,
    "carjam": Category.INTEGRATION,
    "brevo": Category.INTEGRATION,
    "twilio": Category.INTEGRATION,
    "xero": Category.INTEGRATION,
    "myob": Category.INTEGRATION,
    "storage": Category.STORAGE,
    "auth": Category.AUTHENTICATION,
    "tasks": Category.BACKGROUND_JOB,
    "celery": Category.BACKGROUND_JOB,
}


def auto_categorise(module: str) -> Category:
    """Infer an error category from the module path."""
    module_lower = module.lower()
    for keyword, category in _MODULE_CATEGORY_MAP.items():
        if keyword in module_lower:
            return category
    return Category.APPLICATION


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def log_error(
    session: AsyncSession,
    *,
    severity: Severity,
    category: Category | None = None,
    module: str,
    function_name: str | None = None,
    message: str,
    stack_trace: str | None = None,
    org_id: str | uuid.UUID | None = None,
    user_id: str | uuid.UUID | None = None,
    http_method: str | None = None,
    http_endpoint: str | None = None,
    request_body: dict[str, Any] | None = None,
    response_body: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Write an error record to the ``error_log`` table.

    PII and secrets in ``request_body`` / ``response_body`` are
    automatically sanitised before storage.  If *category* is ``None``
    it is inferred from *module*.

    Returns the generated error ID.
    """
    import json

    resolved_category = category or auto_categorise(module)
    error_id = uuid.uuid4()

    sanitised_request = sanitise_value(request_body) if request_body else None
    sanitised_response = sanitise_value(response_body) if response_body else None

    await session.execute(
        text(
            """
            INSERT INTO error_log (
                id, severity, category, module, function_name, message,
                stack_trace, org_id, user_id, http_method, http_endpoint,
                request_body_sanitised, response_body_sanitised, status, created_at
            ) VALUES (
                :id, :severity, :category, :module, :function_name, :message,
                :stack_trace, :org_id, :user_id, :http_method, :http_endpoint,
                :request_body, :response_body, 'open', :created_at
            )
            """
        ),
        {
            "id": str(error_id),
            "severity": severity.value,
            "category": resolved_category.value,
            "module": module,
            "function_name": function_name,
            "message": message,
            "stack_trace": stack_trace,
            "org_id": str(org_id) if org_id else None,
            "user_id": str(user_id) if user_id else None,
            "http_method": http_method,
            "http_endpoint": http_endpoint,
            "request_body": json.dumps(sanitised_request) if sanitised_request else None,
            "response_body": json.dumps(sanitised_response) if sanitised_response else None,
            "created_at": datetime.now(timezone.utc),
        },
    )

    return error_id
