"""Regression test for ISSUE-169 — invoice-send email CTA link target.

The "Send Invoice" action (``POST /invoices/{id}/email`` → ``email_invoice``)
must point its "View Invoice" call-to-action at the PUBLIC INVOICE VIEW
(``/api/v1/public/invoice/{share_token}`` — the same link the "Share" button
produces), NOT at the ``/pay/{token}`` payment page.

Bug: the CTA preferred ``invoice.payment_page_url`` (the payment page). Once an
invoice was settled that page renders "Paid" / payment info, so a customer who
received a "Send Invoice" email saw a payment-status page instead of their
invoice. (Reported on local prod standby: customer "Iqbal singh Pannu",
invoice SPINV-0050 — cash, status=paid, but carried a payment_page_url.)

These tests drive ``email_invoice`` with all I/O mocked and capture the
``cta_url`` handed to ``render_transactional_html`` (and the ``payment_link``
template variable handed to ``resolve_template``).
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
SHARE_TOKEN = "existing-share-token-abc123"
PAYMENT_PAGE_URL = "https://app.example.com/pay/pay-token-xyz789"
FRONTEND_BASE = "https://app.example.com"


def _scalar_one_or_none_result(value):
    """Build a mock result whose ``scalar_one_or_none()`` returns ``value``."""
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=value)
    return res


def _make_org():
    org = MagicMock()
    org.id = ORG_ID
    org.settings = {}
    return org


def _make_send_result():
    res = MagicMock()
    res.success = True
    res.error = None
    res.provider = "brevo"
    return res


def _build_invoice_dict(
    *,
    status: str,
    gateway: str | None,
    share_token: str | None,
    payment_page_url: str = PAYMENT_PAGE_URL,
):
    """Minimal invoice dict matching ``get_invoice``'s shape for this path."""
    data_json: dict = {"payment_gateway": gateway}
    if share_token is not None:
        data_json["share_token"] = share_token
    return {
        "id": INVOICE_ID,
        "customer_id": uuid.uuid4(),
        "invoice_number": "SPINV-0050",
        "org_name": "SP Automotive",
        "balance_due": 0 if status == "paid" else 150.0,
        "currency": "NZD",
        "status": status,
        "payment_gateway": gateway,
        "payment_page_url": payment_page_url,
        "due_date": date(2026, 6, 2),
        "org_email": "spautomotivenz@gmail.com",
        "org_phone": "+64211503444",
        "invoice_data_json": data_json,
        "customer": {
            "first_name": "Iqbal",
            "last_name": "Pannu",
            "email": "iqbalpannu1@gmail.com",
        },
    }


async def _drive_email_invoice(
    *,
    status: str,
    gateway: str | None,
    share_token: str | None,
    base_url: str | None = FRONTEND_BASE,
    settings_frontend_base: str = FRONTEND_BASE,
    payment_page_url: str = PAYMENT_PAGE_URL,
):
    """Run ``email_invoice`` fully mocked; return (cta_url, template_vars).

    ``base_url`` simulates the request origin the router passes (None on the
    background auto-email path). ``settings_frontend_base`` simulates the
    configured FRONTEND_BASE_URL (can be a dev value like http://localhost).
    ``payment_page_url`` simulates the invoice's stored public payment link.
    """
    inv_dict = _build_invoice_dict(
        status=status,
        gateway=gateway,
        share_token=share_token,
        payment_page_url=payment_page_url,
    )
    org = _make_org()

    invoice_obj = MagicMock()
    invoice_obj.id = INVOICE_ID
    invoice_obj.org_id = ORG_ID
    invoice_obj.status = status
    invoice_obj.invoice_number = "SPINV-0050"
    invoice_obj.issue_date = date(2026, 6, 2)
    invoice_obj.due_date = date(2026, 6, 2)
    invoice_obj.invoice_data_json = dict(inv_dict["invoice_data_json"])

    db = AsyncMock()
    # Provide enough scalar results for every db.execute the path may make:
    # org-for-signature, latest-payment, (share-token persist when missing),
    # invoice-for-auto-issue, org-for-numbering. Extra entries are harmless.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),          # org for signature
            _scalar_one_or_none_result(None),         # latest payment (none)
            _scalar_one_or_none_result(invoice_obj),  # share-token persist OR auto-issue
            _scalar_one_or_none_result(invoice_obj),  # auto-issue / numbering
            _scalar_one_or_none_result(org),          # org for numbering
            _scalar_one_or_none_result(None),
        ]
    )

    captured: dict = {}

    def _capture_render(text_body, **kwargs):
        captured["cta_url"] = kwargs.get("cta_url")
        captured["cta_label"] = kwargs.get("cta_label")
        return "<html>rendered</html>"

    resolve_template_stub = AsyncMock(return_value=None)

    settings_stub = MagicMock()
    settings_stub.frontend_base_url = settings_frontend_base

    with patch(
        "app.modules.invoices.service.get_invoice",
        new_callable=AsyncMock,
        return_value=inv_dict,
    ), patch(
        "app.modules.invoices.service.generate_invoice_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake",
    ), patch(
        "app.modules.invoices.service.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.invoices.attachment_service.list_attachments",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.modules.notifications.service.resolve_template",
        new=resolve_template_stub,
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=AsyncMock(),
    ), patch(
        "app.integrations.email_sender.send_email",
        new=AsyncMock(return_value=_make_send_result()),
    ), patch(
        "app.integrations.email_sender.render_transactional_html",
        new=_capture_render,
    ), patch(
        "app.modules.invoices.service._maybe_create_stripe_payment_intent",
        new=AsyncMock(),
    ), patch(
        "app.config.settings",
        new=settings_stub,
    ):
        from app.modules.invoices.service import email_invoice

        await email_invoice(
            db,
            org_id=ORG_ID,
            invoice_id=INVOICE_ID,
            recipient_email="iqbalpannu1@gmail.com",
            base_url=base_url,
        )

    # template variables passed to resolve_template (kwargs)
    template_vars = resolve_template_stub.await_args.kwargs.get("variables", {})
    return captured.get("cta_url"), template_vars


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

