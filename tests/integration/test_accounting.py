"""Integration tests for Xero/MYOB accounting — OAuth flow, invoice/payment/credit note sync, failure handling.

Tests the full flow from integration clients and Celery tasks through to mocked API responses.
All Xero/MYOB API calls are mocked — no real API calls are made.

Requirements: 68.1-68.6
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.integrations.xero import (
    XERO_API_BASE,
    XERO_AUTH_URL,
    XERO_TOKEN_URL,
    exchange_code as xero_exchange_code,
    get_authorization_url as xero_get_authorization_url,
    get_tenant_id as xero_get_tenant_id,
    refresh_tokens as xero_refresh_tokens,
    sync_credit_note as xero_sync_credit_note,
    sync_invoice as xero_sync_invoice,
    sync_payment as xero_sync_payment,
)
from app.integrations.myob import (
    MYOB_AUTH_URL,
    MYOB_TOKEN_URL,
    exchange_code as myob_exchange_code,
    get_authorization_url as myob_get_authorization_url,
    get_company_file as myob_get_company_file,
    refresh_tokens as myob_refresh_tokens,
    sync_credit_note as myob_sync_credit_note,
    sync_invoice as myob_sync_invoice,
    sync_payment as myob_sync_payment,
)
from app.tasks.integrations import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    sync_credit_note_to_accounting_task,
    sync_invoice_to_accounting_task,
    sync_payment_to_accounting_task,
    retry_failed_sync_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REDIRECT_URI = "https://app.workshoppro.nz/settings/accounting/callback"
_ACCESS_TOKEN = "xero_access_token_abc123"
_REFRESH_TOKEN = "xero_refresh_token_xyz789"
_TENANT_ID = "xero-tenant-uuid-001"
_COMPANY_FILE_URI = "https://api.myob.com/accountright/abc-company-file"


def _mock_httpx_client(response_json, status_code=200, headers=None):
    """Create a mock httpx.AsyncClient context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json
    mock_response.headers = headers or {}
    if status_code >= 400:
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_response,
        )
    else:
        mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.put = AsyncMock(return_value=mock_response)
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_response


def _make_token_response(access_token=_ACCESS_TOKEN, refresh_token=_REFRESH_TOKEN):
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 1800,
        "token_type": "Bearer",
    }


def _make_invoice_data():
    return {
        "invoice_number": "INV-0042",
        "customer_name": "Test Workshop Ltd",
        "date": "2025-01-15",
        "due_date": "2025-02-14",
        "gst_inclusive": True,
        "currency": "NZD",
        "line_items": [
            {"description": "WOF Inspection", "quantity": 1, "unit_price": 50.00, "total": 50.00, "account_code": "200"},
            {"description": "Oil Change", "quantity": 1, "unit_price": 85.00, "total": 85.00, "account_code": "200"},
        ],
    }


def _make_payment_data():
    return {
        "invoice_number": "INV-0042",
        "customer_name": "Test Workshop Ltd",
        "date": "2025-01-20",
        "amount": 135.00,
        "reference": "Cash payment",
        "account_code": "090",
        "account_name": "Undeposited Funds",
        "currency_rate": 1.0,
    }


def _make_credit_note_data():
    return {
        "credit_note_number": "CN-0001",
        "customer_name": "Test Workshop Ltd",
        "date": "2025-01-22",
        "gst_inclusive": True,
        "currency": "NZD",
        "line_items": [
            {"description": "WOF Inspection - Refund", "quantity": 1, "unit_price": 50.00, "total": 50.00, "account_code": "200"},
        ],
    }


def _mock_celery_request(retries=0):
    """Create a mock Celery request context."""
    req = MagicMock()
    req.retries = retries
    return req


# ===========================================================================
# 1. Xero OAuth Connection Flow (Req 68.1)
# ===========================================================================


