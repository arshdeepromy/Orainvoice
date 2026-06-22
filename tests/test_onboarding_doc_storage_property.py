"""Property-based test for onboarding working-rights document storage (Task 8.11).

Feature: staff-onboarding-link
Property 17: Working-rights documents are stored and linked

Drives the REAL public submit endpoint
``POST /api/v2/public/staff-onboarding/{token}`` (``onboarding_submit`` in
``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
client (``httpx.AsyncClient`` + ``ASGITransport``) — the route is public so no
JWT is required. The DB harness mirrors the other DB-backed onboarding property
tests in this repo (fresh async engine per example, full ORM import block,
``_ORG_MARKER`` cleanup that also clears ``compliance_documents``,
``_seed_org_and_staff``, ``@settings`` with health-check suppression, and an
``asyncio.run`` driver).

For every example we seed one organisation + one active staff member, mint a
pending onboarding token via ``onboarding_tokens.mint``, then POST a multipart
submit carrying 1..3 VALID working-rights documents (each with correct magic
bytes for its declared ``content_type`` — PDF ``%PDF``, PNG ``\\x89PNG``, JPEG
``\\xff\\xd8\\xff`` — and ≤10 MB) plus minimal valid fields. After a ``200`` we
re-query ``compliance_documents`` WHERE ``staff_id == staff.id`` from a fresh
session and assert:

1. **Count** — exactly as many rows as documents uploaded (R7.6).
2. **Linkage** — every row has ``staff_id == staff.id`` and
   ``org_id == token.org_id`` (linked to the staff member AND the org, R7.6).
3. **Type** — every row has ``document_type == "working_rights"`` (R7.6).
4. **Retrievable** — every row has a non-empty ``file_name`` and ``file_key``,
   and the file actually exists on disk under the storage base path (so the
   stored document can be streamed back, R7.6).

Validates: Requirements 7.6

Notes:
- ``ComplianceService.upload_document_with_file`` instantiates
  ``ComplianceFileStorage()`` with its hardcoded default base path
  (``/app/compliance_files``) and there is no UPLOAD_DIR env knob, so the test
  patches the storage class with a ``functools.partial`` that injects a writable
  per-example tempdir as ``base_path`` and removes the tempdir afterwards.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
- The two post-commit / in-transaction side effects that are NOT part of
  Property 17 (the org in-app notification and the completion emails) are
  isolated with no-op patches so the test exercises the real persistence +
  storage path without network calls or coupling to the notifications schema.
"""

from __future__ import annotations

import asyncio
import functools
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_onboarding_persist_identity_property.py).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401

from app.core.database import get_db_session
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.compliance_docs.file_storage import ComplianceFileStorage
from app.modules.compliance_docs.models import ComplianceDocument
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_11_doc_storage"


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _cleanup(factory) -> None:
    """Delete every row created by the seeder (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in (
                "app_notifications",
                "compliance_documents",
                "staff_onboarding_tokens",
                "staff_members",
            ):
                await session.execute(
                    sa_text(f"DELETE FROM {tbl} WHERE org_id IN ({org_subq})"),
                    params,
                )
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


async def _seed_org_and_staff(factory) -> dict:
    """Seed one org + one active staff member; return their ids."""
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            org = Organisation(
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add(org)
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Onboarding Test Staff",
                first_name="Onboarding",
                last_name="OriginalLast",
                email="onboard-test@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


def _build_app(factory) -> FastAPI:
    """Build an app exposing ONLY the public onboarding router at the prod path."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    async def _override_db():
        async with factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(
        onboarding_public_router, prefix="/api/v2/public/staff-onboarding"
    )
    return app


# ---------------------------------------------------------------------------
# Generators — VALID working-rights documents.
# ---------------------------------------------------------------------------

