"""Unit tests for compliance document router endpoints.

Tests upload, download, edit, delete, categories, and badge-count endpoints
using httpx AsyncClient with ASGITransport and mocked service/storage layers.

**Validates: Requirements 3.4, 3.5, 4.2, 4.3, 5.3, 12.5**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.modules.compliance_docs.router import router

ORG_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDoc:
    """Lightweight stand-in for ComplianceDocument that Pydantic can serialise."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_doc(
    *,
    doc_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    document_type: str = "Business License",
    description: str | None = "Test document",
    file_key: str = "compliance/org/uuid_test.pdf",
    file_name: str = "test.pdf",
    expiry_date: date | None = None,
    invoice_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    uploaded_by: uuid.UUID | None = None,
) -> _FakeDoc:
    """Create a fake ComplianceDocument object compatible with Pydantic model_validate."""
    return _FakeDoc(
        id=doc_id or DOC_ID,
        org_id=org_id or ORG_ID,
        document_type=document_type,
        description=description,
        file_key=file_key,
        file_name=file_name,
        expiry_date=expiry_date,
        invoice_id=invoice_id,
        job_id=job_id,
        uploaded_by=uploaded_by,
        created_at=datetime.now(timezone.utc),
    )


def _make_mock_category(
    *,
    name: str = "Business License",
    is_predefined: bool = True,
    org_id: uuid.UUID | None = None,
) -> _FakeDoc:
    """Create a fake ComplianceDocumentCategory object compatible with Pydantic."""
    return _FakeDoc(
        id=uuid.uuid4(),
        name=name,
        is_predefined=is_predefined,
        org_id=org_id,
        created_at=datetime.now(timezone.utc),
    )


def _build_test_app() -> FastAPI:
    """Build a FastAPI app with the compliance docs router and mocked DB."""
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v2/compliance-docs")

    async def _mock_db_session():
        yield AsyncMock()

    test_app.dependency_overrides[get_db_session] = _mock_db_session

    @test_app.middleware("http")
    async def _inject_org_and_user(request, call_next):
        request.state.org_id = str(ORG_ID)
        request.state.user_id = str(USER_ID)
        return await call_next(request)

    return test_app


# ---------------------------------------------------------------------------
# Upload endpoint tests
# ---------------------------------------------------------------------------


class TestUploadEndpoint:
    """Tests for POST /api/v2/compliance-docs/upload."""

    @pytest.mark.asyncio
    async def test_upload_returns_201_with_valid_file(self):
        """Valid multipart upload returns 201 with document response.

        **Validates: Requirements 3.4**
        """
        mock_doc = _make_mock_doc()
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.upload_document_with_file = AsyncMock(return_value=mock_doc)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v2/compliance-docs/upload",
                    files={"file": ("test.pdf", b"%PDF-1.4 content", "application/pdf")},
                    data={"document_type": "Business License"},
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["file_name"] == "test.pdf"
        assert data["document_type"] == "Business License"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_upload_returns_400_for_invalid_mime(self):
        """Upload with invalid MIME type returns 400.

        **Validates: Requirements 3.4**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.upload_document_with_file = AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="File type not accepted. Allowed types: PDF, JPEG, PNG, GIF, Word (.doc, .docx)",
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v2/compliance-docs/upload",
                    files={"file": ("malware.exe", b"MZ\x90\x00", "application/x-msdownload")},
                    data={"document_type": "Business License"},
                )

        assert resp.status_code == 400
        assert "File type not accepted" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_returns_400_for_oversized_file(self):
        """Upload with file exceeding 10MB returns 400.

        **Validates: Requirements 3.5**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.upload_document_with_file = AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="File size exceeds maximum of 10MB",
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v2/compliance-docs/upload",
                    files={"file": ("big.pdf", b"%PDF" + b"x" * 100, "application/pdf")},
                    data={"document_type": "Business License"},
                )

        assert resp.status_code == 400
        assert "File size exceeds" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_returns_400_for_magic_byte_mismatch(self):
        """Upload where magic bytes don't match declared MIME returns 400.

        **Validates: Requirements 12.5**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            instance = MockSvc.return_value
            instance.upload_document_with_file = AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="File type could not be verified. The file content does not match the declared type.",
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v2/compliance-docs/upload",
                    files={"file": ("fake.pdf", b"NOT_A_PDF_CONTENT", "application/pdf")},
                    data={"document_type": "Business License"},
                )

        assert resp.status_code == 400
        assert "File type could not be verified" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Download endpoint tests
# ---------------------------------------------------------------------------


class TestDownloadEndpoint:
    """Tests for GET /api/v2/compliance-docs/{doc_id}/download."""

    @pytest.mark.asyncio
    async def test_download_streams_file_with_correct_headers(self):
        """Download returns streaming response with Content-Type and Content-Disposition.

        **Validates: Requirements 4.2, 4.3**
        """
        mock_doc = _make_mock_doc(file_name="license.pdf")
        test_app = _build_test_app()

        async def _mock_stream():
            yield b"%PDF-1.4 file content"

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc, patch(
            "app.modules.compliance_docs.router.ComplianceFileStorage"
        ) as MockStorage:
            svc_instance = MockSvc.return_value
            svc_instance.get_document_for_download = AsyncMock(return_value=mock_doc)

            storage_instance = MockStorage.return_value
            storage_instance.read_file = AsyncMock(
                return_value=(_mock_stream(), "application/pdf")
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v2/compliance-docs/{DOC_ID}/download"
                )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert 'attachment; filename="license.pdf"' in resp.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_download_returns_403_for_cross_org_access(self):
        """Download returns 403 when document belongs to another org.

        **Validates: Requirements 4.2**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.get_document_for_download = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v2/compliance-docs/{uuid.uuid4()}/download"
                )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Access denied"

    @pytest.mark.asyncio
    async def test_download_returns_404_for_missing_file(self):
        """Download returns 404 when document record exists but file is missing.

        **Validates: Requirements 4.3**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.get_document_for_download = AsyncMock(
                side_effect=HTTPException(
                    status_code=404,
                    detail="Compliance document not found",
                )
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/v2/compliance-docs/{uuid.uuid4()}/download"
                )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Edit endpoint tests
# ---------------------------------------------------------------------------


class TestEditEndpoint:
    """Tests for PUT /api/v2/compliance-docs/{doc_id}."""

    @pytest.mark.asyncio
    async def test_edit_updates_only_specified_fields(self):
        """PUT updates only the fields provided in the payload.

        **Validates: Requirements 5.3**
        """
        updated_doc = _make_mock_doc(
            description="Updated description",
            expiry_date=date(2026, 12, 31),
        )
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.update_document = AsyncMock(return_value=updated_doc)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    f"/api/v2/compliance-docs/{DOC_ID}",
                    json={"description": "Updated description"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated description"

        # Verify service was called with only the provided field
        call_args = svc_instance.update_document.call_args
        update_data = call_args[1].get("payload") or call_args[0][2]
        assert "description" in update_data
        # document_type and expiry_date should not be in the update payload
        assert "document_type" not in update_data

    @pytest.mark.asyncio
    async def test_edit_returns_403_for_cross_org_access(self):
        """PUT returns 403 when document belongs to another org.

        **Validates: Requirements 5.3**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.update_document = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    f"/api/v2/compliance-docs/{uuid.uuid4()}",
                    json={"description": "Hacked"},
                )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete endpoint tests