class TestXeroOAuthFlow:
    """Integration tests for the Xero OAuth 2.0 connection flow.

    Req 68.1: Org_Admin connects Xero account via OAuth from settings.
    """

    def test_authorization_url_contains_required_params(self):
        """Verify the Xero auth URL includes client_id, redirect_uri, scope, and state."""
        state = str(uuid.uuid4())
        url = xero_get_authorization_url(_REDIRECT_URI, state)

        assert XERO_AUTH_URL in url
        assert "response_type=code" in url
        assert f"state={state}" in url
        assert "redirect_uri=" in url
        assert "scope=" in url
        assert "accounting.transactions" in url

    def test_each_authorization_url_has_unique_state(self):
        """Each call should produce a URL with the given unique state."""
        state_a = str(uuid.uuid4())
        state_b = str(uuid.uuid4())
        url_a = xero_get_authorization_url(_REDIRECT_URI, state_a)
        url_b = xero_get_authorization_url(_REDIRECT_URI, state_b)

        assert state_a in url_a
        assert state_b in url_b
        assert url_a != url_b

    @pytest.mark.asyncio
    async def test_exchange_code_returns_tokens(self):
        """Verify code exchange returns access and refresh tokens."""
        token_resp = _make_token_response()
        mock_client, _ = _mock_httpx_client(token_resp)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_exchange_code("auth_code_123", _REDIRECT_URI)

        assert result["access_token"] == _ACCESS_TOKEN
        assert result["refresh_token"] == _REFRESH_TOKEN
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_tokens_returns_new_tokens(self):
        """Verify token refresh returns new access and refresh tokens."""
        new_tokens = _make_token_response("new_access", "new_refresh")
        mock_client, _ = _mock_httpx_client(new_tokens)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_refresh_tokens(_REFRESH_TOKEN)

        assert result["access_token"] == "new_access"
        assert result["refresh_token"] == "new_refresh"

    @pytest.mark.asyncio
    async def test_get_tenant_id_returns_first_connection(self):
        """Verify tenant ID retrieval returns the first connected tenant."""
        connections = [{"tenantId": _TENANT_ID, "tenantName": "My Company"}]
        mock_client, _ = _mock_httpx_client(connections)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            tenant_id = await xero_get_tenant_id(_ACCESS_TOKEN)

        assert tenant_id == _TENANT_ID

    @pytest.mark.asyncio
    async def test_get_tenant_id_returns_none_when_no_connections(self):
        """Verify None returned when no Xero connections exist."""
        mock_client, _ = _mock_httpx_client([])

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            tenant_id = await xero_get_tenant_id(_ACCESS_TOKEN)

        assert tenant_id is None

    @pytest.mark.asyncio
    async def test_exchange_code_propagates_api_error(self):
        """Verify HTTP errors from Xero token endpoint propagate."""
        mock_client, _ = _mock_httpx_client({"error": "invalid_grant"}, status_code=400)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await xero_exchange_code("bad_code", _REDIRECT_URI)


# ===========================================================================
# 2. MYOB OAuth Connection Flow (Req 68.2)
# ===========================================================================


