"""Tests for the database migration tool (Task 49).

Covers:
- 49.8: Full migration imports all records with correct references
- 49.9: Integrity check detects missing customer references
- 49.10: Rollback removes all migrated data without affecting pre-existing records

Requirements: 7.1–7.8, 41.1–41.6
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.migration_service import (
    DataMigrationService,
    ENTITY_TYPES,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_INTEGRITY_CHECK,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_VALIDATING,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source_data(
    num_customers: int = 2,
    num_products: int = 2,
    num_invoices: int = 2,
    num_payments: int = 1,
    num_jobs: int = 1,
) -> dict:
    """Generate sample source data for migration tests."""
    customers = [
        {"id": f"cust-{i}", "name": f"Customer {i}", "email": f"c{i}@test.com"}
        for i in range(num_customers)
    ]
    products = [
        {"id": f"prod-{i}", "name": f"Product {i}", "sale_price": 100.0 + i, "cost_price": 50.0}
        for i in range(num_products)
    ]
    invoices = [
        {
            "id": f"inv-{i}",
            "invoice_number": f"INV-{1000 + i}",
            "customer_id": f"cust-{i % num_customers}",
            "total_amount": 200.0 + i,
            "tax_amount": 30.0,
            "status": "issued",
        }
        for i in range(num_invoices)
    ]
    payments = [
        {
            "id": f"pay-{i}",
            "invoice_id": f"inv-{i % num_invoices}",
            "amount": 200.0 + (i % num_invoices),
            "payment_method": "card",
        }
        for i in range(num_payments)
    ]
    jobs = [
        {
            "id": f"job-{i}",
            "job_number": f"JOB-{100 + i}",
            "customer_id": f"cust-{i % num_customers}",
            "status": "enquiry",
            "description": f"Test job {i}",
        }
        for i in range(num_jobs)
    ]
    return {
        "customers": customers,
        "products": products,
        "invoices": invoices,
        "payments": payments,
        "jobs": jobs,
    }


class MockDBSession:
    """Mock async DB session that tracks executed SQL and stores data."""

    def __init__(self):
        self.executed: list[tuple] = []
        self._tables: dict[str, list[dict]] = {
            "migration_jobs": [],
            "customers": [],
            "products": [],
            "invoices": [],
            "payments": [],
            "jobs": [],
            "organisations": [
                {"id": "org-1", "name": "Test Org", "setup_wizard_state": "{}"},
            ],
        }

    async def execute(self, stmt, params=None):
        sql = str(stmt) if hasattr(stmt, 'text') else str(stmt)
        self.executed.append((sql, params or {}))
        return self._handle_query(sql, params or {})

    def _handle_query(self, sql: str, params: dict) -> MagicMock:
        result = MagicMock()

        if "INSERT INTO migration_jobs" in sql:
            self._tables["migration_jobs"].append(params)
            result.rowcount = 1
        elif "INSERT INTO customers" in sql:
            self._tables["customers"].append(params)
            result.rowcount = 1
        elif "INSERT INTO products" in sql:
            self._tables["products"].append(params)
            result.rowcount = 1
        elif "INSERT INTO invoices" in sql:
            self._tables["invoices"].append(params)
            result.rowcount = 1
        elif "INSERT INTO payments" in sql:
            self._tables["payments"].append(params)
            result.rowcount = 1
        elif "INSERT INTO jobs" in sql:
            self._tables["jobs"].append(params)
            result.rowcount = 1
        elif "SELECT id, name FROM organisations" in sql:
            result.fetchone.return_value = ("org-1", "Test Org")
        elif "SELECT * FROM migration_jobs" in sql:
            job_id = params.get("jid")
            for j in self._tables["migration_jobs"]:
                if j.get("id") == job_id:
                    mapping = MagicMock()
                    mapping.__getitem__ = lambda s, k: j.get(k)
                    mapping.get = lambda k, d=None: j.get(k, d)
                    mapping.keys = lambda: j.keys()
                    mapping.values = lambda: j.values()
                    mapping.items = lambda: j.items()
                    result.mappings.return_value.fetchone.return_value = mapping
                    return result
            result.mappings.return_value.fetchone.return_value = None
        elif "SELECT COUNT(*)" in sql:
            table = None
            for t in ENTITY_TYPES:
                if f"FROM {t}" in sql:
                    table = t
                    break
            count = len(self._tables.get(table, [])) if table else 0
            result.scalar.return_value = count
        elif "SELECT COALESCE(SUM(total_amount)" in sql:
            total = sum(
                float(inv.get("total", inv.get(":total", 0)))
                for inv in self._tables.get("invoices", [])
            )
            result.scalar.return_value = total
        elif "SELECT COALESCE(SUM(amount)" in sql:
            total = sum(
                float(p.get("amount", p.get(":amount", 0)))
                for p in self._tables.get("payments", [])
            )
            result.scalar.return_value = total
        elif "SELECT i.invoice_number" in sql:
            result.fetchall.return_value = []
        elif "SELECT invoice_number FROM invoices" in sql:
            nums = [inv.get("num", "") for inv in self._tables.get("invoices", [])]
            result.fetchall.return_value = [(n,) for n in sorted(nums)]
        elif "UPDATE migration_jobs" in sql:
            job_id = params.get("jid")
            for j in self._tables["migration_jobs"]:
                if j.get("id") == job_id:
                    if "status" in params:
                        j["status"] = params["status"]
                    if "err" in params and params["err"] is not None:
                        j["error_message"] = params["err"]
                    if "check" in params:
                        j["integrity_check"] = params["check"]
                    if "p" in params:
                        j["records_processed"] = params["p"]
            result.rowcount = 1
        elif "UPDATE organisations" in sql:
            result.rowcount = 1
        elif "DELETE FROM" in sql:
            table = None
            for t in ENTITY_TYPES:
                if f"FROM {t}" in sql:
                    table = t
                    break
            if table:
                job_id = params.get("jid")
                before = len(self._tables.get(table, []))
                self._tables[table] = [
                    r for r in self._tables.get(table, [])
                    if r.get("jid") != job_id
                ]
                result.rowcount = before - len(self._tables.get(table, []))
            else:
                result.rowcount = 0

        return result


# ---------------------------------------------------------------------------
# 49.8: Full migration imports all records with correct references
# ---------------------------------------------------------------------------


class TestFullMigration:
    """Validates: Requirement 7.1, 7.3 — full migration imports all records."""

    @pytest.mark.asyncio
    async def test_full_migration_imports_all_records(self):
        """Full migration should import all customers, products, invoices,
        payments, and jobs with correct cross-references."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = _make_source_data(
            num_customers=3,
            num_products=2,
            num_invoices=3,
            num_payments=2,
            num_jobs=2,
        )

        # Create the job
        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_format="json",
            source_data=source_data,
            description="Test full migration",
        )
        job_id = uuid.UUID(job["id"])

        # Verify job was created with correct total
        assert job["status"] == STATUS_PENDING
        assert job["records_total"] == 12  # 3+2+3+2+2

        # Execute the migration
        result = await service.execute_full_migration(job_id)
        assert result["status"] == "migration_complete"
        assert result["records_processed"] == 12

        # Verify all entity types were imported
        assert len(db._tables["customers"]) == 3
        assert len(db._tables["products"]) == 2
        assert len(db._tables["invoices"]) == 3
        assert len(db._tables["payments"]) == 2
        assert len(db._tables["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_full_migration_resolves_customer_references(self):
        """Invoices and jobs should reference the correct migrated customer IDs."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = {
            "customers": [
                {"id": "cust-A", "name": "Alice"},
                {"id": "cust-B", "name": "Bob"},
            ],
            "products": [],
            "invoices": [
                {
                    "id": "inv-1",
                    "invoice_number": "INV-001",
                    "customer_id": "cust-A",
                    "total_amount": 500.0,
                    "tax_amount": 75.0,
                },
            ],
            "payments": [],
            "jobs": [
                {
                    "id": "job-1",
                    "job_number": "JOB-001",
                    "customer_id": "cust-B",
                    "status": "enquiry",
                },
            ],
        }

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        await service.execute_full_migration(job_id)

        # Verify invoices have resolved customer IDs (not the source IDs)
        assert len(db._tables["invoices"]) == 1
        inv_cid = db._tables["invoices"][0]["cid"]
        assert inv_cid is not None
        # The customer ID should be a new UUID, not the source "cust-A"
        assert inv_cid != "cust-A"

        # Verify jobs have resolved customer IDs
        assert len(db._tables["jobs"]) == 1
        job_cid = db._tables["jobs"][0]["cid"]
        assert job_cid is not None
        assert job_cid != "cust-B"

    @pytest.mark.asyncio
    async def test_create_migration_job_validates_org_exists(self):
        """Creating a job for a non-existent org should raise ValueError."""
        db = MockDBSession()
        # Override org lookup to return None
        original_execute = db.execute

        async def mock_execute(stmt, params=None):
            sql = str(stmt)
            if "SELECT id, name FROM organisations" in sql:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            return await original_execute(stmt, params)

        db.execute = mock_execute
        service = DataMigrationService(db)

        with pytest.raises(ValueError, match="not found"):
            await service.create_migration_job(
                org_id=uuid.UUID("00000000-0000-0000-0000-999999999999"),
                mode="full",
            )


# ---------------------------------------------------------------------------
# 49.9: Integrity check detects missing customer references
# ---------------------------------------------------------------------------


class TestIntegrityChecks:
    """Validates: Requirement 7.5 — integrity checks detect discrepancies."""

    @pytest.mark.asyncio
    async def test_integrity_check_detects_missing_customer_refs(self):
        """Validation should detect invoices referencing unknown customers."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = {
            "customers": [
                {"id": "cust-1", "name": "Alice"},
            ],
            "invoices": [
                {
                    "id": "inv-1",
                    "invoice_number": "INV-001",
                    "customer_id": "cust-MISSING",
                    "total_amount": 100.0,
                },
            ],
            "products": [],
            "payments": [],
            "jobs": [],
        }

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        validation = await service.validate_source_data(job_id)
        assert validation["valid"] is False
        assert any("cust-MISSING" in err for err in validation["errors"])

    @pytest.mark.asyncio
    async def test_validation_detects_missing_required_fields(self):
        """Validation should detect missing required fields in source data."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = {
            "customers": [
                {"email": "no-name@test.com"},  # missing 'name'
            ],
            "invoices": [
                {"status": "draft"},  # missing 'invoice_number' and 'total_amount'
            ],
            "products": [],
            "payments": [],
            "jobs": [],
        }

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        validation = await service.validate_source_data(job_id)
        assert validation["valid"] is False
        assert any("name" in err for err in validation["errors"])
        assert any("invoice_number" in err for err in validation["errors"])


# ---------------------------------------------------------------------------
# 49.10: Rollback removes migrated data without affecting pre-existing
# ---------------------------------------------------------------------------


class TestRollback:
    """Validates: Requirement 7.6 — rollback removes only migrated records."""

    @pytest.mark.asyncio
    async def test_rollback_removes_migrated_data(self):
        """Rollback should delete all records tagged with the migration job ID."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = _make_source_data(
            num_customers=2, num_products=1, num_invoices=2,
            num_payments=1, num_jobs=1,
        )

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        # Execute migration
        await service.execute_full_migration(job_id)

        # Verify data was imported
        assert len(db._tables["customers"]) == 2
        assert len(db._tables["invoices"]) == 2

        # Rollback
        result = await service.rollback_migration(job_id, reason="Test rollback")
        assert result["status"] == STATUS_ROLLED_BACK
        assert result["reason"] == "Test rollback"

    @pytest.mark.asyncio
    async def test_rollback_preserves_pre_existing_records(self):
        """Pre-existing records (without migration_job_id) should not be deleted."""
        db = MockDBSession()
        service = DataMigrationService(db)

        # Add a pre-existing customer (no jid field)
        db._tables["customers"].append({
            "id": "pre-existing-cust",
            "oid": "org-1",
            "name": "Pre-existing Customer",
            # No "jid" field — this is a pre-existing record
        })

        source_data = _make_source_data(num_customers=1, num_products=0,
                                         num_invoices=0, num_payments=0, num_jobs=0)

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        await service.execute_full_migration(job_id)

        # Should have pre-existing + migrated
        assert len(db._tables["customers"]) == 2

        # Rollback — only migrated records should be removed
        await service.rollback_migration(job_id)

        # Pre-existing customer should remain
        remaining = [c for c in db._tables["customers"] if c.get("id") == "pre-existing-cust"]
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_rollback_already_rolled_back_raises(self):
        """Attempting to rollback an already rolled-back job should raise."""
        db = MockDBSession()
        service = DataMigrationService(db)

        source_data = _make_source_data(num_customers=1, num_products=0,
                                         num_invoices=0, num_payments=0, num_jobs=0)

        job = await service.create_migration_job(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            mode="full",
            source_data=source_data,
        )
        job_id = uuid.UUID(job["id"])

        await service.execute_full_migration(job_id)
        await service.rollback_migration(job_id)

        with pytest.raises(ValueError, match="already been rolled back"):
            await service.rollback_migration(job_id)