# ---------------------------------------------------------------------------


class TestDeleteEndpoint:
    """Tests for DELETE /api/v2/compliance-docs/{doc_id}."""

    @pytest.mark.asyncio
    async def test_delete_removes_record_and_file(self):
        """DELETE returns 204 and calls service to remove record + file.

        **Validates: Requirements 5.3**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.delete_document = AsyncMock(return_value=None)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.delete(
                    f"/api/v2/compliance-docs/{DOC_ID}"
                )

        assert resp.status_code == 204
        svc_instance.delete_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_returns_403_for_cross_org_access(self):
        """DELETE returns 403 when document belongs to another org.

        **Validates: Requirements 5.3**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.delete_document = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Access denied")
            )

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.delete(
                    f"/api/v2/compliance-docs/{uuid.uuid4()}"
                )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Categories endpoint tests
# ---------------------------------------------------------------------------


class TestCategoriesEndpoint:
    """Tests for GET /api/v2/compliance-docs/categories."""

    @pytest.mark.asyncio
    async def test_categories_returns_predefined_and_custom_with_predefined_first(self):
        """Categories endpoint returns predefined categories before custom ones.

        **Validates: Requirements 3.4**
        """
        predefined_cats = [
            _make_mock_category(name="Business License", is_predefined=True),
            _make_mock_category(name="Public Liability Insurance", is_predefined=True),
        ]
        custom_cats = [
            _make_mock_category(name="Custom Cert", is_predefined=False, org_id=ORG_ID),
        ]
        # Service returns predefined first, then custom (as per service ordering)
        all_cats = predefined_cats + custom_cats

        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.get_categories = AsyncMock(return_value=all_cats)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v2/compliance-docs/categories")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        items = data["items"]
        # Predefined categories come first
        assert items[0]["is_predefined"] is True
        assert items[1]["is_predefined"] is True
        assert items[2]["is_predefined"] is False
        assert items[2]["name"] == "Custom Cert"


# ---------------------------------------------------------------------------
# Badge count endpoint tests
# ---------------------------------------------------------------------------


class TestBadgeCountEndpoint:
    """Tests for GET /api/v2/compliance-docs/badge-count."""

    @pytest.mark.asyncio
    async def test_badge_count_returns_0_when_no_documents_expiring(self):
        """Badge count returns 0 when no documents are expired or expiring soon.

        **Validates: Requirements 3.4**
        """
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.get_badge_count = AsyncMock(return_value=0)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v2/compliance-docs/badge-count")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_badge_count_returns_positive_when_documents_expiring(self):
        """Badge count returns correct count when documents are expiring."""
        test_app = _build_test_app()

        with patch(
            "app.modules.compliance_docs.router.ComplianceService"
        ) as MockSvc:
            svc_instance = MockSvc.return_value
            svc_instance.get_badge_count = AsyncMock(return_value=5)

            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v2/compliance-docs/badge-count")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 5