class TestMYOBOAuthFlow:
    """Integration tests for the MYOB OAuth 2.0 connection flow.

    Req 68.2: Org_Admin connects MYOB account via OAuth from settings.
    """

    def test_authorization_url_contains_required_params(self):
        """Verify the MYOB auth URL includes client_id, redirect_uri, scope, and state."""
        state = str(uuid.uuid4())
        url = myob_get_authorization_url(_REDIRECT_URI, state)

        assert MYOB_AUTH_URL in url
        assert "response_type=code" in url
        assert f"state={state}" in url
        assert "redirect_uri=" in url
        assert "scope=CompanyFile" in url

    @pytest.mark.asyncio
    async def test_exchange_code_returns_tokens(self):
        """Verify MYOB code exchange returns access and refresh tokens."""
        token_resp = _make_token_response()
        mock_client, _ = _mock_httpx_client(token_resp)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_exchange_code("auth_code_456", _REDIRECT_URI)

        assert result["access_token"] == _ACCESS_TOKEN
        assert result["refresh_token"] == _REFRESH_TOKEN

    @pytest.mark.asyncio
    async def test_refresh_tokens_returns_new_tokens(self):
        """Verify MYOB token refresh returns new tokens."""
        new_tokens = _make_token_response("myob_new_access", "myob_new_refresh")
        mock_client, _ = _mock_httpx_client(new_tokens)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_refresh_tokens(_REFRESH_TOKEN)

        assert result["access_token"] == "myob_new_access"
        assert result["refresh_token"] == "myob_new_refresh"

    @pytest.mark.asyncio
    async def test_get_company_file_returns_first_file(self):
        """Verify company file retrieval returns the first available file."""
        files = [{"Id": "cf-001", "Name": "My Workshop", "Uri": _COMPANY_FILE_URI}]
        mock_client, _ = _mock_httpx_client(files)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_get_company_file(_ACCESS_TOKEN)

        assert result["Id"] == "cf-001"

    @pytest.mark.asyncio
    async def test_get_company_file_returns_none_when_empty(self):
        """Verify None returned when no MYOB company files exist."""
        mock_client, _ = _mock_httpx_client([])

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_get_company_file(_ACCESS_TOKEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_code_propagates_api_error(self):
        """Verify HTTP errors from MYOB token endpoint propagate."""
        mock_client, _ = _mock_httpx_client({"error": "invalid_grant"}, status_code=400)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await myob_exchange_code("bad_code", _REDIRECT_URI)


# ===========================================================================
# 3. Invoice Sync to Xero (Req 68.3)
# ===========================================================================


class TestXeroInvoiceSync:
    """Integration tests for syncing invoices to Xero.

    Req 68.3: Issued invoices auto-sync to connected accounting software.
    """

    @pytest.mark.asyncio
    async def test_sync_invoice_constructs_correct_payload(self):
        """Verify the Xero invoice payload has correct structure and data."""
        invoice_data = _make_invoice_data()
        xero_response = {"Invoices": [{"InvoiceID": "xero-inv-001", "Status": "AUTHORISED"}]}
        mock_client, _ = _mock_httpx_client(xero_response)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_sync_invoice(_ACCESS_TOKEN, _TENANT_ID, invoice_data)

        # Verify API was called with correct endpoint and headers
        call_kwargs = mock_client.post.call_args
        assert f"{XERO_API_BASE}/Invoices" in str(call_kwargs)
        assert result["Invoices"][0]["InvoiceID"] == "xero-inv-001"

        # Verify payload structure
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        inv = payload["Invoices"][0]
        assert inv["Type"] == "ACCREC"
        assert inv["Contact"]["Name"] == "Test Workshop Ltd"
        assert inv["Reference"] == "INV-0042"
        assert inv["CurrencyCode"] == "NZD"
        assert len(inv["LineItems"]) == 2

    @pytest.mark.asyncio
    async def test_sync_invoice_line_items_map_correctly(self):
        """Verify line items are mapped with description, quantity, unit amount."""
        invoice_data = _make_invoice_data()
        xero_response = {"Invoices": [{"InvoiceID": "xero-inv-002"}]}
        mock_client, _ = _mock_httpx_client(xero_response)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            await xero_sync_invoice(_ACCESS_TOKEN, _TENANT_ID, invoice_data)

        payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        items = payload["Invoices"][0]["LineItems"]
        assert items[0]["Description"] == "WOF Inspection"
        assert items[0]["Quantity"] == 1
        assert items[0]["UnitAmount"] == "50.0"
        assert items[1]["Description"] == "Oil Change"

    @pytest.mark.asyncio
    async def test_sync_invoice_api_error_propagates(self):
        """Verify Xero API errors propagate as HTTPStatusError."""
        mock_client, _ = _mock_httpx_client({"error": "unauthorized"}, status_code=401)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await xero_sync_invoice(_ACCESS_TOKEN, _TENANT_ID, _make_invoice_data())


# ===========================================================================
# 4. Invoice Sync to MYOB (Req 68.3)
# ===========================================================================


class TestMYOBInvoiceSync:
    """Integration tests for syncing invoices to MYOB.

    Req 68.3: Issued invoices auto-sync to connected accounting software.
    """

    @pytest.mark.asyncio
    async def test_sync_invoice_constructs_correct_payload(self):
        """Verify the MYOB invoice payload has correct structure and data."""
        invoice_data = _make_invoice_data()
        mock_client, mock_resp = _mock_httpx_client(
            {}, status_code=201, headers={"Location": "/Sale/Invoice/Service/uid-001"},
        )
        # MYOB returns 201 — override raise_for_status to not error
        mock_resp.raise_for_status = MagicMock()

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_sync_invoice(_ACCESS_TOKEN, _COMPANY_FILE_URI, invoice_data)

        assert result["status"] == "created"
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["Number"] == "INV-0042"
        assert payload["Customer"]["Name"] == "Test Workshop Ltd"
        assert payload["IsTaxInclusive"] is True
        assert len(payload["Lines"]) == 2

    @pytest.mark.asyncio
    async def test_sync_invoice_uses_correct_endpoint(self):
        """Verify MYOB invoice sync calls the Sale/Invoice/Service endpoint."""
        mock_client, mock_resp = _mock_httpx_client({}, status_code=201)
        mock_resp.raise_for_status = MagicMock()

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            await myob_sync_invoice(_ACCESS_TOKEN, _COMPANY_FILE_URI, _make_invoice_data())

        url_called = str(mock_client.post.call_args)
        assert "Sale/Invoice/Service" in url_called

    @pytest.mark.asyncio
    async def test_sync_invoice_api_error_propagates(self):
        """Verify MYOB API errors propagate as HTTPStatusError."""
        mock_client, _ = _mock_httpx_client({"error": "forbidden"}, status_code=403)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await myob_sync_invoice(_ACCESS_TOKEN, _COMPANY_FILE_URI, _make_invoice_data())


# ===========================================================================
# 5. Payment Sync (Req 68.4)
# ===========================================================================


class TestPaymentSync:
    """Integration tests for syncing payments to Xero and MYOB.

    Req 68.4: Recorded payments auto-sync to connected accounting software.
    """

    @pytest.mark.asyncio
    async def test_xero_payment_sync_payload(self):
        """Verify Xero payment payload includes invoice number, amount, and account."""
        payment_data = _make_payment_data()
        xero_response = {"Payments": [{"PaymentID": "xero-pay-001"}]}
        mock_client, _ = _mock_httpx_client(xero_response)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_sync_payment(_ACCESS_TOKEN, _TENANT_ID, payment_data)

        assert result["Payments"][0]["PaymentID"] == "xero-pay-001"
        payload = mock_client.put.call_args.kwargs.get("json") or mock_client.put.call_args[1].get("json")
        pay = payload["Payments"][0]
        assert pay["Invoice"]["InvoiceNumber"] == "INV-0042"
        assert pay["Amount"] == "135.0"
        assert pay["Account"]["Code"] == "090"

    @pytest.mark.asyncio
    async def test_myob_payment_sync_payload(self):
        """Verify MYOB payment payload includes customer, amount, and invoice reference."""
        payment_data = _make_payment_data()
        mock_client, mock_resp = _mock_httpx_client({}, status_code=201)
        mock_resp.raise_for_status = MagicMock()

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_sync_payment(_ACCESS_TOKEN, _COMPANY_FILE_URI, payment_data)

        assert result["status"] == "created"
        payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        assert payload["ReceiveFrom"] == "Test Workshop Ltd"
        assert payload["AmountReceived"] == "135.0"
        assert payload["Invoices"][0]["Number"] == "INV-0042"

    @pytest.mark.asyncio
    async def test_xero_payment_sync_error_propagates(self):
        """Verify Xero payment API errors propagate."""
        mock_client, _ = _mock_httpx_client({"error": "not_found"}, status_code=404)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await xero_sync_payment(_ACCESS_TOKEN, _TENANT_ID, _make_payment_data())


# ===========================================================================
# 6. Credit Note Sync (Req 68.5)
# ===========================================================================


class TestCreditNoteSync:
    """Integration tests for syncing credit notes to Xero and MYOB.

    Req 68.5: Credit notes auto-sync to connected accounting software.
    """

    @pytest.mark.asyncio
    async def test_xero_credit_note_sync_payload(self):
        """Verify Xero credit note payload has ACCRECCREDIT type and correct data."""
        cn_data = _make_credit_note_data()
        xero_response = {"CreditNotes": [{"CreditNoteID": "xero-cn-001", "Status": "AUTHORISED"}]}
        mock_client, _ = _mock_httpx_client(xero_response)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_sync_credit_note(_ACCESS_TOKEN, _TENANT_ID, cn_data)

        assert result["CreditNotes"][0]["CreditNoteID"] == "xero-cn-001"
        payload = mock_client.put.call_args.kwargs.get("json") or mock_client.put.call_args[1].get("json")
        cn = payload["CreditNotes"][0]
        assert cn["Type"] == "ACCRECCREDIT"
        assert cn["Contact"]["Name"] == "Test Workshop Ltd"
        assert cn["Reference"] == "CN-0001"
        assert len(cn["LineItems"]) == 1

    @pytest.mark.asyncio
    async def test_myob_credit_note_sync_payload(self):
        """Verify MYOB credit note payload uses CreditSettlement endpoint."""
        cn_data = _make_credit_note_data()
        mock_client, mock_resp = _mock_httpx_client({}, status_code=201)
        mock_resp.raise_for_status = MagicMock()

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_sync_credit_note(_ACCESS_TOKEN, _COMPANY_FILE_URI, cn_data)

        assert result["status"] == "created"
        url_called = str(mock_client.post.call_args)
        assert "Sale/CreditSettlement" in url_called
        payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1].get("json")
        assert payload["Number"] == "CN-0001"
        assert payload["Customer"]["Name"] == "Test Workshop Ltd"

    @pytest.mark.asyncio
    async def test_xero_credit_note_error_propagates(self):
        """Verify Xero credit note API errors propagate."""
        mock_client, _ = _mock_httpx_client({"error": "server_error"}, status_code=500)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await xero_sync_credit_note(_ACCESS_TOKEN, _TENANT_ID, _make_credit_note_data())


