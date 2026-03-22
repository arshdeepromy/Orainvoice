"""Integrity checker for live database migration.

Compares row counts, foreign key references, financial totals, and sequence
values between source and target databases to confirm data consistency.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.admin.live_migration_schemas import (
    FinancialComparison,
    IntegrityCheckResult,
    RowCountComparison,
    SequenceComparison,
)


# ---------------------------------------------------------------------------
# Pure helper functions (testable without database connections)
# ---------------------------------------------------------------------------


def compare_count_maps(
    source: dict[str, int],
    target: dict[str, int],
) -> tuple[dict[str, RowCountComparison], bool]:
    """Compare two maps of table names to counts.

    Returns ``(comparisons, all_match)`` where *comparisons* is a dict of
    ``RowCountComparison`` keyed by table name and *all_match* is ``True``
    only when every table has equal counts in both maps.

    Tables present in one map but not the other are treated as having a count
    of 0 in the missing map.
    """
    all_keys = sorted(set(source) | set(target))
    comparisons: dict[str, RowCountComparison] = {}
    all_match = True

    for key in all_keys:
        src = source.get(key, 0)
        tgt = target.get(key, 0)
        match = src == tgt
        comparisons[key] = RowCountComparison(source=src, target=tgt, match=match)
        if not match:
            all_match = False

    return comparisons, all_match


def compare_sequence_maps(
    source: dict[str, int],
    target: dict[str, int],
) -> tuple[dict[str, SequenceComparison], bool]:
    """Compare two maps of sequence names to values.

    Returns ``(comparisons, all_valid)`` where *comparisons* is a dict of
    ``SequenceComparison`` keyed by sequence name and *all_valid* is ``True``
    only when every target value is >= the corresponding source value.

    Sequences present in source but missing from target are treated as
    ``target_value=0`` (invalid).  Sequences present only in target are
    treated as ``source_value=0`` (valid, since target >= 0).
    """
    all_keys = sorted(set(source) | set(target))
    comparisons: dict[str, SequenceComparison] = {}
    all_valid = True

    for key in all_keys:
        src = source.get(key, 0)
        tgt = target.get(key, 0)
        valid = tgt >= src
        comparisons[key] = SequenceComparison(
            source_value=src, target_value=tgt, valid=valid,
        )
        if not valid:
            all_valid = False

    return comparisons, all_valid


# ---------------------------------------------------------------------------
# Financial table configuration
# ---------------------------------------------------------------------------

_FINANCIAL_TABLES: dict[str, str] = {
    "invoice_amounts": "SELECT COALESCE(SUM(total_amount), 0) FROM invoices",
    "payment_totals": "SELECT COALESCE(SUM(amount), 0) FROM payments",
    "credit_note_totals": "SELECT COALESCE(SUM(amount), 0) FROM credit_notes",
}


# ---------------------------------------------------------------------------
# IntegrityChecker class
# ---------------------------------------------------------------------------


class IntegrityChecker:
    """Orchestrates integrity checks between source and target databases."""

    def __init__(
        self,
        source_engine: AsyncEngine,
        target_engine: AsyncEngine,
    ) -> None:
        self.source_engine = source_engine
        self.target_engine = target_engine

    async def run(self) -> IntegrityCheckResult:
        """Orchestrate all integrity checks."""
        row_counts = await self._compare_row_counts()
        fk_errors = await self._check_foreign_keys()
        financial_totals = await self._compare_financial_totals()
        sequence_checks = await self._compare_sequences()

        passed = (
            all(rc.match for rc in row_counts.values())
            and len(fk_errors) == 0
            and all(ft.match for ft in financial_totals.values())
            and all(sc.valid for sc in sequence_checks.values())
        )

        return IntegrityCheckResult(
            passed=passed,
            row_counts=row_counts,
            fk_errors=fk_errors,
            financial_totals=financial_totals,
            sequence_checks=sequence_checks,
        )

    # -- internal helpers ---------------------------------------------------

    async def _get_table_names(self, engine: AsyncEngine) -> list[str]:
        """Return all user table names from the public schema."""
        query = text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "ORDER BY tablename"
        )
        async with engine.connect() as conn:
            result = await conn.execute(query)
            return [row[0] for row in result.fetchall()]

    async def _get_row_count(self, engine: AsyncEngine, table: str) -> int:
        """Return the row count for a single table."""
        async with engine.connect() as conn:
            result = await conn.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            return result.scalar_one()

    async def _compare_row_counts(self) -> dict[str, RowCountComparison]:
        """Query SELECT count(*) for every table in both databases and compare."""
        source_tables = await self._get_table_names(self.source_engine)
        target_tables = await self._get_table_names(self.target_engine)
        all_tables = sorted(set(source_tables) | set(target_tables))

        source_counts: dict[str, int] = {}
        target_counts: dict[str, int] = {}

        for table in all_tables:
            if table in source_tables:
                source_counts[table] = await self._get_row_count(
                    self.source_engine, table,
                )
            if table in target_tables:
                target_counts[table] = await self._get_row_count(
                    self.target_engine, table,
                )

        comparisons, _ = compare_count_maps(source_counts, target_counts)
        return comparisons

    async def _check_foreign_keys(self) -> list[str]:
        """Verify all FK references in target are valid."""
        query = text("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
        """)

        errors: list[str] = []
        async with self.target_engine.connect() as conn:
            fk_rows = (await conn.execute(query)).fetchall()

            for table, column, ref_table, ref_column in fk_rows:
                orphan_query = text(
                    f"SELECT COUNT(*) FROM {table} t "  # noqa: S608
                    f"LEFT JOIN {ref_table} r ON t.{column} = r.{ref_column} "
                    f"WHERE t.{column} IS NOT NULL AND r.{ref_column} IS NULL"
                )
                count = (await conn.execute(orphan_query)).scalar_one()
                if count > 0:
                    errors.append(
                        f"{table}.{column} -> {ref_table}.{ref_column}: "
                        f"{count} orphaned references"
                    )

        return errors

    async def _compare_financial_totals(self) -> dict[str, FinancialComparison]:
        """Compare sums for invoice amounts, payment totals, credit note totals."""
        comparisons: dict[str, FinancialComparison] = {}

        for label, query_str in _FINANCIAL_TABLES.items():
            async with self.source_engine.connect() as conn:
                source_total = float(
                    (await conn.execute(text(query_str))).scalar_one()
                )
            async with self.target_engine.connect() as conn:
                target_total = float(
                    (await conn.execute(text(query_str))).scalar_one()
                )

            comparisons[label] = FinancialComparison(
                source_total=source_total,
                target_total=target_total,
                match=source_total == target_total,
            )

        return comparisons

    async def _compare_sequences(self) -> dict[str, SequenceComparison]:
        """Compare sequence current values, target must be >= source."""
        seq_query = text(
            "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' "
            "ORDER BY sequencename"
        )

        async with self.source_engine.connect() as conn:
            source_seqs = [
                row[0] for row in (await conn.execute(seq_query)).fetchall()
            ]
        async with self.target_engine.connect() as conn:
            target_seqs = [
                row[0] for row in (await conn.execute(seq_query)).fetchall()
            ]

        all_seqs = sorted(set(source_seqs) | set(target_seqs))
        source_map: dict[str, int] = {}
        target_map: dict[str, int] = {}

        for seq in all_seqs:
            val_query = text(f"SELECT last_value FROM {seq}")  # noqa: S608
            if seq in source_seqs:
                async with self.source_engine.connect() as conn:
                    source_map[seq] = int(
                        (await conn.execute(val_query)).scalar_one()
                    )
            if seq in target_seqs:
                async with self.target_engine.connect() as conn:
                    target_map[seq] = int(
                        (await conn.execute(val_query)).scalar_one()
                    )

        comparisons, _ = compare_sequence_maps(source_map, target_map)
        return comparisons
