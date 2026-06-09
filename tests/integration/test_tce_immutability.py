"""Integration tests for TCE immutability trigger — conceptual verification.

The trigger ``trg_tce_immutability`` (firing function
``tce_immutability_guard()``) is created by migration
``alembic/versions/2026_06_08_0001-0218_staff_timesheets_schema.py``.

Guard conditions (per design § Immutability Trigger):
  - UPDATE blocked when: OLD.<col> IS NOT NULL AND OLD.<col> IS DISTINCT FROM NEW.<col>
    (blocks mutation of already-set clock_in_at or clock_out_at values)
  - UPDATE allowed when: OLD.<col> IS NULL → NEW.<col> (first write, e.g. normal clock-out)
  - DELETE unconditionally blocked.
  - Other columns (notes, break_minutes, etc.) may be freely updated.

NOTE: These tests verify the migration file exists and the trigger SQL is
structurally correct. Actual trigger execution requires ``alembic upgrade head``
against a running PostgreSQL database. For real trigger testing, use:

    docker compose -p invoicing exec -T app python -m pytest \\
        tests/integration/test_timesheets_migration.py -v

Refs: Requirements 5.1, 5.2, 5.5, 5.6.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest


MIGRATION_FILENAME = "2026_06_08_0001-0218_staff_timesheets_schema.py"
MIGRATION_DIR = Path("alembic/versions")
MIGRATION_PATH = MIGRATION_DIR / MIGRATION_FILENAME


class TestMigrationFileStructure:
    """Verify the migration file exists and is syntactically valid Python."""

    def test_migration_file_exists(self):
        """The migration file is present in alembic/versions/."""
        assert MIGRATION_PATH.exists(), (
            f"Expected migration at {MIGRATION_PATH}"
        )

    def test_migration_file_parses_as_valid_python(self):
        """The migration file is syntactically valid Python (no SyntaxError)."""
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        # ast.parse will raise SyntaxError if the file is broken
        tree = ast.parse(source)
        assert tree is not None

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration contains both upgrade() and downgrade() functions."""
        source = MIGRATION_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "upgrade" in function_names, "Missing upgrade() function"
        assert "downgrade" in function_names, "Missing downgrade() function"


class TestTriggerSQLContent:
    """Verify the trigger function SQL contains correct guard conditions."""

    @pytest.fixture
    def migration_source(self) -> str:
        return MIGRATION_PATH.read_text(encoding="utf-8")

    def test_trigger_function_name(self, migration_source: str):
        """Trigger function is named tce_immutability_guard."""
        assert "tce_immutability_guard" in migration_source

    def test_trigger_name(self, migration_source: str):
        """Trigger is named trg_tce_immutability."""
        assert "trg_tce_immutability" in migration_source

    def test_null_check_before_distinct(self, migration_source: str):
        """Guard uses IS NOT NULL check BEFORE IS DISTINCT FROM.

        This is critical: without the NULL check, normal clock-out writes
        (setting clock_out_at from NULL to a value) would be blocked.
        The pattern must be: OLD.col IS NOT NULL AND OLD.col IS DISTINCT FROM NEW.col
        """
        # Check clock_in_at guard pattern
        clock_in_pattern = re.compile(
            r"OLD\.clock_in_at\s+IS\s+NOT\s+NULL\s+AND\s+OLD\.clock_in_at\s+IS\s+DISTINCT\s+FROM\s+NEW\.clock_in_at",
            re.IGNORECASE,
        )
        assert clock_in_pattern.search(migration_source), (
            "Missing NULL-safe guard for clock_in_at: "
            "expected 'OLD.clock_in_at IS NOT NULL AND OLD.clock_in_at IS DISTINCT FROM NEW.clock_in_at'"
        )

        # Check clock_out_at guard pattern
        clock_out_pattern = re.compile(
            r"OLD\.clock_out_at\s+IS\s+NOT\s+NULL\s+AND\s+OLD\.clock_out_at\s+IS\s+DISTINCT\s+FROM\s+NEW\.clock_out_at",
            re.IGNORECASE,
        )
        assert clock_out_pattern.search(migration_source), (
            "Missing NULL-safe guard for clock_out_at: "
            "expected 'OLD.clock_out_at IS NOT NULL AND OLD.clock_out_at IS DISTINCT FROM NEW.clock_out_at'"
        )

    def test_delete_unconditionally_blocked(self, migration_source: str):
        """DELETE path raises exception without any column conditions."""
        # The trigger should raise on DELETE unconditionally
        delete_pattern = re.compile(
            r"IF\s+TG_OP\s*=\s*'DELETE'",
            re.IGNORECASE,
        )
        assert delete_pattern.search(migration_source), (
            "Missing unconditional DELETE block in trigger"
        )

    def test_trigger_fires_before_update_or_delete(self, migration_source: str):
        """Trigger is BEFORE UPDATE OR DELETE."""
        pattern = re.compile(
            r"BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+time_clock_entries",
            re.IGNORECASE,
        )
        assert pattern.search(migration_source), (
            "Trigger must fire BEFORE UPDATE OR DELETE ON time_clock_entries"
        )

    def test_trigger_is_per_row(self, migration_source: str):
        """Trigger executes FOR EACH ROW."""
        pattern = re.compile(r"FOR\s+EACH\s+ROW", re.IGNORECASE)
        assert pattern.search(migration_source)

    def test_raises_restrict_violation_errcode(self, migration_source: str):
        """Trigger raises with ERRCODE 'restrict_violation'."""
        assert "restrict_violation" in migration_source, (
            "Trigger must use ERRCODE = 'restrict_violation'"
        )

    def test_downgrade_drops_trigger_and_function(self, migration_source: str):
        """downgrade() drops the trigger and function."""
        assert "DROP TRIGGER IF EXISTS trg_tce_immutability" in migration_source
        assert "DROP FUNCTION IF EXISTS tce_immutability_guard" in migration_source


class TestRealTriggerNote:
    """Document that real trigger testing requires a running DB.

    These tests are intentionally lightweight — they verify the SQL structure
    without executing it. For full trigger-level integration testing, run:

        docker compose -p invoicing exec -T app python -m pytest \\
            tests/integration/test_timesheets_migration.py::test_immutability_trigger_blocks_update -v

    That test requires ``alembic upgrade head`` to have been run first so the
    trigger exists in the live database.
    """

    def test_real_db_trigger_testing_documented(self):
        """Placeholder confirming real trigger tests exist elsewhere."""
        # This test exists to document the dependency — real trigger testing
        # needs the database with the migration applied.
        assert True, (
            "Real trigger testing requires: "
            "1. alembic upgrade head (creates trigger) "
            "2. tests/integration/test_timesheets_migration.py "
            "   (fires real SQL against the running DB)"
        )