# ===========================================================================
# 7. Sync Failure Handling and Retry (Req 68.6)
# ===========================================================================


class TestSyncFailureHandling:
    """Integration tests for sync failure logging, warnings, and manual retry.

    Req 68.6: Sync failures are logged, warning displayed, manual retry available.
    """

    def test_sync_invoice_task_rejects_invalid_provider(self):
        """Verify invalid provider returns error without calling sync."""
        result = sync_invoice_to_accounting_task(
            org_id=str(uuid.uuid4()),
            entity_id=str(uuid.uuid4()),
            provider="quickbooks",
            invoice_data=_make_invoice_data(),
        )
        assert "error" in result
        assert "Invalid provider" in result["error"]

    def test_sync_payment_task_rejects_invalid_provider(self):
        """Verify invalid provider returns error for payment sync."""
        result = sync_payment_to_accounting_task(
            org_id=str(uuid.uuid4()),
            entity_id=str(uuid.uuid4()),
            provider="sage",
            payment_data=_make_payment_data(),
        )
        assert "error" in result
        assert "Invalid provider" in result["error"]

    def test_sync_credit_note_task_rejects_invalid_provider(self):
        """Verify invalid provider returns error for credit note sync."""
        result = sync_credit_note_to_accounting_task(
            org_id=str(uuid.uuid4()),
            entity_id=str(uuid.uuid4()),
            provider="invalid",
            credit_note_data=_make_credit_note_data(),
        )
        assert "error" in result
        assert "Invalid provider" in result["error"]

    def test_retry_failed_sync_task_rejects_invalid_provider(self):
        """Verify retry task rejects invalid provider."""
        result = retry_failed_sync_task(
            org_id=str(uuid.uuid4()),
            provider="invalid",
        )
        assert "error" in result
        assert "Invalid provider" in result["error"]

    def test_sync_invoice_task_successful_result(self):
        """Verify successful sync returns the result from the async handler."""
        sync_result = {"status": "synced", "external_id": "xero-inv-099"}

        with patch("app.tasks.integrations._run_async", return_value=sync_result):
            result = sync_invoice_to_accounting_task(
                org_id=str(uuid.uuid4()),
                entity_id=str(uuid.uuid4()),
                provider="xero",
                invoice_data=_make_invoice_data(),
            )

        assert result["status"] == "synced"
        assert result["external_id"] == "xero-inv-099"

    def test_sync_payment_task_successful_result(self):
        """Verify successful payment sync returns the result."""
        sync_result = {"status": "synced", "external_id": "myob-pay-001"}

        with patch("app.tasks.integrations._run_async", return_value=sync_result):
            result = sync_payment_to_accounting_task(
                org_id=str(uuid.uuid4()),
                entity_id=str(uuid.uuid4()),
                provider="myob",
                payment_data=_make_payment_data(),
            )

        assert result["status"] == "synced"

    def test_sync_credit_note_task_successful_result(self):
        """Verify successful credit note sync returns the result."""
        sync_result = {"status": "synced", "external_id": "xero-cn-001"}

        with patch("app.tasks.integrations._run_async", return_value=sync_result):
            result = sync_credit_note_to_accounting_task(
                org_id=str(uuid.uuid4()),
                entity_id=str(uuid.uuid4()),
                provider="xero",
                credit_note_data=_make_credit_note_data(),
            )

        assert result["status"] == "synced"

    def test_sync_task_failed_result_returned(self):
        """Verify a failed sync result (from service layer) is returned correctly."""
        sync_result = {"status": "failed", "error_message": "Contact not found in Xero"}

        with patch("app.tasks.integrations._run_async", return_value=sync_result):
            result = sync_invoice_to_accounting_task(
                org_id=str(uuid.uuid4()),
                entity_id=str(uuid.uuid4()),
                provider="xero",
                invoice_data=_make_invoice_data(),
            )

        assert result["status"] == "failed"
        assert "Contact not found" in result["error_message"]

    def test_retry_failed_sync_task_returns_counts(self):
        """Verify retry task returns synced/failed counts."""
        retry_result = {"synced": 3, "failed": 1}

        with patch("app.tasks.integrations._run_async", return_value=retry_result):
            result = retry_failed_sync_task(
                org_id=str(uuid.uuid4()),
                provider="xero",
            )

        assert result["synced"] == 3
        assert result["failed"] == 1

    def test_max_retries_configured_correctly(self):
        """Verify the max retries constant is set to 3."""
        assert MAX_RETRIES == 3

    def test_retry_backoff_configured(self):
        """Verify the retry backoff base delay is 60 seconds."""
        assert RETRY_BACKOFF == 60