# Each MIME maps to (magic-byte header, file extension). The header bytes must
# satisfy ComplianceFileStorage._validate_magic_bytes for the declared MIME:
#   PDF  -> b"%PDF"        PNG -> b"\x89PNG"        JPEG -> b"\xff\xd8\xff"
# We prepend a realistic full signature so the bytes are unambiguously valid.
_MIME_INFO: dict[str, tuple[bytes, str]] = {
    "application/pdf": (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", "pdf"),
    "image/jpeg": (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00", "jpg"),
    "image/png": (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "png"),
}

_MIME_TYPES = tuple(_MIME_INFO.keys())

# A single document descriptor: (mime, padding length). Padding keeps files
# tiny (well under the 10 MB cap) so 100 examples writing to disk stay fast,
# while still varying the byte content.
_doc_strategy = st.fixed_dictionaries(
    {
        "mime": st.sampled_from(_MIME_TYPES),
        "pad": st.integers(min_value=0, max_value=256),
    }
)

# 1..3 documents per submission (MAX_DOCUMENT_COUNT == 3), varying the MIME mix.
_documents_strategy = st.lists(_doc_strategy, min_size=1, max_size=3)


def _build_files(docs: list[dict]) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Render generated doc descriptors as httpx multipart ``files`` entries.

    Every part is named ``documents`` (the submit handler binds them to a
    ``list[UploadFile]``). Each carries a valid magic-byte header for its
    declared content_type plus deterministic padding.
    """
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for idx, doc in enumerate(docs):
        mime = doc["mime"]
        header, ext = _MIME_INFO[mime]
        content = header + (b"\x00" * doc["pad"])
        filename = f"working_rights_{idx}.{ext}"
        files.append(("documents", (filename, content, mime)))
    return files


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(docs: list[dict]) -> None:
    """Seed, mint, POST docs to the submit endpoint, assert storage + linkage."""
    engine, factory = await _make_engine_and_factory()
    tmpdir = tempfile.mkdtemp(prefix="test_8_11_compliance_")
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token; capture the RAW token for the URL. ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        app = _build_app(factory)
        files = _build_files(docs)

        # Minimal valid non-file fields: a last name + phone. Emergency contact
        # is omitted entirely (both-empty is valid), bank is not required by
        # default, and IRD is optional — so the only thing under test is the
        # working-rights document storage path.
        form = {"last_name": "Smith", "phone": "021000111"}

        # Storage writes to a hardcoded default base path with no env override,
        # so patch the class with a partial that injects a writable tempdir.
        patched_storage = functools.partial(ComplianceFileStorage, base_path=tmpdir)

        # Isolate the unrelated side effects (in-app notification + completion
        # emails) that are NOT part of Property 17.
        with patch(
            "app.modules.compliance_docs.service.ComplianceFileStorage",
            new=patched_storage,
        ), patch(
            "app.modules.staff.public_router._dispatch_completion_emails",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}",
                    data=form,
                    files=files,
                )

        assert resp.status_code == 200, (
            f"expected 200 from submit, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("ok") is True, f"submit not ok: {resp.text}"

        expected_count = len(docs)

        # --- Re-query the persisted compliance_documents from a FRESH session. ---
        async with factory() as session:
            rows = (
                await session.execute(
                    sa_text(
                        "SELECT org_id, staff_id, document_type, file_name, file_key "
                        "FROM compliance_documents WHERE staff_id = :sid"
                    ),
                    {"sid": staff_id},
                )
            ).mappings().all()

            # 1. Count — one row per uploaded document (R7.6).
            assert len(rows) == expected_count, (
                f"expected {expected_count} compliance_documents for staff, "
                f"found {len(rows)}"
            )

            for row in rows:
                # 2. Linkage — attached to the staff member AND the org (R7.6).
                assert row["staff_id"] == staff_id, "document not linked to staff"
                assert row["org_id"] == org_id, "document org_id mismatch"

                # 3. Type — working-rights document (R7.6).
                assert row["document_type"] == "working_rights", (
                    f"unexpected document_type: {row['document_type']!r}"
                )

                # 4. Retrievable — file_name + file_key present, file on disk.
                assert row["file_name"], "file_name missing (not retrievable)"
                assert row["file_key"], "file_key missing (not retrievable)"
                stored = Path(tmpdir) / row["file_key"]
                assert stored.is_file(), (
                    f"stored file missing on disk: {stored} (not retrievable)"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 17: Working-rights documents are stored and linked.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(docs=_documents_strategy)
def test_working_rights_documents_stored_and_linked(docs: list[dict]):
    """Property 17: Working-rights documents are stored and linked.

    Driving the real ``POST /api/v2/public/staff-onboarding/{token}`` endpoint:
    after a ``200`` with 1..3 valid documents uploaded, exactly that many
    ``compliance_documents`` rows exist for the staff member, each linked to the
    correct ``staff_id`` / ``org_id``, typed ``working_rights``, and retrievable
    (``file_name`` + ``file_key`` present and the file on disk).

    **Validates: Requirements 7.6**
    """
    asyncio.run(_run_example(docs))


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted example."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
