"""Business logic for Email Providers."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.models import EmailProvider

logger = logging.getLogger(__name__)


async def list_email_providers(db: AsyncSession) -> dict:
    """Return all email providers and identify the active one."""
    result = await db.execute(
        select(EmailProvider).order_by(EmailProvider.display_name)
    )
    providers = result.scalars().all()
    active_key = None
    provider_list = []
    for p in providers:
        provider_list.append(_provider_to_dict(p))
        if p.is_active:
            active_key = p.provider_key
    return {"providers": provider_list, "active_provider": active_key}


async def activate_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Set a provider as the active email provider (only one at a time)."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    # Deactivate all others
    await db.execute(update(EmailProvider).values(is_active=False))
    provider.is_active = True
    await db.flush()
    await db.refresh(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_activated",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key},
        ip_address=ip_address,
    )
    return _provider_to_dict(provider)


async def deactivate_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Deactivate a provider."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    provider.is_active = False
    await db.flush()
    await db.refresh(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_deactivated",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key},
        ip_address=ip_address,
    )
    return _provider_to_dict(provider)


async def save_email_credentials(
    db: AsyncSession,
    *,
    provider_key: str,
    credentials: dict,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_encryption: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Save encrypted credentials and optional config for a provider."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    encrypted = envelope_encrypt(json.dumps(credentials))
    provider.credentials_encrypted = encrypted
    provider.credentials_set = True

    if smtp_host is not None:
        provider.smtp_host = smtp_host
    if smtp_port is not None:
        provider.smtp_port = smtp_port
    if smtp_encryption is not None and hasattr(provider, 'smtp_encryption'):
        provider.smtp_encryption = smtp_encryption

    config = dict(provider.config or {})
    if from_email is not None:
        config["from_email"] = from_email
    if from_name is not None:
        config["from_name"] = from_name
    if reply_to is not None:
        config["reply_to"] = reply_to
    provider.config = config

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_credentials_saved",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key, "credentials_set": True},
        ip_address=ip_address,
    )
    return {"credentials_set": True}


def _provider_to_dict(p: EmailProvider) -> dict:
    """Convert an EmailProvider ORM instance to a serialisable dict."""
    return {
        "id": str(p.id),
        "provider_key": p.provider_key,
        "display_name": p.display_name,
        "description": p.description,
        "smtp_host": p.smtp_host,
        "smtp_port": p.smtp_port,
        "smtp_encryption": getattr(p, 'smtp_encryption', None),
        "priority": getattr(p, 'priority', 1) or 1,
        "is_active": p.is_active,
        "credentials_set": p.credentials_set,
        "config": p.config or {},
        "setup_guide": p.setup_guide,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def test_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    to_email: str | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Send a test email using the specified provider."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return {"success": False, "message": "Provider not found", "error": "Provider not found"}
    
    if not provider.credentials_set or not provider.credentials_encrypted:
        return {"success": False, "message": "Credentials not configured", "error": "Please configure credentials first"}
    
    # Decrypt credentials
    try:
        creds_json = envelope_decrypt_str(provider.credentials_encrypted)
        credentials = json.loads(creds_json)
    except Exception as e:
        logger.error(f"Failed to decrypt credentials for {provider_key}: {e}")
        return {"success": False, "message": "Failed to decrypt credentials", "error": str(e)}
    
    # Get SMTP settings
    smtp_host = provider.smtp_host
    smtp_port = provider.smtp_port or 587
    smtp_encryption = getattr(provider, 'smtp_encryption', 'tls') or 'tls'
    username = credentials.get('username') or credentials.get('api_key', '')
    password = credentials.get('password') or credentials.get('api_key', '')
    
    config = provider.config or {}
    from_email = config.get('from_email', 'test@example.com')
    from_name = config.get('from_name', 'Test')
    
    if not to_email:
        return {"success": False, "message": "No recipient email", "error": "Recipient email required"}
    
    if not smtp_host:
        # Use default hosts for known providers
        default_hosts = {
            'gmail': 'smtp.gmail.com',
            'outlook': 'smtp.office365.com',
            'brevo': 'smtp-relay.brevo.com',
            'sendgrid': 'smtp.sendgrid.net',
            'mailgun': 'smtp.mailgun.org',
            'ses': 'email-smtp.us-east-1.amazonaws.com',
        }
        smtp_host = default_hosts.get(provider_key)
        if not smtp_host:
            return {"success": False, "message": "SMTP host not configured", "error": "Please configure SMTP host"}
    
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = to_email
        msg['Subject'] = f"Test Email from {provider.display_name}"
        
        body = f"""
This is a test email sent from your email provider configuration.

Provider: {provider.display_name}
SMTP Host: {smtp_host}:{smtp_port}
Encryption: {smtp_encryption.upper()}

If you received this email, your email provider is configured correctly!
        """
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect and send
        if smtp_encryption == 'ssl':
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            if smtp_encryption == 'tls':
                server.starttls()
        
        if username and password:
            server.login(username, password)
        
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        
        await write_audit_log(
            session=db,
            org_id=None,
            user_id=admin_user_id,
            action="admin.email_provider_test_sent",
            entity_type="email_provider",
            entity_id=provider.id,
            after_value={"provider_key": provider_key, "to_email": to_email, "success": True},
            ip_address=ip_address,
        )
        
        return {"success": True, "message": f"Test email sent to {to_email}"}
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth error for {provider_key}: {e}")
        return {"success": False, "message": "Authentication failed", "error": "Invalid username or password"}
    except smtplib.SMTPConnectError as e:
        logger.error(f"SMTP connect error for {provider_key}: {e}")
        return {"success": False, "message": "Connection failed", "error": f"Could not connect to {smtp_host}:{smtp_port}"}
    except Exception as e:
        logger.error(f"SMTP error for {provider_key}: {e}")
        return {"success": False, "message": "Failed to send test email", "error": str(e)}


async def update_email_provider_priority(
    db: AsyncSession,
    *,
    provider_key: str,
    priority: int,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> int | None:
    """Update the priority of an email provider."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None
    
    old_priority = getattr(provider, 'priority', 1)
    if hasattr(provider, 'priority'):
        provider.priority = priority
    await db.flush()
    
    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_priority_updated",
        entity_type="email_provider",
        entity_id=provider.id,
        before_value={"priority": old_priority},
        after_value={"priority": priority},
        ip_address=ip_address,
    )
    
    return priority