# ===========================================================================
# 8. Token Refresh on 401 Responses (Req 68.1, 68.2)
# ===========================================================================


class TestTokenRefreshOn401:
    """Integration tests for token refresh when API returns 401.

    Req 68.1/68.2: OAuth tokens can be refreshed when expired.
    """

    @pytest.mark.asyncio
    async def test_xero_refresh_on_expired_token(self):
        """Verify Xero token refresh works and returns new credentials."""
        new_tokens = _make_token_response("refreshed_access", "refreshed_refresh")
        mock_client, _ = _mock_httpx_client(new_tokens)

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            result = await xero_refresh_tokens("old_refresh_token")

        assert result["access_token"] == "refreshed_access"
        assert result["refresh_token"] == "refreshed_refresh"
        # Verify the refresh grant type was used
        call_kwargs = mock_client.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["grant_type"] == "refresh_token"

    @pytest.mark.asyncio
    async def test_myob_refresh_on_expired_token(self):
        """Verify MYOB token refresh works and returns new credentials."""
        new_tokens = _make_token_response("myob_refreshed", "myob_new_refresh")
        mock_client, _ = _mock_httpx_client(new_tokens)

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            result = await myob_refresh_tokens("old_myob_refresh")

        assert result["access_token"] == "myob_refreshed"
        call_kwargs = mock_client.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["grant_type"] == "refresh_token"

    @pytest.mark.asyncio
    async def test_xero_refresh_with_invalid_token_raises(self):
        """Verify refresh with invalid token propagates error."""
        mock_client, _ = _mock_httpx_client(
            {"error": "invalid_grant"}, status_code=400,
        )

        with patch("app.integrations.xero.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await xero_refresh_tokens("invalid_refresh_token")

    @pytest.mark.asyncio
    async def test_myob_refresh_with_invalid_token_raises(self):
        """Verify MYOB refresh with invalid token propagates error."""
        mock_client, _ = _mock_httpx_client(
            {"error": "invalid_grant"}, status_code=400,
        )

        with patch("app.integrations.myob.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await myob_refresh_tokens("invalid_refresh_token")
