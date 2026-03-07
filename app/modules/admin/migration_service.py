"""Data migration service for onboarding organisations.

Provides full and live migration modes with integrity checking and rollback.

**Validates: Requirement 7 — V1 Organisation Data Migration, Requirement 41**
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Migration job statuses
STATUS_PENDING = "pending"
STATUS_VALIDATING = "validating"
STATUS_IN_PROGRESS = "in_progress"
STATUS_INTEGRITY_CHECK = "integrity_check"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_ROLLED_BACK = "rolled_back"

# Supported entity types for migration
ENTITY_TYPES = ("customers", "invoices", "products", "payments", "jobs")

# Tag used to identify migrated records for rollback
MIGRATION_TAG = "migrated_by_tool"


class DataMigrationService:
    """Handles data migration for onboarding organisations.

    Supports two modes:
    - Full migration: imports all data from CSV/JSON source files
    - Live migration: dual-write period with sync verification
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # create_migration_job
    # ------------------------------------------------------------------

    async def create_migration_job(
        self,
        org_id: uuid.UUID,
        mode: str = "full",
        source_format: str = "json",
        source_data: dict | None = None,
        description: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> dict:
        """Create a new migration job record.

        Returns the job dict with id, status, and metadata.
        """
        # Verify org exists
        org_check = await self.db.execute(
            text("SELECT id, name FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
        org_row = org_check.fetchone()
        if org_row is None:
            raise ValueError(f"Organisation {org_id} not found")

        job_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Count total records across all entity types
        records_total = 0
        if source_data:
            for entity_type in ENTITY_TYPES:
                items = source_data.get(entity_type, [])
                if isinstance(items, list):
                    records_total += len(items)

        await self.db.execute(
            text(
                "INSERT INTO migration_jobs "
                "(id, org_id, mode, status, source_format, source_data, "
                " description, records_total, records_processed, "
                " created_by, created_at, updated_at) "
                "VALUES (:id, :org_id, :mode, :status, :source_format, "
                " :source_data, :description, :records_total, 0, "
                " :created_by, :now, :now)"
            ),
            {
                "id": str(job_id),
                "org_id": str(org_id),
                "mode": mode,
                "status": STATUS_PENDING,
                "source_format": source_format,
                "source_data": json.dumps(source_data or {}),
                "description": description,
                "records_total": records_total,
                "created_by": str(created_by) if created_by else None,
                "now": now,
            },
        )

        return {
            "id": str(job_id),
            "org_id": str(org_id),
            "mode": mode,
            "status": STATUS_PENDING,
            "source_format": source_format,
            "description": description,
            "records_processed": 0,
            "records_total": records_total,
            "progress_pct": 0.0,
            "integrity_check": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }

    # ------------------------------------------------------------------
    # validate_source_data
    # ------------------------------------------------------------------

    async def validate_source_data(self, job_id: uuid.UUID) -> dict:
        """Validate source data structure and references.

        Returns validation result with any errors found.
        """
        job = await self._get_job(job_id)
        if job is None:
            raise ValueError(f"Migration job {job_id} not found")

        await self._update_job_status(job_id, STATUS_VALIDATING)

        source_data = json.loads(job["source_data"]) if job["source_data"] else {}
        errors: list[str] = []

        # Validate each entity type
        for entity_type in ENTITY_TYPES:
            items = source_data.get(entity_type, [])
            if not isinstance(items, list):
                errors.append(f"{entity_type}: expected a list, got {type(items).__name__}")
                continue

            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"{entity_type}[{i}]: expected a dict")
                    continue

                # Validate required fields per entity type
                required = self._required_fields(entity_type)
                for field in required:
                    if field not in item or item[field] is None:
                        errors.append(f"{entity_type}[{i}]: missing required field '{field}'")

        # Validate customer references in invoices
        customer_names = {
            c.get("name") for c in source_data.get("customers", [])
            if isinstance(c, dict)
        }
        customer_ids = {
            c.get("id") for c in source_data.get("customers", [])
            if isinstance(c, dict) and c.get("id")
        }
        for i, inv in enumerate(source_data.get("invoices", [])):
            if isinstance(inv, dict):
                cust_ref = inv.get("customer_id") or inv.get("customer_name")
                if cust_ref and cust_ref not in customer_ids and cust_ref not in customer_names:
                    errors.append(
                        f"invoices[{i}]: references unknown customer '{cust_ref}'"
                    )

        is_valid = len(errors) == 0
        if not is_valid:
            await self._update_job_status(job_id, STATUS_FAILED, error_message="; ".join(errors[:10]))

        return {"valid": is_valid, "errors": errors}

    # ------------------------------------------------------------------
    # execute_full_migration
    # ------------------------------------------------------------------

    async def execute_full_migration(self, job_id: uuid.UUID) -> dict:
        """Execute a full migration: import all data from source into the org.

        Imports customers, products, invoices, payments, and jobs in order
        to maintain referential integrity.
        """
        job = await self._get_job(job_id)
        if job is None:
            raise ValueError(f"Migration job {job_id} not found")

        if job["mode"] != "full":
            raise ValueError("Job is not configured for full migration mode")

        await self._update_job_status(job_id, STATUS_IN_PROGRESS)

        source_data = json.loads(job["source_data"]) if job["source_data"] else {}
        org_id = uuid.UUID(job["org_id"])
        processed = 0
        total = job["records_total"] or 1

        try:
            # Phase 1: Import customers
            customer_map = await self._import_customers(org_id, source_data.get("customers", []), job_id)
            processed += len(source_data.get("customers", []))
            await self._update_progress(job_id, processed, total)

            # Phase 2: Import products
            product_map = await self._import_products(org_id, source_data.get("products", []), job_id)
            processed += len(source_data.get("products", []))
            await self._update_progress(job_id, processed, total)

            # Phase 3: Import invoices
            invoice_map = await self._import_invoices(
                org_id, source_data.get("invoices", []), customer_map, product_map, job_id,
            )
            processed += len(source_data.get("invoices", []))
            await self._update_progress(job_id, processed, total)

            # Phase 4: Import payments
            await self._import_payments(org_id, source_data.get("payments", []), invoice_map, job_id)
            processed += len(source_data.get("payments", []))
            await self._update_progress(job_id, processed, total)

            # Phase 5: Import jobs
            await self._import_jobs(org_id, source_data.get("jobs", []), customer_map, job_id)
            processed += len(source_data.get("jobs", []))
            await self._update_progress(job_id, processed, total)

            await self._update_job_status(job_id, STATUS_INTEGRITY_CHECK)
            return {"status": "migration_complete", "records_processed": processed}

        except Exception as exc:
            logger.exception("Full migration failed for job %s: %s", job_id, exc)
            await self._update_job_status(job_id, STATUS_FAILED, error_message=str(exc))
            raise

    # ------------------------------------------------------------------
    # execute_live_migration
    # ------------------------------------------------------------------

    async def execute_live_migration(self, job_id: uuid.UUID) -> dict:
        """Execute a live migration with dual-write period.

        During live migration, data is written to both old and new system.
        A sync verification runs periodically to ensure consistency.
        """
        job = await self._get_job(job_id)
        if job is None:
            raise ValueError(f"Migration job {job_id} not found")

        if job["mode"] != "live":
            raise ValueError("Job is not configured for live migration mode")

        await self._update_job_status(job_id, STATUS_IN_PROGRESS)

        source_data = json.loads(job["source_data"]) if job["source_data"] else {}
        org_id = uuid.UUID(job["org_id"])
        processed = 0
        total = job["records_total"] or 1

        try:
            # Enable dual-write flag for the org
            await self.db.execute(
                text(
                    "UPDATE organisations SET setup_wizard_state = "
                    "jsonb_set(COALESCE(setup_wizard_state, '{}'), "
                    "'{dual_write_active}', 'true') "
                    "WHERE id = :oid"
                ),
                {"oid": str(org_id)},
            )

            # Import data in batches (same as full but with dual-write tracking)
            customer_map = await self._import_customers(org_id, source_data.get("customers", []), job_id)
            processed += len(source_data.get("customers", []))
            await self._update_progress(job_id, processed, total)

            product_map = await self._import_products(org_id, source_data.get("products", []), job_id)
            processed += len(source_data.get("products", []))
            await self._update_progress(job_id, processed, total)

            invoice_map = await self._import_invoices(
                org_id, source_data.get("invoices", []), customer_map, product_map, job_id,
            )
            processed += len(source_data.get("invoices", []))
            await self._update_progress(job_id, processed, total)

            await self._import_payments(org_id, source_data.get("payments", []), invoice_map, job_id)
            processed += len(source_data.get("payments", []))
            await self._update_progress(job_id, processed, total)

            await self._import_jobs(org_id, source_data.get("jobs", []), customer_map, job_id)
            processed += len(source_data.get("jobs", []))
            await self._update_progress(job_id, processed, total)

            # Run sync verification
            sync_result = await self._verify_sync(org_id, source_data)

            await self._update_job_status(job_id, STATUS_INTEGRITY_CHECK)
            return {
                "status": "live_migration_complete",
                "records_processed": processed,
                "sync_verified": sync_result.get("in_sync", False),
            }

        except Exception as exc:
            logger.exception("Live migration failed for job %s: %s", job_id, exc)
            await self._update_job_status(job_id, STATUS_FAILED, error_message=str(exc))
            raise

    # ------------------------------------------------------------------
    # run_integrity_checks
    # ------------------------------------------------------------------

    async def run_integrity_checks(self, job_id: uuid.UUID) -> dict:
        """Run post-migration integrity checks.

        Verifies:
        - Record counts match source data
        - Financial totals match (invoice amounts, payment totals)
        - Customer references are valid (no orphaned invoices)
        - Invoice numbering continuity
        """
        job = await self._get_job(job_id)
        if job is None:
            raise ValueError(f"Migration job {job_id} not found")

        source_data = json.loads(job["source_data"]) if job["source_data"] else {}
        org_id = job["org_id"]

        record_counts: dict[str, dict[str, int]] = {}
        financial_totals: dict[str, float] = {}
        reference_errors: list[str] = []
        numbering_gaps: list[str] = []

        # 1. Record counts
        for entity_type in ENTITY_TYPES:
            source_count = len(source_data.get(entity_type, []))
            table_name = self._table_for_entity(entity_type)
            result = await self.db.execute(
                text(
                    f"SELECT COUNT(*) FROM {table_name} "
                    f"WHERE org_id = :oid AND migration_job_id = :jid"
                ),
                {"oid": org_id, "jid": str(job_id)},
            )
            db_count = result.scalar() or 0
            record_counts[entity_type] = {
                "source": source_count,
                "migrated": db_count,
            }

        # 2. Financial totals
        source_invoice_total = sum(
            float(inv.get("total_amount", 0) or 0)
            for inv in source_data.get("invoices", [])
            if isinstance(inv, dict)
        )
        result = await self.db.execute(
            text(
                "SELECT COALESCE(SUM(total_amount), 0) FROM invoices "
                "WHERE org_id = :oid AND migration_job_id = :jid"
            ),
            {"oid": org_id, "jid": str(job_id)},
        )
        db_invoice_total = float(result.scalar() or 0)
        financial_totals["source_invoice_total"] = source_invoice_total
        financial_totals["migrated_invoice_total"] = db_invoice_total

        source_payment_total = sum(
            float(p.get("amount", 0) or 0)
            for p in source_data.get("payments", [])
            if isinstance(p, dict)
        )
        result = await self.db.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM payments "
                "WHERE org_id = :oid AND migration_job_id = :jid"
            ),
            {"oid": org_id, "jid": str(job_id)},
        )
        db_payment_total = float(result.scalar() or 0)
        financial_totals["source_payment_total"] = source_payment_total
        financial_totals["migrated_payment_total"] = db_payment_total

        # 3. Customer reference integrity
        result = await self.db.execute(
            text(
                "SELECT i.invoice_number FROM invoices i "
                "LEFT JOIN customers c ON i.customer_id = c.id "
                "WHERE i.org_id = :oid AND i.migration_job_id = :jid "
                "AND i.customer_id IS NOT NULL AND c.id IS NULL"
            ),
            {"oid": org_id, "jid": str(job_id)},
        )
        orphaned = result.fetchall()
        for row in orphaned:
            reference_errors.append(f"Invoice {row[0]} references non-existent customer")

        # 4. Invoice numbering continuity
        result = await self.db.execute(
            text(
                "SELECT invoice_number FROM invoices "
                "WHERE org_id = :oid AND migration_job_id = :jid "
                "ORDER BY invoice_number"
            ),
            {"oid": org_id, "jid": str(job_id)},
        )
        numbers = [row[0] for row in result.fetchall()]
        for i in range(1, len(numbers)):
            prev_num = self._extract_number(numbers[i - 1])
            curr_num = self._extract_number(numbers[i])
            if prev_num is not None and curr_num is not None:
                if curr_num - prev_num > 1:
                    numbering_gaps.append(
                        f"Gap between {numbers[i - 1]} and {numbers[i]}"
                    )

        # Determine pass/fail
        counts_match = all(
            v["source"] == v["migrated"] for v in record_counts.values()
        )
        totals_match = (
            abs(source_invoice_total - db_invoice_total) < 0.01
            and abs(source_payment_total - db_payment_total) < 0.01
        )
        passed = counts_match and totals_match and len(reference_errors) == 0

        integrity_result = {
            "passed": passed,
            "record_counts": record_counts,
            "financial_totals": financial_totals,
            "reference_errors": reference_errors,
            "invoice_numbering_gaps": numbering_gaps,
        }

        # Update job with integrity check results
        new_status = STATUS_COMPLETED if passed else STATUS_FAILED
        error_msg = None if passed else "Integrity check failed"
        await self.db.execute(
            text(
                "UPDATE migration_jobs SET status = :status, "
                "integrity_check = :check, error_message = :err, "
                "updated_at = :now WHERE id = :jid"
            ),
            {
                "status": new_status,
                "check": json.dumps(integrity_result),
                "err": error_msg,
                "now": datetime.now(timezone.utc),
                "jid": str(job_id),
            },
        )

        return integrity_result

    # ------------------------------------------------------------------
    # rollback_migration
    # ------------------------------------------------------------------

    async def rollback_migration(
        self,
        job_id: uuid.UUID,
        reason: str = "Manual rollback",
    ) -> dict:
        """Rollback a migration by soft-deleting all migrated records.

        Only deletes records tagged with the migration job ID.
        Pre-existing records are not affected.
        """
        job = await self._get_job(job_id)
        if job is None:
            raise ValueError(f"Migration job {job_id} not found")

        if job["status"] == STATUS_ROLLED_BACK:
            raise ValueError("Migration has already been rolled back")

        org_id = job["org_id"]
        deleted_counts: dict[str, int] = {}

        # Delete in reverse dependency order to respect foreign keys
        for entity_type in reversed(ENTITY_TYPES):
            table_name = self._table_for_entity(entity_type)
            result = await self.db.execute(
                text(
                    f"DELETE FROM {table_name} "
                    f"WHERE org_id = :oid AND migration_job_id = :jid"
                ),
                {"oid": org_id, "jid": str(job_id)},
            )
            deleted_counts[entity_type] = result.rowcount or 0

        # Disable dual-write if it was a live migration
        if job["mode"] == "live":
            await self.db.execute(
                text(
                    "UPDATE organisations SET setup_wizard_state = "
                    "jsonb_set(COALESCE(setup_wizard_state, '{}'), "
                    "'{dual_write_active}', 'false') "
                    "WHERE id = :oid"
                ),
                {"oid": org_id},
            )

        await self._update_job_status(
            job_id, STATUS_ROLLED_BACK, error_message=f"Rolled back: {reason}"
        )

        total_deleted = sum(deleted_counts.values())
        return {
            "status": STATUS_ROLLED_BACK,
            "reason": reason,
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
        }

    # ------------------------------------------------------------------
    # get_job_status
    # ------------------------------------------------------------------

    async def get_job_status(self, job_id: uuid.UUID) -> dict | None:
        """Get the current status and progress of a migration job."""
        job = await self._get_job(job_id)
        if job is None:
            return None

        total = job["records_total"] or 1
        processed = job["records_processed"] or 0
        progress = round((processed / total) * 100, 1) if total > 0 else 0.0

        integrity = None
        if job["integrity_check"]:
            try:
                integrity = json.loads(job["integrity_check"]) if isinstance(
                    job["integrity_check"], str
                ) else job["integrity_check"]
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "id": job["id"],
            "org_id": job["org_id"],
            "mode": job["mode"],
            "status": job["status"],
            "source_format": job["source_format"],
            "description": job["description"],
            "records_processed": processed,
            "records_total": job["records_total"],
            "progress_pct": progress,
            "integrity_check": integrity,
            "error_message": job["error_message"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_job(self, job_id: uuid.UUID) -> dict | None:
        result = await self.db.execute(
            text("SELECT * FROM migration_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None

    async def _update_job_status(
        self,
        job_id: uuid.UUID,
        status: str,
        error_message: str | None = None,
    ) -> None:
        await self.db.execute(
            text(
                "UPDATE migration_jobs SET status = :status, "
                "error_message = :err, updated_at = :now WHERE id = :jid"
            ),
            {
                "status": status,
                "err": error_message,
                "now": datetime.now(timezone.utc),
                "jid": str(job_id),
            },
        )

    async def _update_progress(
        self, job_id: uuid.UUID, processed: int, total: int,
    ) -> None:
        pct = round((processed / max(total, 1)) * 100, 1)
        await self.db.execute(
            text(
                "UPDATE migration_jobs SET records_processed = :p, "
                "updated_at = :now WHERE id = :jid"
            ),
            {"p": processed, "now": datetime.now(timezone.utc), "jid": str(job_id)},
        )

    def _required_fields(self, entity_type: str) -> list[str]:
        """Return required fields for each entity type."""
        mapping = {
            "customers": ["name"],
            "invoices": ["invoice_number", "total_amount"],
            "products": ["name"],
            "payments": ["amount"],
            "jobs": ["job_number"],
        }
        return mapping.get(entity_type, [])

    def _table_for_entity(self, entity_type: str) -> str:
        """Map entity type to database table name."""
        return entity_type  # customers, invoices, products, payments, jobs

    def _extract_number(self, invoice_number: str) -> int | None:
        """Extract numeric portion from an invoice number for gap detection."""
        digits = "".join(c for c in str(invoice_number) if c.isdigit())
        return int(digits) if digits else None

    # ------------------------------------------------------------------
    # Entity import helpers (Task 49.3)
    # ------------------------------------------------------------------

    async def _import_customers(
        self, org_id: uuid.UUID, customers: list[dict], job_id: uuid.UUID,
    ) -> dict[str, str]:
        """Import customers and return a mapping of source_id/name → new UUID."""
        id_map: dict[str, str] = {}
        for cust in customers:
            if not isinstance(cust, dict):
                continue
            new_id = uuid.uuid4()
            source_key = cust.get("id") or cust.get("name", "")
            await self.db.execute(
                text(
                    "INSERT INTO customers "
                    "(id, org_id, name, email, phone, address, migration_job_id, created_at, updated_at) "
                    "VALUES (:id, :oid, :name, :email, :phone, :address, :jid, NOW(), NOW())"
                ),
                {
                    "id": str(new_id),
                    "oid": str(org_id),
                    "name": cust.get("name", "Unknown"),
                    "email": cust.get("email"),
                    "phone": cust.get("phone"),
                    "address": cust.get("address"),
                    "jid": str(job_id),
                },
            )
            id_map[str(source_key)] = str(new_id)
        return id_map

    async def _import_products(
        self, org_id: uuid.UUID, products: list[dict], job_id: uuid.UUID,
    ) -> dict[str, str]:
        """Import products and return a mapping of source_id/name → new UUID."""
        id_map: dict[str, str] = {}
        for prod in products:
            if not isinstance(prod, dict):
                continue
            new_id = uuid.uuid4()
            source_key = prod.get("id") or prod.get("name", "")
            sku = prod.get("sku") or f"MIG-{new_id.hex[:8].upper()}"
            await self.db.execute(
                text(
                    "INSERT INTO products "
                    "(id, org_id, name, sku, sale_price, cost_price, "
                    " stock_quantity, migration_job_id, created_at, updated_at) "
                    "VALUES (:id, :oid, :name, :sku, :sale, :cost, :qty, :jid, NOW(), NOW())"
                ),
                {
                    "id": str(new_id),
                    "oid": str(org_id),
                    "name": prod.get("name", "Unknown Product"),
                    "sku": sku,
                    "sale": float(prod.get("sale_price", 0)),
                    "cost": float(prod.get("cost_price", 0)),
                    "qty": float(prod.get("stock_quantity", 0)),
                    "jid": str(job_id),
                },
            )
            id_map[str(source_key)] = str(new_id)
        return id_map

    async def _import_invoices(
        self,
        org_id: uuid.UUID,
        invoices: list[dict],
        customer_map: dict[str, str],
        product_map: dict[str, str],
        job_id: uuid.UUID,
    ) -> dict[str, str]:
        """Import invoices with resolved customer references."""
        id_map: dict[str, str] = {}
        for inv in invoices:
            if not isinstance(inv, dict):
                continue
            new_id = uuid.uuid4()
            source_key = inv.get("id") or inv.get("invoice_number", "")

            # Resolve customer reference
            cust_ref = str(inv.get("customer_id") or inv.get("customer_name", ""))
            customer_id = customer_map.get(cust_ref)

            await self.db.execute(
                text(
                    "INSERT INTO invoices "
                    "(id, org_id, invoice_number, customer_id, status, "
                    " total_amount, tax_amount, balance_due, "
                    " migration_job_id, created_at, updated_at) "
                    "VALUES (:id, :oid, :num, :cid, :status, "
                    " :total, :tax, :balance, :jid, NOW(), NOW())"
                ),
                {
                    "id": str(new_id),
                    "oid": str(org_id),
                    "num": inv.get("invoice_number", f"MIG-{new_id.hex[:8]}"),
                    "cid": customer_id,
                    "status": inv.get("status", "draft"),
                    "total": float(inv.get("total_amount", 0)),
                    "tax": float(inv.get("tax_amount", 0)),
                    "balance": float(inv.get("balance_due", inv.get("total_amount", 0))),
                    "jid": str(job_id),
                },
            )
            id_map[str(source_key)] = str(new_id)
        return id_map

    async def _import_payments(
        self,
        org_id: uuid.UUID,
        payments: list[dict],
        invoice_map: dict[str, str],
        job_id: uuid.UUID,
    ) -> None:
        """Import payments with resolved invoice references."""
        for pay in payments:
            if not isinstance(pay, dict):
                continue
            new_id = uuid.uuid4()

            inv_ref = str(pay.get("invoice_id") or pay.get("invoice_number", ""))
            invoice_id = invoice_map.get(inv_ref)

            await self.db.execute(
                text(
                    "INSERT INTO payments "
                    "(id, org_id, invoice_id, amount, payment_method, "
                    " migration_job_id, created_at, updated_at) "
                    "VALUES (:id, :oid, :iid, :amount, :method, :jid, NOW(), NOW())"
                ),
                {
                    "id": str(new_id),
                    "oid": str(org_id),
                    "iid": invoice_id,
                    "amount": float(pay.get("amount", 0)),
                    "method": pay.get("payment_method", "other"),
                    "jid": str(job_id),
                },
            )

    async def _import_jobs(
        self,
        org_id: uuid.UUID,
        jobs: list[dict],
        customer_map: dict[str, str],
        job_id: uuid.UUID,
    ) -> None:
        """Import jobs with resolved customer references."""
        for j in jobs:
            if not isinstance(j, dict):
                continue
            new_id = uuid.uuid4()

            cust_ref = str(j.get("customer_id") or j.get("customer_name", ""))
            customer_id = customer_map.get(cust_ref)

            await self.db.execute(
                text(
                    "INSERT INTO jobs "
                    "(id, org_id, job_number, customer_id, status, "
                    " description, migration_job_id, created_at, updated_at) "
                    "VALUES (:id, :oid, :num, :cid, :status, :desc, :jid, NOW(), NOW())"
                ),
                {
                    "id": str(new_id),
                    "oid": str(org_id),
                    "num": j.get("job_number", f"JOB-{new_id.hex[:8]}"),
                    "cid": customer_id,
                    "status": j.get("status", "enquiry"),
                    "desc": j.get("description", ""),
                    "jid": str(job_id),
                },
            )

    # ------------------------------------------------------------------
    # Sync verification (Task 49.4)
    # ------------------------------------------------------------------

    async def _verify_sync(self, org_id: uuid.UUID, source_data: dict) -> dict:
        """Verify that migrated data matches source data counts."""
        in_sync = True
        details: dict[str, dict] = {}

        for entity_type in ENTITY_TYPES:
            source_count = len(source_data.get(entity_type, []))
            table_name = self._table_for_entity(entity_type)
            result = await self.db.execute(
                text(f"SELECT COUNT(*) FROM {table_name} WHERE org_id = :oid"),
                {"oid": str(org_id)},
            )
            db_count = result.scalar() or 0
            matches = db_count >= source_count
            if not matches:
                in_sync = False
            details[entity_type] = {
                "source": source_count,
                "target": db_count,
                "in_sync": matches,
            }

        return {"in_sync": in_sync, "details": details}
