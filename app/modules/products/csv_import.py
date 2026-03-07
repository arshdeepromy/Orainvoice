"""CSV import service for products.

Supports preview mode (validate without importing) and commit mode.
Includes field mapping and trade-specific sample template generation.

**Validates: Requirement 9.9**
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product
from app.modules.products.schemas import (
    CSVFieldMapping,
    CSVImportPreview,
    CSVImportResult,
)

# Default field mapping: CSV header → Product field
DEFAULT_FIELD_MAP = {
    "name": "name",
    "sku": "sku",
    "barcode": "barcode",
    "description": "description",
    "unit_of_measure": "unit_of_measure",
    "sale_price": "sale_price",
    "cost_price": "cost_price",
    "stock_quantity": "stock_quantity",
    "low_stock_threshold": "low_stock_threshold",
    "category": "category_name",
}

REQUIRED_FIELDS = {"name"}

DECIMAL_FIELDS = {
    "sale_price", "cost_price", "stock_quantity",
    "low_stock_threshold", "reorder_quantity",
}

SAMPLE_TEMPLATES = {
    "generic": [
        "name,sku,barcode,description,unit_of_measure,sale_price,cost_price,stock_quantity",
        "Widget A,SKU-001,1234567890123,A sample widget,each,29.99,15.00,100",
        "Widget B,SKU-002,,Another widget,each,49.99,25.00,50",
    ],
    "vehicle-workshop": [
        "name,sku,barcode,description,unit_of_measure,sale_price,cost_price,stock_quantity",
        "Oil Filter,OF-001,9421000000001,Standard oil filter,each,12.50,6.00,200",
        "Brake Pads (Front),BP-001,9421000000002,Front brake pad set,set,89.00,45.00,50",
        "Engine Oil 5W-30 (5L),EO-530,9421000000003,5W-30 synthetic engine oil,each,65.00,35.00,80",
    ],
    "electrician": [
        "name,sku,barcode,description,unit_of_measure,sale_price,cost_price,stock_quantity",
        "LED Downlight 10W,LED-10W,,10W warm white LED downlight,each,18.50,9.00,150",
        "Cable 2.5mm TPS (100m),CBL-25,,2.5mm twin and earth cable,metre,2.50,1.20,500",
    ],
    "plumber": [
        "name,sku,barcode,description,unit_of_measure,sale_price,cost_price,stock_quantity",
        "Copper Pipe 15mm (3m),CP-15,,15mm copper pipe 3m length,each,28.00,14.00,100",
        "Ball Valve 15mm,BV-15,,15mm brass ball valve,each,22.00,11.00,75",
    ],
}


class CSVImportService:
    """Handles CSV product import with preview and commit modes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def get_sample_template(self, trade_slug: str | None = None) -> str:
        """Return a sample CSV template for the given trade category."""
        key = trade_slug if trade_slug in SAMPLE_TEMPLATES else "generic"
        return "\n".join(SAMPLE_TEMPLATES[key])

    def parse_csv(self, csv_content: str) -> list[dict]:
        """Parse CSV string into list of row dicts."""
        reader = csv.DictReader(io.StringIO(csv_content))
        return [dict(row) for row in reader]

    def apply_field_mapping(
        self, rows: list[dict], mappings: list[CSVFieldMapping] | None = None,
    ) -> list[dict]:
        """Apply custom field mappings to parsed rows."""
        if not mappings:
            return rows

        mapping_dict = {m.source_column: m.target_field for m in mappings}
        mapped_rows = []
        for row in rows:
            mapped = {}
            for col, val in row.items():
                target = mapping_dict.get(col, col)
                mapped[target] = val
            mapped_rows.append(mapped)
        return mapped_rows

    def validate_rows(self, rows: list[dict]) -> CSVImportPreview:
        """Validate rows and return a preview with errors."""
        errors: list[dict] = []
        valid_rows: list[dict] = []

        for idx, row in enumerate(rows):
            row_errors: list[str] = []

            # Check required fields
            for field in REQUIRED_FIELDS:
                if not row.get(field, "").strip():
                    row_errors.append(f"Missing required field: {field}")

            # Validate decimal fields
            for field in DECIMAL_FIELDS:
                val = row.get(field, "").strip()
                if val:
                    try:
                        Decimal(val)
                    except (InvalidOperation, ValueError):
                        row_errors.append(f"Invalid number for {field}: {val}")

            if row_errors:
                errors.append({"row": idx + 1, "errors": row_errors, "data": row})
            else:
                valid_rows.append(row)

        return CSVImportPreview(
            total_rows=len(rows),
            valid_rows=len(valid_rows),
            error_rows=len(errors),
            errors=errors,
            preview_data=valid_rows[:20],
        )

    async def import_products(
        self,
        org_id: uuid.UUID,
        rows: list[dict],
    ) -> CSVImportResult:
        """Import validated rows as products."""
        imported = 0
        skipped = 0
        errors: list[dict] = []

        for idx, row in enumerate(rows):
            try:
                product = Product(
                    org_id=org_id,
                    name=row.get("name", "").strip(),
                    sku=row.get("sku", "").strip() or None,
                    barcode=row.get("barcode", "").strip() or None,
                    description=row.get("description", "").strip() or None,
                    unit_of_measure=row.get("unit_of_measure", "each").strip(),
                    sale_price=Decimal(row.get("sale_price", "0") or "0"),
                    cost_price=Decimal(row.get("cost_price", "0") or "0"),
                    stock_quantity=Decimal(row.get("stock_quantity", "0") or "0"),
                    low_stock_threshold=Decimal(
                        row.get("low_stock_threshold", "0") or "0"
                    ),
                )
                self.db.add(product)
                imported += 1
            except Exception as exc:
                errors.append({"row": idx + 1, "error": str(exc)})

        if imported > 0:
            await self.db.flush()

        return CSVImportResult(
            imported_count=imported,
            skipped_count=skipped,
            error_count=len(errors),
            errors=errors,
        )