EXPECTED_VIEW_URL = f"{FRONTEND_BASE}/api/v1/public/invoice/{SHARE_TOKEN}"


@pytest.mark.asyncio
async def test_paid_invoice_cta_links_to_invoice_view_not_payment_page():
    """The exact SPINV-0050 scenario: paid cash invoice with a payment_page_url.

    The CTA must be the invoice-view URL, never the /pay/ payment page.
    """
    cta_url, template_vars = await _drive_email_invoice(
        status="paid", gateway="cash", share_token=SHARE_TOKEN
    )

    assert cta_url == EXPECTED_VIEW_URL
    assert "/pay/" not in (cta_url or "")
    assert cta_url != PAYMENT_PAGE_URL
    # The default "View Invoice" template button uses {{payment_link}} — it must
    # now carry the invoice-view URL, not the payment page.
    assert template_vars.get("payment_link") == EXPECTED_VIEW_URL


@pytest.mark.asyncio
async def test_issued_invoice_cta_links_to_invoice_view():
    """An unpaid/issued invoice also links to the invoice view (which itself
    renders a "Pay Online" button while payable)."""
    cta_url, template_vars = await _drive_email_invoice(
        status="issued", gateway="stripe", share_token=SHARE_TOKEN
    )

    assert cta_url == EXPECTED_VIEW_URL
    assert "/pay/" not in (cta_url or "")
    assert template_vars.get("payment_link") == EXPECTED_VIEW_URL


@pytest.mark.asyncio
async def test_share_token_minted_when_missing():
    """When the invoice has no share_token yet, the CTA still resolves to an
    invoice-view URL (a token is minted), never the payment page."""
    cta_url, _ = await _drive_email_invoice(
        status="issued", gateway="cash", share_token=None
    )

    assert cta_url is not None
    assert cta_url.startswith(f"{FRONTEND_BASE}/api/v1/public/invoice/")
    assert "/pay/" not in cta_url


@pytest.mark.asyncio
async def test_background_send_uses_payment_page_origin_not_localhost():
    """Regression for the localhost leak (background auto-email path).

    On the mark-paid background path the router calls ``email_invoice`` with
    NO ``base_url`` and the deployed FRONTEND_BASE_URL may be a dev value like
    ``http://localhost``. The CTA must NOT become a localhost link — it should
    fall back to the PUBLIC origin already baked into the invoice's stored
    ``payment_page_url`` (the proven-reachable host), matching how the payment
    emails reuse that URL.
    """
    public_origin = "https://invoices.spautomotive.co.nz"

    cta_url, template_vars = await _drive_email_invoice(
        status="paid",
        gateway="cash",
        share_token=SHARE_TOKEN,
        base_url=None,  # background path: no request origin
        settings_frontend_base="http://localhost",  # dev config on the box
        payment_page_url=f"{public_origin}/pay/tok-123",
    )

    assert cta_url == f"{public_origin}/api/v1/public/invoice/{SHARE_TOKEN}"
    assert "localhost" not in (cta_url or "")
    assert "/pay/" not in (cta_url or "")
    assert template_vars.get("payment_link") == cta_url
